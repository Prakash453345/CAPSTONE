"""Train A-CA-MP: build the demand profile, then fit the control
parameters. Two phases, run in this order because the second depends on
the first.

**Phase A -- demand memory.** Run the corridor once per training seed per
demand level with the controller recording (but not blending), then save
the profile. This is the literal "train on past experience" step: each
run is one day, and the saved file is what the controller remembers about
this corridor afterwards.

**Phase B -- parameter search.** CMA-ES over `tuning.PARAM_SPACE`,
evaluating each candidate on the training seeds only. See `tuning.py` for
why CMA-ES rather than PPO/DQN, and for what the search is and is not
permitted to touch (nothing in `Tier0Config`; `alpha_switch` bounded
strictly inside `(0,1)` so the sublinearity condition survives).

**Two economies, both stated because both affect what the result
means.** Candidate evaluations run with `--train-max-steps` (default
1500, against full runs of 2000-3600) and on a subset of the training
seeds. Both trade evaluation fidelity for search breadth, which is the
right trade when the alternative at a fixed compute budget is a handful
of very precise evaluations of a nearly-unsearched space -- but it does
mean a candidate is scored on a truncated run, and truncation flatters
controllers that are slow to degrade. The gate re-measures the winner on
full-length runs on held-out seeds, which is what makes that acceptable:
the shortcut shapes the search, never the reported result.

Usage:
    python scripts/train_acamp.py --generations 6 --population 6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.control.memory import DemandMemory  # noqa: E402
from sim_service.control.strategies.acamp import AcampConfig  # noqa: E402
from sim_service.control.tuning import (  # noqa: E402
    PARAM_SPACE,
    EvaluationResult,
    TuningHistory,
    optimize,
    save_config,
)

# Tuned Webster's measured person-delay at each demand level, from the
# M5 gate's own 10-seed baseline arm (`m5_gate_results.json`). Used only
# to put the three levels on a common scale in the training objective --
# see `evaluate` for why an unnormalized mean silently optimizes heavy
# demand alone. Not a target and not a constraint: the search is free to
# land above or below 1.0 at any level.
_WEBSTER_BASELINE_S = {"light": 69_542.0, "medium": 183_547.0, "heavy": 1_368_840.0}

_ART = H.ARTIFACT_DIR
_MEMORY_PATH = _ART / "demand_memory.json"
_CONFIG_PATH = _ART / "acamp_tuned.json"
_HISTORY_PATH = _ART / "tuning_history.json"


# ---- Phase A ---------------------------------------------------------


def _memory_job(args) -> tuple[str, dict]:
    """One recording run. Returns the serialized memory rather than the
    object, because a `DemandMemory` built in a worker process has to
    cross a process boundary to be merged, and JSON is the same format it
    persists in anyway."""
    level, seed = args
    memory = DemandMemory()
    H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_train_tripinfo"),
        demand_memory=memory,
        record_memory=True,
    )
    payload: dict = {}
    for key, cell in memory._cells.items():  # noqa: SLF001
        payload[key] = {
            "queue_pcu": cell.queue_pcu,
            "approaching_pcu": cell.approaching_pcu,
            "runs": cell.runs,
        }
    return level, payload


def build_memory(levels: list[str], seeds: list[int], workers: int) -> DemandMemory:
    """Fold every training run's observations into one profile.

    Merged by re-folding each run's committed cell values into a shared
    `DemandMemory` in the parent, rather than by averaging the workers'
    EWMAs: an EWMA of EWMAs weights runs by which worker happened to get
    them, which is an artefact of the scheduler and not of the data."""
    jobs = [(level, seed) for level in levels for seed in seeds]
    print(f"Phase A: building demand memory from {len(jobs)} runs", flush=True)
    merged = DemandMemory()
    started = time.time()
    with ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=1) as pool:
        for i, (level, payload) in enumerate(pool.map(_memory_job, jobs), start=1):
            for key, cell in payload.items():
                existing = merged._cells.get(key)  # noqa: SLF001
                if existing is None:
                    from sim_service.control.memory import _BinStats

                    existing = merged._cells[key] = _BinStats()  # noqa: SLF001
                if existing.runs == 0:
                    existing.queue_pcu = cell["queue_pcu"]
                    existing.approaching_pcu = cell["approaching_pcu"]
                else:
                    d = merged.decay
                    existing.queue_pcu = d * existing.queue_pcu + (1 - d) * cell["queue_pcu"]
                    existing.approaching_pcu = (
                        d * existing.approaching_pcu + (1 - d) * cell["approaching_pcu"]
                    )
                existing.runs += cell["runs"]
            usable, total = merged.coverage()
            print(
                f"  [{i}/{len(jobs)}] {level} merged -- coverage {usable}/{total} cells "
                f"({(time.time() - started) / 60:.0f}m)",
                flush=True,
            )
    return merged


# ---- Phase B ---------------------------------------------------------


def _eval_job(args) -> dict:
    params, level, seed, max_steps = args
    return H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_train_tripinfo"),
        acamp_cfg=AcampConfig(**params),
        max_steps=max_steps,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generations", type=int, default=6)
    parser.add_argument("--population", type=int, default=6)
    parser.add_argument("--train-seeds", type=int, default=2, help="seeds per candidate eval")
    parser.add_argument("--memory-seeds", type=int, default=3)
    parser.add_argument("--train-levels", default="light,medium")
    parser.add_argument("--memory-levels", default="light,medium,heavy")
    parser.add_argument("--train-max-steps", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 2))
    parser.add_argument("--skip-memory", action="store_true")
    parser.add_argument("--skip-tuning", action="store_true")
    args = parser.parse_args()

    _ART.mkdir(parents=True, exist_ok=True)
    train_levels = [x for x in args.train_levels.split(",") if x]
    eval_seeds = H.TRAIN_SEEDS[: args.train_seeds]

    if not args.skip_memory:
        memory = build_memory(
            [x for x in args.memory_levels.split(",") if x],
            H.TRAIN_SEEDS[: args.memory_seeds],
            args.workers,
        )
        memory.save(_MEMORY_PATH)
        usable, total = memory.coverage()
        print(f"Phase A done: {usable}/{total} cells usable -> {_MEMORY_PATH}\n", flush=True)

    if args.skip_tuning:
        return

    total_evals = args.generations * args.population
    print(
        f"Phase B: CMA-ES, {args.generations} gens x {args.population} pop = {total_evals} "
        f"candidates, each on {len(train_levels)} levels x {len(eval_seeds)} seeds "
        f"({total_evals * len(train_levels) * len(eval_seeds)} runs, "
        f"max_steps={args.train_max_steps})",
        flush=True,
    )

    history = TuningHistory()
    counter = {"n": 0}
    started = time.time()
    pool = ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1)

    def evaluate(cfg: AcampConfig) -> EvaluationResult:
        params = {name: getattr(cfg, name) for name in PARAM_SPACE}
        jobs = [
            (params, level, seed, args.train_max_steps)
            for level in train_levels
            for seed in eval_seeds
        ]
        rows = list(pool.map(_eval_job, jobs))
        counter["n"] += 1
        elapsed = (time.time() - started) / 60
        # Normalize each level by its own Webster baseline before
        # averaging. A raw mean over levels is not a neutral aggregation:
        # heavy demand's person-delay is ~1.37M against light's ~70k, so
        # an unnormalized mean weights heavy 20x and the search optimizes
        # it almost exclusively. That is not a hypothetical -- the first
        # tuning round ran on light+medium, where medium outweighs light
        # 2.6x, and produced a vector that improved medium while
        # regressing light and heavy. Dividing by each level's baseline
        # makes the objective "mean fraction of Webster's delay across
        # regimes", so a 10% gain at light counts exactly as much as a 10%
        # gain at heavy -- which is what "works across demand levels"
        # actually means.
        scaled = [
            r["person_delay_s"] / _WEBSTER_BASELINE_S[r["demand_level"]] for r in rows
        ]
        result = EvaluationResult(
            person_delay_s=sum(scaled) / len(scaled),
            interlock_violations=sum(r["interlock_violations"] for r in rows),
            completed_trips=sum(r["n_trips_total"] for r in rows),
            seeds=len(rows),
        )
        print(
            f"  cand {counter['n']:3d}/{total_evals}  obj={result.objective:>14,.0f}  "
            f"viol={result.interlock_violations:<5d} "
            f"eta={cfg.eta_arrival:.2f} rho={cfg.rho_jam:.2f} beta={cfg.beta_gate:.2f} "
            f"lf={cfg.lambda_f:.2f} g={cfg.gamma:.2f} k_s={cfg.kappa_switch:.2f} "
            f"a_s={cfg.alpha_switch:.2f} k={cfg.k}  ({elapsed:.0f}m)",
            flush=True,
        )
        return result

    try:
        best, history = optimize(
            evaluate,
            base=AcampConfig(),
            generations=args.generations,
            population=args.population,
            history=history,
            seed=17,
        )
    finally:
        pool.shutdown()

    save_config(best, _CONFIG_PATH)
    history.save(_HISTORY_PATH)

    baseline = next((e for e in history.entries), None)
    print("\n" + "=" * 70)
    print("tuned parameters:")
    for name in PARAM_SPACE:
        print(f"  {name:16s} {getattr(AcampConfig(), name):>8} -> {getattr(best, name):>8}")
    if history.best():
        print(f"\nbest objective: {history.best()['objective']:,.0f}")
        if baseline:
            print(f"first candidate: {baseline['objective']:,.0f}")
    print(f"\nwrote {_CONFIG_PATH}\nwrote {_HISTORY_PATH}")
    print(json.dumps({n: getattr(best, n) for n in PARAM_SPACE}, indent=2))


if __name__ == "__main__":
    main()

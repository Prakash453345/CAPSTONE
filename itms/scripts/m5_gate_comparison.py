"""M5's gate: A-CA-MP vs. M4's CA-MP vs. the tuned Webster baseline.

Same paired-seed methodology as `scripts/bench.py` (M3) and
`scripts/m4_gate_comparison.py` (M4), deliberately unchanged so the three
milestones' numbers are comparable rather than merely adjacent: every
controller sees the identical seed set at each demand level, Webster is
re-tuned per level from that level's own measured flows, and every raw
per-seed result is written out, not just the aggregate.

Three arms instead of two. M4's controller is included as a live arm
rather than quoted from PROGRESS.md, so that any difference between the
milestones is attributable to the controller and not to a changed
harness, a different SUMO build, or the saturation-flow calibration that
landed between them.

Evaluated on `EVAL_SEEDS` (1..10) -- the same seeds M4's gate used, and
disjoint from the `TRAIN_SEEDS` (101..110) the tuned parameters and the
demand profile were fitted on. See `m5_harness.py` for why that
separation is the methodological core of the milestone.

Not part of the pytest suite: shells out to 3 controllers x 3 demand
levels x 10 seeds = 90 real SUMO processes.
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
from sim_service.control import bench_stats  # noqa: E402
from sim_service.control.memory import DemandMemory  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402

_RESULTS_PATH = Path(__file__).resolve().parent / "results" / "m5_gate_results.json"
_ARMS = ("webster", "camp", "acamp")


def _job(args) -> dict:
    controller, level, seed, cfg_path, mem_path = args
    acamp_cfg = load_config(cfg_path) if (controller == "acamp" and cfg_path) else None
    memory = DemandMemory.load(mem_path) if (controller == "acamp" and mem_path) else None
    started = time.time()
    record = H.run_one(
        controller,
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_tripinfo"),
        acamp_cfg=acamp_cfg,
        demand_memory=memory,
        record_memory=False,  # evaluation never writes back -- frozen profile
    )
    record["wall_s"] = round(time.time() - started, 1)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tuned-config", default=None, help="path to a tuned AcampConfig JSON")
    parser.add_argument("--memory", default=None, help="path to a frozen DemandMemory JSON")
    parser.add_argument("--seeds", type=int, default=len(H.EVAL_SEEDS))
    parser.add_argument("--levels", default="light,medium,heavy")
    parser.add_argument("--arms", default=",".join(_ARMS))
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    parser.add_argument("--out", default=str(_RESULTS_PATH))
    args = parser.parse_args()

    levels = [x for x in args.levels.split(",") if x]
    arms = [x for x in args.arms.split(",") if x]
    seeds = H.EVAL_SEEDS[: args.seeds]

    jobs = [
        (arm, level, seed, args.tuned_config, args.memory)
        for level in levels
        for arm in arms
        for seed in seeds
    ]
    print(
        f"M5 gate: {len(jobs)} runs ({len(arms)} arms x {len(levels)} levels x {len(seeds)} seeds)"
    )
    print(f"eval seeds {seeds}  (train seeds {H.TRAIN_SEEDS} are disjoint)")
    print(f"tuned config: {args.tuned_config or '(defaults)'}")
    print(f"demand memory: {args.memory or '(none)'}")
    print(f"workers: {args.workers}\n", flush=True)

    records: list[dict] = []
    started = time.time()
    # `max_tasks_per_child=1`: TraCI keeps module-level connection state,
    # and a worker reused across runs can carry a half-closed connection
    # into the next one. A fresh process per run costs an interpreter
    # start (~0.3s against a ~90s run) and removes the failure mode.
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for record in pool.map(_job, jobs):
            records.append(record)
            done = len(records)
            rate = (time.time() - started) / done
            print(
                f"[{done}/{len(jobs)}] {record['controller']:8s} {record['demand_level']:6s} "
                f"seed={record['seed']:3d}  delay={record['person_delay_s']:>12,.0f}  "
                f"viol={record['interlock_violations']:<5d} ({record['wall_s']:.0f}s, "
                f"eta {rate * (len(jobs) - done) / 60:.0f}m)",
                flush=True,
            )

    summary: dict[str, dict[str, dict]] = {}
    for level in levels:
        summary[level] = {}
        for arm in arms:
            rows = [r for r in records if r["demand_level"] == level and r["controller"] == arm]
            if not rows:
                continue
            delays = [r["person_delay_s"] for r in rows]
            ci = bench_stats.confidence_interval_95(delays)
            summary[level][arm] = {
                "person_delay_mean_s": ci.mean,
                "person_delay_ci95_half_s": ci.half_width_95,
                "interlock_violations_total": sum(r["interlock_violations"] for r in rows),
                "stops_per_vehicle_mean": sum(r["stops_per_vehicle"] for r in rows) / len(rows),
                "trips_completed_mean": sum(r["n_trips_total"] for r in rows) / len(rows),
                "seeds": len(rows),
            }

    Path(args.out).write_text(
        json.dumps(
            {
                "eval_seeds": seeds,
                "train_seeds": H.TRAIN_SEEDS,
                "tuned_config": args.tuned_config,
                "demand_memory": args.memory,
                "summary": summary,
                "runs": records,
            },
            indent=2,
        )
    )

    print("\n" + "=" * 78)
    print(
        f"{'level':8s} {'arm':9s} {'person-delay (mean +/- 95% CI)':36s} {'viol':>6s} {'stops':>7s}"
    )
    print("=" * 78)
    for level in levels:
        for arm in arms:
            s = summary[level].get(arm)
            if not s:
                continue
            print(
                f"{level:8s} {arm:9s} "
                f"{s['person_delay_mean_s']:>14,.0f} +/- {s['person_delay_ci95_half_s']:>10,.0f}"
                f"{'':10s}{s['interlock_violations_total']:>6d} {s['stops_per_vehicle_mean']:>7.2f}"
            )
        print("-" * 78)
    print(f"\nwrote {args.out}   total wall {(time.time() - started) / 60:.0f} min")


if __name__ == "__main__":
    main()

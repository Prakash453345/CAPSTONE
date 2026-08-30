"""Small, targeted search for `switch_scale_ref` under its new *ratio*
semantics (see `AcampConfig.switch_scale_ref`'s docstring) -- not a full
CMA-ES retrain of all 12 parameters, which is not warranted here: only
the congestion-gate's reference point changed meaning, everything else in
`scripts/results/m5_artifacts/acamp_tuned.json` was already properly
fitted and stays fixed.

**Seed discipline, kept identical to `train_acamp.py`/`m5_gate_comparison.py`.**
This is a search, so it must run on `TRAIN_SEEDS` (101-110), never the
`EVAL_SEEDS` (1-10) the final honest gate reports on -- picking a
candidate by looking at the seeds it will later be judged on is exactly
the mistake `memory.py`'s own module docstring calls out. Only a small
slice of `TRAIN_SEEDS` is used (3 seeds), for wall-clock reasons on this
machine's 2 CPUs, not out of methodological choice -- the winning
candidate still gets a full 10-seed `EVAL_SEEDS` verification afterwards,
by a separate script, before any claim of improvement is made.

Searches medium and heavy only. Light demand's smoothed loads never
approach even a ratio of 1.5x its own baseline in
`m5_regime_threshold_probe.py`'s measurement, so light is not expected to
be sensitive to this parameter -- checked, not assumed, by including it
in the final verification gate.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.control import bench_stats  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402

_TUNED_PATH = Path(__file__).resolve().parent / "results" / "m5_artifacts" / "acamp_tuned.json"
_OUT = Path(__file__).resolve().parent / "results" / "m5_relative_congestion_sweep.json"

# A handful of candidate ratio thresholds, log-ish spaced across the new
# bound (1.0, 5.0) from `tuning.PARAM_SPACE`. The old tuned value (7.10)
# is included too, as the "did we even need to change this" control --
# under the new ratio semantics it should behave close to "never fires".
CANDIDATES = [1.3, 1.6, 2.0, 2.5, 3.0, 7.10]

SEARCH_SEEDS = H.TRAIN_SEEDS[:3]  # 101, 102, 103 -- disjoint from EVAL_SEEDS
LEVELS = ["medium", "heavy"]


def _job(args) -> dict:
    ref, level, seed = args
    base = load_config(str(_TUNED_PATH))
    cfg = replace(base, switch_scale_ref=ref)
    started = time.time()
    record = H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_congestion_sweep"),
        acamp_cfg=cfg,
    )
    record["switch_scale_ref"] = ref
    record["wall_s"] = round(time.time() - started, 1)
    return record


def main() -> None:
    jobs = [(ref, level, seed) for ref in CANDIDATES for level in LEVELS for seed in SEARCH_SEEDS]
    print(
        f"Sweeping switch_scale_ref in {CANDIDATES} on {LEVELS} x seeds {SEARCH_SEEDS} "
        f"({len(jobs)} runs)\n",
        flush=True,
    )
    records: list[dict] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=2, max_tasks_per_child=1) as pool:
        for record in pool.map(_job, jobs):
            records.append(record)
            done = len(records)
            print(
                f"[{done}/{len(jobs)}] ref={record['switch_scale_ref']:5.2f} "
                f"{record['demand_level']:6s} seed={record['seed']:3d} "
                f"delay={record['person_delay_s']:>12,.0f} "
                f"viol={record['interlock_violations']:<3d} ({record['wall_s']:.0f}s)",
                flush=True,
            )

    summary: dict[str, dict[str, dict]] = {}
    for level in LEVELS:
        summary[level] = {}
        for ref in CANDIDATES:
            rows = [
                r for r in records if r["demand_level"] == level and r["switch_scale_ref"] == ref
            ]
            delays = [r["person_delay_s"] for r in rows]
            ci = bench_stats.confidence_interval_95(delays)
            summary[level][str(ref)] = {
                "mean": ci.mean,
                "ci95_half": ci.half_width_95,
                "violations": sum(r["interlock_violations"] for r in rows),
                "n": len(rows),
            }

    Path(_OUT).write_text(
        json.dumps(
            {"search_seeds": SEARCH_SEEDS, "candidates": CANDIDATES, "summary": summary, "runs": records},
            indent=2,
        )
    )

    print("\n" + "=" * 70)
    for level in LEVELS:
        print(f"\n{level}:")
        for ref in CANDIDATES:
            s = summary[level][str(ref)]
            print(f"  ref={ref:5.2f}  {s['mean']:>12,.0f} +/- {s['ci95_half']:>8,.0f}  viol={s['violations']}")
    print(f"\ntotal wall {(time.time() - started) / 60:.1f} min, wrote {_OUT}")


if __name__ == "__main__":
    main()

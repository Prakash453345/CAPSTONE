"""Repeat `m5_relative_congestion_sweep.py`'s search, this time with each
run seeded from the cross-run-warmed `LoadBaseline`
(`scripts/m5_warm_load_baseline.py`) instead of starting `_baseline_load_
ewma` cold at 0.

**Why this script exists rather than editing the original sweep in
place.** The original sweep's own results are a recorded negative-ish
result in `PROGRESS.md` ("every value that helped heavy materially hurt
medium") measured under the diagnosed cold-start defect. Overwriting that
script would make its own recorded numbers unreproducible, the same
reason `camp.py` is never edited after M4's gate ran. This is a second,
otherwise-identical search that changes exactly one thing -- the
baseline's starting point -- so any difference between the two results is
attributable to the fix, not to some other drift.

**What "otherwise identical" means precisely.** Same candidates, same
`TRAIN_SEEDS[:3]`, same levels, same tuned config as the base, same
statistics. The only code difference is `load_baseline=LoadBaseline.load(...)`
passed to every run, frozen (`record_baseline` defaults to `False`, so
evaluating a candidate never further warms the baseline -- every
candidate is measured against the identical starting point, which is
what makes the comparison across candidates fair).

Seed discipline is the same as the original sweep and is not repeated at
length here -- see that module's docstring.
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
from sim_service.control.memory import LoadBaseline  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402

_TUNED_PATH = H.ARTIFACT_DIR / "acamp_tuned.json"
_BASELINE_PATH = H.ARTIFACT_DIR / "load_baseline.json"
_OUT = H.ARTIFACT_DIR.parent / "m5_relative_congestion_sweep_warmed.json"

# Identical candidate set to the cold-baseline sweep, so the two results
# sit in directly comparable rows.
CANDIDATES = [1.3, 1.6, 2.0, 2.5, 3.0, 7.10]

SEARCH_SEEDS = H.TRAIN_SEEDS[:3]  # 101, 102, 103 -- disjoint from EVAL_SEEDS
LEVELS = ["light", "medium", "heavy"]  # light included this time -- see main()


def _job(args) -> dict:
    ref, level, seed = args
    base = load_config(str(_TUNED_PATH))
    cfg = replace(base, switch_scale_ref=ref, use_relative_congestion_gate=True)
    baseline = LoadBaseline.load(_BASELINE_PATH)
    started = time.time()
    record = H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_congestion_sweep_warmed"),
        acamp_cfg=cfg,
        load_baseline=baseline,
    )
    record["switch_scale_ref"] = ref
    record["wall_s"] = round(time.time() - started, 1)
    return record


def main() -> None:
    if not _BASELINE_PATH.exists():
        raise SystemExit(
            f"{_BASELINE_PATH} does not exist -- run scripts/m5_warm_load_baseline.py first."
        )
    jobs = [(ref, level, seed) for ref in CANDIDATES for level in LEVELS for seed in SEARCH_SEEDS]
    print(
        f"Sweeping switch_scale_ref (warmed baseline) in {CANDIDATES} on {LEVELS} "
        f"x seeds {SEARCH_SEEDS} ({len(jobs)} runs)\n",
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

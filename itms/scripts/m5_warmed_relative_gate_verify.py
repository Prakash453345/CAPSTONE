"""Honest, held-out verification of the warmed-baseline relative
congestion gate -- the step every other M5 script in this package insists
on before any number gets called an improvement.

`scripts/m5_relative_congestion_sweep_warmed.py` searched `switch_scale_ref`
on `TRAIN_SEEDS[:3]` and found every candidate from 1.3 to 7.10
statistically indistinguishable from each other at heavy demand, and none
of them regressed light or medium the way the *cold*-baseline sweep did.
Since the candidates do not differentiate, this script does not pick a
new one: it keeps `switch_scale_ref` at its already-tuned value (7.10) and
tests exactly one change -- `use_relative_congestion_gate=True` fed a
cross-run-warmed baseline instead of `False` -- on the 10 `EVAL_SEEDS`
these training seeds have never touched.

Reports the same `person_delay_s` mean and 95% CI the M5 gate itself
reports, for direct comparison against `scripts/results/
m5_gate_results_reconciled_tuned.json`'s recorded default-arm numbers.
That comparison, not this script's own printout in isolation, is what
decides whether this is a real result or another documented negative one
-- and it is reported either way.
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
_OUT = H.ARTIFACT_DIR.parent / "m5_warmed_relative_gate_verify.json"

LEVELS = ["light", "medium", "heavy"]


def _job(args) -> dict:
    level, seed = args
    base = load_config(str(_TUNED_PATH))
    cfg = replace(base, use_relative_congestion_gate=True)  # switch_scale_ref stays 7.10, untouched
    baseline = LoadBaseline.load(_BASELINE_PATH)  # frozen: read, never written, at eval time
    started = time.time()
    record = H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_warmed_relative_gate_verify"),
        acamp_cfg=cfg,
        load_baseline=baseline,
    )
    record["wall_s"] = round(time.time() - started, 1)
    return record


def main() -> None:
    if not _BASELINE_PATH.exists():
        raise SystemExit(f"{_BASELINE_PATH} missing -- run m5_warm_load_baseline.py first.")
    jobs = [(level, seed) for level in LEVELS for seed in H.EVAL_SEEDS]
    print(
        f"Held-out verification: warmed relative gate on EVAL_SEEDS {H.EVAL_SEEDS} "
        f"x {LEVELS} ({len(jobs)} runs)\n",
        flush=True,
    )
    records: list[dict] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=2, max_tasks_per_child=1) as pool:
        for record in pool.map(_job, jobs):
            records.append(record)
            print(
                f"[{len(records)}/{len(jobs)}] {record['demand_level']:6s} "
                f"seed={record['seed']:3d} delay={record['person_delay_s']:>12,.0f} "
                f"viol={record['interlock_violations']:<3d} ({record['wall_s']:.0f}s)",
                flush=True,
            )

    summary = {}
    for level in LEVELS:
        delays = [r["person_delay_s"] for r in records if r["demand_level"] == level]
        ci = bench_stats.confidence_interval_95(delays)
        summary[level] = {
            "mean": ci.mean,
            "ci95_half": ci.half_width_95,
            "violations": sum(r["interlock_violations"] for r in records if r["demand_level"] == level),
            "n": len(delays),
        }

    Path(_OUT).write_text(json.dumps({"eval_seeds": H.EVAL_SEEDS, "summary": summary, "runs": records}, indent=2))

    # The comparison that actually matters: this arm against the recorded
    # default-arm (`use_relative_congestion_gate=False`) 10-seed gate.
    default = json.loads(
        (H.ARTIFACT_DIR.parent / "m5_gate_results_reconciled_tuned.json").read_text()
    )["summary"]

    print("\n" + "=" * 70)
    print(f"{'level':8s} {'default (shipped)':>26s}   {'warmed relative gate':>26s}   overlap?")
    for level in LEVELS:
        d = default[level]["acamp"]
        w = summary[level]
        d_lo, d_hi = d["person_delay_mean_s"] - d["person_delay_ci95_half_s"], d["person_delay_mean_s"] + d["person_delay_ci95_half_s"]
        w_lo, w_hi = w["mean"] - w["ci95_half"], w["mean"] + w["ci95_half"]
        overlap = not (w_hi < d_lo or d_hi < w_lo)
        pct = (w["mean"] - d["person_delay_mean_s"]) / d["person_delay_mean_s"] * 100
        print(
            f"{level:8s} {d['person_delay_mean_s']:>14,.0f} +/- {d['person_delay_ci95_half_s']:>9,.0f}   "
            f"{w['mean']:>14,.0f} +/- {w['ci95_half']:>9,.0f}   "
            f"{'OVERLAP' if overlap else 'NO OVERLAP'} ({pct:+.1f}%)"
        )
    print(f"\ntotal wall {(time.time() - started) / 60:.1f} min, wrote {_OUT}")


if __name__ == "__main__":
    main()

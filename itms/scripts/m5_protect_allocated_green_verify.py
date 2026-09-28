"""Honest, held-out verification of `protect_allocated_green` (congestion-
gated, iteration 3) -- the step every other M5 mechanism in this package
gets before any number is called an improvement.

`scripts/m5_protect_allocated_green_probe.py` on `TRAIN_SEEDS[:3]` found
something the two `use_relative_congestion_gate` attempts never did: light
and medium demand came back *bit-for-bit identical* to the default arm
(same `person_delay_s` to the seed, not just a statistically-indistinguishable
mean), while heavy demand improved on *all three* seeds individually
(6.5%, 13.0%, 9.1%), not just on average. That is a much stronger signal
than an overlapping confidence interval -- it says the mechanism is a
true no-op below the congestion gate's threshold and a consistent win
above it, on the seeds tried so far.

This script does not search anything (the flag is a boolean, there is
nothing to tune) -- it tests exactly one change,
`protect_allocated_green=True` against the shipped tuned default, on the
10 `EVAL_SEEDS` these training seeds have never touched. It reports both
the aggregate mean/CI (for direct comparison against
`scripts/results/m5_gate_results_reconciled_tuned.json`) and the paired
per-seed deltas (since the probe's signal was in the pairing, not the
aggregate) so a result that looks flat on average but is consistently
directional per seed is not missed.
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

_TUNED_PATH = H.ARTIFACT_DIR / "acamp_tuned.json"
_OUT = H.ARTIFACT_DIR.parent / "m5_protect_allocated_green_verify.json"

LEVELS = ["light", "medium", "heavy"]


def _job(args) -> dict:
    label, level, seed = args
    base = load_config(str(_TUNED_PATH))
    cfg = base if label == "default" else replace(base, protect_allocated_green=True)
    started = time.time()
    record = H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path(f"/tmp/m5_protect_allocated_green_verify_{label}"),
        acamp_cfg=cfg,
    )
    record["label"] = label
    record["wall_s"] = round(time.time() - started, 1)
    return record


def main() -> None:
    jobs = [
        (label, level, seed)
        for label in ["default", "protected"]
        for level in LEVELS
        for seed in H.EVAL_SEEDS
    ]
    print(
        f"Held-out verification: protect_allocated_green (congestion-gated) on "
        f"EVAL_SEEDS {H.EVAL_SEEDS} x {LEVELS} x 2 arms ({len(jobs)} runs)\n",
        flush=True,
    )
    records: list[dict] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=2, max_tasks_per_child=1) as pool:
        for record in pool.map(_job, jobs):
            records.append(record)
            print(
                f"[{len(records)}/{len(jobs)}] {record['label']:10s} {record['demand_level']:6s} "
                f"seed={record['seed']:3d} delay={record['person_delay_s']:>12,.0f} "
                f"viol={record['interlock_violations']:<3d} ({record['wall_s']:.0f}s)",
                flush=True,
            )

    summary = {}
    for label in ["default", "protected"]:
        summary[label] = {}
        for level in LEVELS:
            delays = [
                r["person_delay_s"]
                for r in records
                if r["label"] == label and r["demand_level"] == level
            ]
            ci = bench_stats.confidence_interval_95(delays)
            viol = sum(
                r["interlock_violations"]
                for r in records
                if r["label"] == label and r["demand_level"] == level
            )
            summary[label][level] = {
                "mean": ci.mean,
                "ci95_half": ci.half_width_95,
                "violations": viol,
                "n": len(delays),
            }

    # Paired per-seed deltas -- the comparison the probe's signal actually lives in.
    paired = {}
    for level in LEVELS:
        by_seed_default = {
            r["seed"]: r["person_delay_s"]
            for r in records
            if r["label"] == "default" and r["demand_level"] == level
        }
        by_seed_protected = {
            r["seed"]: r["person_delay_s"]
            for r in records
            if r["label"] == "protected" and r["demand_level"] == level
        }
        deltas = []
        for seed in H.EVAL_SEEDS:
            d, p = by_seed_default[seed], by_seed_protected[seed]
            pct = (p - d) / d * 100 if d else 0.0
            deltas.append({"seed": seed, "default": d, "protected": p, "pct": pct})
        n_improved = sum(1 for x in deltas if x["pct"] < 0)
        paired[level] = {"deltas": deltas, "n_improved": n_improved, "n": len(deltas)}

    Path(_OUT).write_text(
        json.dumps(
            {"eval_seeds": H.EVAL_SEEDS, "summary": summary, "paired": paired, "runs": records},
            indent=2,
        )
    )

    print("\n" + "=" * 78)
    print(f"{'level':8s} {'default':>26s}   {'protect_allocated_green':>26s}   overlap?")
    for level in LEVELS:
        d = summary["default"][level]
        w = summary["protected"][level]
        d_lo, d_hi = d["mean"] - d["ci95_half"], d["mean"] + d["ci95_half"]
        w_lo, w_hi = w["mean"] - w["ci95_half"], w["mean"] + w["ci95_half"]
        overlap = not (w_hi < d_lo or d_hi < w_lo)
        pct = (w["mean"] - d["mean"]) / d["mean"] * 100 if d["mean"] else 0.0
        overlap_label = "OVERLAP" if overlap else "NO OVERLAP"
        print(
            f"{level:8s} {d['mean']:>14,.0f} +/- {d['ci95_half']:>9,.0f}   "
            f"{w['mean']:>14,.0f} +/- {w['ci95_half']:>9,.0f}   "
            f"{overlap_label} ({pct:+.1f}%)  viol d={d['violations']} p={w['violations']}"
        )

    print("\npaired per-seed (protected vs default, negative = improvement):")
    for level in LEVELS:
        p = paired[level]
        print(f"  {level:6s} improved {p['n_improved']}/{p['n']} seeds")
        for x in p["deltas"]:
            print(
                f"    seed={x['seed']:3d} default={x['default']:>12,.0f} "
                f"protected={x['protected']:>12,.0f} ({x['pct']:+.1f}%)"
            )

    print(f"\ntotal wall {(time.time() - started) / 60:.1f} min, wrote {_OUT}")


if __name__ == "__main__":
    main()

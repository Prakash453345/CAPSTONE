"""Cheap first look at `AcampConfig.protect_allocated_green` on
`TRAIN_SEEDS[:3]` before committing to the full 10-seed `EVAL_SEEDS`
verification (`m5_protect_allocated_green_verify.py`). Unlike the two
congestion-gate attempts before it, this mechanism has no new parameter
to search -- it is a boolean, so there is exactly one candidate to check,
and this script exists only to catch an obvious problem (interlock
violations, a blown-up demand level) cheaply before spending the full
30-run held-out gate on it.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.control import bench_stats  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402
from dataclasses import replace  # noqa: E402

_TUNED_PATH = H.ARTIFACT_DIR / "acamp_tuned.json"
LEVELS = ["light", "medium", "heavy"]
SEEDS = H.TRAIN_SEEDS[:3]


def main() -> None:
    base = load_config(str(_TUNED_PATH))
    default_cfg = base
    protected_cfg = replace(base, protect_allocated_green=True)

    started = time.time()
    for label, cfg in [("default", default_cfg), ("protect_allocated_green", protected_cfg)]:
        rows = []
        for level in LEVELS:
            for seed in SEEDS:
                r = H.run_one(
                    "acamp", level, seed, tripinfo_dir=Path("/tmp/m5_protect_probe"), acamp_cfg=cfg
                )
                rows.append(r)
                print(
                    f"[{label}] {level:6s} seed={seed:3d} delay={r['person_delay_s']:>12,.0f} "
                    f"viol={r['interlock_violations']:<3d}",
                    flush=True,
                )
        print(f"\n{label} summary:")
        for level in LEVELS:
            delays = [r["person_delay_s"] for r in rows if r["demand_level"] == level]
            viol = sum(r["interlock_violations"] for r in rows if r["demand_level"] == level)
            ci = bench_stats.confidence_interval_95(delays)
            served = [
                r["decision_stats"].get("extend_allocation_protected", 0)
                for r in rows
                if r["demand_level"] == level
            ]
            print(
                f"  {level:6s} {ci.mean:>12,.0f} +/- {ci.half_width_95:>8,.0f}  viol={viol}  "
                f"protected_extends={sum(served)}"
            )
        print()
    print(f"total wall {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()

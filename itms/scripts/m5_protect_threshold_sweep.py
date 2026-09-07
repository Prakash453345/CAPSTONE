"""Cheap first look at lowering `protect_allocated_green`'s congestion
threshold below its verified default of 0.5.

`scripts/m5_congestion_profile.py` measured that medium demand's busiest
junction never exceeds a `congestion_weight` of 0.339 on this corridor,
while `protect_allocated_green` requires >= 0.5 before it will hold a
phase -- so the mechanism verified to help heavy demand by 12.1% never
fires at all at medium demand, even though medium independently wastes
about 38% of its own allocated green (`m5_heavy_diagnostics.py --level
medium`), a real version of the same defect at a smaller scale.

This sweeps candidate thresholds low enough to reach medium's ~0.34
ceiling, on `TRAIN_SEEDS[:3]` across all three demand levels, watching
for the same "helps heavy, hurts light" trade-off two earlier attempts
in this module already had to solve -- a lower threshold also changes
what heavy demand does (it already clears 0.5 easily, so lowering it
should not change heavy's behavior much, but light demand's near-zero
congestion means any threshold below its ceiling starts firing there for
the first time, which is exactly the failure mode `use_relative_
congestion_gate` and iterations 1-2 of this same mechanism were both
built to avoid).

Not a claim of anything -- a cheap look before spending the full 10-seed
`EVAL_SEEDS` verification cycle on whichever candidate (if any) looks
clean.
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.control import bench_stats  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402

_TUNED_PATH = H.ARTIFACT_DIR / "acamp_tuned.json"
LEVELS = ["light", "medium", "heavy"]
SEEDS = H.TRAIN_SEEDS[:3]
# 0.5 (verified default) included as the control; candidates below it
# span from just under medium's measured 0.339 ceiling down toward
# light's ~0.0 floor, to see where (if anywhere) medium starts benefiting
# without light starting to pay for it.
CANDIDATES = [0.5, 0.35, 0.3, 0.2, 0.1]


def main() -> None:
    base = load_config(str(_TUNED_PATH))
    started = time.time()
    for threshold in CANDIDATES:
        cfg = replace(base, protect_allocated_green_congestion_threshold=threshold)
        rows = []
        for level in LEVELS:
            for seed in SEEDS:
                r = H.run_one(
                    "acamp", level, seed, tripinfo_dir=Path("/tmp/m5_protect_threshold_sweep"), acamp_cfg=cfg
                )
                rows.append(r)
                print(
                    f"[thr={threshold:.2f}] {level:6s} seed={seed:3d} delay={r['person_delay_s']:>12,.0f} "
                    f"viol={r['interlock_violations']:<3d}",
                    flush=True,
                )
        print(f"\nthreshold={threshold:.2f} summary:")
        for level in LEVELS:
            delays = [r["person_delay_s"] for r in rows if r["demand_level"] == level]
            viol = sum(r["interlock_violations"] for r in rows if r["demand_level"] == level)
            ci = bench_stats.confidence_interval_95(delays)
            protected = [
                r["decision_stats"].get("extend_allocation_protected", 0)
                for r in rows
                if r["demand_level"] == level
            ]
            print(
                f"  {level:6s} {ci.mean:>12,.0f} +/- {ci.half_width_95:>8,.0f}  viol={viol}  "
                f"protected_extends={sum(protected)}"
            )
        print()
    print(f"total wall {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()

"""Sweep `lost_time_weight` at heavy demand -- does pricing the clearance
interval actually buy anything, and is the derived weight of 1.0 right?

`weight = 0` is the ablation arm: sublinear hold bias only, i.e. exactly
the controller measured in `m5_heavy_diag.json`. Everything above it adds
`switch_cost_bias`. If the derivation is sound, delay should fall as the
weight rises off zero and then flatten or reverse -- and if the minimum
sits at 0, the term does not earn its place and should be removed rather
than kept as a knob nobody sets.

Light demand is swept too, at fewer seeds. A term that fixes heavy by
breaking light is not a fix, and that is exactly what the previous tuning
round did in the other direction.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.control.strategies.acamp import AcampConfig  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402

_OUT = Path(__file__).resolve().parent / "results" / "m5_lost_time_sweep.json"


def _job(args) -> dict:
    weight, level, seed, cfg_path = args
    base = load_config(cfg_path) if cfg_path else AcampConfig()
    started = time.time()
    rec = H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_sweep"),
        acamp_cfg=AcampConfig(**{**base.__dict__, "lost_time_weight": weight}),
    )
    rec["lost_time_weight"] = weight
    rec["wall_s"] = round(time.time() - started, 1)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="0,1,2,3")
    ap.add_argument("--levels", default="heavy,light")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--tuned-config", default=None)
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 2))
    args = ap.parse_args()

    weights = [float(w) for w in args.weights.split(",")]
    levels = [x for x in args.levels.split(",") if x]
    seeds = H.EVAL_SEEDS[: args.seeds]
    jobs = [(w, lv, s, args.tuned_config) for lv in levels for w in weights for s in seeds]
    print(f"lost_time_weight sweep: {weights} x {levels} x {seeds} = {len(jobs)} runs\n", flush=True)

    rows = []
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for r in pool.map(_job, jobs):
            rows.append(r)
            print(
                f"[{len(rows)}/{len(jobs)}] w={r['lost_time_weight']:.1f} {r['demand_level']:6s} "
                f"seed={r['seed']} delay={r['person_delay_s']:>12,.0f} "
                f"viol={r['interlock_violations']}  ({r['wall_s']:.0f}s)",
                flush=True,
            )

    _OUT.write_text(json.dumps(rows, indent=2))
    print("\n" + "=" * 60)
    for lv in levels:
        print(f"\n{lv}:")
        base = None
        for w in weights:
            rr = [r for r in rows if r["demand_level"] == lv and r["lost_time_weight"] == w]
            m = statistics.mean([r["person_delay_s"] for r in rr])
            v = sum(r["interlock_violations"] for r in rr)
            if base is None:
                base = m
            print(f"  w={w:.1f}  delay {m:>12,.0f}  viol {v:<3d}  vs w=0 {(m - base) / base:+7.1%}")
    print(f"\nwrote {_OUT}")


if __name__ == "__main__":
    main()

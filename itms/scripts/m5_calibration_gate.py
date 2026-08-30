"""Does learning from prediction error actually help?

Three arms, all A-CA-MP with the same tuned parameters, differing only in
what the controller knows about its own discharge model:

    off      -- `sat_flow_pcu_s` exactly as calibrated offline. The
                controller measured in the M5 gate.
    frozen   -- an `OnlineCalibration` fitted on TRAIN seeds and then
                held fixed. Answers "does what it learned transfer to a
                day it has never seen?"
    online   -- a calibration starting completely cold and learning
                during the evaluation run itself. Answers the sharper
                question: "can it correct its own model from scratch,
                while driving?"

The `online` arm is the one that tests the claim. It starts knowing
nothing beyond the offline numbers, makes its own observations, and any
improvement it shows is self-generated within a single run rather than
carried in. Note it is also the *harder* arm: it spends the early part of
the run with an unlearned model, so it pays for its own education.

Seed discipline holds: `frozen` is fitted on TRAIN_SEEDS and evaluated on
EVAL_SEEDS, which are disjoint. `online` never sees any seed twice
because each run gets a fresh model.
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
from sim_service.control.online_calibration import OnlineCalibration  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402

_ART = H.ARTIFACT_DIR
_CAL_PATH = _ART / "online_calibration.json"
_OUT = Path(__file__).resolve().parent / "results" / "m5_calibration_gate.json"


def _fit_job(args):
    level, seed, cfg_path = args
    cal = OnlineCalibration()
    H.run_one(
        "acamp", level, seed, tripinfo_dir=Path("/tmp/m5_fit"),
        acamp_cfg=load_config(cfg_path) if cfg_path else None, calibration=cal,
    )
    return {
        k: {
            "baseline_sat_flow": m.baseline_sat_flow, "sat_flow": m.sat_flow,
            "saturated_samples": m.saturated_samples, "rejected_samples": m.rejected_samples,
            "rejected_unsaturated": m.rejected_unsaturated,
            "rejected_too_small": m.rejected_too_small,
            "rejected_too_short": m.rejected_too_short,
            "arrival_reliability": m.arrival_reliability, "arrival_samples": m.arrival_samples,
        }
        for k, m in cal.models.items()
    }


def _eval_job(args):
    arm, level, seed, cfg_path, cal_path = args
    acfg = load_config(cfg_path) if cfg_path else None
    cal, record = None, False
    if arm == "frozen":
        cal, record = OnlineCalibration.load(cal_path), False
    elif arm == "online":
        cal, record = OnlineCalibration(), True
    started = time.time()
    rec = H.run_one(
        "acamp", level, seed, tripinfo_dir=Path("/tmp/m5_calgate"),
        acamp_cfg=acfg, calibration=cal, record_calibration=record,
    )
    rec["arm"] = arm
    rec["wall_s"] = round(time.time() - started, 1)
    if cal is not None and record:
        rec["calibration_report"] = cal.report()
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tuned-config", default=str(_ART / "acamp_tuned.json"))
    ap.add_argument("--levels", default="light,medium,heavy")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--fit-seeds", type=int, default=3)
    ap.add_argument("--arms", default="frozen,online")
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 2))
    ap.add_argument("--skip-fit", action="store_true")
    args = ap.parse_args()

    levels = [x for x in args.levels.split(",") if x]
    arms = [x for x in args.arms.split(",") if x]
    seeds = H.EVAL_SEEDS[: args.seeds]

    if not args.skip_fit and "frozen" in arms:
        fit_jobs = [(lv, sd, args.tuned_config)
                    for lv in levels for sd in H.TRAIN_SEEDS[: args.fit_seeds]]
        print(f"fitting calibration on {len(fit_jobs)} TRAIN-seed runs", flush=True)
        merged = OnlineCalibration()
        from sim_service.control.online_calibration import MovementModel
        with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
            for i, payload in enumerate(pool.map(_fit_job, fit_jobs), 1):
                for key, m in payload.items():
                    ex = merged.models.get(key)
                    if ex is None:
                        merged.models[key] = MovementModel(**m)
                        continue
                    n1, n2 = ex.saturated_samples, m["saturated_samples"]
                    if n1 + n2 > 0:
                        ex.sat_flow = (ex.sat_flow * n1 + m["sat_flow"] * n2) / (n1 + n2)
                    ex.saturated_samples += n2
                    ex.rejected_samples += m["rejected_samples"]
                    ex.rejected_unsaturated += m["rejected_unsaturated"]
                    ex.rejected_too_small += m["rejected_too_small"]
                    ex.rejected_too_short += m["rejected_too_short"]
                    a1, a2 = ex.arrival_samples, m["arrival_samples"]
                    if a1 + a2 > 0:
                        ex.arrival_reliability = (
                            ex.arrival_reliability * a1 + m["arrival_reliability"] * a2
                        ) / (a1 + a2)
                    ex.arrival_samples += a2
                print(f"  [{i}/{len(fit_jobs)}] merged", flush=True)
        merged.save(_CAL_PATH)
        print(f"fit done: {json.dumps(merged.report(), indent=2)}\nwrote {_CAL_PATH}\n", flush=True)

    jobs = [(a, lv, sd, args.tuned_config, str(_CAL_PATH))
            for lv in levels for a in arms for sd in seeds]
    print(f"evaluating {len(jobs)} runs ({arms} x {levels} x {len(seeds)} seeds)\n", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for r in pool.map(_eval_job, jobs):
            rows.append(r)
            print(f"[{len(rows)}/{len(jobs)}] {r['arm']:7s} {r['demand_level']:6s} "
                  f"seed={r['seed']:2d} delay={r['person_delay_s']:>12,.0f} "
                  f"viol={r['interlock_violations']}  ({r['wall_s']:.0f}s)", flush=True)
    _OUT.write_text(json.dumps(rows, indent=2))

    print("\n" + "=" * 70)
    for lv in levels:
        print(f"\n{lv}:")
        for a in arms:
            rr = [r for r in rows if r["demand_level"] == lv and r["arm"] == a]
            ci = bench_stats.confidence_interval_95([r["person_delay_s"] for r in rr])
            v = sum(r["interlock_violations"] for r in rr)
            print(f"  {a:8s} {ci.mean:>12,.0f} +/- {ci.half_width_95:>9,.0f}  viol {v}")
    print(f"\nwrote {_OUT}")


if __name__ == "__main__":
    main()

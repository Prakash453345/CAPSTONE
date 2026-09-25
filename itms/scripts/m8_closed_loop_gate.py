"""M8 closed-loop gate: drive CC-A-CAMP from the cameras instead of SUMO.

The question every earlier milestone answered on ground truth, asked again
with the sensor the system would actually have: how much of the controller's
measured advantage over Webster survives realistic perception?

Arms, all on the same held-out seeds (paired):

    webster              tuned fixed-time -- needs no sensors at all
    truth                CC-A-CAMP on SUMO ground truth (the M5 baseline arm)
    vision:<preset>:honest   CC-A-CAMP fed by the vision pipeline (SimCam +
                         <preset> detector errors + ByteTrack + ground plane +
                         estimator), *with* the estimator's confidence, so the
                         controller's degradation ladder reacts to it
    vision:<preset>:trust    the same estimates with confidence withheld
    vision:<preset>:failsafe the same estimates, confidence passed only where
                         it is below 0.5 (a camera that has really failed) --
                         the mode the live wiring uses
    ...:outage           any of the three with every camera at the busiest
                         junction dark from 900 s to 2,700 s
    ...:blind            the same cameras, same window, still sending frames
                         but with a detector that finds nothing
    ...:nocheck          without the stop-bar cross-check for blind cameras
                         (on by default in honest and failsafe)

`vision_service/sim/closed_loop.py` does the swap inside the unmodified
runner; see its docstring for exactly which inputs change (the four queue
fields and confidence) and which stay ground truth (the safety kernel's
has_demand / wait_times).

    python scripts/m8_closed_loop_gate.py --out results/m8_closed_loop.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
import m8_harness as M  # noqa: E402
from m5_ccacamp_gate import paired  # noqa: E402
from vision_service.sim.closed_loop import VisionLoop, VisionSensor  # noqa: E402

METRICS = ("person_delay_s", "stops_per_vehicle", "person_throughput_per_hour")


# `vision:<preset>:<mode>:outage` arms: every camera at the corridor's
# busiest junction goes dark for half an hour (a cabinet power cut, a cut
# fibre) -- the case the confidence value exists for.
OUTAGE_S = (900.0, 2700.0)


def _outage_tls() -> str:
    approach, _ = M.link_maps()
    return max(approach, key=lambda tls: (len(approach[tls]), tls))


def _with_fault(factory, kind: str = "offline"):
    from vision_service.pipeline import CameraFault  # noqa: PLC0415

    tls = _outage_tls()

    def make(classes):
        vs = factory(classes)
        for cid, spec in vs.rig.specs.items():
            if spec.tls_id == tls:
                vs.inject_fault(cid, CameraFault(kind, *OUTAGE_S))
        return vs

    return make


def _job(args) -> dict:
    arm, level, seed, fps = args
    t0 = time.time()
    if arm == "webster":
        rec = M.run_scenario("webster", level, seed, inputs=H.scenario_inputs(level), tag=arm)
    elif arm == "truth":
        rec = M.run_scenario("ccacamp", level, seed, tag=arm)
    else:
        _, preset, mode, *extra = arm.split(":")
        inputs = M.ccacamp_inputs(level)
        base = M.build_strategy("ccacamp", inputs)
        approach, _ = M.link_maps()
        factory = M.vision_factory(preset, seed, fps)
        if "outage" in extra:
            factory = _with_fault(factory, "offline")
        if "blind" in extra:
            factory = _with_fault(factory, "blind")
        loop = VisionLoop(factory, approach.keys())
        check = False if "nocheck" in extra else None
        strategy = {tls: VisionSensor(ctrl, loop, tls, mode, blind_check=check)
                    for tls, ctrl in base.items()}
        rec = M.run_scenario("ccacamp", level, seed, inputs=inputs, strategy=strategy,
                             tag=arm.replace(":", "_"))
        rec["vision"] = {"confidence_fed": loop.confidence_summary(), "ticks": loop.ticks,
                         "blind_check_junction_ticks": sum(s.blind_ticks
                                                           for s in strategy.values())}
    rec["arm"] = arm
    rec["wall_s"] = round(time.time() - t0, 1)
    return rec


def summarise(records: list[dict], arms: list[str]) -> dict:
    out: dict = {}
    for level in sorted({r["demand_level"] for r in records}):
        by = {a: {r["seed"]: r for r in records if r["arm"] == a and r["demand_level"] == level}
              for a in arms}
        lv: dict = {"arms": {}, "paired": {}}
        for a, runs in by.items():
            if not runs:
                continue
            v = list(runs.values())
            lv["arms"][a] = {
                "n": len(v),
                "person_delay_s": st.fmean(r["person_delay_s"] for r in v),
                "stops_per_vehicle": st.fmean(r["stops_per_vehicle"] for r in v),
                "p95_wait_s": st.fmean(r["wait_time_s"]["p95_s"] for r in v),
                "person_throughput_per_hour": st.fmean(r["person_throughput_per_hour"]
                                                       for r in v),
                "interlock_violations": sum(r["interlock_violations"] for r in v),
                "fallback_fixed_time": sum(r.get("decision_stats", {}).get(
                    "fallback_fixed_time", 0) for r in v),
                "ticks": sum(r.get("decision_stats", {}).get("ticks", 0) for r in v),
            }
            conf = [r["vision"]["confidence_fed"] for r in v if "vision" in r]
            if conf:
                lv["arms"][a]["confidence_fed_mean"] = st.fmean(c["mean"] for c in conf)
                lv["arms"][a]["confidence_below_0.8"] = st.fmean(c["below_0.8"] for c in conf)
        for a in arms:
            for base in ("webster", "truth"):
                if a == base or not by.get(a) or not by.get(base):
                    continue
                for key in METRICS[:2]:
                    lv["paired"][f"{a}_vs_{base}:{key}"] = paired(by[base], by[a], key)
        out[level] = lv
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="medium,heavy")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--arms", default="webster,truth,vision:finetuned_day:trust,"
                                      "vision:finetuned_day:failsafe,vision:finetuned_day:honest,"
                                      "vision:coco_pretrained:failsafe,"
                                      "vision:coco_pretrained:honest")
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true",
                    help="keep the runs already in --out and run only the missing ones")
    args = ap.parse_args()
    arms = [a for a in args.arms.split(",") if a]
    levels = [lv for lv in args.levels.split(",") if lv]
    seeds = M.EVAL_SEEDS[: args.seeds]
    # expensive vision runs first, so the cheap ones fill the tail
    jobs = sorted(((a, lv, s, args.fps) for lv in levels for a in arms for s in seeds),
                  key=lambda j: (not j[0].startswith("vision"), j[1] != "heavy"))
    records: list[dict] = M.previous_runs(args.out, "records") if args.resume else []
    done = {(r["arm"], r["demand_level"], r["seed"]) for r in records}
    jobs = [j for j in jobs if (j[0], j[1], j[2]) not in done]
    # a resumed file may hold arms this invocation does not run; summarise them all
    arms = list(dict.fromkeys([*arms, *(r["arm"] for r in records)]))
    print(f"{len(jobs)} runs to do ({len(records)} kept): arms {arms} x levels {levels} x "
          f"seeds {seeds}", flush=True)
    t0 = time.time()
    total = len(jobs) + len(records)
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for rec in pool.map(_job, jobs):
            records.append(rec)
            conf = rec.get("vision", {}).get("confidence_fed", {})
            print(f"[{len(records)}/{total}] {rec['arm']:32s} {rec['demand_level']:6s} "
                  f"seed={rec['seed']:2d} delay={rec['person_delay_s']:>12,.0f} "
                  f"stops={rec['stops_per_vehicle']:.2f} viol={rec['interlock_violations']} "
                  f"fallback={rec.get('decision_stats', {}).get('fallback_fixed_time', 0)} "
                  f"conf={conf.get('mean', float('nan')):.2f} ({rec['wall_s']:.0f}s)",
                  flush=True)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(
                {"meta": {"fps": args.fps, "seeds": seeds,
                          "levels": sorted({r["demand_level"] for r in records}), "arms": arms,
                          "wall_min": round((time.time() - t0) / 60, 1)},
                 "summary": summarise(records, arms), "records": records},
                indent=1, default=str))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

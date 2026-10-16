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
    ...:nogap            without counting the queue past the camera's view
                         (`vision_service/state/gap_count.py`; on by default)
    ...:hol              the blocking-aware controller (`strategies/hol_camp.py`)
                         on the cameras, with a junction-overview camera per
                         junction telling it which lanes are blocked at their
                         head (the scenario needs `--add-box-cameras`)
    hol                  the blocking-aware controller on SUMO ground truth
                         (`hol:price`, `hol:p0`, ... are its development arms)
    truth:c<factor>      CC-A-CAMP with a green ceiling of <factor> x Webster's
                         green instead of 1.25

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
from dataclasses import replace
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
    elif arm == "webster:pair":
        # Webster's fixed timing on the paired phases: how much of the paired layout's
        # gain any controller would get
        inputs = M._scenario_inputs(level, layout="pair")  # noqa: SLF001
        rec = M.run_scenario("webster", level, seed, inputs=inputs,
                             strategy=H.build_webster(inputs[0], inputs[1]), tag="webster_pair")
    elif arm == "truth":
        rec = M.run_scenario("ccacamp", level, seed, tag=arm)
    elif arm.startswith("truth:"):
        # CC-A-CAMP with other settings, "truth:<mod>[:<mod>...]": c<x> green ceiling of
        # x times Webster's green (alone: no floor, as it was first measured), f<s> floor
        # under the ceiling in seconds (f0: the controller before the floor of
        # 2026-10-07), rest: stay green at the ceiling while nobody else waits. Sensing
        # (the default since 2026-10-07 is via2): nov: lanes only, as before; via: a split
        # road is measured and watched whole, internal lanes included; vian: as via, but
        # the road before the split raises no call; via2: as via, and an unchained approach
        # lane under 5 m long is watched together with the lanes leading into it
        mods = arm.split(":")[1:]
        unknown = [t for t in mods
                   if t not in ("rest", "restf", "nov", "via", "vian", "via2",
                                "ovl", "ovl2", "ovl3", "ovl4", "noovl", "restq", "restd", "restx",
                                "pair", "pairt", "nopair", "minph")
                   and t[:1] not in ("c", "f") and not t.startswith(("restm", "restc", "s.", "hz"))]
        if unknown:
            raise SystemExit(f"arm {arm!r}: unknown modifier(s) {unknown}")
        factor = next((float(t[1:]) for t in mods if t[:1] == "c"), None)
        floor = next((float(t[1:]) for t in mods if t[:1] == "f"), None)
        if floor is None:
            floor = 0.0 if factor is not None else M.CEILING_FLOOR_S
        # ovl: every phase also shows the movements that conflict with nothing it shows
        # noovl: without the shown overlaps that are the default since 2026-10-11
        other_overlaps = {"noovl", "ovl", "ovl2", "ovl3", "ovl4"} & set(mods)
        inputs = M.ccacamp_inputs(level, factor if factor is not None else M.CEILING_FACTOR, floor,
                                  overlaps="ovl" in mods, shown_overlaps=not other_overlaps,
                                  layout=None if "nopair" in mods else next(
                                      ({"minph": "compact"}.get(t, t) for t in mods
                                       if t in ("pair", "pairt", "minph")),
                                      M.PHASE_LAYOUT))
        # ovl2: the same extra greens, added after the timing is worked out
        timing = inputs
        if "ovl2" in mods:
            inputs = M.overlaps_kept_timing(timing)
        if "ovl3" in mods or "ovl4" in mods:
            # ... shown but not owned: the controller decides as before (ovl4: no U-turns)
            inputs = M.overlaps_kept_timing(timing, owned=False, uturns="ovl4" not in mods)
        strategy = None
        if "ovl2" in mods and "rest" not in mods:
            strategy = H.build_acamp(timing[0], timing[1], acamp_cfg=M._ARMS["ccacamp"])  # noqa: SLF001
        # s.<field>=<value>: any AcampConfig field (numbers; true/false)
        overrides = {}
        for t in mods:
            if t.startswith("s."):
                k, v = t[2:].split("=", 1)
                overrides[k] = {"true": True, "false": False}.get(v.lower(), None)
                if overrides[k] is None:
                    overrides[k] = float(v)
        if "rest" in mods:
            # restm<s>: rest at most s seconds past the ceiling; restf: rest only
            # while nothing stands halted on the running phase's movements; restc<x>: rest only
            # while the junction's congestion weight is below x
            rest_max = next((float(t[5:]) for t in mods if t.startswith("restm")), None)
            overrides.update(
                rest_in_green=True, rest_max_s=rest_max,
                rest_needs_flow="restf" in mods, rest_needs_no_call="restq" in mods,
                rest_needs_own_demand="restd" in mods,
                rest_needs_free_exit="restx" in mods,
                rest_max_congestion=next((float(t[5:]) for t in mods if t.startswith("restc")),
                                         None))
        if overrides:
            strategy = H.build_acamp(timing[0], timing[1], acamp_cfg=replace(
                M._ARMS["ccacamp"], **overrides))  # noqa: SLF001
        rec = M.run_scenario("ccacamp", level, seed, inputs=inputs, strategy=strategy,
                             tag=arm.replace(":", "_"),
                             vias="nov" not in mods,
                             detector_upstream="vian" not in mods,
                             vias_short_m=None if {"via", "vian"} & set(mods)
                             else M.SHORT_APPROACH_M,
                             arrival_horizon_s=next((float(t[2:]) for t in mods
                                                     if t.startswith("hz")), None))
    elif arm in M.HOL_ARMS:
        rec = M.run_scenario(arm, level, seed, tag=arm.replace(":", "_"))
    else:
        _, preset, mode, *extra = arm.split(":")
        hol_arm = "hol"  # "...:hol:p0:b3": the controller's settings follow "hol"
        if "hol" in extra:
            mods = [t for t in extra[extra.index("hol") + 1:]
                    if M._composed("hol:" + t) is not None]  # noqa: SLF001
            hol_arm = ":".join(["hol", *mods])
            extra = [t for t in extra if t not in mods]
        unknown = set(extra) - {"outage", "blind", "nocheck", "nogap", "hol"}
        if unknown:  # a mistyped modifier must not run a plain arm under its name
            raise SystemExit(f"arm {arm!r}: unknown modifier(s) {sorted(unknown)}")
        blocking_aware = "hol" in extra
        if blocking_aware:
            inputs, base_of = M.hol_inputs(level, M.HOL_ARMS[hol_arm].single_lane_only,
                                           M.hol_ceiling(hol_arm), M.hol_floor(hol_arm))
            base = M.build_hol(hol_arm, inputs, base_of)
        else:
            inputs = M.ccacamp_inputs(level)
            base = M.build_strategy("ccacamp", inputs)
        approach, _ = M.link_maps()
        kw = {}
        if "nogap" in extra:
            from vision_service.state import EstimatorConfig  # noqa: PLC0415

            kw["estimator_config"] = EstimatorConfig(gap_counting=False)
        factory = M.vision_factory(preset, seed, fps, box=blocking_aware, **kw)
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
            if all(r.get("teleports") is not None for r in v):
                # gridlock, measured: vehicles SUMO had to teleport out of a
                # jam, runs with any, runs still unfinished at the step cap
                lv["arms"][a]["teleports"] = sum(r["teleports"] for r in v)
                lv["arms"][a]["runs_with_teleports"] = sum(r["teleports"] > 0 for r in v)
                lv["arms"][a]["runs_unfinished_at_cap"] = sum(
                    (r.get("unfinished_at_cap") or 0) > 0 for r in v)
            excess = [r.get("longest_wait_excess_s") for r in v]
            if all(x is not None for x in excess):
                # the longest wait against the junction's maximum wait (worst
                # run; negative: never reached), and junction-ticks past it
                lv["arms"][a]["longest_wait_excess_s"] = max(excess)
                lv["arms"][a]["waits_over_bound"] = sum(r["waits_over_bound"] for r in v)
            variant = [r.get("decision_stats", {}).get("hol_variant_switch") for r in v]
            if all(x is not None for x in variant):
                lv["arms"][a]["variant_changes_per_run"] = st.fmean(variant)
                lv["arms"][a]["blocked_junction_ticks_per_run"] = st.fmean(
                    r["decision_stats"].get("hol_blocked_ticks", 0) for r in v)
            conf = [r["vision"]["confidence_fed"] for r in v if "vision" in r]
            if conf:
                lv["arms"][a]["confidence_fed_mean"] = st.fmean(c["mean"] for c in conf)
                lv["arms"][a]["confidence_below_0.8"] = st.fmean(c["below_0.8"] for c in conf)
        for a in arms:
            for base in ("webster", "truth", "hol"):
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
    ap.add_argument("--seed-list", help="explicit seeds, e.g. 101,102 (TRAIN seeds, for "
                                        "development); overrides --seeds")
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
    seeds = ([int(v) for v in args.seed_list.split(",")] if args.seed_list
             else M.EVAL_SEEDS[: args.seeds])
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
    # Every run is a fresh interpreter (max_tasks_per_child=1 implies spawn), and
    # a fresh interpreter draws a fresh string-hash seed, which fixes the order
    # Python walks a set of movement ids in. The controller sums pressures over
    # such sets, so two runs of one seed could differ in the last bit of a sum,
    # break a tie between phases differently and part ways: CC-A-CAMP on the
    # district network (medium, TRAIN seed 101) gave 171,849 s of person-delay
    # under most hash seeds and 178,150 or 178,317 under others (found
    # 2026-10-04, when an arm that must equal it did not). Pinning the hash
    # seed for the workers makes a run a function of its arguments again.
    # Results stored before this date were each drawn under an arbitrary seed.
    if not os.environ.get("PYTHONHASHSEED", "").isdigit():
        os.environ["PYTHONHASHSEED"] = "0"
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
                          "python_hash_seed": os.environ["PYTHONHASHSEED"],
                          "levels": sorted({r["demand_level"] for r in records}), "arms": arms,
                          "wall_min": round((time.time() - t0) / 60, 1)},
                 "summary": summarise(records, arms), "records": records},
                indent=1, default=str))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

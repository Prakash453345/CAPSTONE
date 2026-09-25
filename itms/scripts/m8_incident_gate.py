"""M8 incident gate: does the phase-aware vision stream find injected
incidents -- and how often does it cry wolf?

Deliberately the same experiment as `m6_incident_injection_gate.py`, so the
two streams can be read side by side: the same injector
(`control/anomaly/injector.py`: a stalled vehicle, or a lane throttled to a
crawl), the same schedule generator and parameters (6 incidents, 400-tick
warm-up, 300-tick cool-down, 200-tick minimum gap -- but scheduled inside
the run's real length, see `SCHEDULE_TICKS`), the same
Webster control, the same scoring -- a candidate counts if it lands on one of
the incident lane's links between the incident's start and 45 s after it
ends; latency is candidate tick minus start tick; every other candidate is a
false alarm.

One thing the graph detector never had to report: **whether the incident
was in view.** A stall 1.5 km up a 2.4 km approach is invisible to every
junction camera, and a vision stream should not be scored as if it could
see it. Each window is tagged `covered` -- for a stall, whether the stalled
vehicle's position was inside some camera's coverage; for a lane block,
whether any of the lane is covered -- and recall is reported both ways.

    python scripts/m8_incident_gate.py --out results/m8_incident_gate.json
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
import m8_harness as M  # noqa: E402
import numpy as np  # noqa: E402
from sim_service.control.anomaly.injector import IncidentInjector, random_schedule  # noqa: E402
from vision_service.classes import ClassTable  # noqa: E402
from vision_service.incidents import RuleConfig, TraciSignalState  # noqa: E402
from vision_service.simcam import TraciWorld  # noqa: E402

MAX_STEPS = 6000
N_INCIDENTS = 6
LATENCY_GRACE_S = 45
# Where the schedule may put incidents. M6's gate schedules over the whole
# 6000-tick cap, but the corridor's demand drains after ~2,350 s (medium)
# and ~3,100 s (heavy) -- measured, Webster, held-out seeds -- and the run
# ends there, so two thirds of M6's scheduled incidents never happen (the
# first two training runs of this gate realised 1 and 2 of 6). Scheduling
# inside the run, with M6's warm-up, cool-down, gap and durations, puts all
# six on the road.
SCHEDULE_TICKS = {"light": 2000, "medium": 2300, "heavy": 2950}

# The run logs every rule hit at deliberately low thresholds, with the
# measured duration behind it, so the operating thresholds can be chosen
# *afterwards* -- on training seeds -- and a whole recall / false-alarm curve
# comes out of one set of runs instead of one run per threshold.
LOGGING_RULES = RuleConfig(
    stuck_green_s=5.0, stuck_green_alone_s=5.0,
    midblock_stop_s=5.0, midblock_stop_dwell_s=5.0, midblock_impact_s=5.0,
    collision_stop_s=5.0, void_s=20.0, void_min_swerves=0,
    void_min_from_stop_line_m=0.0, void_min_share=0.0, raise_persist_s=0.0,
)


def _job(args) -> dict:
    preset, level, seed, fps, inject = args
    t0 = time.time()
    approach, receiving = M.link_maps()
    rig = M.rig()
    lanes = sorted({ln for links in approach.values() for ln in links.values()})
    injector = None
    if inject:
        schedule = random_schedule(lanes, seed=seed, n_incidents=N_INCIDENTS,
                                   run_ticks=SCHEDULE_TICKS.get(level, MAX_STEPS),
                                   warmup_ticks=400, cooldown_ticks=300, min_gap_ticks=200)
        injector = IncidentInjector(schedule, link_lanes=approach)
    make = M.vision_factory(preset, seed, fps, rule_config=LOGGING_RULES)
    world = TraciWorld()
    signal = TraciSignalState(approach.keys())
    st: dict = {"vs": None, "prev": None, "cands": [], "stall_pos": {}, "hits": []}

    def on_tick(step: int, t: float) -> None:
        snap = world.snapshot()
        if st["vs"] is None:
            dims = world.vtype_dimensions()
            vs = make(ClassTable.default().with_dimensions(dims) if dims else ClassTable.default())
            vs.incidents.signal = signal
            st["vs"] = vs
        vs = st["vs"]
        signal.refresh(t)
        vs.step_world(st["prev"], snap)
        vs.tick(t)
        st["prev"] = snap
        for h in vs.incidents.hits:
            ev = h.evidence
            anchor = ev.get("track") or ev.get("tracks") or int(h.s // 20.0)
            st["hits"].append([t, h.rule, h.lane_id, str(anchor), float(ev.get("measure", 0.0)),
                               [list(k) for k in h.links],
                               {k: ev[k] for k in ("sibling_flowing", "queued_behind", "class",
                                                   "swerves", "share", "from_stop_line_m")
                                if k in ev}])
        if injector is not None:
            # where each stalled vehicle actually is, for the coverage tag
            idx = snap.index()
            for act in getattr(injector, "_active_stalls", {}).values():
                vid = act.vehicle_id
                if vid in idx and vid not in st["stall_pos"]:
                    i = idx[vid]
                    lane = rig.network.lanes.get(snap.lane_id[i])
                    s = float(snap.lane_pos[i]) - (snap.length[i] / 2.0)
                    covered = False
                    if lane is not None and lane.lane_id in rig.coverage_by_lane:
                        covered = bool(rig.coverage_by_lane[lane.lane_id].covers(
                            np.array([s]))[0])
                    st["stall_pos"][vid] = {"lane": snap.lane_id[i], "s": s,
                                            "covered": covered}

    run = M.run_scenario("webster", level, seed, inputs=H.scenario_inputs(level),
                         on_tick=on_tick, max_steps=MAX_STEPS, incident_injector=injector,
                         tag=f"inc_{preset}_{int(inject)}")
    windows = []
    for w in (injector.realised_windows() if injector is not None else []):
        if w.kind == "stall":
            pos = st["stall_pos"].get(w.vehicle_id or "", {})
            covered = bool(pos.get("covered", False))
        else:
            cov = rig.coverage_by_lane.get(w.lane_id)
            covered = cov is not None and cov.fraction > 0
        windows.append({"kind": w.kind, "lane": w.lane_id, "tls": w.intersection_id,
                        "links": list(w.link_ids), "start": w.actual_start_tick,
                        "end": w.end_tick, "covered": covered,
                        "stall": st["stall_pos"].get(w.vehicle_id or "")
                        if w.kind == "stall" else None})
    return {
        "preset": preset, "level": level, "seed": seed, "inject": inject, "fps": fps,
        "run": run, "windows": windows, "hits": st["hits"],
        "sim_hours": run["steps"] / 3600.0, "wall_s": round(time.time() - t0, 1),
    }


# ---- offline scoring ---------------------------------------------------------------------

DEFAULT_POLICY = {
    "stuck_sibling_s": 15.0, "stuck_alone_s": 45.0,
    "midblock_s": 30.0, "midblock_dwell_s": 90.0, "midblock_impact_s": 15.0,
    "void_s": 90.0, "void_min_swerves": 3, "void_min_from_stop_line_m": 60.0,
    "void_min_share": 0.3, "collision_s": 10.0, "wrong_way_s": 3.0,
    "persist_ticks": 3, "rules": ["stuck_on_green", "midblock_stop", "wrong_way",
                                  "collision_cue", "flow_void"],
}


def _threshold(rule: str, measure_flags: dict, pol: dict) -> float | None:
    """The threshold a hit must reach under `pol`, or None if a gate other
    than duration excludes it."""
    if rule not in pol["rules"]:
        return None
    if rule == "stuck_on_green":
        return pol["stuck_sibling_s"] if measure_flags.get("sibling_flowing") else \
            pol["stuck_alone_s"]
    if rule == "midblock_stop":
        if measure_flags.get("queued_behind", 0) >= 2:
            return pol["midblock_impact_s"]
        if measure_flags.get("class") in ("bus", "auto_rickshaw"):
            return pol["midblock_dwell_s"]
        return pol["midblock_s"]
    if rule == "flow_void":
        if measure_flags.get("swerves", 0) < pol["void_min_swerves"]:
            return None
        if measure_flags.get("from_stop_line_m", 1e9) < pol["void_min_from_stop_line_m"]:
            return None
        if measure_flags.get("share", 0.0) < pol["void_min_share"]:
            return None
        return pol["void_s"]
    if rule == "collision_cue":
        return pol["collision_s"]
    if rule == "wrong_way":
        return pol["wrong_way_s"]
    return None


CLEAR_S = 20.0      # RuleConfig.clear_s: an episode ends once its hit has been gone this long
COOLDOWN_S = 120.0  # RuleConfig.cooldown_s: no new candidate at the same place before this


def candidates_under(hits: list, pol: dict) -> list[dict]:
    """Replay the logged hits under a policy exactly as `IncidentEngine`
    raises and resolves candidates: a hit is *present* on a tick where its
    measure meets the policy's threshold; a candidate is raised once it has
    been present for `persist_ticks` ticks (counted from its first presence,
    through gaps shorter than `CLEAR_S`); the episode resolves when the hit
    has been absent for `CLEAR_S`, and the same place cannot raise again for
    `COOLDOWN_S`. The first version raised at most one candidate per place
    per run, which under-counted false alarms that recur at one spot."""
    by_key: dict = {}
    for t, rule, lane, anchor, measure, links, flags in hits:
        by_key.setdefault((rule, lane, anchor), []).append((t, measure, links, flags))
    persist_s = max(0, pol["persist_ticks"] - 1)
    out = []
    for (rule, lane, _), seq in by_key.items():
        seq.sort(key=lambda x: x[0])
        first_over: float | None = None
        last_seen: float | None = None
        raised = False
        cooldown_until = -1e18
        for t, measure, links, flags in seq:
            th = _threshold(rule, flags, pol)
            if th is None or measure < th:
                continue  # below the operating threshold: the engine sees no hit
            if last_seen is not None and t - last_seen >= CLEAR_S:
                if raised:  # the previous episode resolved, and cooled down from then
                    cooldown_until = last_seen + CLEAR_S + COOLDOWN_S
                raised, first_over = False, None
            last_seen = t
            if first_over is None:
                first_over = t
            if not raised and t >= cooldown_until and t - first_over >= persist_s:
                out.append({"t": t, "rule": rule, "lane": lane, "links": links})
                raised = True
    return out


def score(run: dict, pol: dict) -> dict:
    cands = candidates_under(run["hits"], pol)
    matched: set[int] = set()
    rows = []
    for w in run["windows"]:
        targets = {(w["tls"], lk) for lk in w["links"]}
        end = (w["end"] or MAX_STEPS) + LATENCY_GRACE_S
        best = None
        for k, c in enumerate(cands):
            if w["start"] <= c["t"] <= end and any(tuple(lk) in targets for lk in c["links"]):
                lat = c["t"] - w["start"]
                if best is None or lat < best[0]:
                    best = (lat, k)
        if best is not None:
            matched.add(best[1])
        rows.append({**{k: w[k] for k in ("kind", "lane", "covered")},
                     "detected": best is not None,
                     "latency_s": best[0] if best is not None else None,
                     "rule": cands[best[1]]["rule"] if best is not None else None})
    fa = [c for k, c in enumerate(cands) if k not in matched and not any(
        w["start"] <= c["t"] <= (w["end"] or MAX_STEPS) + LATENCY_GRACE_S
        for w in run["windows"])]
    return {"windows": rows, "false_alarms": fa, "hours": run["sim_hours"]}


def summarise(runs: list[dict], pol: dict) -> dict:
    rows, fa, hours = [], [], 0.0
    for r in runs:
        sc = score(r, pol)
        rows += sc["windows"]
        fa += sc["false_alarms"]
        hours += sc["hours"]
    inview = [w for w in rows if w["covered"]]
    lat = [w["latency_s"] for w in inview if w["detected"]]
    by_rule: dict = {}
    for c in fa:
        by_rule[c["rule"]] = by_rule.get(c["rule"], 0) + 1
    return {
        "incidents": len(rows), "in_view": len(inview),
        "recall_all": sum(w["detected"] for w in rows) / len(rows) if rows else None,
        "recall_in_view": sum(w["detected"] for w in inview) / len(inview) if inview else None,
        "mean_latency_s": sum(lat) / len(lat) if lat else None,
        "false_alarms": len(fa), "hours": hours,
        "false_alarms_per_hour": len(fa) / hours if hours else None,
        "false_alarms_by_rule": by_rule,
        "by_kind": {k: {"n": sum(1 for w in inview if w["kind"] == k),
                        "detected": sum(1 for w in inview if w["kind"] == k and w["detected"])}
                    for k in ("stall", "lane_block")},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", default="finetuned_day")
    ap.add_argument("--levels", default="medium,heavy")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed-set", choices=["eval", "train"], default="eval")
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--no-twins", action="store_true", help="skip the incident-off twin runs")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true",
                    help="keep the runs already in --out and run only the missing ones")
    args = ap.parse_args()
    seeds = (M.EVAL_SEEDS if args.seed_set == "eval" else M.TRAIN_SEEDS)[: args.seeds]
    injects = (True,) if args.no_twins else (True, False)
    jobs = [(p, lv, s, args.fps, inj) for lv in args.levels.split(",")
            for p in args.presets.split(",") for s in seeds for inj in injects]
    out: list[dict] = M.previous_runs(args.out, "runs") if args.resume else []
    done = {(r["preset"], r["level"], r["seed"], r["inject"]) for r in out}
    jobs = [j for j in jobs if (j[0], j[1], j[2], j[4]) not in done]
    print(f"{len(jobs)} runs to do ({len(out)} kept)", flush=True)
    t0 = time.time()
    total = len(jobs) + len(out)
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for r in pool.map(_job, jobs):
            out.append(r)
            sm = summarise([r], DEFAULT_POLICY)
            print(f"[{len(out)}/{total}] {r['preset']:14s} {r['level']:6s} seed={r['seed']} "
                  f"inject={int(r['inject'])} incidents {sm['incidents']} "
                  f"(in view {sm['in_view']}) recall(in view) {sm['recall_in_view']}  "
                  f"false alarms {sm['false_alarms']} in {r['sim_hours']:.2f} h "
                  f"({r['wall_s']:.0f}s)", flush=True)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(
                {"meta": {"presets": args.presets, "levels": args.levels, "seeds": seeds,
                          "fps": args.fps, "wall_min": round((time.time() - t0) / 60, 1)},
                 "runs": out}, indent=1, default=str))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

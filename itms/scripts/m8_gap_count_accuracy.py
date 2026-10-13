"""Does counting the queue past the view make the queue estimate better? (M8)

Open loop, so both estimators see the same traffic: CC-A-CAMP runs on ground
truth while the vision system films the corridor, and every tick the same
tracks go to two estimators -- the default one, which counts the queue past
the view on edges filmed at both ends (`vision_service/state/gap_count.py`),
and one with that switched off. Each is scored against the true halted PCU
(`QueueStateSampler`'s definition) on every approach lane of a counted edge,
from `--warmup` on.

    python scripts/m8_gap_count_accuracy.py --level heavy --seeds 101,102 \\
        --out results/m8_gap_count_accuracy.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_harness as M  # noqa: E402
import traci  # noqa: E402
from sim_service.signal_controller.queue_state import _HALTING_SPEED_MPS  # noqa: E402
from vision_service.simcam import TraciWorld  # noqa: E402
from vision_service.state import EstimatorConfig, LinkStateEstimator  # noqa: E402


def one(preset: str, level: str, seed: int, warmup: float, every: int) -> dict:
    inputs = M.ccacamp_inputs(level)
    vtype_pcu = inputs[2]
    approach, receiving = M.link_maps()
    make = M.vision_factory(preset, seed, 5.0)
    world = TraciWorld()
    state: dict = {"vs": None, "prev": None, "off": None}
    rows: list = []

    def on_tick(step: int, t: float) -> None:
        snap = world.snapshot()
        if state["vs"] is None:
            from vision_service.classes import ClassTable  # noqa: PLC0415

            dims = world.vtype_dimensions()
            vs = make(ClassTable.default().with_dimensions(dims) if dims else ClassTable.default())
            state["vs"] = vs
            state["off"] = LinkStateEstimator(vs.rig, approach, receiving,
                                              EstimatorConfig(gap_counting=False))
            state["lanes"] = sorted({ln for g in vs.estimator.gaps.values() for ln in g.lanes
                                     if any(ln in links.values() for links in approach.values())})
        vs = state["vs"]
        # true PCU entering and leaving each counted edge, to judge the counts
        for edge in vs.estimator.gaps:
            now = set(traci.edge.getLastStepVehicleIDs(edge))
            was = state.setdefault("on_edge", {}).get(edge, set())
            tio = state.setdefault("true_io", {}).setdefault(edge, [0.0, 0.0])
            tio[0] += sum(vtype_pcu.get(traci.vehicle.getTypeID(v), 1.0) for v in now - was)
            tio[1] += len(was - now)   # vehicles gone: PCU looked up when they entered
            state["on_edge"][edge] = now
        vs.step_world(state["prev"], snap)
        res = vs.tick(t, keep_tracks=True)
        health = {cid: s[1] for cid, s in res.camera_status.items()}
        state["off"].update(t, res.tracks, health)
        state["prev"] = snap
        if step % every == 0:
            for edge, g in vs.estimator.gaps.items():
                hidden_true = 0.0
                for ln in g.lanes:
                    for v in traci.lane.getLastStepVehicleIDs(ln):
                        if traci.vehicle.getLanePosition(v) < g.near_start[ln]:
                            hidden_true += vtype_pcu.get(traci.vehicle.getTypeID(v), 1.0) \
                                if traci.vehicle.getSpeed(v) < _HALTING_SPEED_MPS else 0.0
                state.setdefault("edge_rows", []).append((edge, t, hidden_true, g.hidden))
        if t < warmup or step % every:
            return
        for ln in state["lanes"]:
            truth = sum(vtype_pcu.get(traci.vehicle.getTypeID(v), 1.0)
                        for v in traci.lane.getLastStepVehicleIDs(ln)
                        if traci.vehicle.getSpeed(v) < _HALTING_SPEED_MPS)
            on, off = vs.estimator.lanes.get(ln), state["off"].lanes.get(ln)
            if on is None or off is None:
                continue
            rows.append((ln, truth, on.queue_pcu, off.queue_pcu))

    t0 = time.time()
    run = M.run_scenario("ccacamp", level, seed, inputs=inputs, on_tick=on_tick,
                         tag=f"gapacc_{preset}")
    per_lane: dict = {}
    for ln in sorted({r[0] for r in rows}):
        sel = [r for r in rows if r[0] == ln]
        per_lane[ln] = _score(sel)
    big = [r for r in rows if r[1] >= 15.0]   # the ticks where a long queue stood
    edges = {}
    for edge, g in state["vs"].estimator.gaps.items():
        er = [r for r in state.get("edge_rows", []) if r[0] == edge and r[1] >= warmup]
        edges[edge] = {
            "counted_in_pcu": round(g.in_pcu, 1), "counted_out_pcu": round(g.out_pcu, 1),
            "true_in_pcu": round(state["true_io"][edge][0], 1),
            "true_out_vehicles": state["true_io"][edge][1], "anchors": g.anchors,
            "hidden_bias": round(st.fmean(r[3] - r[2] for r in er), 2) if er else None,
            "hidden_mae": round(st.fmean(abs(r[3] - r[2]) for r in er), 2) if er else None,
            "hidden_true_mean": round(st.fmean(r[2] for r in er), 2) if er else None,
            "hidden_max_counted": round(max((r[3] for r in er), default=0.0), 1),
            "hidden_max_true": round(max((r[2] for r in er), default=0.0), 1)}
    return {"preset": preset, "level": level, "seed": seed, "n": len(rows),
            "all": _score(rows), "true_queue_at_least_15_pcu": _score(big),
            "per_lane": per_lane, "edges": edges, "person_delay_s": run["person_delay_s"],
            "wall_s": round(time.time() - t0, 1)}


def _score(sel: list) -> dict:
    if not sel:
        return {"n": 0}
    return {"n": len(sel), "truth_mean": round(st.fmean(r[1] for r in sel), 3),
            "counted": {"bias": round(st.fmean(r[2] - r[1] for r in sel), 3),
                        "mae": round(st.fmean(abs(r[2] - r[1]) for r in sel), 3)},
            "visible_only": {"bias": round(st.fmean(r[3] - r[1] for r in sel), 3),
                             "mae": round(st.fmean(abs(r[3] - r[1]) for r in sel), 3)}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="itms6_640")
    ap.add_argument("--level", default="heavy")
    ap.add_argument("--seeds", default="101,102")
    ap.add_argument("--warmup", type=float, default=300.0)
    ap.add_argument("--every", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = []
    for seed in (int(s) for s in args.seeds.split(",")):
        r = one(args.preset, args.level, seed, args.warmup, args.every)
        out.append(r)
        print(json.dumps({k: r[k] for k in ("level", "seed", "n", "all",
                                            "true_queue_at_least_15_pcu")}), flush=True)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

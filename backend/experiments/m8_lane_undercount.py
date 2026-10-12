"""Where does a camera's queue go missing? (M8 jam investigation)

Runs one camera-driven closed-loop scenario (the jam case by default) and,
every `--every` seconds, splits the true halted vehicles on the chosen
approach lanes into:

* out_of_view  -- behind the stretch any camera covers;
* in_view      -- inside it; of those, how many the estimator counted as
                  stopped queue, and the tracks it dropped as furniture.

    python scripts/m8_lane_undercount.py --lanes 470178558_2,470178558_0 \\
        --max-steps 1400 --out results/jam/undercount_s5.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_harness as M  # noqa: E402
import traci  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="vision:itms6_640:failsafe")
    ap.add_argument("--level", default="heavy")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--lanes", default="470178558_2,470178558_0,470178558_1")
    ap.add_argument("--every", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=0, help="0: the whole run")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from vision_service.sim.closed_loop import VisionLoop, VisionSensor  # noqa: PLC0415

    _, preset, mode, *_ = args.arm.split(":")
    inputs = M.ccacamp_inputs(args.level)
    base = M.build_strategy("ccacamp", inputs)
    approach, _ = M.link_maps()
    loop = VisionLoop(M.vision_factory(preset, args.seed, 5.0), approach.keys())
    strategy = {tls: VisionSensor(c, loop, tls, mode) for tls, c in base.items()}
    lanes = args.lanes.split(",")
    rows: list = []

    def on_tick(step: int, t: float) -> None:
        sysm = loop.system
        if sysm is None or step % args.every:
            return
        est = sysm.estimator
        rig = sysm.rig
        for lid in lanes:
            lane = rig.network.lanes[lid]
            cov = rig.coverage(lid)
            view0 = lane.length - cov.covered_from_end_m
            halted = [traci.vehicle.getLanePosition(v)
                      for v in traci.lane.getLastStepVehicleIDs(lid)
                      if traci.vehicle.getSpeed(v) < 0.1]
            le = est.lanes.get(lid)
            tracks = est.lane_tracks.get(lid, [])
            furn = [g for g in tracks if est._is_furniture(t, g)]  # noqa: SLF001
            stopped_tr = [g for g in tracks if g.stopped and not est._is_furniture(t, g)]  # noqa: SLF001
            gap = est.gaps.get(lane.edge_id)
            vt = inputs[2]
            pcu_beyond = sum(vt.get(traci.vehicle.getTypeID(v), 1.0)
                             for v in traci.lane.getLastStepVehicleIDs(lid)
                             if traci.vehicle.getSpeed(v) < 0.1
                             and traci.vehicle.getLanePosition(v) < view0)
            rows.append({
                "true_halted_pcu": round(sum(
                    vt.get(traci.vehicle.getTypeID(v), 1.0)
                    for v in traci.lane.getLastStepVehicleIDs(lid)
                    if traci.vehicle.getSpeed(v) < 0.1), 1),
                "true_halted_pcu_beyond_view": round(pcu_beyond, 1),
                "gap": None if gap is None else {
                    "hidden_edge": round(gap.hidden, 1), "n_between": round(gap.n_between, 1),
                    "in": round(gap.in_pcu, 1), "out": round(gap.out_pcu, 1),
                    "anchors": gap.anchors},
                "t": t, "lane": lid,
                "true_halted": len(halted),
                "true_halted_in_near_view": sum(p >= view0 for p in halted),
                "true_back_m": round(lane.length - min(halted), 1) if halted else 0.0,
                "tracks": len(tracks), "stopped_tracks": len(stopped_tr),
                "furniture_tracks": len(furn),
                "furniture_stopped_truth": sum(1 for g in furn if g.truth_id),
                "est_stopped_pcu": round(le.stopped_pcu, 1) if le else None,
                "est_hidden_pcu": round(le.hidden_pcu, 1) if le else None,
                "est_back_m": round(le.queue_back_m, 1) if le else None,
                "truncated": bool(le.truncated) if le else None,
                "view_from_end_m": round(cov.covered_from_end_m, 1),
            })

    rec = M.run_scenario("ccacamp", args.level, args.seed, inputs=inputs, strategy=strategy,
                         tag="undercount", on_tick=on_tick, max_steps=args.max_steps or None)
    print("delay", round(rec["person_delay_s"]), "steps", rec["steps"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rows))
    for r in rows:
        if r["lane"] == lanes[0] and r["t"] % 100 == 0:
            print(r)


if __name__ == "__main__":
    main()

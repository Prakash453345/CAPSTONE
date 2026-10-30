"""M7 routing benchmark: does the route choice get the emergency vehicle (EV)
there sooner?

The earlier M7 gate ran on one corridor, which has only one route, so a
router could not help there. This one uses networks with many routes,
background demand, and (optionally) an incident placed on the free-flow
shortest path after dispatch.

Arms (same seed, same O-D, same incident, same preemption):
    dist        free-flow fastest path, fixed (no live data, no reroute)
    weighted    production RoutePlanner (weighted RouteCostModel) with the
                production reroute rule (severe anomaly ahead, or >35 %
                cheaper score; 3 s monitor, 30 s cooldown, 3 % progress)
    eta         EtaCostModel (seconds) + A*, fixed after dispatch
    eta_rr      EtaCostModel + reroute when should_reroute() (same gates)
    eta_hex     eta_rr, but each plan searches only the hex band and the
                monitor samples only band edges between full sweeps

Preemption is the same simple reactive rule in every arm: within
`PREEMPT_RANGE_M` of a signal on its path, the EV's links get green.
Background signals run their fixed programs; this isolates route choice.

One JSON line per run goes to --out.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tempfile
import time
from pathlib import Path

import traci

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "services" / "sim-service"))

from sim_service.routing import EdgeConditions, NoRouteError, RoadGraph, RoutePlanner  # noqa: E402
from sim_service.routing.eta_cost import EtaCostModel, should_reroute  # noqa: E402
from sim_service.routing.hexgrid import HexIndex  # noqa: E402
from sim_service.routing.search import GraphSearchEngine  # noqa: E402

GEN = _ROOT / "scenarios" / "generated"
DISPATCH_S = 600.0
INCIDENT_AFTER_S = 20.0
DETECT_DELAY_S = 10.0
INCIDENT_SPEED_MPS = 2.0
INCIDENT_DURATION_S = 900.0
END_S = 3600.0
MONITOR_S = 3.0
COOLDOWN_S = 30.0
MIN_PROGRESS_FRAC = 0.03
PREEMPT_RANGE_M = 150.0
HEX_FULL_SWEEP_S = 60.0
HEX_RINGS = int(os.environ.get("HEX_RINGS", "2"))

EV_TYPE_XML = """<additional>
  <vType id="ev" vClass="emergency" speedFactor="1.2" guiShape="emergency"
         lcStrategic="10" lcSpeedGain="10" minGap="1.5">
    <param key="has.bluelight.device" value="true"/>
  </vType>
</additional>
"""


def pick_od(graph: RoadGraph, rng: random.Random, min_frac: float = 0.45):
    xs = [p for e in graph.edges.values() for p in (e.start_xy[0], e.end_xy[0])]
    ys = [p for e in graph.edges.values() for p in (e.start_xy[1], e.end_xy[1])]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    cands = [
        e for e, info in graph.edges.items()
        if graph.neighbours(e) and info.length_m > 20 and info.speed_limit_mps > 5
    ]
    eng = GraphSearchEngine(graph)
    for _ in range(500):
        o, d = rng.sample(cands, 2)
        a, b = graph.edges[o].end_xy, graph.edges[d].start_xy
        if math.hypot(a[0] - b[0], a[1] - b[1]) < min_frac * diag:
            continue
        ff = eng.shortest_path(o, d, lambda _f, ge: graph.edges[ge.to_edge].free_flow_time_s)
        if ff.found and len(ff.edges) >= 6:
            return o, d, ff.edges
    raise RuntimeError("no O-D pair found")


def sample(graph: RoadGraph, edges, anomalies: dict) -> dict[str, EdgeConditions]:
    out = {}
    for e in edges:
        info = graph.edges[e]
        occ = traci.edge.getLastStepOccupancy(e)
        ms = traci.edge.getLastStepMeanSpeed(e)
        halt = traci.edge.getLastStepHaltingNumber(e)
        sf = 1.0 if ms < 0 else min(1.0, ms / max(0.1, info.speed_limit_mps))
        sev = anomalies.get(e)
        out[e] = EdgeConditions(
            congestion=max(0.0, min(1.0, occ)),
            mean_speed_frac=sf,
            halting=float(halt),
            anomaly_severity=sev[0] if sev else None,
            anomaly_impact=sev[1] if sev else 0.0,
        )
    return out


def run_one(net: str, level: str, seed: int, arm: str, incident: bool) -> dict:
    d = GEN / net
    cfg = d / f"{net}_{level}.sumocfg"
    graph = RoadGraph.from_network(d / f"{net}.net.xml")
    rng = random.Random(seed * 7919 + sum(map(ord, net)))
    o, dst, ff_path = pick_od(graph, rng)
    inc_edge = None
    if incident:
        lo, hi = int(len(ff_path) * 0.4), max(int(len(ff_path) * 0.7), int(len(ff_path) * 0.4) + 1)
        inc_edge = ff_path[rng.randrange(lo, hi)]

    eta_model = EtaCostModel(lefthand=graph.lefthand)
    planner = (
        RoutePlanner(graph) if arm == "weighted"
        else RoutePlanner(graph, cost_model=eta_model, static_prior=arm.endswith("_p"))
        if arm.startswith("eta") else None
    )
    hexi = HexIndex(graph) if arm.startswith("eta_hex") else None

    tmp = tempfile.mkdtemp()
    add = Path(tmp) / "ev.add.xml"
    add.write_text(EV_TYPE_XML)
    traci.start([
        "sumo", "-c", str(cfg), "--seed", str(seed), "-a", str(add), "--end", str(END_S),
        "--no-step-log", "true", "--no-warnings", "true", "--time-to-teleport", "300",
        "--device.bluelight.reactiondist", "60",
    ])
    anomalies: dict[str, tuple[str, float]] = {}
    stats = {"plans": 0, "plan_ms": [], "reroutes": 0, "sampled_edges": 0, "samples": 0}
    all_edges = list(graph.edges)
    try:
        while traci.simulation.getTime() < DISPATCH_S:
            traci.simulationStep()

        def plan(src, conds, band=None):
            t0 = time.perf_counter()
            res = planner.plan(src, dst, conds, allowed_edges=band)
            stats["plans"] += 1
            stats["plan_ms"].append((time.perf_counter() - t0) * 1000)
            return res[0]

        def full_sample():
            stats["sampled_edges"] += len(all_edges)
            stats["samples"] += 1
            return sample(graph, all_edges, anomalies)

        band = None
        if arm == "dist":
            route = list(ff_path)
        else:
            conds = full_sample()
            if hexi is not None:
                hexi.update_state(conds, eta_model.ev_speed)
                band = hexi.band(o, dst, rings=HEX_RINGS, avoid_edges=anomalies)
            first = plan(o, conds, band)
            route = list(first.edges)
            stats["pred_s"] = round(first.score, 1)
            stats["pred_ff_s"] = round(planner.evaluate(tuple(ff_path), conds).score, 1)
        last_full = traci.simulation.getTime()
        traci.route.add("evr", route)
        traci.vehicle.add("EV", "evr", typeID="ev", departLane="best", departSpeed="max")
        t_start = traci.simulation.getTime()
        last_route_t = t_start
        last_mon = t_start
        progress_at_route = 0.0
        total_len = sum(graph.edges[e].length_m for e in route)
        severe_seen = False
        held: dict[str, str] = {}  # tls -> original program
        arrived_t = None
        inc_on = False
        while traci.simulation.getTime() < END_S:
            traci.simulationStep()
            now = traci.simulation.getTime()
            for v in traci.simulation.getStartingTeleportIDList():
                stats["teleports"] = stats.get("teleports", 0) + 1
                if v == "EV":
                    stats["ev_teleported"] = True
            if "EV" in traci.simulation.getArrivedIDList():
                arrived_t = now
                break
            if incident and not inc_on and now >= t_start + INCIDENT_AFTER_S:
                traci.edge.setMaxSpeed(inc_edge, INCIDENT_SPEED_MPS)
                inc_on = True
            if inc_on and now >= t_start + INCIDENT_AFTER_S + INCIDENT_DURATION_S:
                traci.edge.setMaxSpeed(inc_edge, graph.edges[inc_edge].speed_limit_mps)
            if inc_on and inc_edge not in anomalies and (
                now >= t_start + INCIDENT_AFTER_S + DETECT_DELAY_S
            ):
                anomalies[inc_edge] = ("high", 0.8)
            if "EV" not in traci.vehicle.getIDList():
                continue
            # --- reactive preemption, identical in all arms
            nxt = traci.vehicle.getNextTLS("EV")
            near = {}
            for tls_id, link_idx, dist, _st in nxt:
                if dist <= PREEMPT_RANGE_M:
                    near[tls_id] = link_idx
                break
            for tls_id in list(held):
                if tls_id not in near:
                    traci.trafficlight.setProgram(tls_id, held.pop(tls_id))
            for tls_id, li in near.items():
                if tls_id not in held:
                    held[tls_id] = traci.trafficlight.getProgram(tls_id)
                st = list(traci.trafficlight.getRedYellowGreenState(tls_id))
                want = ["G" if i == li else ("r" if c in "GgyYuo" else c) for i, c in enumerate(st)]
                # keep every link sharing the EV's lane group green too
                links = traci.trafficlight.getControlledLinks(tls_id)
                ev_from = links[li][0][0] if links[li] else None
                for i, lk in enumerate(links):
                    if lk and lk[0][0] == ev_from:
                        want[i] = "G"
                traci.trafficlight.setRedYellowGreenState(tls_id, "".join(want))
            # --- monitor / reroute
            if arm in ("dist", "eta", "eta_p"):
                continue
            if now - last_mon < MONITOR_S:
                continue
            last_mon = now
            if now - last_route_t < COOLDOWN_S:
                continue
            cur = traci.vehicle.getRoadID("EV")
            if cur.startswith(":") or cur not in graph.edges:
                continue
            ridx = traci.vehicle.getRouteIndex("EV")
            remaining = tuple(route[ridx:]) if ridx >= 0 else ()
            if len(remaining) < 2 or remaining[0] != cur:
                continue
            done = sum(graph.edges[e].length_m for e in route[:ridx])
            if (done - progress_at_route) / max(1.0, total_len) < MIN_PROGRESS_FRAC:
                continue
            if hexi is not None:
                if now - last_full >= HEX_FULL_SWEEP_S:
                    conds = full_sample()
                    hexi.update_state(conds, eta_model.ev_speed)
                    last_full = now
                band = hexi.band(cur, dst, rings=HEX_RINGS, avoid_edges=anomalies) or set(all_edges)
                band |= set(remaining)
                stats["sampled_edges"] += len(band)
                stats["samples"] += 1
                conds = sample(graph, band, anomalies)
            else:
                conds = full_sample()
            try:
                new = plan(cur, conds, band if hexi is not None else None)
                cur_eval = planner.evaluate(remaining, conds)
            except NoRouteError:
                continue
            switch = False
            if tuple(new.edges) != remaining:
                if arm == "weighted":
                    severe = any(e in anomalies for e in remaining) and not severe_seen
                    if severe:
                        severe_seen = True
                        switch = True
                    elif cur_eval.score > new.score * 1.35:
                        switch = True
                else:
                    switch = should_reroute(cur_eval.score, new.score, eta_model.config)
            elif arm == "weighted" and any(e in anomalies for e in remaining):
                severe_seen = True
            if switch:
                traci.vehicle.setRoute("EV", list(new.edges))
                route = route[:ridx] + list(new.edges)
                total_len = sum(graph.edges[e].length_m for e in route)
                progress_at_route = done
                last_route_t = now
                stats["reroutes"] += 1
        tt = (arrived_t - t_start) if arrived_t is not None else END_S - t_start
        return {
            "net": net, "level": level, "seed": seed, "arm": arm, "incident": incident,
            "ev_time_s": round(tt, 1), "arrived": arrived_t is not None,
            "route_len_m": round(total_len, 1), "inc_on_route": bool(inc_edge in route),
            "reroutes": stats["reroutes"], "plans": stats["plans"],
            "plan_ms_mean": round(sum(stats["plan_ms"]) / max(1, len(stats["plan_ms"])), 2),
            "plan_ms_max": round(max(stats["plan_ms"], default=0.0), 2),
            "edges_sampled_per_tick": round(stats["sampled_edges"] / max(1, stats["samples"]), 1),
            "ev_teleported": stats.get("ev_teleported", False),
            "net_teleports_after_dispatch": stats.get("teleports", 0),
            "pred_s": stats.get("pred_s"), "pred_ff_s": stats.get("pred_ff_s"),
            "first_route_is_ff": route[: len(ff_path)] == list(ff_path),
            "n_edges": len(all_edges), "od": [o, dst], "incident_edge": inc_edge,
        }
    finally:
        traci.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--level", default="medium")
    ap.add_argument("--seeds", required=True, help="e.g. 1-10")
    ap.add_argument("--arms", default="dist,weighted,eta,eta_rr")
    ap.add_argument("--incident", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.seeds.split("-"))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "a") as f:
        for seed in range(lo, hi + 1):
            for arm in a.arms.split(","):
                r = run_one(a.net, a.level, seed, arm, bool(a.incident))
                f.write(json.dumps(r) + "\n")
                f.flush()
                print(r["net"], r["level"], seed, arm, r["ev_time_s"], r["reroutes"], flush=True)


if __name__ == "__main__":
    main()

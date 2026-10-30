"""Simulation check (real SUMO, no Redis): one ambulance, three accidents, and
a road blocked ahead of a moving ambulance.

Runs the live controllers (anomalies, green corridor, emergency routing,
incident response) on the Vijayawada corridor, stepping SUMO directly, with
the ambulance fleet cut to ONE hospital. Script:

  t=300 s  accident an-A, MEDIUM            -> the ambulance goes there
  t=310 s  accidents an-B and an-C, HIGH    -> queued; a reassignment of the
                                              ambulance (still on its way to
                                              the medium call) is suggested;
                                              the "operator" accepts it
  t+5 s after the ambulance sets off for an-B: a road 2-4 edges ahead on
           its route is BLOCKED             -> expect a reroute within one
                                              monitor interval (~3 s), even
                                              though the route is < 30 s old,
                                              and a new green corridor
Then it runs until every accident has had an ambulance or 2 h of simulated
time pass, and prints the timeline.

usage: python scripts/m7_dispatch_queue_check.py [seed]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import traci

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "services" / "sim-service"))

from itms_domain.scenario import current  # noqa: E402
from sim_service.control.dispatch.facilities import Facility, FacilityIndex  # noqa: E402
from sim_service.live.anomaly_control import OperatorAnomalyController  # noqa: E402
from sim_service.live.emergency_control import EmergencyController  # noqa: E402
from sim_service.live.green_corridor import CorridorController  # noqa: E402
from sim_service.live.incident_response import (  # noqa: E402
    FACILITIES_PATH,
    IncidentResponseOrchestrator,
)
from sim_service.routing import RoadGraph  # noqa: E402

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 1
END_S = 7200


def main() -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    reroutes: list[tuple[float, str]] = []
    corridors: list[tuple[float, str]] = []

    class _Grab(logging.Handler):
        def emit(self, record):  # noqa: D102
            msg = record.getMessage()
            t_now = traci.simulation.getTime() if traci.isLoaded() else -1
            if msg.startswith("auto-reroute"):
                reroutes.append((t_now, msg))
            elif "green corridor" in msg and "armed" in msg:
                corridors.append((t_now, msg))

    logging.getLogger("sim-service").addHandler(_Grab())
    scen = current()
    cfg = scen.levels["medium"][0]
    graph = RoadGraph.from_network(scen.net)
    if FACILITIES_PATH.exists():
        full = FacilityIndex.from_json(FACILITIES_PATH)
        hospital = next(f for f in full._facilities if f.kind == "hospital")  # noqa: SLF001
    else:
        # a network without a facility register (generated test networks):
        # put one stand-in hospital on the edge nearest the network's centre
        xs = [p for e in graph.edges.values() for p in (e.start_xy[0], e.end_xy[0])]
        ys = [p for e in graph.edges.values() for p in (e.start_xy[1], e.end_xy[1])]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        centre = min((e for e in graph.edges.values() if graph.neighbours(e.edge_id)),
                     key=lambda e: (e.start_xy[0] - cx) ** 2 + (e.start_xy[1] - cy) ** 2)
        hospital = None
    traci.start(["sumo", "-c", str(cfg), "--seed", str(SEED), "--no-step-log", "true",
                 "--no-warnings", "true", "--time-to-teleport", "300"])
    if hospital is None:
        # generated networks have no map projection (projParameter "!"), so
        # SUMO hands back metres as "degrees" and the hex index cannot work.
        # For this check only, lay the network's metres over a patch of
        # ground near Vijayawada.
        import math as _m

        import sim_service.live.incident_response as _ir

        def _latlon(edge_id: str) -> tuple[float, float]:
            x, y = graph.edges[edge_id].start_xy
            return 16.5 + y / 111_000.0, 80.6 + x / (111_000.0 * _m.cos(_m.radians(16.5)))

        _ir.edge_latlon = _latlon
        lat, lon = _latlon(centre.edge_id)
        hospital = Facility(id="hosp-test", name="Test Hospital", kind="hospital",
                            edge=centre.edge_id, edge_offset_m=5.0, lat=lat, lon=lon,
                            capabilities=frozenset({"general"}))
    one = FacilityIndex([hospital])
    anomalies = OperatorAnomalyController()
    corridor = CorridorController(graph)
    emergency = EmergencyController(graph, anomalies, corridor_controller=corridor)
    orch = IncidentResponseOrchestrator(anomalies, emergency, facility_index=one,
                                        police_depots=[] if not FACILITIES_PATH.exists() else None)
    amb = [u.vehicle_id for u in orch._units[next(k for k in orch._units  # noqa: SLF001
                                                   if k.name == "AMBULANCE")]]
    print("ambulances:", amb, "hospital:", hospital.name, hospital.edge)

    # incident roads: reachable from the hospital, not the hospital road
    # incident roads by route length from the hospital, so an-B is far enough
    # away (>= 10 roads) for a road ahead of the ambulance to be blocked
    from sim_service.routing.search import GraphSearchEngine
    eng = GraphSearchEngine(graph)
    hops = {}
    for e in graph.edges:
        if e == hospital.edge or not graph.neighbours(e) or graph.edges[e].length_m < 60:
            continue
        r = eng.shortest_path(hospital.edge, e,
                              lambda _f, ge: graph.edges[ge.to_edge].free_flow_time_s)
        if r.found:
            hops[e] = len(r.edges)
    top = max(hops.values())
    far = sorted((e for e, n in hops.items() if n >= max(5, top - 2)), key=lambda e: (hops[e], e))
    mid = sorted((e for e, n in hops.items() if 3 <= n < max(5, top - 2)),
                 key=lambda e: (hops[e], e))
    sites = {"an-A": mid[len(mid) // 2], "an-B": far[len(far) // 2], "an-C": mid[-1]}
    timeline: list[str] = []
    served: dict[str, float] = {}
    block_at = None
    blocked_edge = None
    reroute_seen = None
    route_set_t = None
    route_set_t_b = None

    def create(aid: str, sev: str, t: float, step: int, edge: str, atype: str = "ACCIDENT"):
        anomalies.handle_create({"anomaly_id": aid, "edge_id": edge, "severity": sev,
                                 "anomaly_type": atype, "duration_s": 7200},
                                step=step, sim_time_s=t)
        timeline.append(f"t={t:6.0f}  {aid} {sev} {atype} on {edge}")

    step = 0
    try:
        while traci.simulation.getTime() < END_S:
            traci.simulationStep()
            step += 1
            t = traci.simulation.getTime()
            if t == 300:
                create("an-A", "MEDIUM", t, step, sites["an-A"])
            if t == 310:
                create("an-B", "HIGH", t, step, sites["an-B"])
                create("an-C", "HIGH", t, step, sites["an-C"])
            anomalies.tick(step, t)
            emergency.tick(step, t)
            orch.tick(step, t)
            emergency.drain_events()  # reroutes are read from the log (see _Grab)
            for ev in orch.drain_events():
                for d in ev.get("dispatched", []):
                    if d["vehicle_kind"] == "AMBULANCE":
                        served[ev["anomaly_id"]] = t
                        route_set_t = t
                        extra = ""
                        if ev.get("waited_s") is not None:
                            extra += f" after waiting {ev['waited_s']:.0f} s"
                        if ev.get("reassigned_from"):
                            extra += f", moved from {ev['reassigned_from']}"
                        timeline.append(f"t={t:6.0f}  ambulance -> {ev['anomaly_id']}"
                                        f" ({ev['severity']}){extra}")
                        if ev["anomaly_id"] == "an-B" and block_at is None:
                            block_at = -1.0  # arm the block for after departure
                            route_set_t_b = t
                if "ambulance" in ev.get("queued_kinds", []) and not ev.get("reassign_suggestions"):
                    timeline.append(f"t={t:6.0f}  {ev['anomaly_id']} ({ev['severity']}): "
                                    "no free ambulance -> queued")
                for s in ev.get("reassign_suggestions", []):
                    timeline.append(f"t={t:6.0f}  SUGGEST move {s['vehicle_id']} from "
                                    f"{s['from_anomaly_id']} ({s['from_severity']}) to "
                                    f"{ev['anomaly_id']} ({ev['severity']}); operator accepts")
                    orch.accept_reassignment(s["suggestion_id"], step=step, sim_time_s=t)
            # block a road ahead 5 s after the ambulance set off for an-B
            if block_at == -1.0 and route_set_t is not None and t >= route_set_t + 5:
                req = next((r for r in emergency.active_requests()
                            if r.vehicle_id in amb and r.destination_edge == sites["an-B"]), None)
                if req is not None and req.route is not None:
                    here = emergency.current_edge(req.request_id)
                    edges = list(req.route.edges)
                    i = edges.index(here) if here in edges else 0
                    ahead = edges[i + 1:-1]
                    timeline.append(f"t={t:6.0f}  ambulance on {here}, {len(edges) - i} roads"
                                    " left on its route")
                    # block the first road ahead (not the next one) that has
                    # a way round, so the reroute can actually avoid it
                    from sim_service.routing import EdgeConditions
                    pick = None
                    for cand in ahead[1:]:
                        try:
                            alt = emergency.planner.plan(
                                here, req.destination_edge,
                                {cand: EdgeConditions(anomaly_severity="blocked")})
                        except Exception:  # noqa: BLE001
                            continue
                        if alt and cand not in alt[0].edges:
                            pick = cand
                            break
                    if pick is not None:
                        blocked_edge = pick
                        create("blk-1", "BLOCKED", t, step, blocked_edge, "LANE_BLOCKAGE")
                        block_at = t
                    else:
                        block_at = None
            waiting = [w for w in orch.waiting if w["kind"] == "ambulance"]
            if all(a in served for a in sites) and not waiting and t > 400:
                break
    finally:
        traci.close()
    if block_at not in (None, -1.0):
        after = [(t_, m) for t_, m in reroutes if t_ >= block_at]
        if after:
            reroute_seen = after[0][0]
            timeline.append(f"t={reroute_seen:6.0f}  {after[0][1]}")
            arm = [(t_, m) for t_, m in corridors if t_ >= reroute_seen][:1]
            if arm:
                timeline.append(f"t={arm[0][0]:6.0f}  {arm[0][1]}")
            timeline.append(f"          -> rerouted {reroute_seen - block_at:.0f} s after the "
                            f"block, {reroute_seen - route_set_t_b:.0f} s after its route was set; "
                            f"{len(after)} reroute(s) for this block in total")
    print("\n".join(timeline))
    print(json.dumps({"all_served": all(a in served for a in sites),
                      "still_waiting": [w["anomaly_id"] for w in orch.waiting],
                      "served_at": served, "reroute_after_block_s":
                      None if reroute_seen is None or block_at in (None, -1.0)
                      else reroute_seen - block_at}))


if __name__ == "__main__":
    main()

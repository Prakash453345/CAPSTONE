"""Randomised stress test of the live emergency stack in real SUMO (no Redis):
anomaly -> incident response (dispatch, waiting queue, reassignment) ->
emergency routing (monitoring, reroute) -> green corridor.

A seeded random script throws a mix of situations at it:
  * accidents (medium / high) and blockages at random places and times,
    many more than the fleet can serve at once (1-2 units per kind);
  * roads blocked just ahead of an emergency vehicle that is driving;
  * anomalies cleared early or expiring on their own;
  * the "operator" cancelling random trips and accepting about half of the
    reassignment suggestions (the rest are ignored).

After every simulated second it checks rules that must always hold. Any
broken rule is printed with the time and what broke it:

  R1  a vehicle never has two live trips
  R2  a unit is marked busy exactly when it has a live trip
  R3  no unit sits free while a call of its kind waits
  R4  a freshly reported call is never sent a unit while an older call of the
      same kind and at least the same priority keeps waiting (since the
      27 Oct fix a new call joins the queue when any call of its kind waits,
      so on the fixed code R4b is the check that matters)
  R4b a waiting call is never served while a call of the same kind with a
      higher priority is left waiting
  R5  every call for a live anomaly is being served, waiting, or was stood
      down by the operator -- never silently dropped
  R6  a trip leaves ROUTE_READY / GREEN_CORRIDOR_ACTIVE within 60 s
  R7  a driving vehicle with a signal still ahead on its route has a green
      corridor (checked 5 s after any reroute)
  R8  no corridor outlives its trip
  R9  a blocked road ahead of a driving vehicle that has a way round is
      left behind (rerouted) within 10 s
  R10 a call no unit can reach is not retried (one failed trip per call)
  R11 no open reassignment suggestion points at a trip that ended or a call
      that is no longer waiting
  R12 no unit's vehicle is still driving in SUMO without a live trip

usage (from the repo root):
  [ITMS_SCENARIO=<scenario dir>] python scripts/m7_dispatch_stress.py <seed> [units] [end_s] [out.json]
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
import traceback
from collections import defaultdict
from pathlib import Path

import traci

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "services" / "sim-service"))

from itms_domain import EmergencyKind, EmergencyRequestState as S  # noqa: E402
from itms_domain.scenario import current  # noqa: E402
from sim_service.control.dispatch.facilities import Facility, FacilityIndex  # noqa: E402
from sim_service.live.anomaly_control import OperatorAnomalyController  # noqa: E402
from sim_service.live.emergency_control import EmergencyController  # noqa: E402
from sim_service.live.green_corridor import CorridorController  # noqa: E402
import sim_service.live.incident_response as ir  # noqa: E402
from sim_service.routing import EdgeConditions, RoadGraph  # noqa: E402
from sim_service.routing.search import GraphSearchEngine  # noqa: E402

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 1
UNITS = int(sys.argv[2]) if len(sys.argv) > 2 else 1
END_S = float(sys.argv[3]) if len(sys.argv) > 3 else 2400.0
OUT = sys.argv[4] if len(sys.argv) > 4 else None
START_S = 200.0  # let traffic build first
rng = random.Random(SEED)


def main() -> dict:
    scen = current()
    graph = RoadGraph.from_network(scen.net)
    traci.start(["sumo", "-c", str(scen.levels["medium"][0]), "--seed", str(SEED),
                 "--no-step-log", "true", "--no-warnings", "true",
                 "--time-to-teleport", "300"])
    eng = GraphSearchEngine(graph)
    ff = lambda _f, ge: graph.edges[ge.to_edge].free_flow_time_s  # noqa: E731
    usable = sorted(e for e in graph.edges if graph.neighbours(e) and graph.edges[e].length_m >= 60)

    # ---- fleet ----------------------------------------------------------
    if ir.FACILITIES_PATH.exists():
        full = FacilityIndex.from_json(ir.FACILITIES_PATH)
        hosp = [f for f in full._facilities if f.kind == "hospital"]  # noqa: SLF001
        rng.shuffle(hosp)
        hospitals = hosp[:UNITS]
        depots = ir.load_police_depots()
        rng.shuffle(depots)
        police = depots[:UNITS]
    else:
        # generated network: no projection, no facility files. Lay metres
        # over a patch near Vijayawada and put stand-in hospitals on roads
        # that reach most of the network.
        def _latlon(edge_id: str) -> tuple[float, float]:
            x, y = graph.edges[edge_id].start_xy
            return 16.5 + y / 111_000.0, 80.6 + x / (111_000.0 * math.cos(math.radians(16.5)))

        ir.edge_latlon = _latlon
        picks = rng.sample(usable, 40)
        hospitals = []
        for e in picks:
            if len(hospitals) == UNITS:
                break
            n = sum(eng.shortest_path(e, d, ff).found for d in rng.sample(usable, 15))
            if n >= 13:
                lat, lon = _latlon(e)
                hospitals.append(Facility(id=f"hosp-{e}", name=f"Hospital {e}", kind="hospital",
                                          edge=e, edge_offset_m=5.0, lat=lat, lon=lon,
                                          capabilities=frozenset({"general"})))
        police = [ir._Depot(depot_id=f"ps-{h.edge}", name=f"PS {h.edge}", edge=h.edge,  # noqa: SLF001
                            lat=h.lat, lon=h.lon) for h in hospitals]
    anomalies = OperatorAnomalyController()
    corridor = CorridorController(graph)
    emergency = EmergencyController(graph, anomalies, corridor_controller=corridor)
    orch = ir.IncidentResponseOrchestrator(anomalies, emergency,
                                           facility_index=FacilityIndex(hospitals),
                                           police_depots=police)
    units = {k.name: [u.vehicle_id for u in v] for k, v in orch._units.items()}  # noqa: SLF001
    # incident sites: reachable from the first hospital and back
    h0 = hospitals[0].edge
    sites = [e for e in rng.sample(usable, min(len(usable), 400))
             if e != h0 and eng.shortest_path(h0, e, ff).found
             and eng.shortest_path(e, h0, ff).found][:120]

    # ---- bookkeeping ------------------------------------------------------
    viol: list[dict] = []
    seen_v: set[tuple] = set()
    stats = defaultdict(int)

    def bad(rule: str, key, t: float, msg: str) -> None:
        if (rule, key) in seen_v:
            return
        seen_v.add((rule, key))
        viol.append({"rule": rule, "t": t, "msg": msg})
        print(f"  !! {rule} t={t:.0f} {msg}", flush=True)

    op_cancelled: set[str] = set()          # request ids the operator stood down
    state_since: dict[str, tuple[S, float]] = {}
    corridor_missing_since: dict[str, float] = {}
    blocked_since: dict[tuple[str, str], float] = {}
    planned_blocks: list[tuple[float, str, float]] = []   # (t, edge, duration)
    block_tried: set[str] = set()
    next_incident = START_S
    aid_n = 0
    resp_re = re.compile(r"^resp-(.+)-(police|ambulance|fire_truck)(-q\d+)?(-hospital)?$")

    def new_anomaly(t: float, step: int, edge: str, sev: str, atype: str, dur: float) -> str:
        nonlocal aid_n
        aid_n += 1
        aid = f"an{aid_n}"
        anomalies.handle_create({"anomaly_id": aid, "edge_id": edge, "severity": sev,
                                 "anomaly_type": atype, "duration_s": dur},
                                step=step, sim_time_s=t)
        stats[f"anomaly_{atype}_{sev}"] += 1
        return aid

    step = 0
    try:
        while traci.simulation.getTime() < END_S:
            traci.simulationStep()
            step += 1
            t = traci.simulation.getTime()
            # ---- the random script (before the controllers tick) ----------
            if t >= next_incident:
                next_incident = t + rng.uniform(60, 200)
                r = rng.random()
                edge = rng.choice(sites)
                if r < 0.7:
                    new_anomaly(t, step, edge, rng.choice(["MEDIUM", "HIGH"]),
                                "ACCIDENT", rng.uniform(400, 2400))
                elif r < 0.85:
                    new_anomaly(t, step, edge, "BLOCKED", "LANE_BLOCKAGE", rng.uniform(200, 900))
                else:
                    new_anomaly(t, step, edge, "LOW", "ACCIDENT", 600)
            for a in list(anomalies.active_anomalies()):
                if rng.random() < 1 / 3000:   # an operator clears one early now and then
                    anomalies.handle_clear({"anomaly_id": a.anomaly_id}, step=step, sim_time_s=t)
                    stats["cleared_early"] += 1
            for req in emergency.active_requests():
                if rng.random() < 1 / 4000 and resp_re.match(req.request_id):
                    emergency.handle_command({"request_id": req.request_id, "action": "CANCEL",
                                              "operator": "operator:stress"},
                                             step=step, sim_time_s=t)
                    op_cancelled.add(req.request_id)
                    stats["operator_cancels"] += 1
            for tb, e, dur in [p for p in planned_blocks if p[0] <= t]:
                planned_blocks.remove((tb, e, dur))
                if not any(a.edge_id == e for a in anomalies.active_anomalies()):
                    new_anomaly(t, step, e, "BLOCKED", "LANE_BLOCKAGE", dur)
                    stats["blocks_ahead"] += 1

            waiting_before = {k: c for k, c in orch._waiting.items()}  # noqa: SLF001
            anomalies.tick(step, t)
            emergency.tick(step, t)
            orch.tick(step, t)
            emergency.drain_events()
            emergency.drain_vehicle_events()
            fresh_dispatch: list[tuple[str, EmergencyKind]] = []
            queue_served: list[tuple[str, EmergencyKind, float]] = []
            for ev in orch.drain_events():
                for d in ev.get("dispatched", []):
                    stats["dispatches"] += 1
                    if ev.get("waited_s") is None and ev.get("anomaly_type") != "operator_request":
                        fresh_dispatch.append((ev["anomaly_id"],
                                               ir._KIND_BY_NAME[d["vehicle_kind"]]))  # noqa: SLF001
                    if ev.get("reassigned_from"):
                        stats["reassigned"] += 1
                    if ev.get("waited_s") is not None and not ev.get("reassigned_from"):
                        stats["served_from_queue"] += 1
                        sev = ir.AnomalySeverity(ev["severity"])
                        prio = ir._SEVERITY_RANK.get(sev, 1) + ev["waited_s"] / ir.QUEUE_AGING_S  # noqa: SLF001
                        queue_served.append((ev["anomaly_id"],
                                             ir._KIND_BY_NAME[d["vehicle_kind"]], prio))  # noqa: SLF001
                for s in ev.get("reassign_suggestions", []):
                    stats["suggestions"] += 1
                    if rng.random() < 0.5:
                        orch.accept_reassignment(s["suggestion_id"], step=step, sim_time_s=t)

            # schedule a block just ahead of a vehicle that has just set off
            for req in emergency.active_requests():
                if req.state is not S.IN_TRANSIT or req.request_id in block_tried:
                    continue
                block_tried.add(req.request_id)
                if rng.random() < 0.35 and req.route is not None:
                    here = emergency.current_edge(req.request_id)
                    edges = list(req.route.edges)
                    i = edges.index(here) if here in edges else 0
                    ahead = edges[i + 2:-1]
                    if ahead:
                        planned_blocks.append((t + 2, rng.choice(ahead[:4]), rng.uniform(200, 600)))

            # ---- rules ------------------------------------------------------
            live = emergency.active_requests()
            by_vehicle = defaultdict(list)
            for req in live:
                by_vehicle[req.vehicle_id].append(req.request_id)
            for v, rids in by_vehicle.items():
                if len(rids) > 1:
                    bad("R1", v, t, f"{v} has {len(rids)} live trips {rids}")
            for vid, unit in orch._unit_by_vehicle_id.items():  # noqa: SLF001
                if unit.busy != (vid in by_vehicle):
                    bad("R2", (vid, int(t) // 60), t,
                        f"{vid} busy={unit.busy} but live trips={by_vehicle.get(vid)}")
            for (aid, kind), call in orch._waiting.items():  # noqa: SLF001
                free = [u for u in orch._units.get(kind, ()) if not u.busy]  # noqa: SLF001
                if free:
                    bad("R3", (aid, kind), t, f"{kind.value} {free[0].vehicle_id} free while "
                        f"call {aid} ({call.severity.value}) waits")
            for aid, kind in fresh_dispatch:
                rank = None
                for (waid, wkind), wc in waiting_before.items():
                    if wkind is kind and (waid, wkind) in orch._waiting:  # noqa: SLF001
                        an = next((a for a in anomalies.active_anomalies()
                                   if a.anomaly_id == aid), None)
                        rank = ir._SEVERITY_RANK.get(an.severity, 1) if an else 0  # noqa: SLF001
                        if wc.priority(t) >= rank:
                            bad("R4", (aid, kind), t, f"new call {aid} got a {kind.value} while "
                                f"{waid} ({wc.severity.value}, waiting {t - wc.since_s:.0f} s) "
                                "keeps waiting")
            for (waid, wkind), wc in orch._waiting.items():  # noqa: SLF001
                for rid, served in orch._call_of_request.items():  # noqa: SLF001
                    rq = emergency.get_request(rid)
                    if (served.kind is wkind and served.rank < wc.rank and rq is not None
                            and rq.state in ir._EN_ROUTE):  # noqa: SLF001
                        stats["ticks_suggestable"] += 1
            for aid, kind, prio in queue_served:
                for (waid, wkind), wc in orch._waiting.items():  # noqa: SLF001
                    if (wkind is kind and (waid, wkind) in waiting_before  # not just requeued
                            and wc.priority(t) > prio + 1e-6
                            and not getattr(wc, "failed_units", None)):
                        bad("R4b", (aid, waid), t, f"waiting {aid} served while {waid} "
                            f"({wc.severity.value}, waiting {t - wc.since_s:.0f} s) "
                            "with higher priority keeps waiting")
            # R5 silent drop
            reqs_by_call = defaultdict(list)
            for rid, req in emergency._requests.items():  # noqa: SLF001
                m = resp_re.match(rid)
                if m and not m.group(4):
                    reqs_by_call[(m.group(1), m.group(2))].append(req)
            for a in anomalies.active_anomalies():
                if a.severity.name == "LOW" or t - a.created_at_ms / 1000.0 < 2:
                    continue
                for kind in ir._RESPONSE_MAP.get(a.anomaly_type, ()):  # noqa: SLF001
                    if not orch._units.get(kind):  # noqa: SLF001
                        continue
                    rs = reqs_by_call.get((a.anomaly_id, kind.value), [])
                    ok = (a.anomaly_id, kind) in orch._waiting or any(  # noqa: SLF001
                        (not r.is_terminal) or r.state is S.COMPLETED
                        or r.request_id in op_cancelled for r in rs)
                    if not ok:
                        bad("R5", (a.anomaly_id, kind), t,
                            f"call {a.anomaly_id}/{kind.value} dropped: "
                            f"{[(r.request_id, r.state.value) for r in rs]}")
                    failed = [r for r in rs if r.state is S.CANCELLED and r.route is None]
                    if len(failed) > 1:
                        bad("R10", (a.anomaly_id, kind), t,
                            f"call {a.anomaly_id}/{kind.value}: {len(failed)} failed trips")
            for req in live:
                prev = state_since.get(req.request_id)
                if prev is None or prev[0] is not req.state:
                    state_since[req.request_id] = (req.state, t)
                elif req.state in (S.ROUTE_READY, S.GREEN_CORRIDOR_ACTIVE) and t - prev[1] > 60:
                    bad("R6", req.request_id, t, f"{req.request_id} stuck in {req.state.value} "
                        f"for {t - prev[1]:.0f} s")
                if req.state is not S.IN_TRANSIT or req.route is None:
                    continue
                here = emergency.current_edge(req.request_id)
                edges = tuple(req.route.edges)
                rem = edges[edges.index(here):] if here in edges else edges
                run = emergency._ev_runs.get(req.request_id)  # noqa: SLF001
                try:
                    pos = traci.vehicle.getLanePosition(req.vehicle_id) \
                        if traci.vehicle.getRoadID(req.vehicle_id) == here else 0.0
                except traci.TraCIException:
                    pos = 0.0
                sig_ahead = [c for c in corridor.planner.crossings(rem) if c.distance_m > pos + 15]
                if sig_ahead and corridor.corridor_for(req.request_id) is None:
                    since = corridor_missing_since.setdefault(req.request_id, t)
                    if t - since > 5:
                        bad("R7", req.request_id, t, f"{req.request_id} has {len(sig_ahead)} "
                            f"signal(s) ahead and no corridor (route set "
                            f"{emergency._last_route_s.get(req.request_id, -1):.0f})")  # noqa: SLF001
                else:
                    corridor_missing_since.pop(req.request_id, None)
                forced = set(req.route.forced_through or ())
                for a in anomalies.active_anomalies():
                    if a.severity.name != "BLOCKED" or a.edge_id not in rem[1:-1] \
                            or a.edge_id in forced:
                        continue
                    k = (req.request_id, a.anomaly_id)
                    since = blocked_since.setdefault(k, t)
                    if t - since > 10 and run is not None:
                        alt = None
                        try:
                            alt = emergency.planner.plan(
                                here, req.destination_edge,
                                {a.edge_id: EdgeConditions(anomaly_severity="blocked")})
                        except Exception:  # noqa: BLE001
                            pass
                        if alt and a.edge_id not in alt[0].edges:
                            bad("R9", k, t, f"{req.request_id} still routed over blocked "
                                f"{a.edge_id} {t - since:.0f} s later though a way round exists")
            live_ids = {r.request_id for r in live}
            for rid in list(corridor._active):  # noqa: SLF001
                if rid not in live_ids:
                    bad("R8", rid, t, f"corridor for ended trip {rid}")
            for sid, s in orch._suggestions.items():  # noqa: SLF001
                req = emergency.get_request(s["request_id"])
                stale = (req is None or req.state not in ir._EN_ROUTE  # noqa: SLF001
                         or s["to"] not in orch._waiting)  # noqa: SLF001
                if stale:
                    bad("R11", sid, t, f"suggestion {sid} is stale but still open "
                        f"(blocks new suggestions for {s['vehicle_id']})")
            sumo_ids = set(traci.vehicle.getIDList())
            for vid in sumo_ids:
                if vid.startswith("unit-") and vid not in by_vehicle:
                    bad("R12", vid, t, f"{vid} still driving in SUMO with no live trip")
    except Exception:  # noqa: BLE001
        viol.append({"rule": "CRASH", "t": traci.simulation.getTime(),
                     "msg": traceback.format_exc()})
        print(traceback.format_exc())
    finally:
        try:
            traci.close()
        except Exception:  # noqa: BLE001
            pass
    reqs = emergency._requests.values()  # noqa: SLF001
    stats["trips"] = len(reqs)
    stats["completed"] = sum(r.state is S.COMPLETED for r in reqs)
    stats["reroutes"] = sum(1 for r in reqs for h in r.history if h.action.name == "REROUTE")
    stats["still_waiting"] = len(orch._waiting)  # noqa: SLF001
    res = {"scenario": scen.directory.name, "seed": SEED, "units": UNITS, "end_s": END_S,
           "fleet": units, "stats": dict(stats),
           "violations_by_rule": dict(sorted({v["rule"]: sum(x["rule"] == v["rule"] for x in viol)
                                              for v in viol}.items())),
           "violations": viol}
    print(json.dumps({k: res[k] for k in ("scenario", "seed", "units", "stats",
                                          "violations_by_rule")}))
    if OUT:
        Path(OUT).write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main()

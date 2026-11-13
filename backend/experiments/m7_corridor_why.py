"""Why does the corridor engine not beat reactive preemption? (diagnostic,
training seeds only; the benchmark itself is unchanged)

Runs `m7_corridor_benchmark.run_one` with the current controller inputs
(`m8_harness.ccacamp_inputs`) and, every tick, records for each emergency
vehicle:
  * every stop (speed < 0.1 m/s after moving): the next signal, its distance,
    the light the EV faces, vehicles ahead of it on its lane, whether the
    junction holds a reservation for it and in what state, and whether the
    engine is still tracking it;
  * every junction claim for it: when it was granted, how far away the EV was,
    when (and why) it was released, and when the EV actually crossed.

usage: python m7_corridor_why.py <arm> <seed> <out.json> [demand]
"""

from __future__ import annotations

import json
import sys

import m7_corridor_benchmark as B
import m8_harness as M
import traci

arm_name, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
demand = sys.argv[4] if len(sys.argv) > 4 else "medium"

state: dict = {"arm": None}
_build = B.build_arm


def build_arm(name):  # capture the engine
    a = _build(name)
    state["arm"] = a
    return a


B.build_arm = build_arm

if "@" in arm_name:
    # variants of the corridor engine's tunables, e.g. corridor@base_lead_s=12
    from sim_service.control.corridor import CorridorConfig
    base, _, spec = arm_name.partition("@")
    kw = {k: float(v) for k, v in (x.split("=") for x in spec.split(","))}

    def build_arm(name):  # noqa: F811
        a = _build(base, CorridorConfig(**kw))
        state["arm"] = a
        return a

    B.build_arm = build_arm


stops: list[dict] = []
claims: dict[tuple[str, str], dict] = {}     # (ev, tls) -> claim record
passes: dict[tuple[str, str], float] = {}    # (ev, tls) -> time crossed
moving: dict[str, bool] = {}
in_stop: dict[str, dict] = {}
next_tls: dict[str, str | None] = {}
dist_at: dict[tuple[str, str], list] = {}    # distance trace


class Injector(B._Injector):
    def __call__(self, now_s: float) -> None:
        super().__call__(now_s)
        eng = state["arm"].corridor if state["arm"] is not None else None
        live = set(traci.vehicle.getIDList())
        for ev in sorted(B.ev_vehicle_ids()):
            if ev not in live:
                continue
            nt = traci.vehicle.getNextTLS(ev)
            tl, li, dist, light = nt[0] if nt else (None, None, None, None)
            prev = next_tls.get(ev)
            if prev is not None and prev != tl:
                passes[(ev, prev)] = now_s
            next_tls[ev] = tl
            spd = traci.vehicle.getSpeed(ev)
            if tl is not None:
                dist_at.setdefault((ev, tl), []).append((now_s, round(dist, 1), round(spd, 2)))
            # claims
            if eng is not None:
                for jid, jp in eng._junctions.items():  # noqa: SLF001
                    r = jp.reservation
                    k = (ev, jid)
                    if r is not None and r.vehicle_id == ev:
                        c = claims.get(k)
                        if c is None or c.get("released_s") is not None and r.granted_at_s > c["granted_s"]:
                            d = next((x[2] for x in (nt or ()) if x[0] == jid), None)
                            claims[k] = c = {"granted_s": r.granted_at_s, "dist_at_grant": d,
                                             "speed_at_grant": spd, "n": (c or {}).get("n", 0) + 1,
                                             "released_s": None, "states": []}
                        st = jp.state.value
                        if not c["states"] or c["states"][-1][1] != st:
                            c["states"].append((now_s, st))
                    else:
                        c = claims.get(k)
                        if c is not None and c["released_s"] is None:
                            c["released_s"] = now_s
                            rel = jp.releases or {}
                            c["release_counts"] = {k2.value: v for k2, v in rel.items() if v}
            # stops
            if spd > 1.0:
                moving[ev] = True
            if moving.get(ev) and spd < 0.1 and ev not in in_stop:
                lead = traci.vehicle.getLeader(ev, 200.0)
                lane = traci.vehicle.getLaneID(ev)
                ahead = sum(1 for v in traci.lane.getLastStepVehicleIDs(lane)
                            if traci.vehicle.getLanePosition(v) > traci.vehicle.getLanePosition(ev))
                rec = {"t": now_s, "tls": tl, "dist": None if dist is None else round(dist, 1),
                       "light": light, "ahead_on_lane": ahead,
                       "leader_gap": None if lead is None else round(lead[1], 1),
                       "edge": traci.vehicle.getRoadID(ev), "lane": lane}
                # what the car in front is waiting for
                if lead is not None:
                    lv = lead[0]
                    lnt = traci.vehicle.getNextTLS(lv)
                    rec["leader"] = {"id": lv, "speed": round(traci.vehicle.getSpeed(lv), 2),
                                     "edge": traci.vehicle.getRoadID(lv),
                                     "next_tls": lnt[0][0] if lnt else None,
                                     "light": lnt[0][3] if lnt else None,
                                     "dist": round(lnt[0][2], 1) if lnt else None,
                                     "route_next": list(traci.vehicle.getRoute(lv)[
                                         traci.vehicle.getRouteIndex(lv):traci.vehicle.getRouteIndex(lv) + 2])}
                # first car on the lane (the head of the queue) and its light
                vs = sorted(traci.lane.getLastStepVehicleIDs(lane), key=traci.vehicle.getLanePosition)
                if vs:
                    h = vs[-1]
                    hnt = traci.vehicle.getNextTLS(h)
                    ri = traci.vehicle.getRouteIndex(h)
                    nxt = traci.vehicle.getRoute(h)[ri + 1:ri + 2]
                    rec["head"] = {"id": h, "speed": round(traci.vehicle.getSpeed(h), 2),
                                   "light": hnt[0][3] if hnt else None,
                                   "to_edge": nxt[0] if nxt else None,
                                   "to_edge_halting": traci.edge.getLastStepHaltingNumber(nxt[0]) if nxt else None,
                                   "to_edge_occ": round(traci.edge.getLastStepOccupancy(nxt[0]), 1) if nxt else None}
                ri = traci.vehicle.getRouteIndex(ev)
                er = traci.vehicle.getRoute(ev)
                if ri + 1 < len(er):
                    rec["ev_to_edge"] = er[ri + 1]
                if eng is not None and tl is not None:
                    jp = eng._junctions.get(tl)  # noqa: SLF001
                    r = jp.reservation if jp is not None else None
                    rec["reserved_for_ev"] = r is not None and r.vehicle_id == ev
                    rec["jp_state"] = jp.state.value if jp is not None else None
                    rec["tracked"] = ev in eng._tracks  # noqa: SLF001
                    rec["defers"] = ({k2.value: v for k2, v in (jp.defers or {}).items() if v}
                                     if jp is not None else None)
                in_stop[ev] = rec
            elif ev in in_stop and spd > 1.0:
                rec = in_stop.pop(ev)
                rec["dur"] = now_s - rec["t"]
                stops.append(rec)


B._Injector = Injector
rec = B.run_one(arm_name, demand, seed, inputs=M.ccacamp_inputs(demand))
for ev, rec_ in in_stop.items():
    rec_["dur"] = None
    stops.append(rec_)
res = {"arm": arm_name, "seed": seed, "demand": demand,
       "summary": {k: rec[k] for k in ("ev_duration_s", "ev_time_loss_s", "ev_waiting_time_s",
                                       "ev_stops", "n_ev_completed", "person_delay_s",
                                       "interlock_violations")},
       "corridor_stats": rec.get("corridor"),
       "stops": stops,
       "claims": [{"ev": k[0], "tls": k[1], **v, "crossed_s": passes.get(k)} for k, v in claims.items()],
       "passes": [{"ev": k[0], "tls": k[1], "t": v} for k, v in passes.items()]}
json.dump(res, open(out, "w"), indent=1, default=str)
print(json.dumps(res["summary"]))

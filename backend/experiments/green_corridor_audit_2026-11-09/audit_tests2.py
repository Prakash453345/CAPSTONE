"""Reroute (D), race (E) and fire/ambulance (F) tests. Run via audit_run2.py."""
from __future__ import annotations

import heapq
import random
import time
from collections import defaultdict

import traci

from audit_lib import World, dist_m, dump, largest_scc, sample_pairs, RESULTS
from itms_domain import EmergencyRequestState as S
from sim_service.routing import EdgeConditions, NoRouteError, RoutePlanner


def _pick_long_pair(w: World, rng: random.Random, min_edges=9, min_sig=2):
    scc = largest_scc(w.graph)
    pl = RoutePlanner(w.graph)
    edges = sorted(e for e in scc if w.graph.edges[e].length_m >= 80 and w.graph.neighbours(e))
    for _ in range(3000):
        a, b = rng.sample(edges, 2)
        if dist_m(w.graph, a, b) < 1500:
            continue
        r = pl.plan(a, b, {})[0]
        k = len(w.corridor.planner.crossings(tuple(r.edges)))
        if len(r.edges) >= min_edges and k >= min_sig:
            return a, b, list(r.edges)
    raise RuntimeError("no long pair")


# ---------------------------------------------------------------- D: reroute
def test_D(level: str, seed: int, variant: str) -> dict:
    """variant: ahead2..ahead5 | cutoff | flap | blockbefore"""
    w = World(level, seed, "full", end_s=1500)
    rng = random.Random(500 + seed)
    a, b, route = _pick_long_pair(w, rng)
    T = 500.0
    w.at(T, "dispatch", rid="ev0", vid="EV0", src=a, dst=b, tag=variant)
    st = {"blocked": None, "block_t": None, "entered_blocked": 0, "left_t": None,
          "flaps": 0, "first_reroute_t": None, "route_after": None, "armed_after": None,
          "alt_exists": None, "done": False, "flap_events": 0}
    pl = RoutePlanner(w.graph)

    def hook(step, t):
        req = w.emergency.get_request("ev0")
        if req is None or t < T + 1:
            return
        here = w.emergency.current_edge("ev0")
        if st["blocked"] is None and t >= T + 8 and req.state is S.IN_TRANSIT and req.route:
            edges = list(req.route.edges)
            i = edges.index(here) if here in edges else 0
            if variant.startswith("ahead"):
                k = int(variant[5:])
                cand = edges[i + k: i + k + 1]
                if not cand or cand[0] == edges[-1]:
                    st["skipped"] = "route too short"; st["blocked"] = "-"; return
                st["blocked"] = cand[0]
            elif variant == "flap":
                cand = edges[i + 3: i + 4]
                if not cand or cand[0] == edges[-1]:
                    st["skipped"] = "route too short"; st["blocked"] = "-"; return
                st["blocked"] = cand[0]
            elif variant == "cutoff":
                # every road leading INTO the destination is blocked: no way round exists
                st["blocked"] = "CUT"
                preds = [e for e in w.graph.edges if any(n.to_edge == b for n in w.graph.neighbours(e))]
                st["cut_edges"] = preds
                for j, p in enumerate(preds):
                    w.do_anomaly(step, t, f"cut{j}", p, "BLOCKED", "LANE_BLOCKAGE", 900.0)
                st["block_t"] = t
                return
            try:
                alt = pl.plan(here, b, {st["blocked"]: EdgeConditions(anomaly_severity="blocked")})
                st["alt_exists"] = st["blocked"] not in alt[0].edges
            except NoRouteError:
                st["alt_exists"] = False
            w.do_anomaly(step, t, "blk", st["blocked"], "BLOCKED", "LANE_BLOCKAGE", 900.0)
            st["block_t"] = t
        if variant == "flap" and st["block_t"] and st["blocked"] not in (None, "-") and \
                t < st["block_t"] + 120 and int(t - st["block_t"]) % 5 == 0 and int(t) != st.get("lastflap"):
            st["lastflap"] = int(t)
            on = any(x.anomaly_id == "blk" for x in w.anomalies.active_anomalies())
            if on:
                w.do_clear(step, t, "blk")
            else:
                w.do_anomaly(step, t, "blk", st["blocked"], "BLOCKED", "LANE_BLOCKAGE", 900.0)
            st["flap_events"] += 1
        if st["blocked"] not in (None, "-", "CUT") and variant != "flap":
            if req.route and st["blocked"] not in req.route.edges and st["left_t"] is None:
                st["left_t"] = t
                st["route_after"] = list(req.route.edges)
                st["armed_after"] = bool(w.corridor.corridor_for("ev0"))
        try:
            road = traci.vehicle.getRoadID("EV0")
        except traci.TraCIException:
            road = ""
        if st["blocked"] not in (None, "-", "CUT") and road == st["blocked"]:
            st["entered_blocked"] += 1

    w.hooks.append(hook)
    res = w.run()
    ev = res["evs"][0] if res["evs"] else {}
    res["D"] = {"variant": variant, "src": a, "dst": b, "route_len": len(route), **st,
                "time_to_leave_blocked_s": (st["left_t"] - st["block_t"]) if st["left_t"] and st["block_t"] else None}
    return res


# ---------------------------------------------------------------- E1: crossing EVs
def test_E1(level: str, seed: int) -> dict:
    w = World(level, seed, "full", end_s=1900)
    g = w.graph
    rng = random.Random(900 + seed)
    # signalised moves grouped by signal
    by_tl: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in g.edges:
        for n in g.neighbours(e):
            if n.signalised and n.tl_id:
                by_tl[n.tl_id].append((e, n.to_edge))
    preds: dict[str, list[str]] = defaultdict(list)
    for e in g.edges:
        for n in g.neighbours(e):
            preds[n.to_edge].append(e)

    def upstream(e, hops=2):
        cur = e
        for _ in range(hops):
            p = [x for x in preds[cur] if g.edges[x].length_m >= 60 and x != cur]
            if not p:
                break
            cur = rng.choice(p)
        return cur

    pl = RoutePlanner(g)
    trials = []
    tls_list = [t for t, mv in by_tl.items() if len({m[0] for m in mv}) >= 3]
    rng.shuffle(tls_list)
    offsets = [0, 2, -2, 5, -5, 10, -10]
    t0 = 400.0
    slot = 0
    for tl in tls_list[:2]:
        mv = by_tl[tl]
        ins = sorted({m[0] for m in mv})
        # two moves from different approaches
        m1 = rng.choice([m for m in mv if m[0] == ins[0]])
        m2 = rng.choice([m for m in mv if m[0] == ins[1]])
        for d in offsets:
            o1, o2 = upstream(m1[0]), upstream(m2[0])
            try:
                r1 = pl.plan(o1, m1[1], {})[0]; r2 = pl.plan(o2, m2[1], {})[0]
            except Exception:
                continue
            c1 = [c for c in w.corridor.planner.crossings(tuple(r1.edges)) if c.tl_id == tl]
            c2 = [c for c in w.corridor.planner.crossings(tuple(r2.edges)) if c.tl_id == tl]
            if not c1 or not c2:
                continue
            eta1, eta2 = c1[0].eta_s, c2[0].eta_s
            tA = t0 + slot * 110
            tB = tA + (eta1 - eta2) + d      # B reaches the signal d seconds after A
            tB = max(tB, tA - 40)
            trials.append({"tl": tl, "offset_s": d, "A": f"A{slot}", "B": f"B{slot}", "tA": tA, "tB": tB})
            w.at(tA, "dispatch", rid=f"A{slot}", vid=f"VA{slot}", src=o1, dst=m1[1], tag=f"{tl}:{d}")
            w.at(tB, "dispatch", rid=f"B{slot}", vid=f"VB{slot}", src=o2, dst=m2[1], tag=f"{tl}:{d}")
            slot += 1
    w.end_s = t0 + slot * 110 + 250
    res = w.run()
    res["trials"] = trials
    return res


# ---------------------------------------------------------------- E2: N concurrent
def test_E2(level: str, seed: int) -> dict:
    w = World(level, seed, "full", end_s=2300)
    scc = largest_scc(w.graph)
    rng = random.Random(1300 + seed)
    edges = sorted(e for e in scc if w.graph.edges[e].length_m >= 80 and w.graph.neighbours(e))
    waves = []
    for i, n in enumerate((2, 4, 6, 10)):
        t = 400.0 + i * 450
        ids = []
        for k in range(n):
            a, b = rng.sample(edges, 2)
            while dist_m(w.graph, a, b) < 600:
                a, b = rng.sample(edges, 2)
            rid = f"w{n}_{k}"
            ids.append(rid)
            w.at(t, "dispatch", rid=rid, vid=f"V{n}_{k}", src=a, dst=b, tag=f"wave{n}")
        waves.append({"n": n, "t": t, "ids": ids})
    res = w.run()
    res["waves"] = waves
    return res


# ---------------------------------------------------------------- E3: command races
def test_E3(level: str, seed: int) -> dict:
    w = World(level, seed, "full", end_s=900)
    scc = largest_scc(w.graph)
    rng = random.Random(77 + seed)
    pairs = sample_pairs(w.graph, scc, rng, 8, need_signal=True)
    P = [(a, b) for a, b, _, _ in pairs]
    inv = {"two_live_trips": 0, "examples": []}

    def hook(step, t):
        by_v = defaultdict(list)
        for r in w.emergency.active_requests():
            by_v[r.vehicle_id].append(r.request_id)
        for v, rids in by_v.items():
            if len(rids) > 1:
                inv["two_live_trips"] += 1
                if len(inv["examples"]) < 4:
                    inv["examples"].append({"t": t, "vehicle": v, "requests": rids})

    w.hooks.append(hook)
    T = 100.0
    a, b = P[0]
    # a) duplicate create id (same tick) + double ACTIVATE
    w.at(T, "dispatch", rid="dup", vid="VD", src=a, dst=b, tag="dup1")
    w.at(T, "dispatch", rid="dup", vid="VD", src=a, dst=b, tag="dup2")      # same id again
    w.at(T, "command", rid="dup", action="ACTIVATE_CORRIDOR")
    # b) cancel same tick as create
    a2, b2 = P[1]
    w.at(T + 50, "dispatch", rid="cc", vid="VC", src=a2, dst=b2, activate=False, tag="cancel_same_tick")
    w.at(T + 50, "cancel", rid="cc")
    w.at(T + 50, "command", rid="cc", action="ACTIVATE_CORRIDOR")            # activate after cancel
    # c) src == dst
    w.at(T + 100, "dispatch", rid="same", vid="VS", src=P[2][0], dst=P[2][0], tag="src_eq_dst")
    # d) unknown edges
    w.at(T + 110, "dispatch", rid="ghost", vid="VG", src="NOPE_EDGE", dst=P[2][1], tag="unknown_src")
    w.at(T + 112, "dispatch", rid="ghost2", vid="VG2", src=P[2][0], dst="NOPE_EDGE", tag="unknown_dst")
    # e) one vehicle, two different requests, same tick
    a3, b3 = P[3]
    w.at(T + 150, "dispatch", rid="v1", vid="VSAME", src=a3, dst=b3, tag="double_book_1")
    w.at(T + 150, "dispatch", rid="v2", vid="VSAME", src=P[4][0], dst=P[4][1], tag="double_book_2")
    # f) cancel twice, cancel unknown, recalculate before depart, cancel after arrival (late)
    a5, b5 = P[5]
    w.at(T + 200, "dispatch", rid="x5", vid="VX5", src=a5, dst=b5, tag="cancel_twice")
    w.at(T + 205, "cancel", rid="x5"); w.at(T + 205, "cancel", rid="x5")
    w.at(T + 206, "cancel", rid="does_not_exist")
    w.at(T + 207, "command", rid="x5", action="RECALCULATE")
    w.at(T + 208, "command", rid="x5", action="BOGUS_ACTION")
    # g) anomaly races: create+clear same tick, duplicate id, unknown edge, clear unknown
    e = P[6][0]
    w.at(T + 250, "anomaly", aid="an1", edge=e, severity="BLOCKED")
    w.at(T + 250, "clear", aid="an1")
    w.at(T + 252, "anomaly", aid="an2", edge=e, severity="HIGH", atype="ACCIDENT")
    w.at(T + 252, "anomaly", aid="an2", edge=e, severity="BLOCKED")
    w.at(T + 254, "anomaly", aid="an3", edge="NOPE_EDGE", severity="BLOCKED")
    w.at(T + 255, "clear", aid="never_existed")
    # h) request to a destination on a road blocked at creation
    a7, b7 = P[7]
    w.at(T + 300, "anomaly", aid="an4", edge=b7, severity="BLOCKED")
    w.at(T + 301, "dispatch", rid="toblocked", vid="VTB", src=a7, dst=b7, tag="dest_blocked")
    res = w.run()
    res["inv"] = inv
    res["requests"] = {r: (q.state.value, q.route is not None) for r, q in w.emergency._requests.items()}
    return res


# ---------------------------------------------------------------- F: fire / ambulance
def _drain(w):
    return w.all_orch_events


def test_F(variant: str, seed: int) -> dict:
    """variant: current | patched (hypothetical fix, in-process only)"""
    import sim_service.live.incident_response as ir
    from itms_domain import AnomalyType, EmergencyKind
    w = World("light", seed, "full", end_s=1300, with_orch=True)
    if variant == "patched":
        ir._RESPONSE_MAP = dict(ir._RESPONSE_MAP)
        ir._RESPONSE_MAP[AnomalyType.FIRE] = (EmergencyKind.FIRE_TRUCK, EmergencyKind.POLICE,
                                              EmergencyKind.AMBULANCE)
        # fire trucks based at the police depots (what service.py already assumes for crew home edges)
        for i, u in enumerate(list(w.orch._units[EmergencyKind.POLICE])):
            nu = w.orch._unit(f"unit-fire-{i}", EmergencyKind.FIRE_TRUCK, u.depot)
            w.orch._units[EmergencyKind.FIRE_TRUCK].append(nu)
            w.orch._unit_by_vehicle_id[nu.vehicle_id] = nu
    scc = largest_scc(w.graph)
    rng = random.Random(4242)
    edges = sorted(e for e in scc if w.graph.edges[e].length_m >= 80 and w.graph.neighbours(e))
    locs = rng.sample(edges, 20)
    # a fresh, idle fleet for every incident: one incident per 60 s, 20 FIRE then 20 ACCIDENT
    plan = []
    for i, e in enumerate(locs):
        sev = ("MEDIUM", "HIGH", "BLOCKED")[i % 3]
        w.at(100 + i * 25, "anomaly", aid=f"fire{i}", edge=e, severity=sev, atype="FIRE", dur=300)
        plan.append((f"fire{i}", "FIRE", sev, e))
    for i, e in enumerate(locs):
        sev = ("MEDIUM", "HIGH", "BLOCKED")[i % 3]
        w.at(100 + (20 + i) * 25, "anomaly", aid=f"acc{i}", edge=e, severity=sev, atype="ACCIDENT", dur=300)
        plan.append((f"acc{i}", "ACCIDENT", sev, e))
    w.end_s = 100 + 40 * 25 + 150
    res = w.run()
    ev_by_a = {e["anomaly_id"]: e for e in w.all_orch_events if "anomaly_id" in e}
    rows = []
    for aid, typ, sev, edge in plan:
        e = ev_by_a.get(aid)
        rows.append({"aid": aid, "type": typ, "sev": sev, "edge": edge,
                     "dispatched": [d["vehicle_kind"] for d in (e or {}).get("dispatched", [])],
                     "queued": (e or {}).get("queued_kinds"), "undispatched": (e or {}).get("undispatched_kinds"),
                     "seen": e is not None})
    res["F"] = {"variant": variant, "rows": rows,
                "units": {k.name: len(v) for k, v in w.orch._units.items()}}
    return res


def test_F3() -> dict:
    """Coverage: free-flow ETA from the nearest ambulance depot to every road (no SUMO)."""
    from itms_domain.scenario import current
    from sim_service.routing import RoadGraph
    from sim_service.control.dispatch.facilities import FacilityIndex
    from sim_service.live.service import _snapped_depots, _snapped_facilities
    from sim_service.routing.snap import EdgeSnapper
    import sim_service.live.incident_response as ir
    scen = current()
    g = RoadGraph.from_network(scen.net)
    sn = EdgeSnapper(scen.net, g)
    fi = _snapped_facilities(sn)
    hosp = ir.load_hospital_depots(fi)
    pol = _snapped_depots(sn)

    def multi_source(srcs):
        dist = {}
        pq = [(0.0, s) for s in srcs if s in g.edges]
        for d, s in pq:
            dist[s] = 0.0
        heapq.heapify(pq)
        while pq:
            d, e = heapq.heappop(pq)
            if d > dist.get(e, 1e18):
                continue
            for n in g.neighbours(e):
                nd = d + g.edges[n.to_edge].free_flow_time_s
                if nd < dist.get(n.to_edge, 1e18):
                    dist[n.to_edge] = nd
                    heapq.heappush(pq, (nd, n.to_edge))
        return dist

    out = {"scenario_edges": len(g.edges), "ambulance_depots": len(hosp),
           "ambulance_depot_edges": len({h.edge for h in hosp}), "police_depots": len(pol)}
    for name, srcs in (("ambulance", [h.edge for h in hosp]), ("police", [p.edge for p in pol])):
        d = multi_source(srcs)
        vals = sorted(d.get(e, 1e9) for e in g.edges)
        out[name] = {"unreachable": sum(1 for v in vals if v >= 1e9),
                     "median_s": vals[len(vals) // 2], "p90_s": vals[int(len(vals) * .9)],
                     "max_s": vals[-1], "over_300s": sum(1 for v in vals if v > 300),
                     "over_600s": sum(1 for v in vals if v > 600)}
        far = sorted(g.edges, key=lambda e: -d.get(e, 1e9))[:10]
        out[name]["farthest"] = [(e, round(d.get(e, 1e9))) for e in far]
    return out

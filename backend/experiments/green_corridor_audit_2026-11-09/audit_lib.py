"""Shared harness for the 2026-11-09 green-corridor / reroute / race / fire audit.

Wires the same pieces `sim_service.live.service.run_live` wires, minus Redis:
Webster strategy + arbiter (`run_controlled_scenario`), `CorridorController.
preemption_plan` as the preempt source, `EmergencyController`, and (when asked)
`IncidentResponseOrchestrator`. Real SUMO, SIM_NETWORK=district.

Arms:
    plain       fixed free-flow route, NO reroute, signals ignore the corridor
    route_only  planner + reroute monitor, signals ignore the corridor
    full        planner + reroute monitor + corridor preemption (production wiring)
"""
from __future__ import annotations

import json
import math
import os
import random
import logging
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("SIM_NETWORK", "district")

import traci  # noqa: E402

from itms_domain import EmergencyRequestState as S  # noqa: E402
from itms_domain.scenario import current  # noqa: E402
from sim_service.control.runner import run_controlled_scenario  # noqa: E402
from sim_service.live.anomaly_control import OperatorAnomalyController  # noqa: E402
from sim_service.live.corridor import load_corridor  # noqa: E402
from sim_service.live.emergency_control import EmergencyController  # noqa: E402
from sim_service.live.green_corridor import CorridorController  # noqa: E402
from sim_service.routing import RoadGraph  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
ARMS = ("plain", "route_only", "full", "retimed")


def largest_scc(graph: RoadGraph) -> set[str]:
    """Largest strongly connected set of edges (iterative Tarjan)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    comps: list[set[str]] = []
    counter = 0
    for root in graph.edges:
        if root in index:
            continue
        work = [(root, iter(graph.neighbours(root)))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for ge in it:
                w = ge.to_edge
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(graph.neighbours(w))))
                    advanced = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
            if low[v] == index[v]:
                comp = set()
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.add(w)
                    if w == v:
                        break
                comps.append(comp)
    return max(comps, key=len)


def edge_xy(graph: RoadGraph, e: str) -> tuple[float, float]:
    a = graph.edges[e].start_xy
    return float(a[0]), float(a[1])


def dist_m(graph: RoadGraph, a: str, b: str) -> float:
    (x1, y1), (x2, y2) = edge_xy(graph, a), edge_xy(graph, b)
    return math.hypot(x1 - x2, y1 - y2)


def foe_pairs(net_path: Path) -> dict:
    """{tls id: [(i, j), ...]} link-index foe pairs for single-junction signals;
    clustered signals are listed under "__skipped__"."""
    root = ET.parse(net_path).getroot()
    tls_ids = {t.get("id") for t in root.iter("tlLogic")}
    out: dict = {}
    for j in root.iter("junction"):
        jid = j.get("id")
        if jid not in tls_ids:
            continue
        reqs = sorted(j.iter("request"), key=lambda r: int(r.get("index")))
        n = len(reqs)
        pairs = []
        for r in reqs:
            i = int(r.get("index"))
            foes = r.get("foes") or ""
            for k in range(n):
                if k != i and len(foes) == n and foes[n - 1 - k] == "1":
                    pairs.append((i, k))
        out[jid] = pairs
    out["__skipped__"] = sorted(tls_ids - set(out))
    return out


class RetimedCorridor(CorridorController):
    """PROTOTYPE (test harness only, not in the repo): every RETIME_EVERY_S, rebuild the open reservations of
    each active corridor from the EV's measured progress, so windows follow the EV instead of the free-flow
    ETA computed once at activation."""
    RETIME_EVERY_S = 3

    def tick(self, step, sim_time_s, *, progress_by_request=None):
        import dataclasses
        super().tick(step, sim_time_s, progress_by_request=progress_by_request)
        if int(sim_time_s) % self.RETIME_EVERY_S:
            return
        for rid, active in list(self._active.items()):
            prog = (progress_by_request or {}).get(rid)
            if prog is None:
                continue
            c = active.corridor
            full = self.planner.crossings(tuple(c.route_edges))
            ahead_idx = [i for i, x in enumerate(full) if x.distance_m > prog + 1.0]
            if not ahead_idx:
                continue
            new = self.planner.plan(corridor_id=c.corridor_id, request_id=rid, vehicle_id=c.vehicle_id,
                                    route_edges=tuple(c.route_edges), now_ms=int(sim_time_s * 1000),
                                    progress_m=prog)
            if new is None:
                continue
            kept = [r for r in c.reservations if r.order not in set(ahead_idx)]
            moved = [dataclasses.replace(r, order=ahead_idx[r.order]) for r in new.reservations]
            active.corridor = dataclasses.replace(c, reservations=tuple(kept + moved))


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.counts: Counter = Counter()
        self.examples: dict = {}

    def emit(self, record):
        key = f"{record.name.split('.')[-1]}: {record.getMessage()[:70]}"
        key = "".join("#" if c.isdigit() else c for c in key)
        self.counts[key] += 1
        self.examples.setdefault(key, record.getMessage()[:200])


class World:
    def __init__(self, level: str, seed: int, arm: str, *, end_s: float, with_orch: bool = False):
        assert arm in ARMS
        self.level, self.seed, self.arm, self.end_s = level, seed, arm, end_s
        self.scen = current()
        self.setup = load_corridor(level)
        self.graph = RoadGraph.from_network(self.scen.net)
        self.anomalies = OperatorAnomalyController()
        self.corridor = RetimedCorridor(self.graph) if arm == "retimed" else CorridorController(self.graph)
        self.emergency = EmergencyController(self.graph, self.anomalies,
                                             corridor_controller=self.corridor)
        if arm == "plain":
            self.emergency.sample_conditions = lambda *a, **k: {}  # type: ignore[method-assign]
            self.emergency._monitor_routes = lambda *a, **k: None  # type: ignore[method-assign]
        self.orch = make_orchestrator(self) if with_orch else None
        self.script: list = []
        self.hooks: list = []
        self.log: list[dict] = []
        self.foes = foe_pairs(self.scen.net)
        self.skipped_tls = self.foes.pop("__skipped__")
        self.safety: dict = defaultdict(int)
        self.safety_examples: list[dict] = []
        self._prev_state: dict = {}
        self._red_run: dict = defaultdict(int)
        self.max_red: dict = defaultdict(int)
        self.collisions = 0
        self.teleports = 0
        self.ev: dict = {}
        self._corridor_peak = 0
        self._tick_exc: list[str] = []
        self.corr_events: list = []
        self.cap = _Capture()
        logging.getLogger().addHandler(self.cap)

    def at(self, t: float, kind: str, **args) -> None:
        self.script.append((float(t), kind, args))
        self.script.sort(key=lambda x: x[0])

    def note(self, **kw) -> None:
        self.log.append(kw)

    def on_tick(self, step: int, t: float) -> None:
        try:
            while self.script and self.script[0][0] <= t:
                _, kind, a = self.script.pop(0)
                try:
                    getattr(self, f"do_{kind}")(step, t, **a)
                except Exception as e:  # noqa: BLE001
                    self._tick_exc.append(f"do_{kind}@{t:.0f}: {e!r}")
            for h in list(self.hooks):
                h(step, t)
            ctls = [(self.anomalies, "anomalies"), (self.emergency, "emergency")]
            if self.orch is not None:
                ctls.append((self.orch, "orch"))
            for ctl, name in ctls:
                try:
                    ctl.tick(step, t)
                except Exception as e:  # noqa: BLE001
                    self._tick_exc.append(f"{name}@{t:.0f}: {e!r}")
            if self.orch is not None:
                self.last_orch_events = self.orch.drain_events()
                self.all_orch_events = getattr(self, "all_orch_events", []) + self.last_orch_events
            self.emergency.drain_events()
            self.emergency.drain_vehicle_events()
            for _p in self.corridor.drain_events():
                self.corr_events.append((t, _p))
            self._monitor(step, t)
        except Exception:  # noqa: BLE001
            import traceback
            self._tick_exc.append(f"world@{t:.0f}: {traceback.format_exc()[-600:]}")

    # -- actions --
    def do_dispatch(self, step, t, rid, vid, src, dst, kind="AMBULANCE", activate=True, tag=""):
        self.emergency.handle_create(
            {"request_id": rid, "vehicle_id": vid, "vehicle_kind": kind, "source_edge": src,
             "destination_edge": dst, "operator": "audit"}, step=step, sim_time_s=t)
        req = self.emergency.get_request(rid)
        m = self.ev.setdefault(rid, {"rid": rid, "vid": vid, "src": src, "dst": dst, "tag": tag,
                                     "created_t": t, "stop_signal_s": 0, "stop_other_s": 0})
        m["state_after_create"] = req.state.value if req else None
        if req is not None and req.route is not None:
            m["route0"] = list(req.route.edges)
            m["crossings0"] = len(self.corridor.planner.crossings(tuple(req.route.edges)))
            m["eta0_s"] = req.eta_s
        if activate and req is not None and req.state is S.ROUTE_READY:
            self.emergency.handle_command({"request_id": rid, "action": "ACTIVATE_CORRIDOR",
                                           "operator": "audit"}, step=step, sim_time_s=t)
            req = self.emergency.get_request(rid)
            m["corridor_armed"] = bool(self.corridor.corridor_for(rid))
            m["state_after_activate"] = req.state.value if req else None

    def do_anomaly(self, step, t, aid, edge, severity="BLOCKED", atype="LANE_BLOCKAGE", dur=600.0):
        self.anomalies.handle_create({"anomaly_id": aid, "edge_id": edge, "severity": severity,
                                      "anomaly_type": atype, "duration_s": dur},
                                     step=step, sim_time_s=t)

    def do_clear(self, step, t, aid):
        self.anomalies.handle_clear({"anomaly_id": aid}, step=step, sim_time_s=t)

    def do_cancel(self, step, t, rid):
        self.emergency.handle_command({"request_id": rid, "action": "CANCEL", "operator": "audit"},
                                      step=step, sim_time_s=t)

    def do_command(self, step, t, rid, action):
        self.emergency.handle_command({"request_id": rid, "action": action, "operator": "audit"},
                                      step=step, sim_time_s=t)

    # -- monitors --
    def _monitor(self, step: int, t: float) -> None:
        for tl, pairs in self.foes.items():
            try:
                st = traci.trafficlight.getRedYellowGreenState(tl)
            except traci.TraCIException:
                continue
            prev = self._prev_state.get(tl)
            for i, j in pairs:
                if i < j and i < len(st) and j < len(st) and st[i] == "G" and st[j] == "G":
                    self.safety["conflicting_green"] += 1
                    if len(self.safety_examples) < 8:
                        self.safety_examples.append({"t": t, "tl": tl, "links": [i, j], "state": st})
            if prev is not None and len(prev) == len(st):
                for a, b in zip(prev, st):
                    if a in "Gg" and b == "r":
                        self.safety["green_to_red_no_yellow"] += 1
            for k, c in enumerate(st):
                key = (tl, k)
                if c == "r":
                    self._red_run[key] += 1
                    if self._red_run[key] > self.max_red[tl]:
                        self.max_red[tl] = self._red_run[key]
                else:
                    self._red_run[key] = 0
            self._prev_state[tl] = st
        self.collisions += traci.simulation.getCollidingVehiclesNumber()
        self.teleports += traci.simulation.getStartingTeleportNumber()
        self._corridor_peak = max(self._corridor_peak, len(self.corridor.active_corridor_ids()))
        live = set(traci.vehicle.getIDList())
        for rid, m in self.ev.items():
            req = self.emergency.get_request(rid)
            if req is None:
                continue
            vid = m["vid"]
            if vid in live:
                m.setdefault("spawn_t", t)
                m.setdefault("pos_log", [])
                spd = traci.vehicle.getSpeed(vid)
                nxt = traci.vehicle.getNextTLS(vid)
                if spd < 0.5:
                    if nxt and nxt[0][2] <= 40:
                        m["stop_signal_s"] += 1
                        ch = str(nxt[0][3])
                        kind = "red" if ch in "rR" else ("yellow" if ch in "yY" else "green")
                        m["stop_at_" + kind] = m.get("stop_at_" + kind, 0) + 1
                        if kind == "red":
                            try:
                                ldr = traci.vehicle.getLeader(vid, 25)
                            except traci.TraCIException:
                                ldr = None
                            k2 = "stop_red_queued" if ldr else "stop_red_first"
                            m[k2] = m.get(k2, 0) + 1
                        try:
                            if self.corridor._open_reservation(nxt[0][0]) is not None:
                                m["stop_while_reservation_open"] = m.get("stop_while_reservation_open", 0) + 1
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        m["stop_other_s"] += 1
                if step % 10 == 0:
                    m["pos_log"].append((round(t), traci.vehicle.getRoadID(vid), round(spd, 1)))
            if req.state is S.COMPLETED and "arrive_t" not in m:
                m["arrive_t"] = t
            if req.is_terminal and "end_state" not in m:
                m["end_state"] = req.state.value
                m["end_t"] = t
            m["reroutes"] = sum(1 for h in req.history if h.action.name == "REROUTE")

    def _traced_preempt(self):
        """Wrap preemption_plan and the interlock check to count why preemption does or does not happen."""
        from sim_service.signal_controller import arbiter as _arb
        tr = self.preempt_trace = Counter()
        orig = self.corridor.preemption_plan
        real_check = _arb.interlocks.check

        def plan(cfg, ctx, **kw):
            tr["calls"] += 1
            res = orig(cfg, ctx, **kw)
            if res is None:
                tr["no_plan"] += 1
            else:
                tr["plan"] += 1
                tr["plan_hold_same_phase" if len(res.steps) == 1 else "plan_switch"] += 1
            return res

        def check(p, ctx, cfg):
            v = real_check(p, ctx, cfg)
            if getattr(p, "source", "") == "corridor_preemption":
                if v:
                    tr["interlock_rejected"] += 1
                    for x in v:
                        tr["rule_" + str(x.rule)] += 1
                else:
                    tr["interlock_ok"] += 1
            return v

        _arb.interlocks.check = check
        self._restore_check = lambda: setattr(_arb.interlocks, "check", real_check)
        return plan

    def run(self) -> dict:
        preempt = None
        if self.arm in ("full", "retimed"):
            preempt = self._traced_preempt()
        summary = run_controlled_scenario(
            self.setup.sumocfg_path, self.setup.configs, self.setup.strategy,
            seed=self.seed, step_length=1.0, max_steps=int(self.end_s),
            link_lanes=self.setup.link_lanes, receiving_lanes=self.setup.receiving_lanes,
            vtype_pcu=self.setup.vtype_pcu, on_tick=self.on_tick, preempt_source=preempt)
        if hasattr(self, "_restore_check"):
            self._restore_check()
        return self.finish(summary)

    def window_stats(self) -> list[dict]:
        acts: dict = {}
        matched: dict = defaultdict(set)
        rows = []
        for t, p in self.corr_events:
            cid = p["corridor_id"]
            if p["event"] == "activated":
                acts[cid] = {r["order"]: (r["intersection_id"], r["open_at_ms"] / 1000, r["close_at_ms"] / 1000)
                             for r in p["reservations"]}
            elif p["event"] == "junction_passed" and cid in acts:
                for order, (tl, o, c) in sorted(acts[cid].items()):
                    if tl == p["detail"] and order not in matched[cid]:
                        matched[cid].add(order)
                        rows.append({"request": p["request_id"], "corridor": cid, "order": order, "tl": tl,
                                     "pass_t": t, "open_t": o, "close_t": c,
                                     "pass_minus_close_s": round(t - c, 1), "pass_minus_open_s": round(t - o, 1)})
                        break
        return rows

    def finish(self, summary: dict) -> dict:
        evs = []
        for rid, m in self.ev.items():
            req = self.emergency.get_request(rid)
            d = {k: v for k, v in m.items() if k != "pos_log"}
            d["final_state"] = req.state.value if req else None
            if "spawn_t" in m and "arrive_t" in m:
                d["travel_s"] = m["arrive_t"] - m["spawn_t"]
            d["pos_tail"] = m.get("pos_log", [])[-6:]
            evs.append(d)
        return {
            "level": self.level, "seed": self.seed, "arm": self.arm, "end_s": self.end_s,
            "evs": evs, "safety": dict(self.safety), "safety_examples": self.safety_examples,
            "max_red_s": max(self.max_red.values()) if self.max_red else 0,
            "max_red_tl": max(self.max_red, key=self.max_red.get) if self.max_red else None,
            "collisions": self.collisions, "teleports": self.teleports,
            "corridors_left": self.corridor.active_corridor_ids(),
            "unprotected_junctions": dict(getattr(self.corridor, "unprotected_junctions", {})),
            "corridor_peak": self._corridor_peak,
            "skipped_clustered_tls": self.skipped_tls,
            "tick_exceptions": self._tick_exc[:10], "n_tick_exceptions": len(self._tick_exc),
            "window_stats": self.window_stats(),
            "preempt_trace": dict(getattr(self, "preempt_trace", {})),
            "log": self.log, "warnings": dict(self.cap.counts.most_common(25)),
            "runner": {k: summary.get(k) for k in summary if not isinstance(summary[k], (dict, list))},
        }


def make_orchestrator(w: World):
    import sim_service.live.incident_response as ir
    from sim_service.live.service import _snapped_depots, _snapped_facilities
    from sim_service.routing.snap import EdgeSnapper
    snapper = EdgeSnapper(w.scen.net, w.graph)
    return ir.IncidentResponseOrchestrator(
        w.anomalies, w.emergency, facility_index=_snapped_facilities(snapper),
        police_depots=_snapped_depots(snapper))


def sample_pairs(graph: RoadGraph, scc: set[str], rng: random.Random, n: int,
                 bands=((1200, 2500), (2500, 9000), (400, 1200), (2500, 9000)), need_signal=True):
    from sim_service.routing import RoutePlanner
    planner = RoutePlanner(graph)
    cp = CorridorController(graph).planner
    edges = sorted(e for e in scc if graph.edges[e].length_m >= 80 and graph.neighbours(e))
    out, tries = [], 0
    while len(out) < n and tries < 6000:
        tries += 1
        lo, hi = bands[len(out) % len(bands)]
        a, b = rng.sample(edges, 2)
        d = dist_m(graph, a, b)
        if not lo <= d < hi:
            continue
        try:
            r = planner.plan(a, b, {})[0]
        except Exception:  # noqa: BLE001
            continue
        k = len(cp.crossings(tuple(r.edges)))
        if need_signal and k < 1:
            continue
        out.append((a, b, round(d), k))
    return out


def dump(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str))

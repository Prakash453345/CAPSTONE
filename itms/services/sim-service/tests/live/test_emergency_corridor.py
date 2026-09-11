"""EmergencyController + CorridorController: ACTIVATE_CORRIDOR arms a corridor,
spawns the vehicle in SUMO, and the per-tick loop drives
GREEN_CORRIDOR_ACTIVE -> IN_TRANSIT -> COMPLETED off the vehicle's live
position. TraCI is a hand-rolled fake."""

from __future__ import annotations

import pytest
from itms_domain import Anomaly, AnomalySeverity, AnomalySource, AnomalyType
from sim_service.live import emergency_control as ec
from sim_service.live.emergency_control import EmergencyController
from sim_service.live.green_corridor import CorridorController
from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph


def _edge(eid: str, length: float, speed: float = 10.0) -> EdgeInfo:
    return EdgeInfo(eid, length, 1, speed, f"{eid}_a", f"{eid}_b", (0.0, 0.0), (length, 0.0))


def _blocked(edge_id: str, aid: str = "an-1") -> Anomaly:
    return Anomaly.create(
        anomaly_id=aid, source=AnomalySource.OPERATOR, anomaly_type=AnomalyType.LANE_BLOCKAGE,
        severity=AnomalySeverity.BLOCKED, edge_id=edge_id, at_ms=1, estimated_impact=1.0,
    )


def _graph() -> RoadGraph:
    edges = {
        "S": _edge("S", 100.0), "A": _edge("A", 200.0),
        "B": _edge("B", 150.0), "T": _edge("T", 100.0),
    }
    adjacency = {
        "S": (GraphEdge("A", "jA", False, None),),
        "A": (GraphEdge("B", "J1", True, "J1"),),
        "B": (GraphEdge("T", "J2", True, "J2"),),
    }
    link_movements = {
        "J1": {("A", "B"): frozenset({"L0"})},
        "J2": {("B", "T"): frozenset({"L0"})},
    }
    return RoadGraph(
        edges=edges, adjacency=adjacency,
        signalised_junctions=frozenset({"J1", "J2"}), link_movements=link_movements,
    )


def _bypass_graph() -> RoadGraph:
    """S -> A -> B -> T (B entered via signal J1), plus an A -> C -> T bypass.
    Both B and C enter T through signal J2, so a reroute onto the bypass still
    has a junction for the green corridor to re-arm around."""
    edges = {
        "S": _edge("S", 100.0), "A": _edge("A", 200.0),
        "B": _edge("B", 150.0), "C": _edge("C", 450.0), "T": _edge("T", 100.0),
    }
    adjacency = {
        "S": (GraphEdge("A", "jA", False, None),),
        "A": (GraphEdge("B", "J1", True, "J1"), GraphEdge("C", "jC", False, None)),
        "B": (GraphEdge("T", "J2", True, "J2"),),
        "C": (GraphEdge("T", "J2", True, "J2"),),
    }
    link_movements = {
        "J1": {("A", "B"): frozenset({"L0"})},
        "J2": {("B", "T"): frozenset({"L0"}), ("C", "T"): frozenset({"L1"})},
    }
    return RoadGraph(
        edges=edges, adjacency=adjacency,
        signalised_junctions=frozenset({"J1", "J2"}), link_movements=link_movements,
    )


class _FakeAnomalies:
    def __init__(self):
        self.items = []

    def active_anomalies(self):
        return list(self.items)


class _FakeVehicles:
    """Stand-in for traci.vehicle: a dict of live vehicles the test drives."""

    def __init__(self):
        self.state: dict[str, dict] = {}
        self.added: list[tuple] = []
        self.removed: list[str] = []
        self.routes_set: list[tuple[str, tuple[str, ...]]] = []

    def getIDList(self):
        return list(self.state)

    def setRoute(self, veh_id, edges):  # noqa: N802
        self.routes_set.append((veh_id, tuple(edges)))

    def add(self, veh_id, route_id, typeID="", departSpeed=""):  # noqa: N803
        self.added.append((veh_id, route_id))
        self.state[veh_id] = {"edge": "S", "pos": 0.0, "speed": 0.0, "xy": (0.0, 0.0)}

    def remove(self, veh_id):
        self.removed.append(veh_id)
        self.state.pop(veh_id, None)

    def setColor(self, veh_id, color):  # noqa: N802, N803
        pass

    def getRoadID(self, veh_id):  # noqa: N802
        return self.state[veh_id]["edge"]

    def getLanePosition(self, veh_id):  # noqa: N802
        return self.state[veh_id]["pos"]

    def getSpeed(self, veh_id):  # noqa: N802
        return self.state[veh_id]["speed"]

    def getPosition(self, veh_id):  # noqa: N802
        return self.state[veh_id]["xy"]


@pytest.fixture
def wired(monkeypatch):
    veh = _FakeVehicles()
    routes: list[tuple] = []
    monkeypatch.setattr(ec.traci.edge, "getLastStepOccupancy", lambda e: 0.0)
    monkeypatch.setattr(ec.traci.edge, "getLastStepMeanSpeed", lambda e: -1.0)
    monkeypatch.setattr(ec.traci, "vehicle", veh)
    monkeypatch.setattr(
        ec.traci.route, "add", lambda rid, edges: routes.append((rid, tuple(edges)))
    )
    monkeypatch.setattr(ec.traci.simulation, "convertGeo", lambda x, y: (80.6 + x / 1e5, 16.5))

    graph = _graph()
    corridor = CorridorController(graph)
    c = EmergencyController(graph, _FakeAnomalies(), corridor_controller=corridor)
    return c, corridor, veh, routes


@pytest.fixture
def wired_bypass(monkeypatch):
    """Same monkeypatched TraCI as `wired`, but the bypass graph + a mutable
    anomaly source, for in-flight rerouting."""
    veh = _FakeVehicles()
    routes: list[tuple] = []
    monkeypatch.setattr(ec.traci.edge, "getLastStepOccupancy", lambda e: 0.0)
    monkeypatch.setattr(ec.traci.edge, "getLastStepMeanSpeed", lambda e: -1.0)
    monkeypatch.setattr(ec.traci, "vehicle", veh)
    monkeypatch.setattr(
        ec.traci.route, "add", lambda rid, edges: routes.append((rid, tuple(edges)))
    )
    monkeypatch.setattr(ec.traci.simulation, "convertGeo", lambda x, y: (80.6 + x / 1e5, 16.5))

    graph = _bypass_graph()
    anoms = _FakeAnomalies()
    corridor = CorridorController(graph)
    c = EmergencyController(graph, anoms, corridor_controller=corridor)
    return c, corridor, veh, anoms


def _payload(**over):
    p = dict(
        request_id="er-1", vehicle_id="amb-1", vehicle_kind="AMBULANCE",
        source_edge="S", destination_edge="T", priority=1,
        operator="operator:sam", requested_at=1_000_000,
    )
    p.update(over)
    return p


def _activate(c: EmergencyController) -> None:
    c.handle_create(_payload(), step=1, sim_time_s=1.0)
    c.drain_events()
    c.handle_command(
        {"request_id": "er-1", "action": "ACTIVATE_CORRIDOR", "requested_at": 2_000,
         "operator": "operator:sam"},
        step=2, sim_time_s=2.0,
    )


def test_activate_arms_the_corridor_and_spawns_the_vehicle(wired):
    c, corridor, veh, routes = wired
    _activate(c)

    req = c.active_requests()[0]
    assert req.state.name == "GREEN_CORRIDOR_ACTIVE"
    assert req.green_corridor_id == "gc-0001"
    assert corridor.active_corridor_ids() == ["gc-0001"]
    assert veh.added == [("amb-1", "ev-route-er-1")]
    assert routes == [("ev-route-er-1", ("S", "A", "B", "T"))]
    (evt,) = c.drain_events()
    assert evt["state"] == "GREEN_CORRIDOR_ACTIVE"
    assert evt["green_corridor_id"] == "gc-0001"


def test_a_moving_vehicle_departs_into_transit_and_emits_position(wired):
    c, corridor, veh, _ = wired
    _activate(c)
    c.drain_events()

    veh.state["amb-1"].update(edge="A", pos=50.0, speed=8.0, xy=(150.0, 0.0))
    c.tick(step=3, sim_time_s=3.0)

    assert c.active_requests()[0].state.name == "IN_TRANSIT"
    (vevt,) = c.drain_vehicle_events()
    assert vevt["vehicle_id"] == "amb-1"
    assert vevt["status"] == "EN_ROUTE"
    assert 0.0 < vevt["route_progress"] < 1.0
    assert vevt["edge_id"] == "A"


def test_vehicle_leaving_the_sim_completes_the_request_and_ends_the_corridor(wired):
    c, corridor, veh, _ = wired
    _activate(c)
    veh.state["amb-1"].update(edge="A", pos=50.0, speed=8.0)
    c.tick(step=3, sim_time_s=3.0)          # departs
    c.drain_events()
    c.drain_vehicle_events()

    veh.state.clear()                       # SUMO removed it at route end
    c.tick(step=4, sim_time_s=40.0)

    assert c.active_requests() == []
    done = c._requests["er-1"]
    assert done.state.name == "COMPLETED"
    assert corridor.active_corridor_ids() == []
    kinds = [e["event"] for e in corridor.drain_events()]
    assert "terminated" in kinds
    vstatuses = [e["status"] for e in c.drain_vehicle_events()]
    assert "ARRIVED" in vstatuses


def test_cancel_after_activate_tears_down_the_corridor_and_removes_the_vehicle(wired):
    c, corridor, veh, _ = wired
    _activate(c)
    c.drain_events()

    c.handle_command(
        {"request_id": "er-1", "action": "CANCEL", "requested_at": 5_000,
         "operator": "operator:sam", "reason": "stood down"},
        step=5, sim_time_s=5.0,
    )
    assert c.active_requests() == []
    assert corridor.active_corridor_ids() == []
    assert veh.removed == ["amb-1"]
    term = [e for e in corridor.drain_events() if e["event"] == "terminated"]
    assert term and term[0]["status"] == "CANCELLED"


def test_activate_on_a_route_with_no_signal_stays_route_ready(wired, monkeypatch):
    c, corridor, veh, _ = wired
    # a graph whose S->T hop crosses no signal
    plain = RoadGraph(
        edges={"S": _edge("S", 100.0), "T": _edge("T", 100.0)},
        adjacency={"S": (GraphEdge("T", "j", False, None),)},
        signalised_junctions=frozenset(),
    )
    c.graph = plain
    c.planner.graph = plain
    corridor.graph = plain
    corridor.planner.graph = plain

    c.handle_create(_payload(source_edge="S", destination_edge="T"), step=1, sim_time_s=1.0)
    c.drain_events()
    c.handle_command(
        {"request_id": "er-1", "action": "ACTIVATE_CORRIDOR", "requested_at": 2_000},
        step=2, sim_time_s=2.0,
    )
    req = c.active_requests()[0]
    assert req.state.name == "ROUTE_READY"
    (evt,) = c.drain_events()
    assert "no corridor needed" in evt["detail"]


# ---- in-flight rerouting (Phase 7) -----------------------------------


def _activate_bypass(c: EmergencyController) -> None:
    c.handle_create(_payload(), step=1, sim_time_s=1_000.0)
    c.drain_events()
    c.handle_command(
        {"request_id": "er-1", "action": "ACTIVATE_CORRIDOR", "requested_at": 1_000_000,
         "operator": "operator:sam"},
        step=2, sim_time_s=1_000.0,
    )
    c.drain_events()


def test_blockage_ahead_reroutes_the_moving_vehicle_and_repoints_sumo(wired_bypass):
    c, corridor, veh, anoms = wired_bypass
    _activate_bypass(c)
    assert c.active_requests()[0].route.edges == ("S", "A", "B", "T")

    # vehicle departs onto A
    veh.state["amb-1"].update(edge="A", pos=60.0, speed=8.0, xy=(160.0, 0.0))
    c.tick(step=1100, sim_time_s=1_100.0)
    assert c.active_requests()[0].state.name == "IN_TRANSIT"
    veh.routes_set.clear()

    # B (still ahead) is blocked; next monitor pass must reroute onto A->C->T
    anoms.items = [_blocked("B")]
    veh.state["amb-1"].update(edge="A", pos=130.0, speed=8.0)
    c.tick(step=1104, sim_time_s=1_104.0)

    req = c.active_requests()[0]
    assert req.state.name == "IN_TRANSIT"
    assert req.route.edges == ("A", "C", "T")
    assert veh.routes_set == [("amb-1", ("A", "C", "T"))]
    assert req.verify_chain()
    assert any(t.action.name == "REROUTE" for t in req.history)


def test_no_viable_reroute_holds_the_current_route_without_crashing(wired_bypass):
    c, corridor, veh, anoms = wired_bypass
    _activate_bypass(c)
    veh.state["amb-1"].update(edge="A", pos=60.0, speed=8.0)
    c.tick(step=1100, sim_time_s=1_100.0)
    veh.routes_set.clear()

    # everything ahead of A is blocked -> planner has nothing; hold, don't cancel
    anoms.items = [_blocked("B"), _blocked("C", aid="an-c"), _blocked("T", aid="an-t")]
    veh.state["amb-1"].update(edge="A", pos=130.0, speed=8.0)
    c.tick(step=1104, sim_time_s=1_104.0)

    req = c.active_requests()[0]
    assert req.state.name == "IN_TRANSIT"          # not CANCELLED
    assert req.route.edges == ("S", "A", "B", "T")  # unchanged
    assert veh.routes_set == []
    held = [e for e in c.drain_events() if "reroute held" in (e.get("detail") or "")]
    assert held

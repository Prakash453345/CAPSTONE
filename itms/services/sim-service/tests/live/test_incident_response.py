"""`IncidentResponseOrchestrator`: a sufficiently severe anomaly becomes an
alert + one EmergencyRequest/corridor per responding authority kind, and an
ambulance that arrives gets chained to the nearest hospital. TraCI is a
hand-rolled fake, the same shape `test_emergency_corridor.py`'s `wired`
fixture uses -- this module composes `EmergencyController` and
`control.dispatch.dispatcher`, both exercised elsewhere; what's new here is
the wiring between them."""

from __future__ import annotations

import pytest
from itms_domain import Anomaly, AnomalySeverity, AnomalySource, AnomalyType, EmergencyKind
from sim_service.control.dispatch import Facility, FacilityIndex
from sim_service.live import emergency_control as ec
from sim_service.live import incident_response as ir
from sim_service.live.emergency_control import EmergencyController
from sim_service.live.green_corridor import CorridorController
from sim_service.live.incident_response import (
    _RESPONSE_MAP,
    IncidentResponseOrchestrator,
    _Depot,
)
from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph


def _edge(eid: str, length: float = 100.0, speed: float = 10.0) -> EdgeInfo:
    return EdgeInfo(eid, length, 1, speed, f"{eid}_a", f"j_{eid}", (0.0, 0.0), (length, 0.0))


def _graph() -> RoadGraph:
    """Police depot S -> incident T crosses two signals (S-A-B-T); ambulance
    depot (the hospital) H <-> T is one unsignalised hop each way -- exactly
    the "route crosses no signal-controlled junction" branch, so this graph
    exercises both the corridor path and the DISPATCH-without-a-corridor
    path in the same test module."""
    edges = {k: _edge(k, ln) for k, ln in
              {"S": 100.0, "A": 200.0, "B": 150.0, "T": 100.0, "H": 100.0}.items()}
    adjacency = {
        "S": (GraphEdge("A", "jA", False, None),),
        "A": (GraphEdge("B", "J1", True, "J1"),),
        "B": (GraphEdge("T", "J2", True, "J2"),),
        "T": (GraphEdge("H", "jTH", False, None),),
        "H": (GraphEdge("T", "jHT", False, None),),
    }
    link_movements = {
        "J1": {("A", "B"): frozenset({"L0"})},
        "J2": {("B", "T"): frozenset({"L0"})},
    }
    return RoadGraph(
        edges=edges, adjacency=adjacency,
        signalised_junctions=frozenset({"J1", "J2"}), link_movements=link_movements,
    )


class _FakeAnomalies:
    def __init__(self) -> None:
        self.items: list[Anomaly] = []

    def active_anomalies(self) -> list[Anomaly]:
        return list(self.items)


class _FakeVehicles:
    def __init__(self) -> None:
        self.state: dict[str, dict] = {}
        self.added: list[tuple] = []
        self.removed: list[str] = []

    def getIDList(self):  # noqa: N802
        return list(self.state)

    def setRoute(self, veh_id, edges):  # noqa: N802
        pass

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


def _accident(edge_id: str = "T", severity: AnomalySeverity = AnomalySeverity.HIGH) -> Anomaly:
    return Anomaly.create(
        anomaly_id="an-1", source=AnomalySource.OPERATOR, anomaly_type=AnomalyType.ACCIDENT,
        severity=severity, edge_id=edge_id, at_ms=1, estimated_impact=0.8,
    )


def _hospital(edge: str = "H") -> Facility:
    return Facility(
        id="hosp-1", name="General Hospital", kind="hospital", edge=edge,
        edge_offset_m=10.0, lat=16.51, lon=80.62, capabilities=frozenset({"general"}),
    )


def _fake_route_fn():
    """A minimal `dispatch.RouteFn`: only knows the one T -> H hop the
    chained-dispatch test needs."""
    routes = {("T", "H"): (("T", "H"), 50.0)}

    def route(from_edge: str, to_edge: str):
        return routes.get((from_edge, to_edge))

    return route


@pytest.fixture
def wired(monkeypatch):
    veh = _FakeVehicles()
    monkeypatch.setattr(ec.traci.edge, "getLastStepOccupancy", lambda e: 0.0)
    monkeypatch.setattr(ec.traci.edge, "getLastStepMeanSpeed", lambda e: -1.0)
    monkeypatch.setattr(ec.traci, "vehicle", veh)
    monkeypatch.setattr(ec.traci.route, "add", lambda rid, edges: None)
    monkeypatch.setattr(ec.traci.simulation, "convertGeo", lambda x, y: (80.6, 16.5))
    # incident_response's own GPS / route lookups go through
    # signal_controller.ev_routing, not emergency_control's traci calls --
    # faked directly where incident_response imported them.
    monkeypatch.setattr(ir, "edge_latlon", lambda edge_id: (16.50, 80.63))
    monkeypatch.setattr(ir, "traci_route_fn", _fake_route_fn)

    graph = _graph()
    anomalies = _FakeAnomalies()
    corridor = CorridorController(graph)
    emergency = EmergencyController(graph, anomalies, corridor_controller=corridor)
    facility_index = FacilityIndex([_hospital()])
    police_depot = _Depot(depot_id="police-1", name="Central PS", edge="S", lat=16.49, lon=80.60)
    orch = IncidentResponseOrchestrator(
        anomalies, emergency, facility_index=facility_index, police_depots=[police_depot],
    )
    return orch, emergency, anomalies, veh


# ---- response map ------------------------------------------------------


def test_response_map_covers_every_anomaly_type():
    assert set(_RESPONSE_MAP) == set(AnomalyType)


def test_accident_pages_police_ambulance_and_fire_truck():
    assert set(_RESPONSE_MAP[AnomalyType.ACCIDENT]) == {
        EmergencyKind.POLICE, EmergencyKind.AMBULANCE, EmergencyKind.FIRE_TRUCK,
    }


def test_heavy_congestion_pages_nobody():
    assert _RESPONSE_MAP[AnomalyType.HEAVY_CONGESTION] == ()


def test_fire_pages_fire_truck_and_police():
    """Default policy for the M8 fire candidate once an operator confirms it; change here if the policy changes."""
    assert set(_RESPONSE_MAP[AnomalyType.FIRE]) == {EmergencyKind.FIRE_TRUCK, EmergencyKind.POLICE}


# ---- dispatch on tick ---------------------------------------------------


def test_high_severity_accident_dispatches_police_and_ambulance(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_accident()]
    orch.tick(step=1, sim_time_s=1.0)

    requests = {r.vehicle_id: r for r in emergency.active_requests()}
    assert set(requests) == {"unit-police-0", "unit-ambulance-0"}
    assert requests["unit-police-0"].state.name == "GREEN_CORRIDOR_ACTIVE"  # S-A-B-T, 2 signals
    assert requests["unit-ambulance-0"].state.name == "IN_TRANSIT"          # H-T, no signal
    assert {v for v, _ in veh.added} == {"unit-police-0", "unit-ambulance-0"}

    (alert,) = orch.drain_events()
    assert alert["anomaly_id"] == "an-1"
    assert alert["anomaly_type"] == "accident"
    assert alert["lat"] == 16.50 and alert["lon"] == 80.63
    dispatched_kinds = {d["vehicle_kind"] for d in alert["dispatched"]}
    assert dispatched_kinds == {"POLICE", "AMBULANCE"}
    assert alert["undispatched_kinds"] == ["fire_truck"]  # no depot data for it


def test_low_severity_anomaly_is_not_dispatched(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_accident(severity=AnomalySeverity.LOW)]
    orch.tick(step=1, sim_time_s=1.0)

    assert emergency.active_requests() == []
    assert orch.drain_events() == []


def test_same_anomaly_is_only_dispatched_once(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_accident()]
    orch.tick(step=1, sim_time_s=1.0)
    orch.drain_events()
    orch.tick(step=2, sim_time_s=2.0)  # anomaly still active on the next tick

    assert orch.drain_events() == []  # no second alert / no second dispatch
    assert len(emergency.active_requests()) == 2


def test_fleet_exhaustion_leaves_the_kind_undispatched(wired):
    orch, emergency, anomalies, veh = wired
    second = Anomaly.create(
        anomaly_id="an-2", source=AnomalySource.OPERATOR, anomaly_type=AnomalyType.ACCIDENT,
        severity=AnomalySeverity.HIGH, edge_id="H", at_ms=1, estimated_impact=0.8,
    )
    anomalies.items = [_accident(edge_id="T"), second]
    orch.tick(step=1, sim_time_s=1.0)

    alerts = orch.drain_events()
    assert len(alerts) == 2
    # only one police depot exists -- the second incident gets none
    second = next(a for a in alerts if a["anomaly_id"] == "an-2")
    assert "police" in second["undispatched_kinds"]


# ---- chained ambulance -> hospital dispatch -----------------------------


def _arrive(emergency: EmergencyController, veh: _FakeVehicles, vehicle_id: str, edge: str) -> None:
    """Drive one EV from its spawn through departure to arrival, the same
    two-tick shape `test_emergency_corridor.py` uses."""
    veh.state[vehicle_id].update(edge=edge, pos=90.0, speed=8.0)
    emergency.tick(step=10, sim_time_s=10.0)   # departs
    emergency.drain_events()
    emergency.drain_vehicle_events()
    veh.state.pop(vehicle_id, None)            # SUMO removed it at route end
    emergency.tick(step=11, sim_time_s=11.0)   # arrives -> on_arrival hook fires


def test_ambulance_arrival_chains_to_the_nearest_hospital(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_accident()]
    orch.tick(step=1, sim_time_s=1.0)
    orch.drain_events()

    _arrive(emergency, veh, "unit-ambulance-0", edge="T")

    chained = emergency.get_request("resp-an-1-ambulance-hospital")
    assert chained is not None
    assert chained.state.name == "IN_TRANSIT"          # T-H, no signal
    assert chained.destination_edge == "H"
    assert orch._unit_by_vehicle_id["unit-ambulance-0"].busy is True  # departing again


def test_police_arrival_releases_with_no_chained_corridor(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_accident()]
    orch.tick(step=1, sim_time_s=1.0)
    orch.drain_events()

    _arrive(emergency, veh, "unit-police-0", edge="T")

    assert emergency.get_request("resp-an-1-police-hospital") is None
    assert orch._unit_by_vehicle_id["unit-police-0"].busy is False

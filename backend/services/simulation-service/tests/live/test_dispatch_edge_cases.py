"""Edge cases of the dispatch queue, reassignment and in-flight rerouting,
found on 27-28 Oct by code review, small probes and the SUMO stress test
(scripts/m7_dispatch_stress.py). Each test failed before its fix."""

from __future__ import annotations

import pytest
from itms_domain import (
    Anomaly,
    AnomalySeverity,
    AnomalySource,
    AnomalyType,
    EmergencyKind,
    EmergencyRequestAction,
)
from sim_service.live import emergency_control as ec
from sim_service.live.emergency_control import EmergencyController
from sim_service.live.green_corridor import CorridorController
from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph

# the incident-response fixture and helpers (tests/live has no __init__, so
# pytest puts this directory on sys.path)
from test_incident_response import _FakeVehicles, _anomaly, _arrive, wired  # noqa: F401

HIGH, MEDIUM = AnomalySeverity.HIGH, AnomalySeverity.MEDIUM


def _police_sent_to(events) -> list[str]:
    return [a["anomaly_id"] for a in events
            if any(d["vehicle_kind"] == "POLICE" for d in a.get("dispatched", []))]


# ---- incident response -------------------------------------------------


def test_a_unit_that_comes_free_goes_to_the_waiting_call_not_a_new_one(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_anomaly("an-1", "T", HIGH), _anomaly("an-2", "H", HIGH)]
    orch.tick(step=1, sim_time_s=1.0)             # an-2 waits for the one police unit
    orch.drain_events()
    _arrive(emergency, veh, "unit-police-0", edge="T")
    anomalies.items.append(_anomaly("an-3", "H", MEDIUM))   # new call in the same tick
    orch.tick(step=12, sim_time_s=12.0)
    assert _police_sent_to(orch.drain_events()) == ["an-2"]
    assert [w["anomaly_id"] for w in orch.waiting if w["kind"] == "police"] == ["an-3"]


def test_two_new_calls_in_one_tick_the_more_severe_goes_first(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_anomaly("an-1", "T", MEDIUM), _anomaly("an-2", "H", HIGH)]
    orch.tick(step=1, sim_time_s=1.0)
    assert _police_sent_to(orch.drain_events()) == ["an-2"]


def test_a_stale_suggestion_does_not_block_later_ones(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_anomaly("an-1", "T", MEDIUM)]
    orch.tick(step=1, sim_time_s=1.0)
    anomalies.items.append(_anomaly("an-2", "H", HIGH))
    orch.tick(step=2, sim_time_s=2.0)             # suggested; the operator ignores it
    anomalies.items = [anomalies.items[0]]        # an-2 clears by itself
    _arrive(emergency, veh, "unit-police-0", edge="T")
    orch.tick(step=12, sim_time_s=12.0)
    assert not orch._suggestions                  # the dead suggestion is withdrawn
    anomalies.items = [_anomaly("an-4", "T", MEDIUM)]
    orch.tick(step=13, sim_time_s=13.0)           # police on its way to a medium call
    anomalies.items.append(_anomaly("an-5", "H", HIGH))
    orch.drain_events()
    orch.tick(step=14, sim_time_s=14.0)
    sugg = [s for e in orch.drain_events() for s in e.get("reassign_suggestions", [])
            if s["vehicle_id"] == "unit-police-0"]
    assert sugg and sugg[0]["from_anomaly_id"] == "an-4"


def test_one_open_suggestion_per_waiting_call(wired):
    orch, emergency, anomalies, veh = wired
    orch.register_crew("unit-police-9", EmergencyKind.POLICE, lat=16.49, lon=80.60, edge="S")
    anomalies.items = [_anomaly("an-1", "T", MEDIUM), _anomaly("an-2", "T", MEDIUM)]
    orch.tick(step=1, sim_time_s=1.0)             # both police units on medium calls
    anomalies.items.append(_anomaly("an-3", "H", HIGH))
    police = []
    for k in range(2, 6):
        orch.tick(step=k, sim_time_s=float(k))
        police += [s for e in orch.drain_events() if e["anomaly_id"] == "an-3"
                   for s in e.get("reassign_suggestions", []) if s["vehicle_id"].startswith(
                       "unit-police")]
    assert len(police) == 1


def test_a_call_no_unit_can_reach_is_tried_once_then_dropped(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_anomaly("an-1", "T", HIGH), _anomaly("an-2", "NOWHERE", HIGH)]
    orch.tick(step=1, sim_time_s=1.0)
    _arrive(emergency, veh, "unit-police-0", edge="T")
    for k in range(12, 20):
        orch.tick(step=k, sim_time_s=float(k))
    tries = [r for r in emergency._requests if r.startswith("resp-an-2-police")]
    assert len(tries) == 1                        # not one failed trip per tick
    assert not [w for w in orch.waiting if w["anomaly_id"] == "an-2" and w["kind"] == "police"]
    assert orch._unit_by_vehicle_id["unit-police-0"].busy is False


def test_cancelled_ambulance_trip_does_not_arm_a_hospital_leg_for_its_next_trip(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_anomaly("an-1", "T", HIGH)]
    orch.tick(step=1, sim_time_s=1.0)
    amb = next(r for r in emergency.active_requests() if r.vehicle_id == "unit-ambulance-0")
    emergency.handle_command({"request_id": amb.request_id, "action": "CANCEL"},
                             step=2, sim_time_s=2.0)
    orch.tick(step=3, sim_time_s=3.0)
    # the operator now sends the same ambulance somewhere (not an incident)
    orch.handle_nearest_request(
        {"request_id": "op-1", "vehicle_id": "", "vehicle_kind": "AMBULANCE",
         "source_edge": "", "destination_edge": "T"},
        step=4, sim_time_s=4.0, create=emergency.handle_create)
    emergency.handle_command({"request_id": "op-1", "action": "ACTIVATE_CORRIDOR"},
                             step=4, sim_time_s=4.0)
    _arrive(emergency, veh, "unit-ambulance-0", edge="T")
    assert emergency.get_request("op-1-hospital") is None
    assert orch._unit_by_vehicle_id["unit-ambulance-0"].busy is False


def test_a_free_unit_beyond_the_search_radius_is_still_sent(wired, monkeypatch):
    orch, emergency, anomalies, veh = wired
    monkeypatch.setattr(orch._crews, "nearest", lambda *a, **k: [])   # nobody within 10 km
    anomalies.items = [_anomaly("an-1", "T", HIGH)]
    orch.tick(step=1, sim_time_s=1.0)
    assert "an-1" in _police_sent_to(orch.drain_events())


def test_a_reassigned_unit_starts_where_it_is_on_the_road(wired, monkeypatch):
    orch, emergency, anomalies, veh = wired
    added: list[dict] = []
    real_add = veh.add

    def add(veh_id, route_id, typeID="", departSpeed="", **kw):  # noqa: N803
        added.append({"veh": veh_id, **kw})
        real_add(veh_id, route_id, typeID, departSpeed)

    monkeypatch.setattr(veh, "add", add)
    anomalies.items = [_anomaly("an-1", "T", MEDIUM)]
    orch.tick(step=1, sim_time_s=1.0)
    veh.state["unit-police-0"].update(edge="A", pos=120.0, speed=8.0)  # driving, mid-road
    emergency.tick(step=2, sim_time_s=2.0)
    anomalies.items.append(_anomaly("an-2", "T", HIGH))
    orch.tick(step=3, sim_time_s=3.0)
    sid = next(s["suggestion_id"] for e in orch.drain_events()
               for s in e.get("reassign_suggestions", []) if s["vehicle_id"] == "unit-police-0")
    assert orch.accept_reassignment(sid, step=4, sim_time_s=4.0)
    last = [a for a in added if a["veh"] == "unit-police-0"][-1]
    assert float(last["departPos"]) == pytest.approx(120.0)


# ---- in-flight rerouting -----------------------------------------------


def _e(eid: str, ln: float) -> EdgeInfo:
    return EdgeInfo(eid, ln, 1, 10.0, f"{eid}_a", f"j_{eid}", (0.0, 0.0), (ln, 0.0))


def _fork() -> RoadGraph:
    """S -> U -> {A short, no signal; B long, signal J1 into T} -> T."""
    edges = {k: _e(k, ln) for k, ln in
             {"S": 100.0, "U": 100.0, "A": 100.0, "B": 300.0, "T": 100.0}.items()}
    adj = {"S": (GraphEdge("U", "jU", False, None),),
           "U": (GraphEdge("A", "jA", False, None), GraphEdge("B", "jB", False, None)),
           "A": (GraphEdge("T", "jAT", False, None),),
           "B": (GraphEdge("T", "J1", True, "J1"),)}
    return RoadGraph(edges=edges, adjacency=adj,  # type: ignore[arg-type]
                     signalised_junctions=frozenset({"J1"}),
                     link_movements={"J1": {("B", "T"): frozenset({"L0"})}})


def _an(aid: str, edge: str, sev: AnomalySeverity) -> Anomaly:
    return Anomaly.create(anomaly_id=aid, source=AnomalySource.OPERATOR,
                          anomaly_type=AnomalyType.LANE_BLOCKAGE, severity=sev,
                          edge_id=edge, at_ms=1, estimated_impact=0.8)


class _Anoms:
    def __init__(self) -> None:
        self.items: list[Anomaly] = []

    def active_anomalies(self) -> list[Anomaly]:
        return list(self.items)


@pytest.fixture
def fork(monkeypatch):
    veh = _FakeVehicles()
    monkeypatch.setattr(ec.traci.edge, "getLastStepOccupancy", lambda e: 0.0)
    monkeypatch.setattr(ec.traci.edge, "getLastStepMeanSpeed", lambda e: -1.0)
    monkeypatch.setattr(ec.traci.edge, "getLastStepHaltingNumber", lambda e: 0)
    monkeypatch.setattr(ec.traci, "vehicle", veh)
    monkeypatch.setattr(ec.traci.route, "add", lambda rid, edges: None)
    monkeypatch.setattr(ec.traci.simulation, "convertGeo", lambda x, y: (80.6, 16.5))
    anoms = _Anoms()
    graph = _fork()
    corridor = CorridorController(graph)
    return EmergencyController(graph, anoms, corridor_controller=corridor), corridor, anoms, veh


def _drive(c: EmergencyController, veh: _FakeVehicles, rid: str, vid: str) -> None:
    c.handle_create(dict(request_id=rid, vehicle_id=vid, vehicle_kind="AMBULANCE",
                         source_edge="S", destination_edge="T"), step=1, sim_time_s=1.0)
    c.handle_command({"request_id": rid, "action": "ACTIVATE_CORRIDOR"}, step=1, sim_time_s=1.0)
    veh.state[vid].update(edge="S", pos=10.0, speed=8.0)


def _reroutes(c: EmergencyController, rid: str) -> int:
    return sum(h.action is EmergencyRequestAction.REROUTE for h in c.get_request(rid).history)


def test_rerouting_onto_a_signalised_road_arms_a_corridor(fork):
    c, corridor, anoms, veh = fork
    _drive(c, veh, "er-1", "amb-1")
    c.tick(step=2, sim_time_s=2.0)
    assert c.get_request("er-1").route.edges == ("S", "U", "A", "T")
    assert corridor.corridor_for("er-1") is None          # no signal on this route
    anoms.items = [_an("blk", "A", AnomalySeverity.BLOCKED)]
    c.tick(step=5, sim_time_s=5.0)
    assert c.get_request("er-1").route.edges == ("S", "U", "B", "T")
    assert corridor.corridor_for("er-1") is not None      # J1 is now preempted


def test_a_new_severe_anomaly_reroutes_every_vehicle_it_is_ahead_of(fork):
    c, corridor, anoms, veh = fork
    _drive(c, veh, "er-1", "amb-1")
    _drive(c, veh, "er-2", "amb-2")
    c.tick(step=2, sim_time_s=2.0)
    anoms.items = [_an("hi", "A", HIGH)]
    c.tick(step=5, sim_time_s=5.0)
    for rid in ("er-1", "er-2"):
        assert c.get_request(rid).route.edges == ("S", "U", "B", "T"), rid


def test_a_severe_anomaly_known_when_the_route_was_planned_is_not_news(fork):
    c, corridor, anoms, veh = fork
    anoms.items = [_an("hiU", "U", HIGH)]   # on the only way out, before planning
    _drive(c, veh, "er-1", "amb-1")
    c.tick(step=2, sim_time_s=2.0)
    c.tick(step=6, sim_time_s=6.0)
    assert _reroutes(c, "er-1") == 0


def test_beyond_the_search_radius_the_nearest_free_unit_is_sent(wired, monkeypatch):
    orch, emergency, anomalies, veh = wired
    orch.register_crew("unit-police-near", EmergencyKind.POLICE, lat=16.50, lon=80.629, edge="S")
    monkeypatch.setattr(orch._crews, "nearest", lambda *a, **k: [])   # nobody within 10 km
    anomalies.items = [_anomaly("an-1", "T", HIGH)]                   # at (16.50, 80.63)
    orch.tick(step=1, sim_time_s=1.0)
    sent = [d["vehicle_id"] for e in orch.drain_events() for d in e.get("dispatched", [])
            if d["vehicle_kind"] == "POLICE"]
    assert sent == ["unit-police-near"]                    # not the first one listed


def test_a_reassignment_that_cannot_route_from_where_the_unit_is_does_not_drop_the_call(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_anomaly("an-1", "H", MEDIUM)]
    orch.tick(step=1, sim_time_s=1.0)
    veh.state["unit-police-0"].update(edge="H", pos=50.0, speed=8.0)  # H only leads to T
    emergency.tick(step=2, sim_time_s=2.0)
    anomalies.items.append(_anomaly("an-2", "A", HIGH))     # A: reachable from the depot only
    orch.tick(step=3, sim_time_s=3.0)
    sid = next(s["suggestion_id"] for e in orch.drain_events()
               for s in e.get("reassign_suggestions", []) if s["vehicle_id"] == "unit-police-0")
    assert not orch.accept_reassignment(sid, step=4, sim_time_s=4.0)
    orch.tick(step=5, sim_time_s=5.0)
    assert "an-2" in _police_sent_to(orch.drain_events())  # sent from the depot instead


def test_moving_a_unit_off_a_resolved_call_does_not_requeue_that_call(wired):
    orch, emergency, anomalies, veh = wired
    anomalies.items = [_anomaly("an-1", "T", MEDIUM)]
    orch.tick(step=1, sim_time_s=1.0)
    anomalies.items.append(_anomaly("an-2", "H", HIGH))
    orch.tick(step=2, sim_time_s=2.0)
    sid = next(s["suggestion_id"] for e in orch.drain_events()
               for s in e.get("reassign_suggestions", []) if s["vehicle_id"] == "unit-police-0")
    anomalies.items = [anomalies.items[1]]                  # an-1 is cleared meanwhile
    assert orch.accept_reassignment(sid, step=3, sim_time_s=3.0)
    assert not [w for w in orch.waiting if w["anomaly_id"] == "an-1"]

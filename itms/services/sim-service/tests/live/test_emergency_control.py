"""`EmergencyController` -- create/route/preview, recalculate, cancel. TraCI
edge reads are monkeypatched; the graph is a hand-built diamond so routes have
a real choice."""

from __future__ import annotations

import pytest
from itms_common.events import decode_envelope, encode_envelope
from itms_domain import Anomaly, AnomalySeverity, AnomalySource, AnomalyType
from sim_service.live import emergency_control as ec
from sim_service.live.emergency_control import EmergencyController
from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph
from sim_service.routing.planner import NoRouteError


def _edge(eid: str, length: float = 100.0, speed: float = 10.0) -> EdgeInfo:
    return EdgeInfo(eid, length, 1, speed, f"{eid}_a", f"j_{eid}", (0.0, 0.0), (length, 0.0))


def _diamond() -> RoadGraph:
    edges = {k: _edge(k, ln) for k, ln in
             {"S": 100.0, "A": 100.0, "B": 260.0, "T": 100.0}.items()}
    adjacency = {
        "S": (GraphEdge("A", "j_A", False, None), GraphEdge("B", "j_B", False, None)),
        "A": (GraphEdge("T", "j_T", True, "TL1"),),
        "B": (GraphEdge("T", "j_T", False, None),),
    }
    return RoadGraph(edges=edges, adjacency=adjacency, signalised_junctions=frozenset({"j_T"}))


class _FakeAnomalies:
    def __init__(self, active: list[Anomaly] | None = None):
        self._active = active or []

    def active_anomalies(self) -> list[Anomaly]:
        return list(self._active)


@pytest.fixture
def patched_edges(monkeypatch):
    occ: dict[str, float] = {}
    spd: dict[str, float] = {}
    monkeypatch.setattr(ec.traci.edge, "getLastStepOccupancy", lambda e: occ.get(e, 0.0))
    monkeypatch.setattr(ec.traci.edge, "getLastStepMeanSpeed", lambda e: spd.get(e, -1.0))
    return occ, spd


def _create_payload(**over):
    p = dict(
        request_id="er-1",
        vehicle_id="amb-01",
        vehicle_kind="AMBULANCE",
        source_edge="S",
        destination_edge="T",
        priority=1,
        operator="operator:sam",
        requested_at=1_000_000,
    )
    p.update(over)
    return p


# ---- create + route --------------------------------------------------


def test_create_routes_and_emits_route_ready_with_a_full_route_summary(patched_edges):
    c = EmergencyController(_diamond(), _FakeAnomalies())
    c.handle_create(_create_payload(), step=10, sim_time_s=10.0)

    (evt,) = c.drain_events()
    assert evt["state"] == "ROUTE_READY"
    assert evt["request_id"] == "er-1"
    assert evt["eta_s"] is not None
    r = evt["route"]
    assert r["edges"] == ["S", "A", "T"]                 # short branch, nothing wrong
    assert r["n_intersections"] == 2
    assert r["signalised_intersections"] == ["j_T"]
    assert r["route_score"] > 0
    assert set(r["weights_used"]) >= {"anomaly_weight", "travel_time_weight"}
    assert c.active_requests()[0].state.name == "ROUTE_READY"


def test_a_blocked_short_branch_routes_around_it(patched_edges):
    blk = Anomaly.create(
        anomaly_id="an-1", source=AnomalySource.OPERATOR, anomaly_type=AnomalyType.LANE_BLOCKAGE,
        severity=AnomalySeverity.BLOCKED, edge_id="A", at_ms=1, estimated_impact=1.0,
    )
    c = EmergencyController(_diamond(), _FakeAnomalies([blk]))
    c.handle_create(_create_payload(), step=1, sim_time_s=1.0)
    (evt,) = c.drain_events()
    assert evt["route"]["edges"] == ["S", "B", "T"]


def test_both_branches_blocked_still_reaches_route_ready_forced_through(patched_edges):
    """Neither branch avoids the blockage -- this must still route (as the
    operator's only option) rather than cancel the mission."""
    blocked_both = [
        Anomaly.create(
            anomaly_id="an-a", source=AnomalySource.OPERATOR, anomaly_type=AnomalyType.LANE_BLOCKAGE,
            severity=AnomalySeverity.BLOCKED, edge_id="A", at_ms=1, estimated_impact=1.0,
        ),
        Anomaly.create(
            anomaly_id="an-b", source=AnomalySource.OPERATOR, anomaly_type=AnomalyType.LANE_BLOCKAGE,
            severity=AnomalySeverity.BLOCKED, edge_id="B", at_ms=1, estimated_impact=1.0,
        ),
    ]
    c = EmergencyController(_diamond(), _FakeAnomalies(blocked_both))
    c.handle_create(_create_payload(), step=1, sim_time_s=1.0)
    (evt,) = c.drain_events()
    assert evt["state"] == "ROUTE_READY"
    assert evt["route"] is not None
    assert evt["route"]["forced_through"]
    assert evt["route"]["reliable"] is False
    assert c.active_requests()[0].state.name == "ROUTE_READY"


def test_recalculate_failure_holds_the_route_instead_of_crashing(patched_edges, monkeypatch):
    """Regression: a planning failure on RECALCULATE (or the background
    monitor) used to be treated like the *initial* routing attempt --
    applying ROUTE_FAILED from ROUTE_READY, which the state machine doesn't
    allow, raising IllegalRequestTransition and taking the whole sim-service
    tick down with it. It must now hold the existing route instead."""
    c = EmergencyController(_diamond(), _FakeAnomalies())
    c.handle_create(_create_payload(), step=1, sim_time_s=1.0)
    c.drain_events()
    assert c.active_requests()[0].state.name == "ROUTE_READY"

    monkeypatch.setattr(
        c.planner, "plan",
        lambda *a, **k: (_ for _ in ()).throw(NoRouteError("no route is currently available")),
    )

    c.handle_command(
        {"request_id": "er-1", "action": "RECALCULATE", "requested_at": 2_000_000},
        step=2, sim_time_s=2.0,
    )

    (evt,) = c.drain_events()
    assert evt["state"] == "ROUTE_READY"           # held, never cancelled
    assert "reroute held" in evt["detail"]
    assert c.active_requests()[0].state.name == "ROUTE_READY"


def test_unreachable_destination_fails_the_request_and_releases_the_vehicle(patched_edges):
    g = RoadGraph(
        edges={"S": _edge("S"), "ISL": _edge("ISL")},
        adjacency={"S": ()}, signalised_junctions=frozenset(),
    )
    c = EmergencyController(g, _FakeAnomalies())
    c.handle_create(_create_payload(destination_edge="ISL"), step=1, sim_time_s=1.0)
    (evt,) = c.drain_events()
    assert evt["state"] == "CANCELLED"
    assert evt["route"] is None
    assert "isolated" in evt["detail"] or "no route" in evt["detail"].lower()
    assert c.active_requests() == []


# ---- sample_conditions -----------------------------------------


def test_sample_conditions_reads_live_occupancy_and_mean_speed(patched_edges):
    occ, spd = patched_edges
    occ["A"], spd["A"] = 60.0, 3.0   # 60% occupancy, 3 m/s on a 10 m/s edge
    c = EmergencyController(_diamond(), _FakeAnomalies())
    cond = c.sample_conditions()
    assert cond["A"].congestion == pytest.approx(0.6)
    assert cond["A"].mean_speed_frac == pytest.approx(0.3)
    assert cond["S"].mean_speed_frac == 1.0    # no vehicles -> free flow


def test_sample_conditions_folds_in_active_anomalies(patched_edges):
    a = Anomaly.create(
        anomaly_id="x", source=AnomalySource.GRAPH_MODEL, anomaly_type=AnomalyType.ACCIDENT,
        severity=AnomalySeverity.HIGH, edge_id="B", at_ms=1, estimated_impact=0.7,
    )
    c = EmergencyController(_diamond(), _FakeAnomalies([a]))
    cond = c.sample_conditions()
    assert cond["B"].anomaly_severity == "high"
    assert cond["B"].anomaly_impact == pytest.approx(0.7)
    assert cond["A"].anomaly_severity is None


# ---- follow-up commands ---------------------------------------


def test_recalculate_reroutes_when_conditions_change(patched_edges):
    anoms = _FakeAnomalies()
    c = EmergencyController(_diamond(), anoms)
    c.handle_create(_create_payload(), step=1, sim_time_s=1.0)
    c.drain_events()
    assert c.active_requests()[0].route.edges == ("S", "A", "T")

    # a blockage appears on A; operator hits recalculate
    anoms._active = [Anomaly.create(
        anomaly_id="an-9", source=AnomalySource.OPERATOR, anomaly_type=AnomalyType.LANE_BLOCKAGE,
        severity=AnomalySeverity.BLOCKED, edge_id="A", at_ms=2, estimated_impact=1.0,
    )]
    c.handle_command(
        {"request_id": "er-1", "action": "RECALCULATE", "requested_at": 2_000_000,
         "operator": "operator:sam", "reason": "A blocked"},
        step=2, sim_time_s=2.0,
    )
    (evt,) = c.drain_events()
    assert evt["state"] in ("ROUTE_READY", "IN_TRANSIT")
    assert evt["route"]["edges"] == ["S", "B", "T"]
    assert c.active_requests()[0].verify_chain()


def test_cancel_ends_the_request_and_releases_the_vehicle(patched_edges):
    c = EmergencyController(_diamond(), _FakeAnomalies())
    c.handle_create(_create_payload(), step=1, sim_time_s=1.0)
    c.drain_events()
    c.handle_command(
        {"request_id": "er-1", "action": "CANCEL", "requested_at": 3_000_000,
         "operator": "operator:sam", "reason": "stood down"},
        step=3, sim_time_s=3.0,
    )
    (evt,) = c.drain_events()
    assert evt["state"] == "CANCELLED"
    assert c.active_requests() == []


def test_activate_corridor_without_a_controller_is_ignored(patched_edges):
    c = EmergencyController(_diamond(), _FakeAnomalies())  # no corridor_controller
    c.handle_create(_create_payload(), step=1, sim_time_s=1.0)
    c.drain_events()
    c.handle_command(
        {"request_id": "er-1", "action": "ACTIVATE_CORRIDOR", "requested_at": 4},
        step=4, sim_time_s=4.0,
    )
    assert c.drain_events() == []
    assert c.active_requests()[0].state.name == "ROUTE_READY"


def test_command_for_unknown_request_is_ignored(patched_edges):
    c = EmergencyController(_diamond(), _FakeAnomalies())
    c.handle_command({"request_id": "ghost", "action": "CANCEL"}, step=1, sim_time_s=1.0)
    assert c.drain_events() == []


# ---- payload schema + republish -----------------------------


def test_payload_round_trips_through_the_schema(patched_edges):
    c = EmergencyController(_diamond(), _FakeAnomalies())
    c.handle_create(_create_payload(), step=7, sim_time_s=7.0)
    (payload,) = c.drain_events()
    env = decode_envelope(
        encode_envelope(event_type="EmergencyRequestUpdated", source="t", payload=payload)
    )["payload"]
    assert env["state"] == "ROUTE_READY"
    assert env["route"]["edges"] == ["S", "A", "T"]
    assert env["route"]["weights_used"]["anomaly_weight"] > 0
    assert env["chain_hash"]


def test_tick_republishes_active_requests_on_the_interval(patched_edges):
    c = EmergencyController(_diamond(), _FakeAnomalies())
    c.handle_create(_create_payload(), step=1, sim_time_s=0.0)
    c.drain_events()
    c.tick(step=2, sim_time_s=5.0)
    assert c.drain_events() == []          # < interval
    c.tick(step=3, sim_time_s=12.0)
    (evt,) = c.drain_events()
    assert evt["state"] == "ROUTE_READY" and evt["actor"] == "system:monitor"

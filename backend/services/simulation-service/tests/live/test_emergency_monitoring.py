"""Phase 7 continuous monitoring: `EmergencyController._monitor_routes` triggers
an automatic reroute on a blocked/severe anomaly ahead or a materially cheaper
replan, gated by cooldown / monitor-interval / minimum-progress so it never
recomputes every tick or oscillates."""

from __future__ import annotations

import pytest
from itms_domain import (
    Anomaly,
    AnomalySeverity,
    AnomalySource,
    AnomalyType,
    EmergencyRequestAction,
    EmergencyRoutingConfig,
)
from sim_service.live import emergency_control as ec
from sim_service.live.emergency_control import EmergencyController
from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph


def _edge(eid: str, length: float, speed: float = 10.0) -> EdgeInfo:
    return EdgeInfo(eid, length, 1, speed, f"{eid}_a", f"{eid}_b", (0.0, 0.0), (length, 0.0))


def _diamond() -> RoadGraph:
    """S -> {A short, B long} -> T."""
    edges = {k: _edge(k, ln) for k, ln in
             {"S": 100.0, "A": 100.0, "B": 240.0, "T": 100.0}.items()}
    adjacency = {
        "S": (GraphEdge("A", "jA", False, None), GraphEdge("B", "jB", False, None)),
        "A": (GraphEdge("T", "jT", False, None),),
        "B": (GraphEdge("T", "jT", False, None),),
    }
    return RoadGraph(edges=edges, adjacency=adjacency, signalised_junctions=frozenset())


class _Anoms:
    def __init__(self):
        self.items: list[Anomaly] = []

    def active_anomalies(self):
        return list(self.items)


def _blocked(edge_id: str, sev=AnomalySeverity.BLOCKED, aid="an-1") -> Anomaly:
    return Anomaly.create(
        anomaly_id=aid, source=AnomalySource.OPERATOR, anomaly_type=AnomalyType.LANE_BLOCKAGE,
        severity=sev, edge_id=edge_id, at_ms=1, estimated_impact=1.0,
    )


@pytest.fixture
def patched_edges(monkeypatch):
    occ: dict[str, float] = {}
    spd: dict[str, float] = {}
    monkeypatch.setattr(ec.traci.edge, "getLastStepOccupancy", lambda e: occ.get(e, 0.0))
    monkeypatch.setattr(ec.traci.edge, "getLastStepMeanSpeed", lambda e: spd.get(e, -1.0))
    monkeypatch.setattr(ec.traci.edge, "getLastStepHaltingNumber", lambda e: 0)
    return occ, spd


def _controller(anoms: _Anoms, **cfg_over) -> EmergencyController:
    return EmergencyController(_diamond(), anoms, EmergencyRoutingConfig(**cfg_over))  # type: ignore[arg-type]


def _create(c: EmergencyController, at_ms: int = 1000) -> None:
    c.handle_create(
        dict(request_id="er-1", vehicle_id="amb-1", vehicle_kind="AMBULANCE",
             source_edge="S", destination_edge="T", priority=1,
             operator="operator:sam", requested_at=at_ms),
        step=1, sim_time_s=at_ms / 1000.0,
    )
    c.drain_events()


def _reroute_count(c: EmergencyController) -> int:
    """How many REROUTE transitions the request's own tamper-evident chain
    carries -- the unambiguous 'did it reroute' signal (a `tick` also emits
    heartbeat events that inherit the last transition's detail)."""
    req = c._requests["er-1"]
    return sum(1 for t in req.history if t.action is EmergencyRequestAction.REROUTE)


def _route_edges(c: EmergencyController) -> tuple[str, ...]:
    return c._requests["er-1"].route.edges


# ---- triggers ------------------------------------------------------------


def test_blocked_edge_ahead_triggers_an_auto_reroute(patched_edges):
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)
    assert _route_edges(c) == ("S", "A", "T")

    anoms.items = [_blocked("A")]
    c.tick(step=40, sim_time_s=40.0)            # past cooldown (route set at t=1)

    assert _reroute_count(c) == 1
    assert _route_edges(c) == ("S", "B", "T")
    last = c._requests["er-1"].history[-1]
    assert last.action is EmergencyRequestAction.REROUTE
    assert last.actor == "system:monitor" and "blocked" in last.detail
    assert c._requests["er-1"].verify_chain()


def test_a_cheaper_replan_triggers_a_reroute(patched_edges):
    occ, spd = patched_edges
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)

    # A is now crawling. Default (time-based) cost: the saving must beat
    # max(15 s, 10 %) + 5 s switch cost, so the crawl has to be real.
    occ["A"], spd["A"] = 95.0, 0.3
    c.tick(step=40, sim_time_s=40.0)

    assert _reroute_count(c) == 1
    assert _route_edges(c) == ("S", "B", "T")
    assert "faster path" in c._requests["er-1"].history[-1].detail


def test_a_cheaper_replan_triggers_a_reroute_weighted_cost(patched_edges, monkeypatch):
    monkeypatch.setenv("ITMS_ROUTE_COST", "weighted")
    occ, spd = patched_edges
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)

    occ["A"], spd["A"] = 95.0, 1.0              # A is now crawling
    c.tick(step=40, sim_time_s=40.0)

    assert _reroute_count(c) == 1
    assert _route_edges(c) == ("S", "B", "T")
    assert "faster path" in c._requests["er-1"].history[-1].detail


def test_mild_congestion_below_the_hysteresis_band_does_not_reroute(patched_edges):
    occ, spd = patched_edges
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)

    occ["A"], spd["A"] = 30.0, 7.0              # a little slow, not enough to switch
    c.tick(step=40, sim_time_s=40.0)
    assert _reroute_count(c) == 0
    assert _route_edges(c) == ("S", "A", "T")


def test_a_new_severe_anomaly_ahead_only_fires_once(patched_edges):
    anoms = _Anoms()
    c = _controller(anoms, reroute_on_blocked_edge=False)  # force the "new severe" path
    _create(c)

    anoms.items = [_blocked("A", sev=AnomalySeverity.HIGH, aid="sev-1")]
    c.tick(step=40, sim_time_s=40.0)
    assert _reroute_count(c) == 1
    assert _route_edges(c) == ("S", "B", "T")

    # same anomaly still there, cooldown elapsed again -> must NOT reroute again
    c.tick(step=200, sim_time_s=200.0)
    assert _reroute_count(c) == 1


# ---- gates: cooldown / interval ---------------------------------------


def test_new_blockage_ahead_skips_the_cooldown_once(patched_edges):
    """Since 2026-10-27 a road ahead that has just become blocked is acted on
    at once, inside the cooldown -- but only once per anomaly, so a blockage
    with no way around is not retried every few seconds."""
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)
    anoms.items = [_blocked("A")]
    c.tick(step=40, sim_time_s=40.0)
    assert _reroute_count(c) == 1 and _route_edges(c) == ("S", "B", "T")

    # B is blocked too, within reroute_cooldown_s (default 30) of the reroute:
    # acted on now (there is no clean way round, so this is the forced route)
    anoms.items = [_blocked("A"), _blocked("B", aid="an-2")]
    c.tick(step=45, sim_time_s=45.0)
    assert _reroute_count(c) == 2

    # same blockages, still inside the cooldown: no further reroute
    c.tick(step=50, sim_time_s=50.0)
    assert _reroute_count(c) == 2


def test_blocked_destination_does_not_trigger_a_reroute(patched_edges):
    """The destination is not 'ahead': an incident there is why the vehicle
    is going."""
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)
    anoms.items = [_blocked("T")]
    c.tick(step=40, sim_time_s=40.0)
    c.tick(step=80, sim_time_s=80.0)
    assert _reroute_count(c) == 0


def test_monitor_interval_limits_evaluation_frequency(patched_edges):
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)
    c.tick(step=40, sim_time_s=40.0)            # first monitor pass, nothing wrong
    anoms.items = [_blocked("A")]
    c.tick(step=41, sim_time_s=41.0)            # < _MONITOR_INTERVAL_S later -> skipped
    assert _reroute_count(c) == 0
    c.tick(step=44, sim_time_s=44.0)            # now past the interval
    assert _reroute_count(c) == 1 and _route_edges(c) == ("S", "B", "T")


def test_no_trigger_leaves_the_route_and_state_untouched(patched_edges):
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)
    c.tick(step=40, sim_time_s=40.0)
    c.tick(step=80, sim_time_s=80.0)
    assert _reroute_count(c) == 0
    assert c.active_requests()[0].state.name == "ROUTE_READY"
    assert _route_edges(c) == ("S", "A", "T")


def test_a_blockage_the_route_is_forced_through_is_not_retried(patched_edges):
    """No way round: the route crosses the blocked road (forced_through). The
    monitor must not keep 'rerouting' onto the same forced route."""
    anoms = _Anoms()
    c = _controller(anoms)
    _create(c)
    anoms.items = [_blocked("A"), _blocked("B", aid="an-2")]   # both ways blocked
    c.tick(step=40, sim_time_s=40.0)
    first = _reroute_count(c)
    assert first <= 1                                       # at most one forced reroute
    for t in (80.0, 120.0, 160.0, 200.0):                   # several cooldowns later
        c.tick(step=int(t), sim_time_s=t)
    assert _reroute_count(c) == first

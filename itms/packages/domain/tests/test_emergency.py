"""`itms_domain.emergency` -- EmergencyVehicle, the EmergencyRequest state
machine + audit chain, and GreenCorridorRequest."""

from __future__ import annotations

import dataclasses

import pytest
from itms_domain.emergency import (
    CorridorReservation,
    CorridorStatus,
    EmergencyKind,
    EmergencyRequest,
    EmergencyRequestAction,
    EmergencyRequestState,
    EmergencyVehicle,
    EmergencyVehicleStatus,
    GreenCorridorRequest,
    IllegalRequestTransition,
)
from itms_domain.routing import RouteCostBreakdown, RouteResult

_A = EmergencyRequestAction
_S = EmergencyRequestState


def _route(score: float = 28.7, edges=("E1", "E2", "E3")) -> RouteResult:
    return RouteResult(
        edges=tuple(edges),
        total_distance_m=1000.0,
        total_travel_time_s=120.0,
        eta_s=140.0,
        n_intersections=3,
        signalised_intersections=("J1", "J2"),
        congested_segments=(),
        anomalous_segments_avoided=(),
        cost=RouteCostBreakdown(120.0, 0.5, 0.0, 20.0, 0.3, 0.1, score),
        reliable=True,
    )


def _req(**over) -> EmergencyRequest:
    kw = dict(
        request_id="er-1",
        vehicle_id="amb-01",
        source_edge="E1",
        destination_edge="E9",
        at_ms=1_000,
        operator="operator:sam",
    )
    kw.update(over)
    return EmergencyRequest.create(**kw)


# ---- EmergencyVehicle -------------------------------------------------


def test_vehicle_assign_and_release():
    v = EmergencyVehicle(vehicle_id="amb-01", kind=EmergencyKind.AMBULANCE, home_edge="E0")
    assert v.status is EmergencyVehicleStatus.IDLE
    a = v.assigned_to("er-1")
    assert a.status is EmergencyVehicleStatus.ASSIGNED and a.active_request_id == "er-1"
    r = a.released()
    assert r.status is EmergencyVehicleStatus.IDLE and r.active_request_id is None


# ---- EmergencyRequest happy path -----------------------------------


def test_full_lifecycle_created_to_completed_via_green_corridor():
    req = _req()
    assert req.state is _S.CREATED and len(req.history) == 1

    req = req.apply(_A.START_ROUTING, at_ms=1_100, actor="system")
    assert req.state is _S.ROUTING

    route = _route()
    req = req.apply(_A.ROUTE_READY, at_ms=1_400, actor="system", route=route, eta_s=140.0)
    assert req.state is _S.ROUTE_READY
    assert req.route is route and req.eta_s == 140.0
    assert req.routing_latency_ms() == 400

    req = req.apply(_A.ACTIVATE_CORRIDOR, at_ms=1_500, actor="operator:sam",
                    green_corridor_id="gc-1")
    assert req.state is _S.GREEN_CORRIDOR_ACTIVE and req.green_corridor_id == "gc-1"

    req = req.apply(_A.DEPART, at_ms=1_510, actor="system")
    assert req.state is _S.IN_TRANSIT

    req = req.apply(_A.ARRIVE, at_ms=60_000, actor="system")
    assert req.state is _S.COMPLETED and req.is_terminal
    assert [t.action for t in req.history] == [
        _A.CREATE, _A.START_ROUTING, _A.ROUTE_READY, _A.ACTIVATE_CORRIDOR, _A.DEPART, _A.ARRIVE
    ]
    assert req.verify_chain()


def test_dispatch_without_a_corridor_and_reroute_in_transit():
    req = _req().apply(_A.START_ROUTING, at_ms=2, actor="s").apply(
        _A.ROUTE_READY, at_ms=3, actor="s", route=_route(score=30.0)
    )
    req = req.apply(_A.DISPATCH, at_ms=4, actor="operator:sam")
    assert req.state is _S.IN_TRANSIT

    better = _route(score=22.0, edges=("E1", "E7", "E3"))
    req = req.apply(_A.REROUTE, at_ms=5, actor="system", route=better, detail="E2 blocked")
    assert req.state is _S.IN_TRANSIT
    assert req.route is better
    assert req.history[-1].route_score == 22.0
    assert req.verify_chain()


def test_route_failed_from_routing_cancels():
    req = _req().apply(_A.START_ROUTING, at_ms=2, actor="s")
    req = req.apply(_A.ROUTE_FAILED, at_ms=3, actor="system", detail="destination isolated")
    assert req.state is _S.CANCELLED and req.is_terminal


# ---- illegal transitions ----------------------------------------


@pytest.mark.parametrize("action", [_A.ACTIVATE_CORRIDOR, _A.DEPART, _A.ARRIVE, _A.REROUTE])
def test_cannot_skip_ahead_from_created(action):
    with pytest.raises(IllegalRequestTransition):
        _req().apply(action, at_ms=2, actor="s")


def test_no_action_on_a_terminal_request():
    done = _req().apply(_A.CANCEL, at_ms=2, actor="operator:sam")
    for action in _A:
        if action is _A.CREATE:
            continue
        with pytest.raises(IllegalRequestTransition):
            done.apply(action, at_ms=3, actor="s")


def test_create_is_not_a_transition():
    with pytest.raises(IllegalRequestTransition):
        _req().apply(_A.CREATE, at_ms=2, actor="s")


# ---- audit chain ----------------------------------------------


def test_editing_a_recorded_transition_breaks_the_chain():
    req = _req().apply(_A.START_ROUTING, at_ms=2, actor="s")
    hist = list(req.history)
    hist[-1] = dataclasses.replace(hist[-1], detail="changed after the fact")
    tampered = dataclasses.replace(req, history=tuple(hist))
    assert not tampered.verify_chain()


def test_swapping_the_attached_route_is_detectable_via_the_digest():
    req = _req().apply(_A.START_ROUTING, at_ms=2, actor="s").apply(
        _A.ROUTE_READY, at_ms=3, actor="s", route=_route(edges=("E1", "E2", "E3"))
    )
    # a transition recorded the digest of the route it was given
    assert req.history[-1].route_digest is not None
    swapped = dataclasses.replace(req, route=_route(edges=("E1", "X9", "E3")))
    # the chain still verifies (history untouched) but the recorded digest no
    # longer matches the attached route -- the mismatch is the tamper signal
    assert swapped.verify_chain()
    from itms_domain.emergency import _route_digest

    assert _route_digest(swapped.route) != swapped.history[-1].route_digest


# ---- GreenCorridorRequest -----------------------------------


def _reservation(iid: str, order: int, open_ms: int, close_ms: int) -> CorridorReservation:
    return CorridorReservation(
        intersection_id=iid, movements=("L0", "L1"),
        open_at_ms=open_ms, close_at_ms=close_ms, order=order,
    )


def test_corridor_orders_and_reports_intersections():
    gc = GreenCorridorRequest(
        corridor_id="gc-1", request_id="er-1", vehicle_id="amb-01",
        route_edges=("E1", "E2", "E3"),
        reservations=(
            _reservation("J1", 0, 0, 20_000),
            _reservation("J2", 1, 15_000, 35_000),
            _reservation("J3", 2, 40_000, 60_000),
        ),
    )
    assert gc.intersection_ids == ("J1", "J2", "J3")
    assert gc.status is CorridorStatus.PROPOSED
    assert gc.with_status(CorridorStatus.ACTIVE).status is CorridorStatus.ACTIVE


def test_corridor_rejects_out_of_order_reservations():
    with pytest.raises(ValueError):
        GreenCorridorRequest(
            corridor_id="gc-1", request_id="er-1", vehicle_id="amb-01",
            route_edges=("E1",),
            reservations=(_reservation("J2", 1, 0, 10_000), _reservation("J1", 0, 0, 10_000)),
        )


def test_peak_concurrency_counts_overlapping_windows():
    gc = GreenCorridorRequest(
        corridor_id="gc-1", request_id="er-1", vehicle_id="amb-01",
        route_edges=("E1",),
        reservations=(
            _reservation("J1", 0, 0, 30_000),
            _reservation("J2", 1, 10_000, 40_000),
            _reservation("J3", 2, 20_000, 50_000),  # all three overlap around t=20-30k
        ),
    )
    assert gc.peak_concurrency() == 3


def test_reservation_overlap_is_symmetric_and_half_open():
    a = _reservation("J1", 0, 0, 10_000)
    b = _reservation("J2", 1, 10_000, 20_000)   # touches but does not overlap
    c = _reservation("J3", 2, 9_000, 20_000)    # overlaps a
    assert not a.overlaps(b) and not b.overlaps(a)
    assert a.overlaps(c) and c.overlaps(a)

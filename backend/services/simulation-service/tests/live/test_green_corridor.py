"""Green corridor: planning (`GreenCorridorPlanner`) and the arbiter-facing
`CorridorController.preemption_plan`. No SUMO -- a hand-built graph + config."""

from __future__ import annotations

from itms_common.events import decode_envelope, encode_envelope
from itms_domain import (
    CorridorStatus,
    JunctionContext,
    Phase,
    Tier0Config,
    Violation,
)
from sim_service.control.safety import interlocks
from sim_service.live.green_corridor import CorridorController, GreenCorridorPlanner
from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph


def _edge(eid: str, length: float, speed: float = 10.0) -> EdgeInfo:
    return EdgeInfo(eid, length, 1, speed, f"{eid}_a", f"{eid}_b", (0.0, 0.0), (length, 0.0))


def _graph() -> RoadGraph:
    """S -> A -> B -> T. Signals entering B (J1) and entering T (J2), each a
    single controlled movement the through route uses."""
    edges = {
        "S": _edge("S", 100.0),
        "A": _edge("A", 200.0),
        "B": _edge("B", 150.0),
        "T": _edge("T", 100.0),
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
        edges=edges,
        adjacency=adjacency,
        signalised_junctions=frozenset({"J1", "J2"}),
        link_movements=link_movements,
    )


def _cfg(iid: str) -> Tier0Config:
    return Tier0Config(
        intersection_id=iid,
        phases={
            "P0": Phase("P0", frozenset({"L0"})),   # the corridor movement
            "P1": Phase("P1", frozenset({"L1"})),   # the cross street
        },
        ring_order=("P0", "P1"),
        conflict_matrix={"L0": frozenset({"L1"}), "L1": frozenset({"L0"})},
        min_green_s={"P0": 10.0, "P1": 10.0},
        max_green_s={"P0": 60.0, "P1": 60.0},
        yellow_s=3.0,
        all_red_s=2.0,
        max_wait_s=600.0,
        max_preempt_s_per_hour=300.0,
    )


ROUTE = ("S", "A", "B", "T")


# ---- planner --------------------------------------------------------------


def test_planner_finds_the_signalised_crossings_in_route_order():
    p = GreenCorridorPlanner(_graph())
    crossings = p.crossings(ROUTE)
    assert [c.tl_id for c in crossings] == ["J1", "J2"]
    assert crossings[0].movements == ("L0",)
    # J1 sits at the end of A: 100 (S) + 200 (A) = 300 m in
    assert crossings[0].distance_m == 300.0
    assert crossings[1].distance_m == 450.0
    # free-flow time: 300 m / 10 m/s = 30 s to J1
    assert crossings[0].eta_s == 30.0


def test_plan_builds_windowed_reservations_anchored_to_now():
    p = GreenCorridorPlanner(_graph())
    gc = p.plan(
        corridor_id="gc-1", request_id="er-1", vehicle_id="amb",
        route_edges=ROUTE, now_ms=1_000_000,
    )
    assert gc is not None
    assert gc.status is CorridorStatus.PROPOSED
    assert [r.intersection_id for r in gc.reservations] == ["J1", "J2"]
    j1 = gc.reservations[0]
    # arrival ~ now + 30 s; window opens prepare_lead (15 s) before, closes
    # release_lag (4 s) after
    assert j1.open_at_ms == 1_000_000 + (30 - 15) * 1000
    assert j1.close_at_ms == 1_000_000 + (30 + 4) * 1000
    assert j1.order == 0
    assert gc.peak_concurrency() <= gc.max_simultaneous


def test_plan_returns_none_when_the_route_has_no_signal():
    g = RoadGraph(
        edges={"S": _edge("S", 100.0), "T": _edge("T", 100.0)},
        adjacency={"S": (GraphEdge("T", "j", False, None),)},
        signalised_junctions=frozenset(),
    )
    p = GreenCorridorPlanner(g)
    assert p.plan(
        corridor_id="c", request_id="r", vehicle_id="v",
        route_edges=("S", "T"), now_ms=0,
    ) is None


# ---- controller: lifecycle + events ------------------------------------


def test_activate_emits_proposed_then_activated_and_tracks_the_corridor():
    c = CorridorController(_graph())
    cid = c.activate(
        request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=0, step=5
    )
    assert cid == "gc-0001"
    events = c.drain_events()
    assert [e["event"] for e in events] == ["proposed", "activated"]
    assert events[-1]["status"] == "ACTIVE"
    assert events[-1]["reservations"][0]["intersection_id"] == "J1"
    assert c.active_corridor_ids() == ["gc-0001"]


def test_deactivate_emits_terminated_and_drops_it():
    c = CorridorController(_graph())
    c.activate(request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=0)
    c.drain_events()
    c.deactivate("er-1", reason="arrived")
    (evt,) = c.drain_events()
    assert evt["event"] == "terminated"
    assert evt["status"] == "COMPLETED"
    assert c.active_corridor_ids() == []


def test_tick_marks_passed_junctions_and_completes_when_all_cleared():
    c = CorridorController(_graph())
    c.activate(request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=0)
    c.drain_events()
    # EV has driven 320 m -> past J1 (300 m) but not J2 (450 m)
    c.tick(step=1, sim_time_s=32.0, progress_by_request={"er-1": 320.0})
    (evt,) = c.drain_events()
    assert evt["event"] == "junction_passed" and evt["detail"] == "J1"
    # now past J2 as well
    c.tick(step=2, sim_time_s=46.0, progress_by_request={"er-1": 500.0})
    kinds = [e["event"] for e in c.drain_events()]
    assert "junction_passed" in kinds and "terminated" in kinds
    assert c.active_corridor_ids() == []


# ---- controller: the arbiter hook -----------------------------------


def test_no_open_window_means_no_preemption_plan():
    c = CorridorController(_graph())
    c.activate(request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=1_000_000)
    ctx = JunctionContext("J1", "P0", 5.0)
    # window for J1 opens at now + 15 s; at +0 s there is nothing yet
    c.tick(step=1, sim_time_s=1000.0, progress_by_request={})
    assert c.preemption_plan(_cfg("J1"), ctx) is None


def test_open_window_holds_the_ev_phase_when_it_is_already_green():
    c = CorridorController(_graph())
    c.activate(request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=0)
    # J1 window: open at 15 s, close at 34 s. Put the clock at 20 s.
    c.tick(step=1, sim_time_s=20.0, progress_by_request={})
    cfg = _cfg("J1")
    ctx = JunctionContext("J1", "P0", 12.0)          # EV's phase already live
    plan = c.preemption_plan(cfg, ctx)
    assert plan is not None
    assert plan.source == "corridor_preemption"
    assert len(plan.steps) == 1 and plan.steps[0].phase_id == "P0"
    assert interlocks.check(plan, ctx, cfg) == []    # a same-phase hold is safe


def test_open_window_switches_with_full_clearance_when_a_different_phase_is_live():
    c = CorridorController(_graph())
    c.activate(request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=0)
    c.tick(step=1, sim_time_s=20.0, progress_by_request={})
    cfg = _cfg("J1")
    ctx = JunctionContext("J1", "P1", 15.0)          # cross street live, past its min-green
    plan = c.preemption_plan(cfg, ctx)
    assert plan is not None
    assert [s.phase_id for s in plan.steps] == ["P1", "P0"]
    assert plan.steps[0].yellow_s == cfg.yellow_s and plan.steps[0].all_red_s == cfg.all_red_s
    assert interlocks.check(plan, ctx, cfg) == []


def test_interlocks_reject_a_switch_that_would_truncate_min_green():
    """The planner never truncates a green, but a hand-forced plan that does
    must still be caught by the same interlocks the arbiter runs."""
    cfg = _cfg("J1")
    ctx = JunctionContext("J1", "P1", 3.0)           # only 3 s into P1's 10 s min-green
    c = CorridorController(_graph())
    c.activate(request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=0)
    c.tick(step=1, sim_time_s=20.0, progress_by_request={})
    plan = c.preemption_plan(cfg, ctx)
    assert plan is not None
    # the controller's own plan carries the min-green remainder, so it's legal
    assert interlocks.check(plan, ctx, cfg) == []
    # force the truncation the controller refuses to make
    from dataclasses import replace
    bad = replace(plan, steps=(replace(plan.steps[0], green_s=0.0), plan.steps[1]))
    violations = interlocks.check(bad, ctx, cfg)
    assert any(v.rule == "I3" for v in violations)


def test_passed_junction_is_no_longer_preempted():
    c = CorridorController(_graph())
    c.activate(request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=0)
    c.tick(step=1, sim_time_s=20.0, progress_by_request={"er-1": 320.0})  # past J1
    c.drain_events()
    ctx = JunctionContext("J1", "P0", 12.0)
    assert c.preemption_plan(_cfg("J1"), ctx) is None


# ---- payload schema -------------------------------------------------


def test_corridor_payload_round_trips_through_the_schema():
    c = CorridorController(_graph())
    c.activate(request_id="er-1", vehicle_id="amb", route_edges=ROUTE, now_ms=1234, step=9)
    payload = c.drain_events()[-1]
    env = decode_envelope(
        encode_envelope(event_type="GreenCorridorUpdated", source="t", payload=payload)
    )["payload"]
    assert env["corridor_id"] == "gc-0001"
    assert env["status"] == "ACTIVE"
    assert env["reservations"][0]["movements"] == ["L0"]
    assert env["reservations"][0]["order"] == 0


# a Violation import guard so the unused-import linter and the reader agree
_ = Violation

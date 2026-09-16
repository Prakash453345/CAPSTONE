"""The contract between a `SignalPlan` the interlocks approved and what
`control/runner.py` physically does with it -- tested against
`FakeCabinet`, no SUMO.

Two runner-level defects motivated this file (see `_apply_decision`'s
docstring in `runner.py`):

1. A one-step plan's `green_s` was added to `current_phase_elapsed_s`
   verbatim. Only `step_length` of simulated time passes per tick, so a
   requester that put a *commitment* in `green_s` (the corridor engine's
   ENTRY_HOLD, `green_s = remaining_ped_s`) inflated the junction's own
   notion of how long its green had run, and I3 was then judged against
   a green that had never been shown.
2. A two-step plan whose first step carried `green_s > tick` -- which
   `interlocks.min_green_satisfied` reads as "hold this long, *then*
   clear" and accepts on that basis -- was executed as "clear now". The
   live green corridor emits exactly such a plan when preempting inside
   a phase's minimum green. The plan was legal; the runner truncated the
   green anyway.

Plus the fault-recovery path, which jumped green -> green with no yellow
or all-red between two conflicting phases.
"""

from __future__ import annotations

from itms_domain import JunctionContext, Phase, PlanStep, SignalPlan, Tier0Config

from sim_service.control.runner import (
    _advance_transition,
    _apply_decision,
    _JunctionState,
    _recover_from_fault,
)
from sim_service.signal_controller.cabinet import FakeCabinet

YELLOW, ALL_RED = 3.0, 2.0


def _cfg() -> Tier0Config:
    phases = {
        "P0": Phase("P0", frozenset({"L0"})),
        "P1": Phase("P1", frozenset({"L1"})),
    }
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=("P0", "P1"),
        conflict_matrix={"L0": frozenset({"L1"}), "L1": frozenset({"L0"})},
        min_green_s={"P0": 10.0, "P1": 10.0},
        max_green_s={"P0": 30.0, "P1": 30.0},
        yellow_s=YELLOW,
        all_red_s=ALL_RED,
    )


def _junction(current: str, elapsed: float) -> _JunctionState:
    cabinet = FakeCabinet()
    cabinet.command(current)
    cabinet.raw_states.clear()
    ctx = JunctionContext(intersection_id="J", current_phase_id=current, current_phase_elapsed_s=elapsed)
    return _JunctionState(cfg=_cfg(), cabinet=cabinet, ctx=ctx)


def _run_transition_to_completion(js: _JunctionState, step_length: float = 1.0) -> int:
    ticks = 0
    while js.transition is not None:
        _advance_transition(js, step_length)
        ticks += 1
        assert ticks < 100, "transition never completed"
    return ticks


# ---- one-step plans ----------------------------------------------------------


def test_extend_advances_elapsed_by_one_tick_not_by_the_plans_green_s():
    js = _junction("P0", 4.0)
    # A commitment-shaped hold, exactly what `corridor/junction.py`'s
    # ENTRY_HOLD emits with a pedestrian interval still running.
    plan = SignalPlan("J", (PlanStep("P0", green_s=15.0),), source="corridor_preemption")

    _apply_decision(js, "J", plan, step_length=1.0)

    assert js.ctx.current_phase_id == "P0"
    assert js.ctx.current_phase_elapsed_s == 5.0  # not 19.0
    assert js.transition is None
    assert js.cabinet.raw_states == []  # nothing physically changed


def test_extend_respects_a_non_unit_step_length():
    js = _junction("P0", 4.0)
    _apply_decision(js, "J", SignalPlan("J", (PlanStep("P0", green_s=0.5),)), step_length=0.5)
    assert js.ctx.current_phase_elapsed_s == 4.5


# ---- two-step plans ----------------------------------------------------------


def test_transition_with_one_tick_of_green_starts_yellow_immediately():
    js = _junction("P0", 12.0)
    plan = SignalPlan(
        "J",
        (PlanStep("P0", green_s=1.0, yellow_s=YELLOW, all_red_s=ALL_RED), PlanStep("P1", 10.0)),
    )

    _apply_decision(js, "J", plan, step_length=1.0)

    assert js.transition is not None
    assert js.transition.outgoing_phase == "P0" and js.transition.incoming_phase == "P1"
    assert js.cabinet.raw_states == ["yellow:P0"]


def test_transition_that_still_owes_green_holds_instead_of_clearing():
    """The live green corridor's own shape: 3 s into a 10 s minimum, plan
    promises `green_s = 7` before the yellow. The interlocks pass that plan
    (`3 + 7 >= 10`). The runner must keep the promise, not start yellow at
    3 s."""
    js = _junction("P1", 3.0)
    plan = SignalPlan(
        "J",
        (PlanStep("P1", green_s=7.0, yellow_s=YELLOW, all_red_s=ALL_RED), PlanStep("P0", 10.0)),
        source="corridor_preemption",
    )

    _apply_decision(js, "J", plan, step_length=1.0)

    assert js.transition is None, "must not begin clearing while green is still owed"
    assert js.ctx.current_phase_id == "P1"
    assert js.ctx.current_phase_elapsed_s == 4.0
    assert js.cabinet.raw_states == []


def test_min_green_is_physically_delivered_when_a_requester_asks_inside_it():
    """Drive the live-corridor plan shape tick by tick, re-proposing each
    tick as the arbiter would, and count the seconds of green actually
    shown before the yellow appears. It must be at least `min_green_s`."""
    js = _junction("P1", 0.0)
    min_g = js.cfg.min_green_s["P1"]
    ticks_green = 0
    for _ in range(50):
        remaining = max(0.0, min_g - js.ctx.current_phase_elapsed_s)
        plan = SignalPlan(
            "J",
            (
                PlanStep("P1", green_s=remaining, yellow_s=YELLOW, all_red_s=ALL_RED),
                PlanStep("P0", 10.0),
            ),
            source="corridor_preemption",
        )
        _apply_decision(js, "J", plan, step_length=1.0)
        ticks_green += 1  # this tick's simulation step will display whatever is set now
        if js.transition is not None:
            break
    # `elapsed` at the decision that started the yellow was >= min_g, and
    # the green was displayed for every tick before that plus the one in
    # which the decision was taken.
    assert js.transition is not None
    assert ticks_green >= min_g


def test_faulted_exit_with_zero_green_clears_immediately():
    js = _junction("P0", 2.0)
    js.ctx = JunctionContext("J", "P0", 2.0, faulted_phases=frozenset({"P0"}))
    plan = SignalPlan(
        "J",
        (PlanStep("P0", green_s=0.0, yellow_s=YELLOW, all_red_s=ALL_RED), PlanStep("P1", 10.0)),
    )
    _apply_decision(js, "J", plan, step_length=1.0)
    assert js.transition is not None and js.transition.incoming_phase == "P1"


# ---- fault recovery ------------------------------------------------------------


def test_fault_recovery_never_jumps_green_to_green_between_conflicting_phases():
    """The arbiter has just commanded all-red after an interlock rejection
    while P0 was green; I5 named L1. Recovery must show P0's yellow, then
    all-red for the full clearance, and only then P1's green."""
    js = _junction("P0", 25.0)
    js.cabinet.command_all_red()  # what `arbiter.tick` just did
    js.cabinet.raw_states.clear()

    _recover_from_fault(js, "J", frozenset({"L1"}))

    assert js.transition is not None
    assert js.transition.incoming_phase == "P1"
    assert js.cabinet.raw_states == ["yellow:P0"]
    assert js.cabinet.read_state().phase_id is None  # not green yet

    ticks = _run_transition_to_completion(js)
    assert ticks == int(YELLOW + ALL_RED)
    assert js.cabinet.raw_states == ["yellow:P0", "all_red", "green:P1"]
    assert js.ctx.current_phase_id == "P1"
    assert js.ctx.current_phase_elapsed_s == 0.0
    assert js.cabinet.read_state().phase_id == "P1"


def test_fault_recovery_into_the_same_phase_recommands_it_without_a_transition():
    js = _junction("P0", 25.0)
    js.cabinet.command_all_red()
    js.cabinet.raw_states.clear()

    _recover_from_fault(js, "J")  # ring_order[0] == P0 == current

    assert js.transition is None
    assert js.cabinet.read_state().phase_id == "P0"
    assert js.ctx.current_phase_id == "P0" and js.ctx.current_phase_elapsed_s == 0.0


def test_fault_recovery_keeps_the_outgoing_phase_as_current_until_the_green_lands():
    """While mid-transition the runner does not arbitrate the junction, but
    anything that *does* read the context (event publishing, the anomaly
    feature sampler's `phase_by_tls`) must not be told the incoming phase
    is live before the cabinet actually shows it."""
    js = _junction("P0", 25.0)
    _recover_from_fault(js, "J", frozenset({"L1"}))
    assert js.ctx.current_phase_id == "P0"
    _advance_transition(js, 1.0)  # still in yellow
    assert js.ctx.current_phase_id == "P0"

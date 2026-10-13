"""Hypothesis property tests for I1-I7 [build guide §3.3]. Written before
any optimiser exists, exactly as the guide insists -- these are the actual
gate for M2: "the property suite passes with 10 000 generated cases per
invariant... `SignalPlan` proposals from a deliberately malicious test
strategy cannot produce a conflicting green."

Each test below plays the "malicious test strategy": it constructs a
`SignalPlan` engineered to violate exactly one invariant (via a Hypothesis
strategy that can inject the violation or not, tagged so the test knows
which), then asserts `interlocks.check()` catches it if and only if the
violation was actually injected. This is the shape that actually tests the
checker rather than just re-deriving its own logic: a test that only ever
feeds it valid plans could pass with a checker that does nothing.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, PlanStep, SignalPlan, Tier0Config
from sim_service.control.safety import interlocks

# Slow (10 000 cases x 8 invariants, ~55s), not flaky -- this is the actual
# M2 gate the build guide specifies, so `make test` still runs it. Marked
# only so `make test-fast` can skip it for a quick dev loop.
pytestmark = pytest.mark.slow_property

N_CASES = 10_000

# A small fixed two-phase, two-movement-per-phase junction, reused across
# invariants so each test can focus on one violation shape at a time
# without re-deriving a whole random junction generator per invariant.
_CFG = Tier0Config(
    intersection_id="J",
    phases={
        "NS": Phase("NS", frozenset({"N", "S"})),
        "EW": Phase("EW", frozenset({"E", "W"})),
        "PED": Phase("PED", frozenset({"ped_all"}), is_pedestrian=True),
    },
    ring_order=("NS", "EW", "PED"),
    conflict_matrix={
        "N": frozenset({"E", "W", "ped_all"}),
        "S": frozenset({"E", "W", "ped_all"}),
        "E": frozenset({"N", "S", "ped_all"}),
        "W": frozenset({"N", "S", "ped_all"}),
        "ped_all": frozenset({"N", "S", "E", "W"}),
    },
    min_green_s={"NS": 10.0, "EW": 10.0, "PED": 8.0},
    max_green_s={"NS": 30.0, "EW": 30.0, "PED": 8.0},
    yellow_s=3.0,
    all_red_s=2.0,
    ped_walk_s={"PED": 5.0},
    ped_clearance_s={"PED": 3.0},
    max_wait_s=120.0,
    max_preempt_s_per_hour=300.0,
)


@given(inject=st.booleans(), extra_green=st.floats(min_value=0.1, max_value=20.0))
@settings(max_examples=N_CASES, deadline=None)
def test_I1_no_conflicting_greens(inject, extra_green):
    """A phase that (if `inject`) is engineered to hold two conflicting
    movements green at once must always be caught."""
    if inject:
        # Fabricate an illegal ad hoc phase outside the configured set by
        # reusing NS's id but the checker resolves phases via cfg, so
        # instead inject the violation the honest way: extend cfg's own
        # conflict data isn't mutable per-call, so build a *plan* against a
        # small ad hoc cfg with a genuinely conflicting phase.
        bad_cfg = Tier0Config(
            intersection_id="J",
            # N and E conflict in _CFG's matrix
            phases={"BAD": Phase("BAD", frozenset({"N", "E"}))},
            ring_order=("BAD",),
            conflict_matrix=_CFG.conflict_matrix,
            min_green_s={"BAD": 5.0},
            max_green_s={"BAD": 5.0},
            yellow_s=3.0,
            all_red_s=2.0,
        )
        ctx = JunctionContext(
            intersection_id="J", current_phase_id="BAD", current_phase_elapsed_s=0.0
        )
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("BAD", extra_green),))
        violations = interlocks.check(plan, ctx, bad_cfg)
        assert any(v.rule == "I1" for v in violations)
    else:
        ctx = JunctionContext(
            intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=0.0
        )
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("NS", extra_green + 10.0),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert not any(v.rule == "I1" for v in violations)


@given(
    inject=st.booleans(),
    elapsed=st.floats(min_value=0.0, max_value=9.9),
    proposed_green=st.floats(min_value=0.1, max_value=50.0),
)
@settings(max_examples=N_CASES, deadline=None)
def test_I3_min_green_never_truncated(inject, elapsed, proposed_green):
    """NS has min_green_s=10. With `elapsed < 10`, a plan that immediately
    switches away from NS must be flagged; one that stays on NS (or one
    where elapsed already >= 10) must not be, regardless of what
    `proposed_green` is."""
    if inject:
        ctx = JunctionContext(
            intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=elapsed
        )
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("EW", proposed_green),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert any(v.rule == "I3" for v in violations)
    else:
        ctx = JunctionContext(
            intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=elapsed
        )
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("NS", proposed_green),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert not any(v.rule == "I3" for v in violations)


@given(
    inject=st.booleans(),
    yellow_s=st.floats(min_value=0.0, max_value=2.9),
    all_red_s=st.floats(min_value=0.0, max_value=10.0),
)
@settings(max_examples=N_CASES, deadline=None)
def test_I2_clearance_present_on_conflicting_transition(inject, yellow_s, all_red_s):
    """NS -> EW conflicts (both movements interfere). cfg requires
    yellow_s=3, all_red_s=2. Anything short on either must be flagged."""
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=10.0)
    if inject:
        plan = SignalPlan(
            intersection_id="J",
            steps=(
                PlanStep("NS", 10.0, yellow_s=yellow_s, all_red_s=all_red_s),
                PlanStep("EW", 10.0),
            ),
        )
        violations = interlocks.check(plan, ctx, _CFG)
        assert any(v.rule == "I2" for v in violations)
    else:
        plan = SignalPlan(
            intersection_id="J",
            steps=(
                PlanStep("NS", 10.0, yellow_s=3.0, all_red_s=2.0),
                PlanStep("EW", 10.0),
            ),
        )
        violations = interlocks.check(plan, ctx, _CFG)
        assert not any(v.rule == "I2" for v in violations)


@given(inject=st.booleans(), ped_elapsed=st.floats(min_value=0.0, max_value=7.9))
@settings(max_examples=N_CASES, deadline=None)
def test_I4_pedestrian_clearance_always_completes(inject, ped_elapsed):
    """PED needs walk(5) + clearance(3) = 8s total. With `ped_elapsed < 8`,
    a plan that switches away (or under-serves the remainder) must be
    flagged; one that finishes serving the remaining time must not be."""
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="PED",
        current_phase_elapsed_s=ped_elapsed,
        ped_phase_in_progress="PED",
        ped_phase_elapsed_s=ped_elapsed,
    )
    if inject:
        # Simulate a preemption arriving mid-walk and trying to jump straight to NS.
        plan = SignalPlan(
            intersection_id="J",
            steps=(PlanStep("NS", 10.0),),
            source="corridor_preemption",
        )
        violations = interlocks.check(plan, ctx, _CFG)
        assert any(v.rule == "I4" for v in violations)
    else:
        required_remaining = 8.0 - ped_elapsed
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("PED", required_remaining + 0.5),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert not any(v.rule == "I4" for v in violations)


@given(inject=st.booleans(), waited=st.floats(min_value=120.0, max_value=600.0))
@settings(max_examples=N_CASES, deadline=None)
def test_I5_max_wait_bound_forces_service(inject, waited):
    """A movement with demand that has waited >= max_wait_s(120) must be
    served by the plan's very first step."""
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="EW",
        current_phase_elapsed_s=10.0,
        wait_times_s={"N": waited},
        has_demand={"N": True},
    )
    if inject:
        # Plan keeps serving EW, starving the starved N movement further.
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("EW", 10.0),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert any(v.rule == "I5" for v in violations)
    else:
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("NS", 10.0),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert not any(v.rule == "I5" for v in violations)


@given(inject=st.booleans(), used_this_hour=st.floats(min_value=0.0, max_value=299.0))
@settings(max_examples=N_CASES, deadline=None)
def test_preempt_budget_enforced(inject, used_this_hour):
    """max_preempt_s_per_hour=300. A corridor-preemption plan that would
    push the hourly total over the cap must be flagged; a non-preemption
    plan or one that stays within budget must not be."""
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="NS",
        current_phase_elapsed_s=10.0,
        preempt_seconds_last_hour=used_this_hour,
    )
    remaining_budget = 300.0 - used_this_hour
    if inject:
        plan = SignalPlan(
            intersection_id="J",
            steps=(PlanStep("NS", remaining_budget + 10.0),),
            source="corridor_preemption",
        )
        violations = interlocks.check(plan, ctx, _CFG)
        assert any(v.rule == "PREEMPT_BUDGET" for v in violations)
    else:
        plan = SignalPlan(
            intersection_id="J",
            steps=(PlanStep("NS", max(0.0, remaining_budget - 1.0)),),
            source="corridor_preemption",
        )
        violations = interlocks.check(plan, ctx, _CFG)
        assert not any(v.rule == "PREEMPT_BUDGET" for v in violations)


@given(inject=st.booleans(), green_s=st.floats(min_value=0.1, max_value=50.0))
@settings(max_examples=N_CASES, deadline=None)
def test_I6_faulted_phase_never_commanded(inject, green_s):
    """A phase in `faulted_phases` must never appear in a proposed plan."""
    faulted = frozenset({"NS"})
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="EW",
        current_phase_elapsed_s=10.0,
        faulted_phases=faulted,
    )
    if inject:
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("NS", green_s),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert any(v.rule == "I6" for v in violations)
    else:
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("EW", green_s),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert not any(v.rule == "I6" for v in violations)


@given(inject=st.booleans(), green_s=st.floats(min_value=0.1, max_value=50.0))
@settings(max_examples=N_CASES, deadline=None)
def test_ring_integrity_rejects_undefined_phase(inject, green_s):
    """A plan referencing a phase id that doesn't exist in this junction's
    ring at all must be rejected -- catches a rogue/mistyped proposer."""
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=10.0)
    if inject:
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("GHOST_PHASE", green_s),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert any(v.rule in ("RING_INTEGRITY", "I1") for v in violations)
    else:
        plan = SignalPlan(intersection_id="J", steps=(PlanStep("EW", green_s),))
        violations = interlocks.check(plan, ctx, _CFG)
        assert not any(v.rule == "RING_INTEGRITY" for v in violations)


def test_empty_plan_is_a_violation_not_a_crash():
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS", current_phase_elapsed_s=10.0)
    plan = SignalPlan(intersection_id="J", steps=())
    violations = interlocks.check(plan, ctx, _CFG)
    assert violations and violations[0].rule == "EMPTY_PLAN"


@given(elapsed=st.floats(min_value=0.0, max_value=120.0),
       green_s=st.floats(min_value=0.1, max_value=50.0))
@settings(max_examples=N_CASES, deadline=None)
def test_a_plan_must_start_at_the_phase_the_junction_is_showing(elapsed, green_s):
    """A one-step plan naming another phase used to pass every predicate
    (minimum green is judged on the running phase, a clearance is only asked
    for between steps) and the runner applies a one-step plan by relabelling
    the current phase: a change with no yellow and no all-red."""
    ctx = JunctionContext(intersection_id="J", current_phase_id="NS",
                          current_phase_elapsed_s=elapsed)
    jump = SignalPlan(intersection_id="J", steps=(PlanStep("EW", green_s),))
    assert any(v.rule == "PLAN_CONTINUITY" for v in interlocks.check(jump, ctx, _CFG))
    for steps in ((PlanStep("NS", green_s),),
                  (PlanStep("NS", green_s, yellow_s=_CFG.yellow_s, all_red_s=_CFG.all_red_s),
                   PlanStep("EW", 10.0))):
        ok = interlocks.check(SignalPlan(intersection_id="J", steps=steps), ctx, _CFG)
        assert not any(v.rule == "PLAN_CONTINUITY" for v in ok)

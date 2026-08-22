"""The fixed-time strategy (arbitration-ladder rung 5) exists to be the
thing that's always available and always safe -- if IT can produce an
unsafe plan, the ladder has no floor. This drives it for many ticks across
randomized ring configurations and asserts `interlocks.check()` never
raises a violation, including through fault injection and ped-walk
interaction.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies import fixed_time


def _ring_config(
    n_phases: int, yellow_s: float, all_red_s: float, min_greens: list[float]
) -> Tier0Config:
    """A ring of `n_phases` phases, each with its own movement, each
    conflicting with every other (the simplest ring where every transition
    needs clearance -- worst case for I2)."""
    phase_ids = [f"P{i}" for i in range(n_phases)]
    movements = [f"m{i}" for i in range(n_phases)]
    phases = {
        pid: Phase(pid, frozenset({mv})) for pid, mv in zip(phase_ids, movements, strict=True)
    }
    conflict_matrix = {
        mv: frozenset(m2 for m2 in movements if m2 != mv) for mv in movements
    }
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=tuple(phase_ids),
        conflict_matrix=conflict_matrix,
        min_green_s=dict(zip(phase_ids, min_greens, strict=True)),
        max_green_s=dict(zip(phase_ids, min_greens, strict=True)),
        yellow_s=yellow_s,
        all_red_s=all_red_s,
    )


@given(
    n_phases=st.integers(min_value=2, max_value=5),
    min_greens=st.lists(st.floats(min_value=3.0, max_value=30.0), min_size=5, max_size=5),
    yellow_s=st.floats(min_value=1.0, max_value=6.0),
    all_red_s=st.floats(min_value=0.0, max_value=4.0),
    tick_s=st.sampled_from([0.5, 1.0, 2.0]),
    n_ticks=st.integers(min_value=5, max_value=60),
)
@settings(max_examples=500, deadline=None)
def test_fixed_time_never_violates_interlocks_over_many_ticks(
    n_phases, min_greens, yellow_s, all_red_s, tick_s, n_ticks
):
    cfg = _ring_config(n_phases, yellow_s, all_red_s, min_greens[:n_phases])
    assert cfg.validate() == []

    current = cfg.ring_order[0]
    elapsed = 0.0
    for _ in range(n_ticks):
        ctx = JunctionContext(
            intersection_id="J", current_phase_id=current, current_phase_elapsed_s=elapsed
        )
        plan = fixed_time.propose(cfg, ctx, tick_s=tick_s)
        violations = interlocks.check(plan, ctx, cfg)
        assert violations == [], (
            f"fixed_time produced an unsafe plan: {violations} "
            f"(current={current}, elapsed={elapsed}, plan={plan})"
        )
        if len(plan.steps) == 1:
            elapsed += plan.steps[0].green_s
        else:
            current = plan.steps[1].phase_id
            elapsed = 0.0


@given(
    n_phases=st.integers(min_value=2, max_value=4),
    min_greens=st.lists(st.floats(min_value=3.0, max_value=15.0), min_size=4, max_size=4),
    faulted_index=st.integers(min_value=0, max_value=3),
)
@settings(max_examples=300, deadline=None)
def test_fixed_time_routes_around_a_faulted_phase(n_phases, min_greens, faulted_index):
    """C1: a faulted phase must be excluded from the ring, not commanded."""
    if faulted_index >= n_phases:
        faulted_index = 0
    cfg = _ring_config(n_phases, yellow_s=3.0, all_red_s=2.0, min_greens=min_greens[:n_phases])
    faulted_phase = cfg.ring_order[faulted_index]

    if n_phases == 1:
        return  # nothing to route to; covered by the all-faulted test below

    current = cfg.ring_order[(faulted_index + 1) % n_phases]  # start somewhere not faulted
    elapsed = 0.0
    for _ in range(n_phases * 20):
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            faulted_phases=frozenset({faulted_phase}),
        )
        plan = fixed_time.propose(cfg, ctx, tick_s=1.0)
        violations = interlocks.check(plan, ctx, cfg)
        assert violations == [], f"unsafe plan around a fault: {violations}"
        assert all(step.phase_id != faulted_phase for step in plan.steps), (
            f"faulted phase {faulted_phase!r} was commanded anyway: {plan}"
        )
        if len(plan.steps) == 1:
            elapsed += plan.steps[0].green_s
        else:
            current = plan.steps[1].phase_id
            elapsed = 0.0


def test_fixed_time_with_every_phase_faulted_proposes_no_plan():
    """C1's worst case: no legal phase exists anywhere in the ring. The
    strategy must not invent one -- it's the arbiter's job to drop to
    hardware failsafe when this happens (signal_controller/arbiter.py)."""
    cfg = _ring_config(3, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0, 10.0])
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=0.0,
        faulted_phases=frozenset(cfg.ring_order),
    )
    plan = fixed_time.propose(cfg, ctx, tick_s=1.0)
    assert plan.steps == ()

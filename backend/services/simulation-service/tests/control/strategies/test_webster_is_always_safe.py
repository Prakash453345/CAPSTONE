"""`webster.propose` reuses fixed_time's exact plan shape with one number
source swapped (see webster.py's docstring) -- this drives it the same way
`test_fixed_time_is_always_safe.py` drives fixed_time, across randomized
ring configs AND randomized (not necessarily Webster-computed) timings, to
confirm the substitution didn't quietly reopen a hole the original proof
closed. It deliberately does not require the timing to have come from
`compute_timing` -- a strategy module has to be safe for *any* timing
`green_s` mapping a caller hands it, including ones outside a phase's own
min/max_green, since `compute_timing` is not the only thing that could
construct a `WebsterTiming`.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies import webster


def _ring_config(
    n_phases: int, yellow_s: float, all_red_s: float, min_greens: list[float]
) -> Tier0Config:
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
        max_green_s=dict(zip(phase_ids, [g * 5 for g in min_greens], strict=True)),
        yellow_s=yellow_s,
        all_red_s=all_red_s,
    )


@given(
    n_phases=st.integers(min_value=2, max_value=5),
    min_greens=st.lists(st.floats(min_value=3.0, max_value=30.0), min_size=5, max_size=5),
    tuned_greens=st.lists(st.floats(min_value=1.0, max_value=150.0), min_size=5, max_size=5),
    yellow_s=st.floats(min_value=1.0, max_value=6.0),
    all_red_s=st.floats(min_value=0.0, max_value=4.0),
    tick_s=st.sampled_from([0.5, 1.0, 2.0]),
    n_ticks=st.integers(min_value=5, max_value=60),
)
@settings(max_examples=500, deadline=None)
def test_webster_never_violates_interlocks_over_many_ticks(
    n_phases, min_greens, tuned_greens, yellow_s, all_red_s, tick_s, n_ticks
):
    cfg = _ring_config(n_phases, yellow_s, all_red_s, min_greens[:n_phases])
    assert cfg.validate() == []

    # A deliberately adversarial "tuning" -- arbitrary floats, not run
    # through compute_timing, some possibly below a phase's own min_green.
    # The strategy must still never truncate a green below min_green
    # regardless of what the timing plan asked for (see propose's docstring).
    timing = webster.WebsterTiming(
        intersection_id="J",
        cycle_s=sum(tuned_greens[:n_phases]),
        green_s=dict(zip(cfg.ring_order, tuned_greens[:n_phases], strict=True)),
        critical_flow_ratios={},
        degree_of_saturation=0.0,
    )

    current = cfg.ring_order[0]
    elapsed = 0.0
    for _ in range(n_ticks):
        ctx = JunctionContext(
            intersection_id="J", current_phase_id=current, current_phase_elapsed_s=elapsed
        )
        plan = webster.propose(cfg, ctx, timing, tick_s=tick_s)
        violations = interlocks.check(plan, ctx, cfg)
        assert violations == [], (
            f"webster produced an unsafe plan: {violations} "
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
def test_webster_routes_around_a_faulted_phase(n_phases, min_greens, faulted_index):
    """C1, same guarantee fixed_time gives: a faulted phase is excluded
    from the ring regardless of what the tuned timing says about it."""
    if faulted_index >= n_phases:
        faulted_index = 0
    cfg = _ring_config(n_phases, yellow_s=3.0, all_red_s=2.0, min_greens=min_greens[:n_phases])
    faulted_phase = cfg.ring_order[faulted_index]
    timing = webster.WebsterTiming(
        intersection_id="J",
        cycle_s=0.0,
        green_s=dict.fromkeys(cfg.ring_order, 8.0),
        critical_flow_ratios={},
        degree_of_saturation=0.0,
    )

    if n_phases == 1:
        return

    current = cfg.ring_order[(faulted_index + 1) % n_phases]
    elapsed = 0.0
    for _ in range(n_phases * 20):
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            faulted_phases=frozenset({faulted_phase}),
        )
        plan = webster.propose(cfg, ctx, timing, tick_s=1.0)
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

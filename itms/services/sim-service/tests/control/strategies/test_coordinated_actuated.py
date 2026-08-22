"""Coordinated-actuated adds one new kind of input over semi-actuated's
(an absolute schedule: `system_time_s`, `CoordinationPlan.offset_s`/
`cycle_s`) and one new safety-adjacent behaviour to check for (force-off
never truncating a green below min_green -- `_can_fit`'s whole reason for
existing). The Hypothesis suite mirrors semi-actuated's realistic-
accumulation design (see that module's test file for why independent
per-tick redraws of wait_times_s would be unfair); the deterministic tests
check the coordination-specific mechanics directly: the guaranteed window
never yields, a call that can't fit waits rather than being started and
then truncated, and force-off fires on schedule regardless of demand.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies import coordinated_actuated as ca


def _ring_config(
    n_phases: int,
    yellow_s: float,
    all_red_s: float,
    min_greens: list[float],
    max_greens: list[float],
    max_wait_s: float | None = None,
) -> Tier0Config:
    phase_ids = [f"P{i}" for i in range(n_phases)]
    movements = [f"m{i}" for i in range(n_phases)]
    phases = {
        pid: Phase(pid, frozenset({mv})) for pid, mv in zip(phase_ids, movements, strict=True)
    }
    conflict_matrix = {
        mv: frozenset(m2 for m2 in movements if m2 != mv) for mv in movements
    }
    kwargs = {} if max_wait_s is None else {"max_wait_s": max_wait_s}
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=tuple(phase_ids),
        conflict_matrix=conflict_matrix,
        min_green_s=dict(zip(phase_ids, min_greens, strict=True)),
        max_green_s=dict(zip(phase_ids, max_greens, strict=True)),
        yellow_s=yellow_s,
        all_red_s=all_red_s,
        **kwargs,
    )


@given(
    n_phases=st.integers(min_value=2, max_value=4),
    min_greens=st.lists(st.floats(min_value=3.0, max_value=15.0), min_size=4, max_size=4),
    max_greens=st.lists(st.floats(min_value=20.0, max_value=60.0), min_size=4, max_size=4),
    yellow_s=st.floats(min_value=1.0, max_value=6.0),
    all_red_s=st.floats(min_value=0.0, max_value=4.0),
    cycle_s=st.floats(min_value=40.0, max_value=180.0),
    offset_s=st.floats(min_value=0.0, max_value=200.0),
    tick_s=st.sampled_from([0.5, 1.0, 2.0]),
    data=st.data(),
)
@settings(max_examples=300, deadline=None)
def test_coordinated_actuated_never_violates_interlocks_over_many_ticks(
    n_phases, min_greens, max_greens, yellow_s, all_red_s, cycle_s, offset_s, tick_s, data
):
    max_wait_s = sum(max_greens[:n_phases]) + n_phases * (yellow_s + all_red_s) + 60.0 + cycle_s
    cfg = _ring_config(
        n_phases, yellow_s, all_red_s, min_greens[:n_phases], max_greens[:n_phases],
        max_wait_s=max_wait_s,
    )
    assert cfg.validate() == []
    coord_phase = cfg.ring_order[0]
    # A modest coordinated green share -- big enough to be meaningful,
    # small enough to leave real room for the permissive window this test
    # actually wants to exercise.
    coordinated_green_s = min(min_greens[0], cycle_s / (n_phases + 1))
    coordination = ca.CoordinationPlan(
        intersection_id="J",
        coordinated_phase_id=coord_phase,
        cycle_s=cycle_s,
        offset_s=offset_s,
        coordinated_green_s=coordinated_green_s,
    )

    current = coord_phase
    elapsed = 0.0
    system_time_s = data.draw(st.floats(min_value=0.0, max_value=500.0))
    demand = {f"m{i}": data.draw(st.booleans(), label=f"init_demand_m{i}") for i in range(n_phases)}
    wait_times = dict.fromkeys(demand, 0.0)
    n_ticks = data.draw(st.integers(min_value=10, max_value=80))
    for _ in range(n_ticks):
        for m in demand:
            if data.draw(st.floats(min_value=0.0, max_value=1.0), label=f"flip_{m}") < 0.1:
                demand[m] = not demand[m]

        served_now = cfg.phases[current].green_movements
        for m in wait_times:
            wait_times[m] = wait_times[m] + tick_s if (demand[m] and m not in served_now) else 0.0

        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            has_demand=dict(demand),
            wait_times_s=dict(wait_times),
        )
        plan = ca.propose(
            cfg, ctx, coordination=coordination, system_time_s=system_time_s, tick_s=tick_s
        )
        violations = interlocks.check(plan, ctx, cfg)
        assert violations == [], (
            f"coordinated_actuated produced an unsafe plan: {violations} "
            f"(current={current}, elapsed={elapsed}, system_time_s={system_time_s}, "
            f"demand={demand}, wait_times={wait_times}, plan={plan})"
        )
        if len(plan.steps) == 1:
            elapsed += plan.steps[0].green_s
        else:
            current = plan.steps[1].phase_id
            elapsed = 0.0
        system_time_s += tick_s


@given(
    n_phases=st.integers(min_value=2, max_value=4),
    min_greens=st.lists(st.floats(min_value=3.0, max_value=15.0), min_size=4, max_size=4),
    faulted_index=st.integers(min_value=0, max_value=3),
)
@settings(max_examples=200, deadline=None)
def test_coordinated_actuated_routes_around_a_faulted_phase(n_phases, min_greens, faulted_index):
    if faulted_index >= n_phases:
        faulted_index = 0
    max_greens = [g * 4 for g in min_greens]
    cfg = _ring_config(
        n_phases, yellow_s=3.0, all_red_s=2.0,
        min_greens=min_greens[:n_phases], max_greens=max_greens[:n_phases],
        max_wait_s=10_000.0,
    )
    faulted_phase = cfg.ring_order[faulted_index]
    coord_phase = next(p for p in cfg.ring_order if p != faulted_phase)
    coordination = ca.CoordinationPlan(
        intersection_id="J", coordinated_phase_id=coord_phase,
        cycle_s=200.0, offset_s=0.0, coordinated_green_s=10.0,
    )

    if n_phases == 1:
        return

    current = coord_phase
    elapsed = 0.0
    has_demand = {
        f"m{i}": cfg.ring_order[i] != faulted_phase and cfg.ring_order[i] != coord_phase
        for i in range(n_phases)
    }
    wait_times = dict.fromkeys(has_demand, 50.0)
    system_time_s = 0.0

    for _ in range(n_phases * 30):
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            has_demand=has_demand,
            wait_times_s=wait_times,
            faulted_phases=frozenset({faulted_phase}),
        )
        plan = ca.propose(
            cfg, ctx, coordination=coordination, system_time_s=system_time_s, tick_s=1.0
        )
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
        system_time_s += 1.0


def test_coordinated_phase_never_yields_during_its_guaranteed_window():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[60.0, 60.0]
    )
    coordination = ca.CoordinationPlan(
        intersection_id="J", coordinated_phase_id="P0", cycle_s=60.0, offset_s=0.0,
        coordinated_green_s=30.0,
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=15.0,  # past P0's own min_green
        has_demand={"m1": True},
        wait_times_s={"m1": 90.0},
    )
    # system_time_s = 10 -> pos = 10, well inside the [0, 30) guaranteed window
    plan = ca.propose(cfg, ctx, coordination=coordination, system_time_s=10.0, tick_s=1.0)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"


def test_minor_call_served_once_guaranteed_window_ends():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[60.0, 60.0]
    )
    coordination = ca.CoordinationPlan(
        intersection_id="J", coordinated_phase_id="P0", cycle_s=60.0, offset_s=0.0,
        coordinated_green_s=30.0,
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=35.0,
        has_demand={"m1": True},
    )
    # pos = 40 -> past the 30s guaranteed window, plenty of the cycle left to fit P1
    plan = ca.propose(cfg, ctx, coordination=coordination, system_time_s=40.0, tick_s=1.0)
    assert len(plan.steps) == 2
    assert plan.steps[1].phase_id == "P1"


def test_late_call_that_cannot_fit_before_force_off_waits_for_next_cycle():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[60.0, 60.0]
    )
    coordination = ca.CoordinationPlan(
        intersection_id="J", coordinated_phase_id="P0", cycle_s=60.0, offset_s=0.0,
        coordinated_green_s=30.0,
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=35.0,
        has_demand={"m1": True},
    )
    # pos = 55 -> only 5s left before the next guaranteed window; P1 needs
    # 10s min_green + 5s clearance = 15s, which doesn't fit. Must not start it.
    plan = ca.propose(cfg, ctx, coordination=coordination, system_time_s=55.0, tick_s=1.0)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"


def test_force_off_ends_minor_phase_even_with_continued_demand():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[60.0, 60.0]
    )
    coordination = ca.CoordinationPlan(
        intersection_id="J", coordinated_phase_id="P0", cycle_s=60.0, offset_s=0.0,
        coordinated_green_s=30.0,
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P1",
        current_phase_elapsed_s=20.0,
        has_demand={"m1": True},  # still calling -- must not matter, force-off wins
    )
    # pos = 55 -> remaining_in_cycle = 5s <= clearance(5s) + tick_s(1s) -> force off
    plan = ca.propose(cfg, ctx, coordination=coordination, system_time_s=55.0, tick_s=1.0)
    assert len(plan.steps) == 2
    assert plan.steps[1].phase_id == "P0"


def test_coordinated_actuated_with_every_phase_faulted_proposes_no_plan():
    cfg = _ring_config(3, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0] * 3, max_greens=[30.0] * 3)
    coordination = ca.CoordinationPlan(
        intersection_id="J", coordinated_phase_id="P0", cycle_s=60.0, offset_s=0.0,
        coordinated_green_s=20.0,
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=0.0,
        faulted_phases=frozenset(cfg.ring_order),
    )
    plan = ca.propose(cfg, ctx, coordination=coordination, system_time_s=0.0, tick_s=1.0)
    assert plan.steps == ()

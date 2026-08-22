"""Semi-actuated has two kinds of claim to check: the safety proof every
strategy owes (Hypothesis, mirroring fixed_time's/webster's suites, driven
here across randomized has_demand/wait_times_s sequences since that's the
new input surface this strategy reads that the other two don't), and a
handful of deterministic behavioural checks that this is actually
semi-actuated logic and not just a safe no-op -- major rests in green
indefinitely with no calls, a call gets served once the major's own
min_green clears, a served minor gaps out when its call disappears, and a
served minor still max-outs even against a call that never stops.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies import semi_actuated


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


def test_pick_major_phase_picks_the_highest_flow_ratio():
    ratios = {"P0": 0.2, "P1": 0.55, "P2": 0.1}
    assert semi_actuated.pick_major_phase(ratios) == "P1"


@given(
    n_phases=st.integers(min_value=2, max_value=4),
    min_greens=st.lists(st.floats(min_value=3.0, max_value=15.0), min_size=4, max_size=4),
    max_greens=st.lists(st.floats(min_value=20.0, max_value=60.0), min_size=4, max_size=4),
    yellow_s=st.floats(min_value=1.0, max_value=6.0),
    all_red_s=st.floats(min_value=0.0, max_value=4.0),
    tick_s=st.sampled_from([0.5, 1.0, 2.0]),
    data=st.data(),
)
@settings(max_examples=300, deadline=None)
def test_semi_actuated_never_violates_interlocks_over_many_ticks(
    n_phases, min_greens, max_greens, yellow_s, all_red_s, tick_s, data
):
    # max_wait_s scaled to this ring's own worst-case full-service time (every
    # phase maxing out once, plus clearance overhead) with a comfortable
    # margin -- the same relationship a real deployment would tune, so I5 is
    # actually achievable by the config rather than an arbitrary global
    # default the ring's own parameters can't structurally satisfy.
    max_wait_s = sum(max_greens[:n_phases]) + n_phases * (yellow_s + all_red_s) + 60.0
    cfg = _ring_config(
        n_phases, yellow_s, all_red_s, min_greens[:n_phases], max_greens[:n_phases],
        max_wait_s=max_wait_s,
    )
    assert cfg.validate() == []
    major_phase_id = cfg.ring_order[0]

    current = major_phase_id
    elapsed = 0.0
    # has_demand persists across ticks rather than being redrawn independently
    # each time (which could otherwise construct a physically-impossible
    # instant jump in wait_times_s) -- occasional flips model calls arriving
    # and clearing, closer to what a real detector would actually report.
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
        plan = semi_actuated.propose(cfg, ctx, major_phase_id=major_phase_id, tick_s=tick_s)
        violations = interlocks.check(plan, ctx, cfg)
        assert violations == [], (
            f"semi_actuated produced an unsafe plan: {violations} "
            f"(current={current}, elapsed={elapsed}, demand={demand}, "
            f"wait_times={wait_times}, plan={plan})"
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
@settings(max_examples=200, deadline=None)
def test_semi_actuated_routes_around_a_faulted_phase(n_phases, min_greens, faulted_index):
    if faulted_index >= n_phases:
        faulted_index = 0
    max_greens = [g * 4 for g in min_greens]
    cfg = _ring_config(
        n_phases, yellow_s=3.0, all_red_s=2.0,
        min_greens=min_greens[:n_phases], max_greens=max_greens[:n_phases],
    )
    faulted_phase = cfg.ring_order[faulted_index]
    major_phase_id = next(p for p in cfg.ring_order if p != faulted_phase)

    if n_phases == 1:
        return

    current = major_phase_id
    elapsed = 0.0
    # Every non-faulted, non-major movement calls continuously -- worst
    # case for routing logic, since something is always asking to be served.
    has_demand = {
        f"m{i}": cfg.ring_order[i] != faulted_phase and cfg.ring_order[i] != major_phase_id
        for i in range(n_phases)
    }
    wait_times = dict.fromkeys(has_demand, 50.0)

    for _ in range(n_phases * 30):
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            has_demand=has_demand,
            wait_times_s=wait_times,
            faulted_phases=frozenset({faulted_phase}),
        )
        plan = semi_actuated.propose(cfg, ctx, major_phase_id=major_phase_id, tick_s=1.0)
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


def test_major_rests_in_green_indefinitely_with_no_calls():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[30.0, 30.0]
    )
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=500.0
    )
    plan = semi_actuated.propose(cfg, ctx, major_phase_id="P0", tick_s=1.0)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"


def test_minor_call_served_once_major_min_green_cleared():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[30.0, 30.0]
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=15.0,  # past P0's min_green
        has_demand={"m1": True},
    )
    plan = semi_actuated.propose(cfg, ctx, major_phase_id="P0", tick_s=1.0)
    assert len(plan.steps) == 2
    assert plan.steps[1].phase_id == "P1"


def test_minor_call_ignored_until_major_min_green_cleared():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[30.0, 30.0]
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=2.0,  # short of P0's min_green
        has_demand={"m1": True},
    )
    plan = semi_actuated.propose(cfg, ctx, major_phase_id="P0", tick_s=1.0)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"


def test_minor_gaps_out_when_call_disappears_after_min_green():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[30.0, 30.0]
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P1",
        current_phase_elapsed_s=12.0,  # past P1's min_green
        has_demand={"m1": False},  # the call that brought us here is gone
    )
    plan = semi_actuated.propose(cfg, ctx, major_phase_id="P0", tick_s=1.0)
    assert len(plan.steps) == 2
    assert plan.steps[1].phase_id == "P0"


def test_minor_extends_while_still_called_below_max_green():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[30.0, 30.0]
    )
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P1", current_phase_elapsed_s=12.0,
        has_demand={"m1": True},
    )
    plan = semi_actuated.propose(cfg, ctx, major_phase_id="P0", tick_s=1.0)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P1"


def test_minor_max_outs_despite_continuous_call():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[30.0, 30.0]
    )
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P1",
        current_phase_elapsed_s=29.5,  # one more tick reaches max_green
        has_demand={"m1": True},  # still calling -- must not matter
    )
    plan = semi_actuated.propose(cfg, ctx, major_phase_id="P0", tick_s=1.0)
    assert len(plan.steps) == 2
    assert plan.steps[1].phase_id == "P0"


def test_longest_waiting_minor_call_wins_when_several_call_at_once():
    cfg = _ring_config(3, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0] * 3, max_greens=[30.0] * 3)
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=20.0,
        has_demand={"m1": True, "m2": True},
        wait_times_s={"m1": 15.0, "m2": 45.0},
    )
    plan = semi_actuated.propose(cfg, ctx, major_phase_id="P0", tick_s=1.0)
    assert len(plan.steps) == 2
    assert plan.steps[1].phase_id == "P2"  # m2's longer wait wins


def test_semi_actuated_with_every_phase_faulted_proposes_no_plan():
    cfg = _ring_config(3, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0] * 3, max_greens=[30.0] * 3)
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=0.0,
        faulted_phases=frozenset(cfg.ring_order),
    )
    plan = semi_actuated.propose(cfg, ctx, major_phase_id="P0", tick_s=1.0)
    assert plan.steps == ()

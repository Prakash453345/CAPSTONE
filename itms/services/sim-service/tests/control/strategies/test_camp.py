"""CA-MP (M4) test suite, same two-part shape as semi_actuated's and
coordinated_actuated's: the safety proof every strategy owes (Hypothesis,
over randomized queue_pcu/receiving_occupancy/wait_times_s), plus
deterministic checks that this is actually max-pressure logic -- flow
pressure favors the heavier queue, blocking pressure collapses a phase
flowing into a full link, fairness rises with wait, hysteresis holds a
still-competitive phase, and the degradation ladder actually falls back
to fixed_time below the confidence threshold.

`wait_times_s` is threaded across ticks the same realistic way
semi_actuated's suite establishes (grows while unserved, resets when
served) -- independent per-tick redraws would manufacture physically
impossible instant jumps that could trip I5 unfairly. `queue_pcu` and
`receiving_occupancy` are drawn independently per tick instead: unlike a
detector's internal wait clock, these represent live physical
measurements with no memory of their own to get wrong."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies import camp


def _ring_config(
    n_phases: int,
    yellow_s: float,
    all_red_s: float,
    min_greens: list[float],
    max_greens: list[float],
    max_wait_s: float | None = None,
    sat_flows: list[float] | None = None,
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
    sat_flow_pcu_s = dict(zip(movements, sat_flows or [1.0] * n_phases, strict=True))
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=tuple(phase_ids),
        conflict_matrix=conflict_matrix,
        min_green_s=dict(zip(phase_ids, min_greens, strict=True)),
        max_green_s=dict(zip(phase_ids, max_greens, strict=True)),
        yellow_s=yellow_s,
        all_red_s=all_red_s,
        sat_flow_pcu_s=sat_flow_pcu_s,
        **kwargs,
    )


# ---- select_mode -----------------------------------------------------------


def test_select_mode_full_when_fully_confident():
    ctx = JunctionContext(intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0)
    assert camp.select_mode(ctx, frozenset({"m0", "m1"})) == "camp_full"


def test_select_mode_missing_movement_defaults_to_fully_confident():
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        confidence={"m0": 0.9},
    )
    assert camp.select_mode(ctx, frozenset({"m0", "m1"})) == "camp_full"


def test_select_mode_blended_in_the_middle_band():
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        confidence={"m0": 0.6},
    )
    assert camp.select_mode(ctx, frozenset({"m0"})) == "camp_blended"


def test_select_mode_profile_actuated_when_low_confidence():
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        confidence={"m0": 0.2},
    )
    assert camp.select_mode(ctx, frozenset({"m0"})) == "profile_actuated"


def test_select_mode_uses_the_worst_movement():
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        confidence={"m0": 0.95, "m1": 0.3},
    )
    assert camp.select_mode(ctx, frozenset({"m0", "m1"})) == "profile_actuated"


def test_degraded_confidence_falls_back_to_fixed_time():
    cfg = _ring_config(
        2, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[30.0, 30.0]
    )
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=20.0,
        confidence={"m0": 0.1},
        queue_pcu={"m1": 50.0},
    )
    plan = camp.propose(cfg, ctx)
    assert plan.source == "fixed_time"


# ---- pressure terms, hand-checkable ----------------------------------------


def test_flow_pressure_scales_with_queue_and_sat_flow():
    cfg = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0], sat_flows=[2.0, 2.0])
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 5.0},
    )
    # No blocking (occupancy 0 -> theta=1, but q for block uses the SAME
    # queue as flow -- see module docstring), no fairness (single movement
    # already flowing, but fairness only fires when q>0... it WILL fire
    # here too, so isolate flow by checking the raw helper directly.
    assert camp._flow_pressure(cfg, ctx, "P0") == 2.0 * 5.0
    assert camp._flow_pressure(cfg, ctx, "P1") == 0.0


def test_block_pressure_is_zero_when_receiving_link_is_empty():
    cfg = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0], sat_flows=[2.0, 2.0])
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 5.0}, receiving_occupancy={"m0": 0.0},
    )
    camp_cfg = camp.CampConfig()
    # theta = min(theta_max, 1/max(eps, 1-0)) = min(10, 1) = 1
    assert camp._block_pressure(camp_cfg, cfg, ctx, "P0") == 2.0 * 5.0 * 1.0


def test_block_pressure_grows_hyperbolically_and_caps_at_theta_max():
    cfg = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0], sat_flows=[2.0, 2.0])
    camp_cfg = camp.CampConfig()
    ctx_full = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 5.0}, receiving_occupancy={"m0": 0.999},
    )
    # theta = min(10, 1/max(0.05, 0.001)) = min(10, 1000) = 10 (capped)
    assert camp._block_pressure(camp_cfg, cfg, ctx_full, "P0") == 2.0 * 5.0 * 10.0


def test_pressure_drops_the_block_term_when_blocking_disabled():
    # The M4 gate's own ablation switch -- disabled arm should behave as
    # if Term 2 never existed, leaving flow + fairness - switch.
    cfg = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0], sat_flows=[2.0, 2.0])
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 5.0}, receiving_occupancy={"m0": 0.999},  # near-saturated
    )
    enabled = camp.CampConfig(enable_blocking=True)
    disabled = camp.CampConfig(enable_blocking=False)
    pressure_enabled = camp.pressure(enabled, cfg, ctx, "P0")
    pressure_disabled = camp.pressure(disabled, cfg, ctx, "P0")
    # With blocking enabled, the near-saturated receiving link should pull
    # pressure well below the disabled arm's (no penalty at all).
    assert pressure_enabled < pressure_disabled
    assert pressure_disabled == camp._flow_pressure(cfg, ctx, "P0") + camp._fairness(
        enabled, cfg, ctx, "P0"
    ) - camp._switch(enabled, cfg, ctx.current_phase_id, "P0")


def test_fairness_is_zero_for_an_empty_movement():
    cfg = _ring_config(1, 3.0, 2.0, [10.0], [30.0], sat_flows=[1.0])
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 0.0}, wait_times_s={"m0": 200.0},
    )
    assert camp._fairness(camp.CampConfig(), cfg, ctx, "P0") == 0.0


def test_fairness_rises_with_wait_and_caps_at_full_wait_ratio():
    cfg = _ring_config(1, 3.0, 2.0, [10.0], [30.0], sat_flows=[1.0], max_wait_s=100.0)
    camp_cfg = camp.CampConfig()
    low_wait = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 1.0}, wait_times_s={"m0": 10.0},
    )
    high_wait = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 1.0}, wait_times_s={"m0": 500.0},  # far past max_wait_s
    )
    low = camp._fairness(camp_cfg, cfg, low_wait, "P0")
    high = camp._fairness(camp_cfg, cfg, high_wait, "P0")
    assert 0.0 < low < high
    # Capped: wait_ratio clamps to 1.0 regardless of how far past max_wait_s.
    assert high == camp_cfg.lambda_f * 1.0 * (1.0**camp_cfg.gamma)


def test_switch_is_zero_for_the_current_phase_and_positive_otherwise():
    cfg = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0])
    camp_cfg = camp.CampConfig()
    assert camp._switch(camp_cfg, cfg, "P0", "P0") == 0.0
    expected = camp_cfg.lambda_s * ((3.0 + 2.0 + camp_cfg.startup_lost_s) / camp_cfg.t_dec_s)
    assert camp._switch(camp_cfg, cfg, "P0", "P1") == expected


# ---- ring candidates / skip -------------------------------------------------


def test_ring_candidates_wrap_and_respect_k():
    order = ("P0", "P1", "P2", "P3")
    assert camp._ring_candidates(order, "P0", k=2) == ["P1", "P2"]
    assert camp._ring_candidates(order, "P3", k=2) == ["P0", "P1"]
    assert camp._ring_candidates(order, "P2", k=1) == ["P3"]


def test_ring_candidates_empty_for_a_single_phase_ring():
    assert camp._ring_candidates(("P0",), "P0", k=2) == []


def test_skippable_true_for_empty_low_wait_non_pedestrian_phase():
    cfg = _ring_config(1, 3.0, 2.0, [10.0], [30.0], max_wait_s=100.0)
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 0.0}, wait_times_s={"m0": 5.0},
    )
    assert camp._skippable(cfg, ctx, "P0") is True


def test_skippable_false_when_queue_present():
    cfg = _ring_config(1, 3.0, 2.0, [10.0], [30.0], max_wait_s=100.0)
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 1.0},
    )
    assert camp._skippable(cfg, ctx, "P0") is False


def test_skippable_false_when_wait_close_to_bound():
    cfg = _ring_config(1, 3.0, 2.0, [10.0], [30.0], max_wait_s=100.0)
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 0.0}, wait_times_s={"m0": 90.0},  # within the margin of max_wait_s
    )
    assert camp._skippable(cfg, ctx, "P0") is False


def test_pedestrian_phase_is_never_skippable():
    phases = {"P0": Phase("P0", frozenset({"m0"}), is_pedestrian=True)}
    cfg = Tier0Config(
        intersection_id="J", phases=phases, ring_order=("P0",),
        conflict_matrix={"m0": frozenset()},
        min_green_s={"P0": 10.0}, max_green_s={"P0": 30.0},
        yellow_s=3.0, all_red_s=2.0, ped_walk_s={"P0": 7.0},
    )
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m0": 0.0}, wait_times_s={"m0": 0.0},
    )
    assert camp._skippable(cfg, ctx, "P0") is False


# ---- Hypothesis: the safety proof every strategy owes -----------------------


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
def test_camp_never_violates_interlocks_over_many_ticks(
    n_phases, min_greens, max_greens, yellow_s, all_red_s, tick_s, data
):
    max_wait_s = sum(max_greens[:n_phases]) + n_phases * (yellow_s + all_red_s) + 60.0
    cfg = _ring_config(
        n_phases, yellow_s, all_red_s, min_greens[:n_phases], max_greens[:n_phases],
        max_wait_s=max_wait_s, sat_flows=[1.0] * n_phases,
    )
    assert cfg.validate() == []

    current = cfg.ring_order[0]
    elapsed = 0.0
    movements = [f"m{i}" for i in range(n_phases)]
    demand = {m: data.draw(st.booleans(), label=f"init_demand_{m}") for m in movements}
    wait_times = dict.fromkeys(movements, 0.0)
    n_ticks = data.draw(st.integers(min_value=10, max_value=80))

    for _ in range(n_ticks):
        for m in movements:
            if data.draw(st.floats(min_value=0.0, max_value=1.0), label=f"flip_{m}") < 0.1:
                demand[m] = not demand[m]
        served_now = cfg.phases[current].green_movements
        for m in wait_times:
            wait_times[m] = wait_times[m] + tick_s if (demand[m] and m not in served_now) else 0.0

        queue_pcu = {
            m: data.draw(st.floats(min_value=0.0, max_value=30.0), label=f"q_{m}")
            if demand[m] else 0.0
            for m in movements
        }
        receiving_occupancy = {
            m: data.draw(st.floats(min_value=0.0, max_value=1.0), label=f"occ_{m}")
            for m in movements
        }

        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            wait_times_s=dict(wait_times),
            queue_pcu=queue_pcu,
            receiving_occupancy=receiving_occupancy,
        )
        plan = camp.propose(cfg, ctx, tick_s=tick_s)
        violations = interlocks.check(plan, ctx, cfg)
        assert violations == [], (
            f"camp produced an unsafe plan: {violations} (current={current}, "
            f"elapsed={elapsed}, queue_pcu={queue_pcu}, wait_times={wait_times}, plan={plan})"
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
def test_camp_routes_around_a_faulted_phase(n_phases, min_greens, faulted_index):
    if faulted_index >= n_phases:
        faulted_index = 0
    max_greens = [g * 4 for g in min_greens]
    cfg = _ring_config(
        n_phases, yellow_s=3.0, all_red_s=2.0,
        min_greens=min_greens[:n_phases], max_greens=max_greens[:n_phases],
        max_wait_s=10_000.0, sat_flows=[1.0] * n_phases,
    )
    faulted_phase = cfg.ring_order[faulted_index]
    start_phase = next(p for p in cfg.ring_order if p != faulted_phase)

    if n_phases == 1:
        return

    current = start_phase
    elapsed = 0.0
    movements = [f"m{i}" for i in range(n_phases)]
    queue_pcu = {
        f"m{i}": 5.0 for i in range(n_phases)
        if cfg.ring_order[i] != faulted_phase
    }
    wait_times = dict.fromkeys(movements, 50.0)

    for _ in range(n_phases * 30):
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            wait_times_s=wait_times,
            queue_pcu=queue_pcu,
            faulted_phases=frozenset({faulted_phase}),
        )
        plan = camp.propose(cfg, ctx, tick_s=1.0)
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


def test_camp_with_every_phase_faulted_proposes_no_plan():
    cfg = _ring_config(3, yellow_s=3.0, all_red_s=2.0, min_greens=[10.0] * 3, max_greens=[30.0] * 3)
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        faulted_phases=frozenset(cfg.ring_order),
    )
    plan = camp.propose(cfg, ctx)
    assert plan.steps == ()


# ---- deterministic mechanics -------------------------------------------------


def test_extends_below_min_green_regardless_of_pressure():
    cfg = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0], sat_flows=[1.0, 1.0])
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=2.0,
        queue_pcu={"m1": 100.0},  # the other phase desperately wants to flow
    )
    plan = camp.propose(cfg, ctx)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"


def test_advances_to_the_highest_pressure_candidate_once_maxed_out():
    # At zero receiving-link occupancy theta_m == 1, so _flow_pressure and
    # _block_pressure cancel EXACTLY regardless of queue size (both reuse
    # the same queue_pcu[m] -- see camp.py's module docstring on Term 2's
    # resolved ambiguity). Raw queue size alone can't differentiate two
    # candidates here, so this test differentiates via the fairness term
    # (wait time) instead, which is real signal even in free flow.
    cfg = _ring_config(3, 3.0, 2.0, [5.0, 5.0, 5.0], [10.0, 10.0, 10.0], sat_flows=[1.0, 1.0, 1.0])
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=10.0,  # maxed out
        queue_pcu={"m1": 1.0, "m2": 1.0},
        wait_times_s={"m1": 5.0, "m2": 100.0},
    )
    plan = camp.propose(cfg, ctx, tick_s=1.0)
    assert len(plan.steps) == 2
    assert plan.steps[1].phase_id == "P2"


def test_hysteresis_holds_a_still_competitive_current_phase():
    cfg = _ring_config(2, 3.0, 2.0, [5.0, 5.0], [30.0, 30.0], sat_flows=[1.0, 1.0])
    # Equal queues -> equal pressure -> hysteresis keeps the current phase.
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=10.0,
        queue_pcu={"m0": 5.0, "m1": 5.0},
    )
    plan = camp.propose(cfg, ctx, tick_s=1.0)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"


def test_allocate_green_falls_back_to_min_green_when_total_pressure_nonpositive():
    cfg = _ring_config(2, 3.0, 2.0, [8.0, 8.0], [30.0, 30.0])
    pressures = {"P0": -1.0, "P1": -2.0}
    assert camp._allocate_green(cfg, "P1", pressures, nominal_cycle_s=60.0) == 8.0


def test_allocate_green_clamps_to_max_green():
    cfg = _ring_config(2, 3.0, 2.0, [5.0, 5.0], [15.0, 15.0])
    pressures = {"P0": 1.0, "P1": 99.0}
    g = camp._allocate_green(cfg, "P1", pressures, nominal_cycle_s=200.0)
    assert g == 15.0

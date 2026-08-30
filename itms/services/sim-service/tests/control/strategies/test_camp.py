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
    # sat_flow defaults to 1.0 in _ring_config, where the sat_flow-weighted
    # formula (see _switch's docstring -- the M4 root-cause fix) reduces to
    # exactly the original bare lost_time_s/t_dec_s value.
    cfg = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0])
    camp_cfg = camp.CampConfig()
    assert camp._switch(camp_cfg, cfg, "P0", "P0") == 0.0
    expected = camp_cfg.lambda_s * ((3.0 + 2.0 + camp_cfg.startup_lost_s) / camp_cfg.t_dec_s)
    assert camp._switch(camp_cfg, cfg, "P0", "P1") == expected


def test_switch_scales_with_saturation_flow_squared():
    # Regression test for the M4 root-cause fix (see _switch's docstring
    # and PROGRESS.md's "Root cause confirmed" section): before the fix,
    # switching cost was a flat constant, entirely independent of
    # sat_flow_pcu_s, unlike every other pressure term. It must now shrink
    # and grow with sat_flow the same way _flow_pressure does -- and since
    # sat_flow enters twice (the phantom lost queue, then that queue's own
    # pricing), a 4x change in sat_flow is a 16x change in switch cost.
    low_sat = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0], sat_flows=[0.5, 0.5])
    high_sat = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0], sat_flows=[2.0, 2.0])
    camp_cfg = camp.CampConfig()
    low = camp._switch(camp_cfg, low_sat, "P0", "P1")
    high = camp._switch(camp_cfg, high_sat, "P0", "P1")
    assert low > 0.0
    assert high == low * 16.0


def test_switch_cost_does_not_scale_with_the_candidate_phases_movement_count():
    # A phase with two green movements must not cost more to switch into
    # than one with a single movement at the same sat_flow -- the ring's
    # own yellow/all-red/startup clearance interval doesn't get longer just
    # because more movements happen to share the next phase. (A first draft
    # of this fix summed sat_flow over the phase's own movements instead of
    # averaging, and that materialized as real `failsafe_interlock_rejected`
    # events on the real corridor that the unfixed build never produced --
    # see _switch's docstring for the full story.)
    phases = {
        "P0": Phase("P0", frozenset({"m0"})),
        "P1": Phase("P1", frozenset({"m1a", "m1b"})),
    }
    cfg = Tier0Config(
        intersection_id="J", phases=phases, ring_order=("P0", "P1"),
        conflict_matrix={
            "m0": frozenset({"m1a", "m1b"}),
            "m1a": frozenset({"m0"}),
            "m1b": frozenset({"m0"}),
        },
        min_green_s={"P0": 10.0, "P1": 10.0}, max_green_s={"P0": 30.0, "P1": 30.0},
        yellow_s=3.0, all_red_s=2.0,
        sat_flow_pcu_s={"m0": 1.0, "m1a": 1.0, "m1b": 1.0},
    )
    camp_cfg = camp.CampConfig()
    switch_into_single_movement_phase = camp._switch(camp_cfg, cfg, "P1", "P0")
    switch_into_two_movement_phase = camp._switch(camp_cfg, cfg, "P0", "P1")
    assert switch_into_single_movement_phase == switch_into_two_movement_phase


def test_switch_cost_no_longer_swamps_flow_pressure_at_light_demand_scale():
    # Pins down the diagnosed bug as a regression test: at this corridor's
    # real placeholder saturation flow (0.5 pcu/s) and a realistic small
    # queue, switching cost must be the same order of magnitude as flow
    # pressure -- a modest discount -- not the 22x-61x blowout
    # `m4_camp_diagnostics.py` measured against the old flat-constant
    # formula (fixed switch cost 9.86 vs mean flow pressure 0.16-1.98).
    cfg = _ring_config(2, 3.0, 2.0, [10.0, 10.0], [30.0, 30.0], sat_flows=[0.5, 0.5])
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=0.0,
        queue_pcu={"m1": 2.0},
    )
    camp_cfg = camp.CampConfig()
    flow = camp._flow_pressure(cfg, ctx, "P1")
    switch = camp._switch(camp_cfg, cfg, "P0", "P1")
    assert switch < flow * 5.0


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


# ---- starvation override -----------------------------------------------------
#
# Regression tests for a real, pre-existing gap that a real saturation-flow
# calibration run on the corridor finally exercised (see PROGRESS.md's "Real
# saturation-flow calibration" section): at zero receiving-link occupancy,
# pressure() reduces to fairness minus switching cost, fairness's own
# ceiling for a movement is capped once wait_ratio hits 1.0, and _switch's
# sat_flow-weighted fix can price a multi-movement phase's switching cost
# several times higher than that ceiling -- so a starved movement's own
# phase can be structurally unable to ever win, no matter how long it
# waits, while a completely idle current phase (own pressure exactly 0)
# keeps "extending" itself forever. _critical_phases/the override in
# propose() exist to make sure I5 is never the only thing standing between
# that gap and an unserved movement.


def test_critical_phases_empty_when_nothing_is_close_to_the_bound():
    cfg = _ring_config(2, 3.0, 2.0, [5.0, 5.0], [30.0, 30.0], max_wait_s=100.0)
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=10.0,
        wait_times_s={"m1": 50.0}, queue_pcu={"m1": 1.0},
    )
    assert camp._critical_phases(cfg, ctx, list(cfg.ring_order)) == []


def test_critical_phases_ignores_a_movement_with_no_demand():
    # High wait alone isn't enough -- I5 itself only fires "with demand"
    # (has_demand=True), so a movement with a stale wait clock but no
    # current demand must not force an override either.
    cfg = _ring_config(2, 3.0, 2.0, [5.0, 5.0], [30.0, 30.0], max_wait_s=100.0)
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=10.0,
        wait_times_s={"m1": 95.0}, has_demand={"m1": False},
    )
    assert camp._critical_phases(cfg, ctx, list(cfg.ring_order)) == []


def test_critical_phases_orders_most_urgent_first():
    cfg = _ring_config(3, 3.0, 2.0, [5.0, 5.0, 5.0], [30.0, 30.0, 30.0], max_wait_s=100.0)
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=10.0,
        wait_times_s={"m1": 90.0, "m2": 95.0},  # both within the 15s margin of 100
        has_demand={"m1": True, "m2": True},
    )
    assert camp._critical_phases(cfg, ctx, list(cfg.ring_order)) == ["P2", "P1"]


def test_starvation_override_advances_even_though_current_has_the_highest_pressure():
    # Reconstructs the real corridor's failure mode with real-scale numbers:
    # an idle current phase (own pressure exactly 0, per the documented
    # zero-occupancy P_flow/P_block cancellation) versus a 3-movement
    # candidate phase whose own real sat_flow makes its switching cost
    # dwarf fairness's ceiling -- so ordinary pressure ranking picks the
    # idle phase every time, and only the override can ever reach the
    # starved one.
    cfg = _ring_config(
        2, yellow_s=6.0, all_red_s=2.0, min_greens=[10.0, 10.0], max_greens=[90.0, 90.0],
        max_wait_s=452.0, sat_flows=[0.4, 0.4],
    )
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=57.0,
        wait_times_s={"m1": 452.0}, has_demand={"m1": True}, queue_pcu={"m1": 5.4},
    )
    # Pin lambda_s to the build guide's own §3.9 default (1.0) explicitly,
    # rather than relying on CampConfig()'s bare default -- that default
    # is now the corridor-calibrated 0.143 (see CampConfig.lambda_s's own
    # docstring / PROGRESS.md's "Recalibrating lambda_s" section), which
    # happens to no longer reproduce this exact trap on these exact
    # numbers. The override this test guards must hold regardless of
    # which lambda_s is in effect -- a different corridor, or a reset to
    # the guide's own default, can still hit this trap -- so the
    # regression test stays pinned to the value that reproduces it
    # instead of silently tracking whatever CampConfig's default becomes.
    camp_cfg = camp.CampConfig(lambda_s=1.0)
    # Confirm the trap is real before checking the fix: P1's own pressure
    # (fairness capped at wait_ratio=1.0, minus P0->P1's switching cost)
    # must be negative, i.e. worse than idle P0's exact 0.0.
    assert camp.pressure(camp_cfg, cfg, ctx, "P1") < 0.0
    assert camp.pressure(camp_cfg, cfg, ctx, "P0") == 0.0

    plan = camp.propose(cfg, ctx, camp_cfg=camp_cfg, tick_s=1.0)
    assert len(plan.steps) == 2
    assert plan.steps[1].phase_id == "P1"


def test_starvation_override_never_cuts_short_of_min_green():
    # I3's floor is absolute -- even a movement already past its I5 bound
    # must wait for current's own min_green_s, exactly like the ordinary
    # pressure-based advance already does.
    cfg = _ring_config(
        2, 3.0, 2.0, min_greens=[20.0, 20.0], max_greens=[90.0, 90.0],
        max_wait_s=100.0, sat_flows=[0.4, 0.4],
    )
    ctx = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=5.0,  # < min_green
        wait_times_s={"m1": 100.0}, has_demand={"m1": True}, queue_pcu={"m1": 5.0},
    )
    plan = camp.propose(cfg, ctx, tick_s=1.0)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"


@given(
    n_phases=st.integers(min_value=2, max_value=4),
    sat_flows=st.lists(st.floats(min_value=0.2, max_value=0.6), min_size=4, max_size=4),
    data=st.data(),
)
@settings(max_examples=200, deadline=None)
def test_camp_never_lets_i5_fire_across_heterogeneous_saturation_flows(n_phases, sat_flows, data):
    # The property test above (test_camp_never_violates_interlocks_over_many_ticks)
    # uses a uniform sat_flow=1.0 across every phase, which can't exercise
    # this bug class at all -- the fairness-ceiling-vs-switching-cost gap
    # only shows up once phases have genuinely different sat_flow_pcu_s, the
    # real corridor's own condition once calibrated. A tight max_wait_s (so
    # the bound is actually reachable within a short run) plus real
    # heterogeneous sat_flow is the direct regression guard for the
    # override this test file's "starvation override" section added.
    yellow_s, all_red_s = 3.0, 2.0
    min_greens = [5.0] * n_phases
    max_greens = [20.0] * n_phases
    max_wait_s = 40.0  # tight enough to be reachable in well under 80 ticks
    cfg = _ring_config(
        n_phases, yellow_s, all_red_s, min_greens, max_greens,
        max_wait_s=max_wait_s, sat_flows=sat_flows[:n_phases],
    )
    assert cfg.validate() == []

    current = cfg.ring_order[0]
    elapsed = 0.0
    movements = [f"m{i}" for i in range(n_phases)]
    wait_times = dict.fromkeys(movements, 0.0)
    n_ticks = data.draw(st.integers(min_value=10, max_value=80))

    for _ in range(n_ticks):
        served_now = cfg.phases[current].green_movements
        # Every movement has standing demand throughout -- the adversarial
        # case: nothing ever un-demands itself to give the ring an easy out.
        for m in wait_times:
            wait_times[m] = wait_times[m] + 1.0 if m not in served_now else 0.0
        queue_pcu = {
            m: data.draw(st.floats(min_value=0.0, max_value=10.0), label=f"q_{m}")
            for m in movements
        }
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            wait_times_s=dict(wait_times),
            has_demand=dict.fromkeys(movements, True),
            queue_pcu=queue_pcu,
        )
        plan = camp.propose(cfg, ctx, tick_s=1.0)
        violations = interlocks.check(plan, ctx, cfg)
        assert violations == [], (
            f"camp let I5 (or another interlock) fire: {violations} "
            f"(current={current}, elapsed={elapsed}, wait_times={wait_times}, "
            f"sat_flows={sat_flows[:n_phases]}, plan={plan})"
        )
        if len(plan.steps) == 1:
            elapsed += plan.steps[0].green_s
        else:
            current = plan.steps[1].phase_id
            elapsed = 0.0

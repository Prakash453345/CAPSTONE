"""A-CA-MP (M5) test suite.

Three parts, in the order the claims need to be established:

1. **The regression the whole milestone rests on.** `test_m4_pressure_
   sign_defect` and its A-CA-MP counterpart are executable proofs of the
   defect described in `acamp.py`'s docstring -- that M4's flow/block
   pair is non-positive for every legal input, and that A-CA-MP's
   replacement is monotone increasing in queue as max-pressure requires.
   These are written as property tests over the whole legal input domain
   rather than as examples, because "always" is the actual claim and one
   worked example cannot carry it.

2. **The safety proof every strategy in this package owes**, in the
   stronger heterogeneous-saturation-flow form M4's own suite adopted
   after a uniform `sat_flow=1.0` property test proved unable to
   exercise the starvation bug that shipped.

3. **Deterministic behaviour checks** for the things that are new:
   anticipation, the sublinear hold bias, memory blending.
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control import memory as memory_mod
from sim_service.control.safety import interlocks
from sim_service.control.strategies import acamp, camp


def _ring_config(
    n_phases: int,
    yellow_s: float = 3.0,
    all_red_s: float = 2.0,
    min_greens: list[float] | None = None,
    max_greens: list[float] | None = None,
    max_wait_s: float | None = None,
    sat_flows: list[float] | None = None,
) -> Tier0Config:
    phase_ids = [f"P{i}" for i in range(n_phases)]
    movements = [f"m{i}" for i in range(n_phases)]
    phases = {pid: Phase(pid, frozenset({mv})) for pid, mv in zip(phase_ids, movements, strict=True)}
    conflict_matrix = {mv: frozenset(m2 for m2 in movements if m2 != mv) for mv in movements}
    kwargs = {} if max_wait_s is None else {"max_wait_s": max_wait_s}
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=tuple(phase_ids),
        conflict_matrix=conflict_matrix,
        min_green_s=dict(zip(phase_ids, min_greens or [5.0] * n_phases, strict=True)),
        max_green_s=dict(zip(phase_ids, max_greens or [40.0] * n_phases, strict=True)),
        yellow_s=yellow_s,
        all_red_s=all_red_s,
        sat_flow_pcu_s=dict(zip(movements, sat_flows or [1.0] * n_phases, strict=True)),
        **kwargs,
    )


# =====================================================================
# 1. The pressure-sign defect, and its fix
# =====================================================================


@settings(max_examples=300, deadline=None)
@given(
    queue=st.floats(min_value=0.0, max_value=60.0),
    occupancy=st.floats(min_value=0.0, max_value=0.999),
    sat_flow=st.floats(min_value=0.05, max_value=2.0),
)
def test_m4_flow_minus_block_is_never_positive(queue, occupancy, sat_flow):
    """M4's `P_flow − P_block` is `≤ 0` for every legal input.

    This is the defect, stated as a property and checked over the whole
    domain rather than argued from the algebra. `θ_m = min(θ_max,
    1/max(ε, 1−ρ)) ≥ 1` always, and both terms multiply the same
    `s_m · q_m`, so their difference is `s_m·q_m·(1−θ_m) ≤ 0`.

    The consequence, which is the part that matters: the two terms that
    constitute the max-pressure core of M4's controller can never reward
    a queue. `test_m4_pressure_decreases_as_queue_grows` below is the
    same fact in the form that explains the gate result."""
    cfg = _ring_config(2, sat_flows=[sat_flow, sat_flow])
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m0": queue},
        receiving_occupancy={"m0": occupancy},
    )
    camp_cfg = camp.CampConfig()
    flow = camp._flow_pressure(cfg, ctx, "P0")
    block = camp._block_pressure(camp_cfg, cfg, ctx, "P0")
    assert flow - block <= 1e-9, (
        f"expected non-positive, got {flow - block} at q={queue}, rho={occupancy}"
    )


@settings(max_examples=200, deadline=None)
@given(
    small_q=st.floats(min_value=0.0, max_value=10.0),
    delta=st.floats(min_value=0.5, max_value=30.0),
    occupancy=st.floats(min_value=0.01, max_value=0.9),
)
def test_m4_pressure_decreases_as_queue_grows(small_q, delta, occupancy):
    """Strictly worse than "cannot reward a queue": M4's flow/block pair
    gets *more negative* as the queue grows, at any nonzero receiving
    occupancy. A phase with more traffic waiting scores lower than an
    otherwise-identical phase with less.

    This is the mechanism behind the M4 gate's negative result. At light
    and medium demand receiving links are near-empty and nothing else in
    `𝒫(p)` scales with queue size either, so queue size has no positive
    influence on phase choice anywhere in the controller."""
    cfg = _ring_config(2, sat_flows=[1.0, 1.0])
    camp_cfg = camp.CampConfig()

    def pair(q: float) -> float:
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id="P0",
            current_phase_elapsed_s=10.0,
            queue_pcu={"m0": q},
            receiving_occupancy={"m0": occupancy},
        )
        return camp._flow_pressure(cfg, ctx, "P0") - camp._block_pressure(camp_cfg, cfg, ctx, "P0")

    assert pair(small_q + delta) < pair(small_q) + 1e-9


@settings(max_examples=300, deadline=None)
@given(
    small_q=st.floats(min_value=0.0, max_value=40.0),
    delta=st.floats(min_value=0.1, max_value=40.0),
    occupancy=st.floats(min_value=0.0, max_value=0.999),
    receiving_q=st.floats(min_value=0.0, max_value=40.0),
    sat_flow=st.floats(min_value=0.05, max_value=2.0),
)
def test_acamp_pressure_is_monotone_increasing_in_queue(
    small_q, delta, occupancy, receiving_q, sat_flow
):
    """A-CA-MP's fix, as the property M4's version violated: pressure is
    non-decreasing in queue size at *every* receiving occupancy, and
    strictly increasing wherever the gate is open.

    Non-decreasing rather than strictly increasing is the correct claim:
    at `ρ ≥ ρ_jam` the gate is fully closed, and a phase discharging into
    a jammed link genuinely should not gain pressure from having a longer
    queue -- that is the spillback guard working, and it is a *bounded*
    zero rather than M4's unbounded negative."""
    cfg = _ring_config(2, sat_flows=[sat_flow, sat_flow])
    acfg = acamp.AcampConfig()

    def press(q: float) -> float:
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id="P0",
            current_phase_elapsed_s=10.0,
            queue_pcu={"m0": q},
            receiving_occupancy={"m0": occupancy},
            receiving_queue_pcu={"m0": receiving_q},
        )
        return acamp.press_pressure(cfg, ctx, acfg, "P0")

    lo, hi = press(small_q), press(small_q + delta)
    assert hi >= lo - 1e-9
    if acamp.gate(occupancy, acfg) > 0.0:
        assert hi > lo


@settings(max_examples=200, deadline=None)
@given(
    occupancy=st.floats(min_value=0.0, max_value=1.0),
    rho_jam=st.floats(min_value=0.1, max_value=1.0),
    beta=st.floats(min_value=0.5, max_value=4.0),
)
def test_gate_is_bounded_in_unit_interval(occupancy, rho_jam, beta):
    """The property that makes the gate a safe replacement for `θ`: it is
    a discount in `[0, 1]`, so it can reduce a discharge benefit to
    nothing but can never invert its sign. `θ ∈ [1, θ_max]` had exactly
    the opposite guarantee."""
    cfg = acamp.AcampConfig(rho_jam=rho_jam, beta_gate=beta)
    g = acamp.gate(occupancy, cfg)
    assert 0.0 <= g <= 1.0


def test_acamp_reduces_to_textbook_max_pressure_at_free_flow():
    """At zero receiving occupancy and zero downstream queue, pressure is
    exactly `Σ s_m · q̂_m` -- Varaiya's max-pressure. The point of the
    check is that the free-flow case is the *identity*, not a special
    case: M4's version cancelled to exactly zero here."""
    cfg = _ring_config(2, sat_flows=[0.8, 0.8])
    acfg = acamp.AcampConfig(eta_arrival=0.0)
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m0": 12.0},
        receiving_occupancy={},
        receiving_queue_pcu={},
    )
    assert acamp.press_pressure(cfg, ctx, acfg, "P0") == 0.8 * 12.0


def test_downstream_queue_produces_negative_pressure():
    """The behaviour M4's θ term was reaching for and could not express:
    a phase whose receiving link is fuller than its own approach has
    genuinely negative pressure, so it loses to an idle phase."""
    cfg = _ring_config(2, sat_flows=[1.0, 1.0])
    acfg = acamp.AcampConfig()
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m0": 3.0, "m1": 0.0},
        receiving_occupancy={"m0": 0.1},
        receiving_queue_pcu={"m0": 20.0, "m1": 0.0},
    )
    assert acamp.press_pressure(cfg, ctx, acfg, "P0") < 0.0
    assert acamp.press_pressure(cfg, ctx, acfg, "P1") == 0.0


# =====================================================================
# 2. Anticipation
# =====================================================================


def test_approaching_traffic_raises_pressure():
    """The `q̂_m = q_m + η·a_m` term, isolated: two phases with identical
    stop-line queues rank differently when one has a platoon inbound."""
    cfg = _ring_config(2, sat_flows=[1.0, 1.0])
    acfg = acamp.AcampConfig(eta_arrival=0.5)
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m0": 4.0, "m1": 4.0},
        approaching_pcu={"m0": 0.0, "m1": 6.0},
    )
    assert acamp.press_pressure(cfg, ctx, acfg, "P1") > acamp.press_pressure(cfg, ctx, acfg, "P0")


def test_eta_zero_disables_anticipation_exactly():
    """`eta_arrival = 0` must reproduce the no-anticipation controller
    bit-for-bit -- this is the ablation arm the gate uses to attribute
    any measured gain to anticipation specifically, so it has to be an
    exact identity and not merely a small effect."""
    cfg = _ring_config(2, sat_flows=[1.0, 1.0])
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m0": 4.0},
        approaching_pcu={"m0": 99.0},
    )
    off = acamp.AcampConfig(eta_arrival=0.0)
    assert acamp.press_pressure(cfg, ctx, off, "P0") == 4.0


def test_phase_with_only_inbound_traffic_is_not_skipped():
    """`_skippable`'s new `a > 0` clause: a phase with an empty stop line
    but a platoon 6 seconds out is exactly what anticipation exists to
    catch, and M4's skip rule (queue-only) would pass over it."""
    cfg = _ring_config(3, max_wait_s=200.0)
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m1": 0.0},
        approaching_pcu={"m1": 5.0},
        wait_times_s={"m1": 0.0},
    )
    assert not acamp._skippable(cfg, ctx, "P1")


# =====================================================================
# 3. The sublinear hold bias
# =====================================================================


def test_hold_bias_rejects_alpha_outside_open_unit_interval():
    """`alpha = 0` is precisely M4's constant switching cost and `alpha =
    1` never becomes negligible against pressure. Both are rejected
    loudly rather than clamped: a tuner that wandered there would
    otherwise silently reconstruct a known, already-diagnosed bug."""
    for bad in (0.0, 1.0, -0.5, 1.5):
        try:
            memory_mod.sublinear_hold_bias(10.0, 1.0, bad)
        except ValueError:
            continue
        raise AssertionError(f"alpha={bad} should have been rejected")


@settings(max_examples=100, deadline=None)
@given(
    kappa=st.floats(min_value=0.01, max_value=5.0),
    alpha=st.floats(min_value=0.06, max_value=0.94),
)
def test_hold_bias_is_asymptotically_negligible(kappa, alpha):
    """The sublinearity guarantee, checked numerically: `F(x)/x → 0`.

    This is what makes M4's failure mode unreachable *by construction*.
    M4's `S(p)` was `O(1)` against pressure differences that scale with
    queue size, so some demand level below which it dominated always
    existed -- and PROGRESS.md measured it dominating at all three tested
    levels. Here, however large `kappa` is, the hold bias eventually
    stops mattering, so no parameter setting the tuner can reach
    reproduces a controller that structurally refuses to switch.

    Asserted as the exact analytic decay rather than as a fixed
    threshold: `F(x)/x = κ·x^(α−1)`, so a tenfold increase in `x` must
    shrink the ratio by exactly `10^(α−1)`. A threshold assertion would
    be arbitrary and, worse, would fail for `α` near 1 purely because
    convergence is slow there -- slow convergence is still convergence,
    and the claim being tested is the limit, not a rate."""
    xs = [1e2, 1e3, 1e4, 1e5, 1e6]
    ratios = [memory_mod.sublinear_hold_bias(x, kappa, alpha) / x for x in xs]
    for earlier, later in zip(ratios, ratios[1:], strict=False):
        assert later < earlier
        assert math.isclose(later / earlier, 10.0 ** (alpha - 1.0), rel_tol=1e-9)
    # And the limit itself: pick an `x` large enough for this particular
    # alpha rather than one fixed for all of them.
    huge = 10.0 ** (3.0 / (1.0 - alpha) + 2.0)
    assert memory_mod.sublinear_hold_bias(huge, kappa, alpha) / huge < 1e-2


def test_hold_bias_is_zero_at_an_empty_junction():
    """No traffic anywhere means no reason to resist cycling onward. A
    nonzero floor here would reintroduce M4's "never leaves the current
    phase at light demand" behaviour in miniature."""
    assert memory_mod.sublinear_hold_bias(0.0, 3.0, 0.5) == 0.0


def test_pressure_scale_uses_qhat_not_signed_pressure():
    """A gridlocked junction (large queues upstream *and* downstream) has
    near-zero signed pressure but is maximally loaded. Sizing the hold
    bias off `𝒫` would read it as empty and switch it freely; sizing off
    `q̂` reads it as loaded, which is what congestion calls for."""
    cfg = _ring_config(2, sat_flows=[1.0, 1.0])
    acfg = acamp.AcampConfig()
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m0": 25.0, "m1": 25.0},
        receiving_queue_pcu={"m0": 25.0, "m1": 25.0},
    )
    assert abs(acamp.pressure(cfg, ctx, acfg, "P0")) < 1e-9
    assert acamp.pressure_scale(cfg, ctx, acfg) == 50.0


# =====================================================================
# 4. Safety -- the proof every strategy in this package owes
# =====================================================================


@settings(max_examples=200, deadline=None)
@given(
    n_phases=st.integers(min_value=2, max_value=4),
    sat_flows=st.lists(st.floats(min_value=0.05, max_value=2.0), min_size=4, max_size=4),
    max_wait_s=st.floats(min_value=40.0, max_value=90.0),
    queue_seq=st.lists(
        st.lists(st.floats(min_value=0.0, max_value=25.0), min_size=4, max_size=4),
        min_size=40,
        max_size=60,
    ),
    occ_seq=st.lists(
        st.lists(st.floats(min_value=0.0, max_value=0.99), min_size=4, max_size=4),
        min_size=40,
        max_size=60,
    ),
    kappa=st.floats(min_value=0.0, max_value=5.0),
    alpha=st.floats(min_value=0.06, max_value=0.94),
)
def test_acamp_never_lets_an_interlock_fire(
    n_phases, sat_flows, max_wait_s, queue_seq, occ_seq, kappa, alpha
):
    """Drive a junction for many ticks against randomized live state and
    assert `interlocks.check()` never rejects the plan.

    Deliberately in the *heterogeneous* saturation-flow form M4's suite
    adopted after the fact: its original safety property test used a
    uniform `sat_flow = 1.0`, which PROGRESS.md records as structurally
    unable to exercise the starvation bug that then shipped and produced
    10,235 interlock rejections on the real corridor. Drawing per-movement
    saturation flow independently, and holding `max_wait_s` tight enough
    to actually be reachable within the tick budget, is what makes this
    test capable of failing.

    The switching parameters are drawn too, not fixed at their defaults:
    the whole point of `tuning.py` is that these move, and a safety proof
    that only holds at the default parameter vector would be worthless
    the moment the optimizer ran."""
    cfg = _ring_config(
        n_phases,
        min_greens=[5.0] * n_phases,
        max_greens=[25.0] * n_phases,
        max_wait_s=max_wait_s,
        sat_flows=sat_flows[:n_phases],
    )
    controller = acamp.AdaptiveCamp(
        acamp.AcampConfig(kappa_switch=kappa, alpha_switch=alpha), tick_s=1.0
    )
    movements = [f"m{i}" for i in range(n_phases)]
    waits = dict.fromkeys(movements, 0.0)
    current, elapsed = "P0", 0.0

    for tick, (queues, occs) in enumerate(zip(queue_seq, occ_seq, strict=False)):
        queue_pcu = dict(zip(movements, queues[:n_phases], strict=True))
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            queue_pcu=queue_pcu,
            receiving_occupancy=dict(zip(movements, occs[:n_phases], strict=True)),
            receiving_queue_pcu=dict(zip(movements, occs[:n_phases], strict=True)),
            approaching_pcu=dict(zip(movements, [q * 0.3 for q in queues[:n_phases]], strict=True)),
            wait_times_s=dict(waits),
            has_demand={m: queue_pcu[m] > 0.0 for m in movements},
        )
        controller.set_sim_time(float(tick))
        plan = controller(cfg, ctx)
        violations = interlocks.check(plan, ctx, cfg)
        assert not violations, f"tick {tick}: {violations}"

        served = cfg.phases[plan.steps[0].phase_id].green_movements
        if len(plan.steps) == 1:
            elapsed += plan.steps[0].green_s
        else:
            current = plan.steps[1].phase_id
            elapsed = 0.0
            served = cfg.phases[current].green_movements
        for m in movements:
            waits[m] = 0.0 if m in served else waits[m] + 1.0


@settings(max_examples=150, deadline=None)
@given(
    elapsed=st.floats(min_value=0.0, max_value=4.9),
    queues=st.lists(st.floats(min_value=0.0, max_value=50.0), min_size=3, max_size=3),
    waits=st.lists(st.floats(min_value=0.0, max_value=500.0), min_size=3, max_size=3),
)
def test_min_green_is_absolute(elapsed, queues, waits):
    """I3 outranks every adaptive consideration in this module -- a
    starving movement elsewhere, an enormous queue elsewhere, a jammed
    receiving link -- exactly as it does in `camp.propose`. Checked with
    `wait_times_s` drawn well past `max_wait_s` so the starvation
    override is actively trying to fire."""
    cfg = _ring_config(3, min_greens=[5.0] * 3, max_wait_s=60.0)
    movements = [f"m{i}" for i in range(3)]
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=elapsed,
        queue_pcu=dict(zip(movements, queues, strict=True)),
        wait_times_s=dict(zip(movements, waits, strict=True)),
        has_demand=dict.fromkeys(movements, True),
    )
    plan = acamp.AdaptiveCamp()(cfg, ctx)
    assert len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"


# =====================================================================
# 5. Memory blending -- the rung M4 left dead
# =====================================================================


def test_low_confidence_blends_toward_history():
    """The "camp_blended" rung, made real. With confidence at 0.6 the
    controller sits between the live reading and what this junction
    historically shows -- M4 returned `fixed_time.propose` here."""
    mem = memory_mod.DemandMemory(min_runs=1)
    for _ in range(2):
        for t in range(10):
            mem.observe_tick("J", float(t), {"m0": 20.0, "m1": 0.0}, {"m0": 0.0, "m1": 0.0})
        mem.end_run()

    controller = acamp.AdaptiveCamp(demand_memory=mem)
    controller.set_sim_time(5.0)
    cfg = _ring_config(2)
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m0": 0.0, "m1": 0.0},
        confidence={"m0": 0.6, "m1": 0.6},
    )
    blended = controller._blend_context(ctx)
    assert 0.0 < blended.queue_pcu["m0"] < 20.0
    assert blended.queue_pcu["m1"] == 0.0
    # And the ladder actually routes there rather than to fixed_time.
    assert acamp.select_mode(ctx, frozenset({"m0", "m1"})) == "camp_blended"
    controller(cfg, ctx)
    assert controller.stats["blended"] == 1
    assert controller.stats["fallback_fixed_time"] == 0


def test_cold_start_memory_does_not_alter_live_state():
    """A controller with no history must degrade to live-only, not to
    zeros. `blend` returning `live` on `historical is None` is what makes
    the first run of a fresh deployment behave identically to a
    memoryless controller rather than worse than one."""
    controller = acamp.AdaptiveCamp(demand_memory=memory_mod.DemandMemory())
    controller.set_sim_time(100.0)
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=10.0,
        queue_pcu={"m0": 7.0},
        approaching_pcu={"m0": 3.0},
        confidence={"m0": 0.55},
    )
    blended = controller._blend_context(ctx)
    assert blended.queue_pcu["m0"] == 7.0
    assert blended.approaching_pcu["m0"] == 3.0


def test_blending_cannot_reach_the_safety_kernel():
    """Blending is a control-side *estimate*. The interlocks check the
    unblended reality the cabinet actually faces, so a wrong historical
    profile can degrade delay but can never manufacture a safe-looking
    plan for an unsafe world. Verified by checking the returned plan
    against the original context, not the blended one."""
    mem = memory_mod.DemandMemory(min_runs=1)
    for _ in range(2):
        for t in range(10):
            mem.observe_tick("J", float(t), {"m0": 0.0, "m1": 0.0}, {"m0": 0.0, "m1": 0.0})
        mem.end_run()
    cfg = _ring_config(2, max_wait_s=50.0)
    controller = acamp.AdaptiveCamp(demand_memory=mem)
    controller.set_sim_time(5.0)
    ctx = JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=30.0,
        queue_pcu={"m0": 0.0, "m1": 15.0},
        wait_times_s={"m0": 0.0, "m1": 48.0},
        has_demand={"m0": False, "m1": True},
        confidence={"m0": 0.6, "m1": 0.6},
    )
    plan = controller(cfg, ctx)
    assert not interlocks.check(plan, ctx, cfg)


# =====================================================================
# 6. Decision accounting
# =====================================================================


def test_controller_counts_its_own_decisions():
    """M4's central diagnostic finding ("100% of phase changes were
    max_green timeouts") needed a separate instrumented rerun to
    discover. Counting decisions in the controller means the equivalent
    question is answerable from any run, the gate's included."""
    cfg = _ring_config(2, min_greens=[2.0, 2.0], max_greens=[8.0, 8.0])
    controller = acamp.AdaptiveCamp()
    current, elapsed = "P0", 0.0
    for tick in range(60):
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id=current,
            current_phase_elapsed_s=elapsed,
            queue_pcu={"m0": 1.0, "m1": 18.0},
            has_demand={"m0": True, "m1": True},
        )
        controller.set_sim_time(float(tick))
        plan = controller(cfg, ctx)
        if len(plan.steps) == 1:
            elapsed += plan.steps[0].green_s
        else:
            current, elapsed = plan.steps[1].phase_id, 0.0

    assert controller.stats["ticks"] == 60
    # The point of the fix: real pressure-driven switching happens, rather
    # than every change being a max-green timeout as M4 measured.
    assert controller.stats["switch_pressure"] > 0
    assert math.isclose(
        controller.stats["extend"]
        + controller.stats["switch_pressure"]
        + controller.stats["switch_max_green"]
        + controller.stats["switch_starvation"],
        60,
    )

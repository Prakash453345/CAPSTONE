"""The cycle supervisor: CC-A-CAMP's phase-order and cycle-length halves.

Every test here fixes a property the supervisor was built to have, and
most of them exist because getting the *placement* wrong inside
`AdaptiveCamp.__call__` would break something that already works. The
decision path is ordered, and the order is the design:

    minimum green (I3, absolute)
      -> starvation override (a movement already at max_wait_s)
        -> cycle supervisor (stop a movement ever reaching max_wait_s)
          -> allocation protection
            -> pressure contest, with the hold bias
"""

from __future__ import annotations

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies import acamp


def _ring_config(n_phases: int, max_greens: list[float] | None = None) -> Tier0Config:
    phase_ids = [f"P{i}" for i in range(n_phases)]
    movements = [f"m{i}" for i in range(n_phases)]
    phases = {p: Phase(p, frozenset({m})) for p, m in zip(phase_ids, movements, strict=True)}
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=tuple(phase_ids),
        conflict_matrix={m: frozenset(o for o in movements if o != m) for m in movements},
        min_green_s=dict.fromkeys(phase_ids, 10.0),
        max_green_s=dict(zip(phase_ids, max_greens or [20.0] * n_phases, strict=True)),
        yellow_s=3.0,
        all_red_s=2.0,
        sat_flow_pcu_s=dict.fromkeys(movements, 1.0),
    )


def _ctx(cfg: Tier0Config, current: str, elapsed: float, queues: dict[str, float]):
    return JunctionContext(
        intersection_id="J",
        current_phase_id=current,
        current_phase_elapsed_s=elapsed,
        queue_pcu=queues,
    )


def _controller(**cfg_kwargs) -> acamp.AdaptiveCamp:
    return acamp.AdaptiveCamp(acamp.AcampConfig(**cfg_kwargs))


def _drive(controller, cfg, current, queues, seconds: float, elapsed: float = 30.0):
    """Hold one phase for `seconds` of simulated time, returning the last
    plan. Advancing `set_sim_time` is what makes the cycle clock move --
    the controller reads no wall clock of its own."""
    plan = None
    for t in range(int(seconds)):
        controller.set_sim_time(float(t))
        plan = controller(cfg, _ctx(cfg, current, elapsed, queues))
    return plan


# -- the supervisor must be invisible when off -------------------------


def test_off_by_default_and_never_fires_when_off():
    """Every recorded gate in this project ran with no supervisor. It
    stays off by default so those numbers remain reproducible, and the
    arm that enables it is a gate arm rather than a silent change."""
    assert acamp.AcampConfig().cycle_supervisor is False
    cfg = _ring_config(4)
    controller = _controller()
    _drive(controller, cfg, "P0", {"m0": 5.0, "m1": 9.0, "m2": 9.0, "m3": 9.0}, 400)
    assert controller.stats["switch_cycle_supervisor"] == 0


def test_cycle_is_measured_even_when_the_supervisor_is_off():
    """A control arm that cannot report the quantity under test is not
    much of a control. The bookkeeping runs unconditionally; only the
    action is gated."""
    cfg = _ring_config(2)
    controller = _controller()
    _drive(controller, cfg, "P0", {"m0": 0.0, "m1": 0.0}, 30)
    assert controller.stats["cycles_completed"] > 0, (
        "an all-empty junction completes a cycle trivially and should say so"
    )


# -- the phase-order constraint ----------------------------------------


def test_a_phase_owed_a_green_past_the_envelope_forces_a_switch():
    """The Levin constraint, and the defect it closes. A movement that
    waits long enough hits `max_wait_s` mid-way through another phase's
    minimum green, at which point I3 forbids cutting the incumbent short
    and I5 rejects the resulting plan -- measured at heavy demand on the
    real corridor, one second before the starvation override could have
    fired. Serving every phase inside a bounded cycle is what stops the
    wait reaching that far."""
    cfg = _ring_config(4, max_greens=[20.0] * 4)
    controller = _controller(cycle_supervisor=True)
    queues = {"m0": 50.0, "m1": 1.0, "m2": 1.0, "m3": 1.0}
    # Envelope = 4 x (20 + 3 + 2) = 100 s. Hold P0 well past it while the
    # other three phases sit with real demand they are never given.
    plan = _drive(controller, cfg, "P0", queues, 150)
    assert controller.stats["switch_cycle_supervisor"] > 0
    assert plan is not None and plan.steps[-1].phase_id != "P0", (
        "the supervisor must actually move off the starved-in phase"
    )


def test_the_supervisor_is_silent_while_inside_the_envelope():
    """Point 3 of the design: normal A-CA-MP acts freely while the cycle
    is within target. A supervisor that fires constantly is Webster with
    extra steps, and the intervention count is how that is detected."""
    cfg = _ring_config(4, max_greens=[20.0] * 4)
    controller = _controller(cycle_supervisor=True)
    _drive(controller, cfg, "P0", {"m0": 50.0, "m1": 1.0, "m2": 1.0, "m3": 1.0}, 60)
    assert controller.stats["switch_cycle_supervisor"] == 0, (
        "60 s is inside a 100 s envelope; nothing should have been forced"
    )


def test_an_empty_phase_is_not_owed_a_green():
    """The deliberate departure from Levin, fixed as a property so it
    cannot be silently reverted. Their rule actuates every phase
    unconditionally; forcing a switch to an empty approach spends a
    clearance interval to serve nobody, which is the cost `_skippable`
    already exists to avoid."""
    cfg = _ring_config(4, max_greens=[20.0] * 4)
    controller = _controller(cycle_supervisor=True)
    _drive(controller, cfg, "P0", {"m0": 50.0, "m1": 0.0, "m2": 0.0, "m3": 0.0}, 200)
    assert controller.stats["switch_cycle_supervisor"] == 0


def test_the_forced_switch_goes_to_the_highest_pressure_owed_phase():
    """"Move to the best safe competing phase", not merely to the next
    one in the ring. The choice is still max-pressure's; the supervisor
    only narrows the field to phases the cycle owes."""
    cfg = _ring_config(4, max_greens=[20.0] * 4)
    controller = _controller(cycle_supervisor=True)
    plan = _drive(controller, cfg, "P0", {"m0": 50.0, "m1": 1.0, "m2": 30.0, "m3": 1.0}, 150)
    assert plan is not None
    assert plan.steps[-1].phase_id == "P2", (
        f"expected the largest owed queue (P2), got {plan.steps[-1].phase_id}"
    )


# -- the constraints it must never break -------------------------------


def test_the_supervisor_can_never_cut_a_green_below_its_minimum():
    """I3 is absolute, and placement is the whole guarantee: the
    supervisor sits *after* the minimum-green gate, so the only invariant
    a forced switch could threaten has already been enforced. Checked as
    behaviour rather than trusted from the ordering."""
    cfg = _ring_config(4, max_greens=[20.0] * 4)
    controller = _controller(cycle_supervisor=True)
    queues = {"m0": 50.0, "m1": 9.0, "m2": 9.0, "m3": 9.0}
    # Far past the envelope, but only 4 s into P0's 10 s minimum.
    plan = _drive(controller, cfg, "P0", queues, 300, elapsed=4.0)
    assert plan is not None
    assert plan.steps[0].phase_id == "P0", "cut a phase short of its minimum green"
    assert controller.stats["switch_cycle_supervisor"] == 0


def test_every_plan_the_supervisor_proposes_passes_the_interlocks():
    """The rule the corridor engine states and this must follow too:
    never propose a plan the interlocks will reject, because rejection
    commands the failsafe. A supervisor that trades an I5 violation for
    an I1 or I2 one has moved the problem, not solved it."""
    cfg = _ring_config(4, max_greens=[20.0] * 4)
    controller = _controller(cycle_supervisor=True)
    queues = {"m0": 50.0, "m1": 4.0, "m2": 7.0, "m3": 2.0}
    for t in range(400):
        controller.set_sim_time(float(t))
        ctx = _ctx(cfg, "P0", 30.0, queues)
        plan = controller(cfg, ctx)
        assert not interlocks.check(plan, ctx, cfg), (
            f"supervisor proposed a plan the kernel rejects at t={t}"
        )
    assert controller.stats["switch_cycle_supervisor"] > 0, "test never exercised the branch"


def test_starvation_still_outranks_the_supervisor():
    """Ordering, as a property. A movement already at its `max_wait_s`
    bound is the more urgent claim; the supervisor exists to stop that
    bound being reached, not to compete with the override for it."""
    cfg = _ring_config(4, max_greens=[20.0] * 4)
    controller = _controller(cycle_supervisor=True)
    queues = {"m0": 50.0, "m1": 1.0, "m2": 1.0, "m3": 1.0}
    for t in range(200):
        controller.set_sim_time(float(t))
        ctx = JunctionContext(
            intersection_id="J",
            current_phase_id="P0",
            current_phase_elapsed_s=30.0,
            queue_pcu=queues,
            # P3 is at its bound; P2 merely has the larger queue.
            wait_times_s={"m3": cfg.max_wait_s, "m2": 10.0},
            has_demand={"m1": True, "m2": True, "m3": True},
        )
        plan = controller(cfg, ctx)
        if controller.stats["switch_starvation"]:
            assert plan.steps[-1].phase_id == "P3"
            return
    raise AssertionError("starvation override never fired; test did not exercise the ordering")

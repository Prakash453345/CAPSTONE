"""Semi-actuated strategy [build guide §7 M3]: the second of the three
tuned baselines the M3 gate wants alongside Webster fixed-time and
coordinated-actuated. Standard traffic-engineering semi-actuated logic --
the major-street phase is placed on continuous recall (it rests in green
with no maximum, exactly the ordinary state of affairs on an arterial with
steady through traffic), while every other phase is actuated: it is only
ever served because a real call showed up for it, extends only while calls
keep arriving, and gives the green back the moment its call gap expires
(gap-out) or its own `max_green_s` is reached (max-out), whichever comes
first. `signal_controller/detectors.py`'s `ActuationDetector` is what turns
real TraCI lane occupancy into the `ctx.has_demand`/`wait_times_s` this
module reads -- this module itself never touches TraCI or any other I/O,
same pure-function discipline as `fixed_time.py`/`webster.py`.

Which phase is "major" is not this module's decision -- see
`pick_major_phase`, a one-line argmax over measured critical flow ratios
(the same numbers `webster.compute_timing` already computes): the
busiest phase gets the recall treatment, which is exactly the real-world
justification for calling one approach "major" in the first place. Passing
it in explicitly (like `webster.propose` takes a `timing`) keeps the
decision traceable to real data rather than baked into this module as a
guess.

Priority when more than one minor phase is calling at once: the call with
the longest accumulated wait wins (`ctx.wait_times_s`) -- the same
"longest-waiting demand goes first" principle I5 encodes as a hard bound,
applied here as an ordinary scheduling preference rather than a safety
invariant (nothing here is exempt from I5 regardless of this choice;
`interlocks.check()` still enforces the hard bound independently).
"""

from __future__ import annotations

from collections.abc import Mapping

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config


def pick_major_phase(critical_flow_ratios: Mapping[str, float]) -> str:
    """The phase with the highest measured critical flow ratio (Webster's
    own y_i, `WebsterTiming.critical_flow_ratios`) becomes the recall
    phase. Requires a non-empty mapping -- a junction with no ring has
    nothing to pick a major phase from, and that's a caller error, not
    something to silently paper over with a default."""
    return max(critical_flow_ratios, key=lambda phase_id: critical_flow_ratios[phase_id])


def _next_in_ring(ring_order: tuple[str, ...], current: str, faulted: frozenset[str]) -> str | None:
    """Identical to fixed_time's/webster's -- see webster.py's docstring
    for why this is duplicated rather than imported."""
    if not ring_order:
        return None
    try:
        start = ring_order.index(current)
    except ValueError:
        start = -1
    for offset in range(1, len(ring_order) + 1):
        candidate = ring_order[(start + offset) % len(ring_order)]
        if candidate not in faulted:
            return candidate
    return None


def _phase_has_call(cfg: Tier0Config, ctx: JunctionContext, phase_id: str) -> bool:
    phase = cfg.phases.get(phase_id)
    if phase is None:
        return False
    return any(ctx.has_demand.get(m, False) for m in phase.green_movements)


def _phase_call_age_s(cfg: Tier0Config, ctx: JunctionContext, phase_id: str) -> float:
    phase = cfg.phases.get(phase_id)
    if phase is None:
        return 0.0
    return max((ctx.wait_times_s.get(m, 0.0) for m in phase.green_movements), default=0.0)


def _exit_step(
    cfg: Tier0Config, ctx: JunctionContext, current: str, min_g: float, tick_s: float
) -> PlanStep:
    """The departing half of a two-step transition: leave now if faulted,
    otherwise top up to at least min_green (plus one more tick, matching
    fixed_time/webster's own margin) before clearing -- same I3 handling as
    both. Note: a faulted phase that is *also* `ctx.current_phase_id`
    (the fault landed on the live phase itself, not one still ahead in the
    ring) still names that phase in this step -- `interlocks.phase_reachable`
    doesn't distinguish ending a green from entering one, so this plan gets
    rejected and the arbiter forces all-red instead of this graceful
    reroute. That's a real, if minor, fault-handling gap in the M2 kernel
    shared by fixed_time -- not something introduced here -- and it stays
    safe (all-red is a defined safe state) even though it isn't the
    smoothest one. See PROGRESS.md for the note to revisit it."""
    if current in ctx.faulted_phases:
        green_s = 0.0
    else:
        green_s = max(tick_s, min_g - ctx.current_phase_elapsed_s)
    return PlanStep(
        phase_id=current, green_s=green_s, yellow_s=cfg.yellow_s, all_red_s=cfg.all_red_s
    )


def propose(
    cfg: Tier0Config, ctx: JunctionContext, *, major_phase_id: str, tick_s: float = 1.0
) -> SignalPlan:
    """One controller tick's proposal under semi-actuated control.
    `major_phase_id` must be a member of `cfg.ring_order` -- see
    `pick_major_phase`."""
    current = ctx.current_phase_id
    elapsed = ctx.current_phase_elapsed_s
    min_g = cfg.min_green_s.get(current, 0.0)
    max_g = cfg.max_green_s.get(current, min_g)
    current_is_faulted = current in ctx.faulted_phases
    min_served = current_is_faulted or elapsed >= min_g

    if current == major_phase_id and not current_is_faulted:
        calling_minors = [
            p
            for p in cfg.ring_order
            if p != major_phase_id and p not in ctx.faulted_phases and _phase_has_call(cfg, ctx, p)
        ]
        if min_served and calling_minors:
            target = max(calling_minors, key=lambda p: _phase_call_age_s(cfg, ctx, p))
        elif not min_served:
            # Major hasn't even served its own floor yet -- rest in green,
            # unconditionally, same as a same-phase extend below.
            target = None
        else:
            target = None  # no minor is calling -- rest in green, no maximum

        if target is None:
            return SignalPlan(
                intersection_id=cfg.intersection_id,
                steps=(PlanStep(phase_id=current, green_s=tick_s),),
                source="semi_actuated",
            )
        return SignalPlan(
            intersection_id=cfg.intersection_id,
            steps=(
                _exit_step(cfg, ctx, current, min_g, tick_s),
                PlanStep(phase_id=target, green_s=cfg.min_green_s.get(target, 0.0)),
            ),
            source="semi_actuated",
        )

    # Current is a minor (actuated) phase, or the major phase itself is
    # faulted (treated the same as any other faulted exit: leave now).
    still_calling = (not current_is_faulted) and _phase_has_call(cfg, ctx, current)
    would_max_out = elapsed + tick_s >= max_g

    if current_is_faulted or not still_calling or would_max_out:
        next_phase = major_phase_id if major_phase_id not in ctx.faulted_phases else _next_in_ring(
            cfg.ring_order, current, ctx.faulted_phases
        )
        if next_phase is None:
            return SignalPlan(intersection_id=cfg.intersection_id, steps=(), source="semi_actuated")
        return SignalPlan(
            intersection_id=cfg.intersection_id,
            steps=(
                _exit_step(cfg, ctx, current, min_g, tick_s),
                PlanStep(phase_id=next_phase, green_s=cfg.min_green_s.get(next_phase, 0.0)),
            ),
            source="semi_actuated",
        )

    # Still being called, not yet maxed out -- extend by one tick.
    return SignalPlan(
        intersection_id=cfg.intersection_id,
        steps=(PlanStep(phase_id=current, green_s=tick_s),),
        source="semi_actuated",
    )

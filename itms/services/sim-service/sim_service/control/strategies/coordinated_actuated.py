"""Coordinated-actuated strategy [build guide §7 M3]: the third and last
of the tuned baselines the gate wants, alongside Webster fixed-time and
semi-actuated. Where semi-actuated (this file's closest relative) gives
the major phase unconditional rest-in-green with no ceiling, coordinated-
actuated answers to a corridor-wide schedule instead of only its own local
state: every junction shares one cycle length, and each junction's
coordinated (major) phase is guaranteed a fixed window within that shared
cycle, positioned by a real travel-time offset from its upstream neighbour
-- a green wave. `corridor_geometry.py` measures the real distances that
offset needs; `build_corridor_plan` below turns those distances plus each
junction's own Webster split (recomputed against the shared cycle via
`webster.compute_timing`'s `fixed_cycle_s`) into one `CoordinationPlan`
per junction.

The real mechanism, standard NEMA coordinated-actuated logic, not invented
here: outside its guaranteed window, a junction's minor phases behave
exactly like semi-actuated's (call, extend, gap-out) -- except every
non-coordinated phase now answers to a *force-off*: a hard deadline
(the coordinated window's next scheduled start) it must clear before,
regardless of continued demand, because the corridor's whole point is that
the coordinated phase starts on time every cycle or the green wave falls
apart. Two things keep that deadline from ever colliding with I3 (never
truncate a green below min_green): a call is only ever accepted if the
remaining time before force-off can fit its full min_green plus clearance
back (`_can_fit`) -- a call that arrives too late in the cycle simply
waits for the next one, exactly like a real controller's late call would
-- and once accepted, the phase's own `max_green_s` is additionally capped
by whatever's left before the deadline, so it can never be told to hold
past a promise `_can_fit` already made. During the guaranteed window
itself, the coordinated phase never yields no matter what calls -- handing
off mid-window would let the platoon it exists to serve hit a red.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config

from sim_service.control.strategies import semi_actuated, webster

_DEFAULT_PROGRESSION_SPEED_M_S = 11.11  # ~40 km/h, a conventional urban arterial design speed
_PERMISSIVE_WINDOW_MARGIN_S = 5.0  # slack beyond the bare structural minimum -- see below


@dataclass(frozen=True)
class CoordinationPlan:
    """One junction's place in the corridor's shared progression.
    `cycle_s` is the CORRIDOR's shared cycle (every coordinated junction
    uses the same value -- see `build_corridor_plan`), not this junction's
    own independently-optimal Webster cycle. `offset_s` positions this
    junction's guaranteed window within that shared cycle so a platoon
    released by the upstream junction arrives just as this junction's
    green begins."""

    intersection_id: str
    coordinated_phase_id: str
    cycle_s: float
    offset_s: float
    coordinated_green_s: float


def build_corridor_plan(
    configs: Mapping[str, Tier0Config],
    link_flows: Mapping[str, Mapping[str, float]],
    distances_m: Mapping[str, float],
    *,
    progression_speed_m_s: float = _DEFAULT_PROGRESSION_SPEED_M_S,
) -> dict[str, CoordinationPlan]:
    """Pure function: every input is already-measured/already-computed
    data (`distances_m` from `corridor_geometry.cumulative_distances_m`,
    `link_flows` from `measure_flows.compute_link_flows`) -- no I/O here,
    matching the pure/impure split every other strategy in this project
    keeps (see `webster.py`'s own docstring for the same point).

    The shared cycle is the *slowest* junction's own Webster optimum --
    the critical intersection sets the cycle for the whole corridor, a
    real coordination principle: a shorter shared cycle would under-serve
    whichever junction needs more capacity than that."""
    own_timings = {
        tls_id: webster.compute_timing(cfg, link_flows.get(tls_id, {}))
        for tls_id, cfg in configs.items()
    }
    shared_cycle_s = max((t.cycle_s for t in own_timings.values()), default=0.0)

    plans: dict[str, CoordinationPlan] = {}
    for tls_id, cfg in configs.items():
        coordinated_phase_id = semi_actuated.pick_major_phase(
            own_timings[tls_id].critical_flow_ratios
        )
        shared_timing = webster.compute_timing(
            cfg, link_flows.get(tls_id, {}), fixed_cycle_s=shared_cycle_s
        )
        distance_m = distances_m.get(tls_id, 0.0)
        offset_s = (distance_m / progression_speed_m_s) % shared_cycle_s if shared_cycle_s else 0.0

        # Webster's own per-phase clamp (compute_timing's `max(lower,
        # min(upper, proposed))`) protects each phase's OWN floor, but
        # doesn't rebalance the others when a low-flow phase gets bumped up
        # to it -- fine for standalone Webster/fixed_time, whose realised
        # cycle is just whatever `propose` actually sums to, but not fine
        # here, where `cycle_s` is a hard, exactly-recurring commitment
        # every other junction's offset depends on. A coordinated phase's
        # raw split can legitimately leave less room than the *other*
        # phases structurally need (their own min_green plus clearance,
        # every cycle) -- discovered by running this against the real
        # 2-phase Vijayawada junctions, where it produced a phase that
        # could structurally never be served (see PROGRESS.md). Capping
        # the coordinated share here, once, keeps every downstream
        # `propose` call simple: the window it's handed is always
        # actually usable.
        # `_PERMISSIVE_WINDOW_MARGIN_S` on top of the bare structural need:
        # at 1Hz tick granularity, a window sized to the exact minimum
        # leaves `_can_fit`'s `>=` check almost no room -- floating-point
        # rounding or simply which integer second the schedule happens to
        # land on can skip over the one instant a call could have been
        # accepted, starving that phase just as surely as too little
        # window in the first place. Real coordination plans always carry
        # slack in the permissive period rather than running it at the
        # mathematical minimum; this is that slack.
        other_phases = [p for p in cfg.ring_order if p != coordinated_phase_id]
        clearance_s = cfg.yellow_s + cfg.all_red_s
        reserved_for_others = (
            sum(cfg.min_green_s.get(p, 0.0) for p in other_phases)
            + len(other_phases) * clearance_s
            + _PERMISSIVE_WINDOW_MARGIN_S
        )
        max_coordinated_green_s = max(0.0, shared_cycle_s - reserved_for_others)
        coordinated_green_s = min(
            shared_timing.green_s.get(coordinated_phase_id, 0.0), max_coordinated_green_s
        )

        plans[tls_id] = CoordinationPlan(
            intersection_id=tls_id,
            coordinated_phase_id=coordinated_phase_id,
            cycle_s=shared_cycle_s,
            offset_s=offset_s,
            coordinated_green_s=coordinated_green_s,
        )
    return plans


def _next_in_ring(ring_order: tuple[str, ...], current: str, faulted: frozenset[str]) -> str | None:
    """Identical to fixed_time's/webster's/semi_actuated's -- see
    webster.py's docstring for why this is duplicated rather than
    imported."""
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
    """Same shape and same known limitation as semi_actuated's `_exit_step`
    (see that module's docstring): a fault landing on the currently-live
    phase itself still produces a step `phase_reachable` rejects, forcing
    all-red rather than a graceful reroute. Safe, not smooth -- unchanged
    from semi-actuated, not something this module introduces."""
    if current in ctx.faulted_phases:
        green_s = 0.0
    else:
        green_s = max(tick_s, min_g - ctx.current_phase_elapsed_s)
    return PlanStep(
        phase_id=current, green_s=green_s, yellow_s=cfg.yellow_s, all_red_s=cfg.all_red_s
    )


def _can_fit(
    cfg: Tier0Config, phase_id: str, remaining_in_cycle: float, clearance_s: float
) -> bool:
    """Would starting `phase_id` right now leave enough runway to serve
    its own min_green and still clear back before force-off? If not, its
    call has to wait for next cycle -- never start something I3 would
    later force this module to either truncate or overrun the deadline
    for."""
    needed = cfg.min_green_s.get(phase_id, 0.0) + clearance_s
    return remaining_in_cycle >= needed


def propose(
    cfg: Tier0Config,
    ctx: JunctionContext,
    *,
    coordination: CoordinationPlan,
    system_time_s: float,
    tick_s: float = 1.0,
) -> SignalPlan:
    """One controller tick's proposal under corridor coordination.
    `system_time_s` is the simulation's absolute clock (e.g.
    `traci.simulation.getTime()`) -- coordination is inherently about a
    shared clock across junctions, unlike every other strategy in this
    project, which reasons only from `ctx`'s own local elapsed time."""
    current = ctx.current_phase_id
    elapsed = ctx.current_phase_elapsed_s
    min_g = cfg.min_green_s.get(current, 0.0)
    current_is_faulted = current in ctx.faulted_phases
    coord_phase = coordination.coordinated_phase_id
    cycle_s = coordination.cycle_s
    clearance_s = cfg.yellow_s + cfg.all_red_s

    pos = (system_time_s - coordination.offset_s) % cycle_s if cycle_s > 0 else 0.0
    remaining_in_cycle = cycle_s - pos

    if current == coord_phase and not current_is_faulted:
        min_served = elapsed >= min_g
        in_guaranteed_window = pos < coordination.coordinated_green_s
        target = None
        if min_served and not in_guaranteed_window:
            calling_minors = [
                p
                for p in cfg.ring_order
                if p != coord_phase
                and p not in ctx.faulted_phases
                and _phase_has_call(cfg, ctx, p)
                and _can_fit(cfg, p, remaining_in_cycle, clearance_s)
            ]
            if calling_minors:
                target = max(calling_minors, key=lambda p: _phase_call_age_s(cfg, ctx, p))

        if target is None:
            return SignalPlan(
                intersection_id=cfg.intersection_id,
                steps=(PlanStep(phase_id=current, green_s=tick_s),),
                source="coordinated_actuated",
            )
        return SignalPlan(
            intersection_id=cfg.intersection_id,
            steps=(
                _exit_step(cfg, ctx, current, min_g, tick_s),
                PlanStep(phase_id=target, green_s=cfg.min_green_s.get(target, 0.0)),
            ),
            source="coordinated_actuated",
        )

    # Current is a minor (actuated) phase, or the coordinated phase itself
    # is faulted.
    still_calling = (not current_is_faulted) and _phase_has_call(cfg, ctx, current)
    max_g = cfg.max_green_s.get(current, min_g)
    force_off = remaining_in_cycle <= clearance_s + tick_s
    would_max_out = elapsed + tick_s >= max_g

    if current_is_faulted or not still_calling or would_max_out or force_off:
        next_phase = (
            coord_phase
            if coord_phase not in ctx.faulted_phases
            else _next_in_ring(cfg.ring_order, current, ctx.faulted_phases)
        )
        if next_phase is None:
            return SignalPlan(
                intersection_id=cfg.intersection_id, steps=(), source="coordinated_actuated"
            )
        return SignalPlan(
            intersection_id=cfg.intersection_id,
            steps=(
                _exit_step(cfg, ctx, current, min_g, tick_s),
                PlanStep(phase_id=next_phase, green_s=cfg.min_green_s.get(next_phase, 0.0)),
            ),
            source="coordinated_actuated",
        )

    return SignalPlan(
        intersection_id=cfg.intersection_id,
        steps=(PlanStep(phase_id=current, green_s=tick_s),),
        source="coordinated_actuated",
    )

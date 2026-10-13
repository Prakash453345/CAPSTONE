"""Webster fixed-time strategy [build guide §7 M3]: the *properly tuned*
baseline the M3 gate demands -- "compute optimal cycle from measured flows,
do not guess." `fixed_time.py` (M2) is a different thing wearing a similar
shape: it holds every phase for exactly its own `min_green_s`, which is
correct as the arbitration ladder's always-safe floor but is not a tuned
timing plan and was never meant to be graded as one (see that module's own
docstring). This module is the real timing plan: a cycle length and a set
of per-phase green splits derived from Webster's 1958 delay-minimisation
formula, applied to actual measured demand for this network
(`scenarios/networks/vijayawada/measure_flows.py` does the measuring).

Split deliberately in two, mirroring the project's pure/impure boundary
everywhere else (`interlocks.py` pure vs. `extract_tier0_config.py` doing
XML I/O for the same reason): `compute_timing` below is a pure function of
a `Tier0Config` and a flow measurement -- no file I/O, no SUMO, trivially
unit-testable with synthetic numbers. Turning a net.xml + route file into
that flow measurement is `measure_flows.py`'s job, not this module's.

Worked math, so every constant below is traceable to something real rather
than tuned to make a number come out nicely:

- **Saturation flow** `_SATURATION_FLOW_VEH_PER_HOUR`: 1900 veh/h is the
  standard base saturation flow rate per traffic lane used throughout
  Webster's original work and carried into the HCM -- one vehicle every
  ~1.9s of continuous green, per lane. Every link this extraction produces
  (`extract_tier0_config.py`) is already one SUMO lane-to-lane connection,
  so "per link" and "per lane" are the same unit here; no lane-counting
  needed.
- **Lost time per phase** `_LOST_TIME_PER_PHASE_S`: 4.0s is the standard
  textbook default (~2s driver start-up reaction lag + ~2s of the
  yellow/all-red interval that isn't actually used by clearing traffic)
  when it isn't separately field-measured -- which it isn't here; this
  network's actual yellow_s/all_red_s (3s/2s, [ARCH-required] real
  clearance intervals I2 enforces) are a *safety* clearance, a different
  quantity from Webster's lost-time term, and are not reused for it.
- **Cycle length formula**: C_o = (1.5*L + 5) / (1 - Y), Webster's own
  optimum-cycle formula, L = total lost time per cycle, Y = sum of the
  critical flow ratios y_i = q_i/s_i over every phase in the ring.
- **Degree-of-saturation clamp** `_MAX_DEGREE_OF_SATURATION`: Webster's
  formula blows up (and the corresponding real intersection would be
  failing) as Y -> 1. Real practice caps the value of Y actually used in
  the formula rather than reporting an infinite or negative cycle --
  0.95 is the conventional ceiling. When actual measured Y exceeds it,
  `WebsterTiming.degree_of_saturation` still reports the *true* value
  (worth knowing: this junction is over-saturated), only the cycle-length
  formula's input is clamped.
- **Cycle bounds** `_MIN_CYCLE_S`/`_MAX_CYCLE_S`: 40s/180s bracket every
  cycle length real signal timing practice considers usable regardless of
  what the raw formula returns -- guards against a degenerate near-zero-flow
  junction producing an absurdly short cycle, or a clamped-Y junction still
  producing an unworkably long one.

Every computed green_s is clamped a second time against this specific
junction's own `cfg.min_green_s`/`cfg.max_green_s` before being used --
Webster's formula has no idea those bounds exist, but the safety kernel
does, and this module doesn't get to relitigate I3 with a plan that trims
below the floor `interlocks.check()` would reject anyway.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config

_SATURATION_FLOW_VEH_PER_HOUR = 1900.0
_LOST_TIME_PER_PHASE_S = 4.0
_MAX_DEGREE_OF_SATURATION = 0.95
_MIN_CYCLE_S = 40.0
_MAX_CYCLE_S = 180.0
_STARTUP_CLEARANCE_S = 5.0  # Webster's own formula constant, not a network measurement


@dataclass(frozen=True)
class WebsterTiming:
    """One junction's tuned timing plan. `green_s` covers every phase in
    `Tier0Config.ring_order` (never a subset -- `compute_timing` always
    fills every phase, falling back to an even split when a phase carries
    no measured flow at all). `degree_of_saturation` is the *unclamped*
    Y, reported honestly even when it exceeds the formula's usable range --
    see module docstring."""

    intersection_id: str
    cycle_s: float
    green_s: Mapping[str, float]
    critical_flow_ratios: Mapping[str, float]
    degree_of_saturation: float


def compute_timing(
    cfg: Tier0Config,
    link_flows_veh_per_hour: Mapping[str, float],
    *,
    fixed_cycle_s: float | None = None,
) -> WebsterTiming:
    """Webster's method, applied to one junction. `link_flows_veh_per_hour`
    is keyed by link id (`"L{i}"`, matching `Phase.green_movements`) --
    measured demand for that specific movement, veh/h. A link missing from
    the mapping is treated as zero measured flow (a real, if unlikely,
    outcome for a turn nothing in the route file ever uses).

    `fixed_cycle_s`, when given, skips this junction's own optimum-cycle
    formula and splits green proportionally within that externally-fixed
    cycle instead -- what `coordinated_actuated.build_corridor_plan` needs:
    every junction along a coordinated corridor shares one cycle length
    (the critical junction's own optimum, picked by whichever junction
    needs the longest cycle to serve its demand), and each junction's own
    Webster *split* still has to be recomputed against that shared number
    rather than its own independently-optimal one. `degree_of_saturation`
    is still this junction's own true measured value either way -- fixing
    the cycle changes how the green pool is divided, not what demand this
    junction actually has."""
    n_phases = len(cfg.ring_order)
    if n_phases == 0:
        return WebsterTiming(cfg.intersection_id, 0.0, {}, {}, 0.0)

    critical_flow_ratios: dict[str, float] = {}
    for phase_id in cfg.ring_order:
        phase = cfg.phases[phase_id]
        movements = phase.protected_movements or phase.green_movements
        if not movements:
            critical_flow_ratios[phase_id] = 0.0
            continue
        critical_flow_ratios[phase_id] = max(
            link_flows_veh_per_hour.get(m, 0.0) / _SATURATION_FLOW_VEH_PER_HOUR
            for m in movements
        )

    degree_of_saturation = sum(critical_flow_ratios.values())
    total_lost_time_s = n_phases * _LOST_TIME_PER_PHASE_S

    if fixed_cycle_s is not None:
        cycle_s = fixed_cycle_s
    else:
        y_for_formula = min(degree_of_saturation, _MAX_DEGREE_OF_SATURATION)
        raw_cycle_s = (1.5 * total_lost_time_s + _STARTUP_CLEARANCE_S) / (1 - y_for_formula)
        cycle_s = max(_MIN_CYCLE_S, min(_MAX_CYCLE_S, raw_cycle_s))

    effective_green_pool_s = max(cycle_s - total_lost_time_s, 0.0)
    green_s: dict[str, float] = {}
    for phase_id in cfg.ring_order:
        y_i = critical_flow_ratios[phase_id]
        if degree_of_saturation > 0:
            share = y_i / degree_of_saturation
        else:
            share = 1.0 / n_phases  # no measured demand anywhere -- split the cycle evenly
        proposed = share * effective_green_pool_s
        lower = cfg.min_green_s.get(phase_id, 0.0)
        upper = cfg.max_green_s.get(phase_id, proposed)
        green_s[phase_id] = max(lower, min(upper, proposed))

    return WebsterTiming(
        intersection_id=cfg.intersection_id,
        cycle_s=cycle_s,
        green_s=green_s,
        critical_flow_ratios=critical_flow_ratios,
        degree_of_saturation=degree_of_saturation,
    )


def _next_in_ring(ring_order: tuple[str, ...], current: str, faulted: frozenset[str]) -> str | None:
    """Identical in behaviour to `fixed_time._next_in_ring` -- duplicated
    rather than imported. It's ten lines of pure ring arithmetic with no
    Webster-specific content; importing another strategy module's private
    helper would couple two independently-reasoned-about safety-adjacent
    modules for no real reuse benefit. See that module for the canonical
    docstring."""
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


def propose(
    cfg: Tier0Config, ctx: JunctionContext, timing: WebsterTiming, *, tick_s: float = 1.0
) -> SignalPlan:
    """One controller tick's proposal under a tuned Webster timing plan.
    Structurally identical to `fixed_time.propose` -- same single-step-
    extend-vs-two-step-transition shape, same fault handling -- with one
    substitution: the nominal hold duration for each phase comes from
    `timing.green_s`, not `cfg.min_green_s`. That substitution is the
    entire difference between "guessed" and "tuned"; everything that makes
    a fixed-time plan safe (I2/I3/I6 handling) is unchanged and unchanged
    for the same reason it was correct in M2 -- the safety kernel doesn't
    care where a plan's numbers came from."""
    current = ctx.current_phase_id
    nominal = timing.green_s.get(current, cfg.min_green_s.get(current, 0.0))
    min_g = cfg.min_green_s.get(current, 0.0)
    elapsed = ctx.current_phase_elapsed_s
    current_is_faulted = current in ctx.faulted_phases

    if not current_is_faulted and elapsed + tick_s < nominal:
        return SignalPlan(
            intersection_id=cfg.intersection_id,
            steps=(PlanStep(phase_id=current, green_s=tick_s),),
            source="webster_fixed_time",
        )

    next_phase = _next_in_ring(cfg.ring_order, current, ctx.faulted_phases)
    if next_phase is None:
        return SignalPlan(
            intersection_id=cfg.intersection_id, steps=(), source="webster_fixed_time"
        )

    # Same I3 exemption as fixed_time: a faulted phase leaves immediately,
    # a healthy one is topped up to at least its own min_green before it
    # goes, even if the tuned nominal duration was somehow shorter.
    remaining = tick_s if current_is_faulted else max(tick_s, min_g - elapsed)
    return SignalPlan(
        intersection_id=cfg.intersection_id,
        steps=(
            PlanStep(
                phase_id=current,
                green_s=remaining,
                yellow_s=cfg.yellow_s,
                all_red_s=cfg.all_red_s,
            ),
            PlanStep(
                phase_id=next_phase,
                green_s=timing.green_s.get(next_phase, cfg.min_green_s.get(next_phase, 0.0)),
            ),
        ),
        source="webster_fixed_time",
    )

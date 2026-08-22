"""Fixed-time strategy -- arbitration-ladder rung 5 [build guide §3.8,
ARCH §2.2]: the plan the safety kernel falls back to when nothing smarter
is available (no optimiser running, no usable traffic state, or comms/
fault conditions that rule out anything adaptive).

M2 scope: this cycles the ring at each phase's own `min_green_s` -- it is
**not** the "properly tuned Webster... compute optimal cycle from measured
flows, do not guess" strategy the build guide asks for as an M3 baseline
(§7 M3). That's real work (measuring saturation flow, computing an optimal
cycle length and green splits) that belongs with the KPI harness it'll be
benchmarked against, not with the safety kernel. What M2 needs from this
module is narrower and more important: a strategy that is *always*
interlock-safe by construction, demand-blind, and available even when
every sensor is gone -- literally the bottom rung, not a good rung.

Called once per controller tick; decides "extend the current phase" vs
"advance to the next phase in the ring," per §3.7's DECIDE(i, t) shape,
minus the pressure-based skip/lookahead logic that only makes sense once
an optimiser (M4) is proposing phases by demand.

Known gap, left deliberately unhandled here rather than papered over: a
faulted exit (see `_next_in_ring`) doesn't check `ctx.ped_phase_in_progress`
before leaving -- if the SAME phase is both faulted and mid-walk, this
strategy can propose a plan that fails I4. That's fine, not a hole in the
kernel: `control.safety.interlocks.check()` is the actual guarantee, and it
will reject that proposal regardless of what produced it. It's on the
arbiter (`signal_controller/arbiter.py`) to fall back further (hardware
failsafe) when even the fallback strategy's plan doesn't clear the kernel --
which is the point of the ladder having a rung below this one.
"""

from __future__ import annotations

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config


def _next_in_ring(ring_order: tuple[str, ...], current: str, faulted: frozenset[str]) -> str | None:
    """Next phase after `current`, skipping any faulted ones (C1). Returns
    None if every phase in the ring is faulted -- the caller's job to turn
    that into a failsafe plan, not this function's."""
    if not ring_order:
        return None
    try:
        start = ring_order.index(current)
    except ValueError:
        start = -1  # current isn't even in this ring (shouldn't happen); start scanning from 0
    for offset in range(1, len(ring_order) + 1):
        candidate = ring_order[(start + offset) % len(ring_order)]
        if candidate not in faulted:
            return candidate
    return None


def propose(cfg: Tier0Config, ctx: JunctionContext, *, tick_s: float = 1.0) -> SignalPlan:
    """One controller tick's proposal. Always passes
    `control.safety.interlocks.check()` against the same `cfg`/`ctx` it was
    built from -- covered by
    `tests/control/strategies/test_fixed_time_is_always_safe.py`."""
    current = ctx.current_phase_id
    min_g = cfg.min_green_s.get(current, 0.0)
    # M2's "fixed" nominal split: hold each phase for exactly its own
    # min_green, no more. A real fixed-time plan (M3) would size this from
    # measured flow instead of always picking the floor.
    nominal = min_g
    elapsed = ctx.current_phase_elapsed_s
    current_is_faulted = current in ctx.faulted_phases

    if not current_is_faulted and elapsed + tick_s < nominal:
        # Not yet time to move on -- extend by one tick. A single-step,
        # same-phase plan is always safe: it can't truncate a green (I3),
        # it doesn't need internal clearance (I2, nothing to transition
        # between), and it doesn't newly enter a faulted phase (I6).
        return SignalPlan(
            intersection_id=cfg.intersection_id,
            steps=(PlanStep(phase_id=current, green_s=tick_s),),
            source="fixed_time",
        )

    next_phase = _next_in_ring(cfg.ring_order, current, ctx.faulted_phases)
    if next_phase is None:
        # Every phase in the ring is faulted -- there is no legal green to
        # propose anywhere in this junction. Ladder rung 1's job, not this
        # strategy's: the arbiter is expected to drop to hardware failsafe
        # (flash / all-red) rather than command a `SignalPlan` at all. See
        # signal_controller/arbiter.py.
        return SignalPlan(intersection_id=cfg.intersection_id, steps=(), source="fixed_time")

    # Faulted exit: leave immediately regardless of elapsed (I3 exempts a
    # faulted phase from its own min-green promise -- see
    # interlocks.min_green_satisfied's docstring), but still with full
    # physical clearance (I2 has no such exemption).
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
            PlanStep(phase_id=next_phase, green_s=cfg.min_green_s.get(next_phase, 0.0)),
        ),
        source="fixed_time",
    )

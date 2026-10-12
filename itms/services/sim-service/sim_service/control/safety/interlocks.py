"""Layer 0 -- the safety kernel as executable predicates [build guide §3.3,
ARCH §2.2]. Pure functions over a proposed `SignalPlan`: no I/O, no clock
reads (time is always a parameter, via `JunctionContext`), so the exact
same code runs inside the live controller and inside a property test.

This is the piece the build guide calls "the foundation" and insists gets
built *before* any optimiser exists: "every subsequent algorithm change is
safe to make recklessly and fast" once this exists with its property
tests. Nothing here knows or cares whether a plan came from fixed-time
(M2), CA-MP (M4), or an adversarial fuzzer (this module's own test suite)
-- nothing about the invariants below depends on the source, only
`preempt_budget_ok` even inspects `plan.source`, and only to decide
whether the preemption-hour cap applies.

Convention (see `itms_domain.signal.SignalPlan`/`PlanStep` docstrings):
`plan.steps[0]` describes what happens to the junction's *current* live
phase (continue it, or end it with proper clearance) before any later
step's phase begins. A plan that starts on a different phase from
`ctx.current_phase_id` is proposing an instantaneous change and will fail
`min_green_satisfied` unless the context shows the current phase already
served its minimum.

Not every predicate maps onto one of the I1-I7 invariants from the build
guide's table -- `preempt_budget_ok` and `transition_legal` enforce real
Tier-0 config guards the guide's own `check()` pseudocode calls for, but
aren't literally numbered invariants. They're tagged with their own rule
ids (`PREEMPT_BUDGET`, `RING_INTEGRITY`) rather than forced onto a nearby
I-number that wouldn't quite be honest.

I7 ("commanded state and read-back state converge, or commanding stops")
is deliberately NOT here: it's a property of a live command/ack/readback
sequence over time, not of a single proposed plan, so it can't be a pure
predicate over `SignalPlan`. It's implemented in
`signal_controller/arbiter.py`'s cabinet reconciliation and exercised by
the C2/C3/C5 fault-injection tests instead of a Hypothesis property.
"""

from __future__ import annotations

from itms_domain import JunctionContext, SignalPlan, Tier0Config, Violation


def no_conflicting_greens(plan: SignalPlan, cfg: Tier0Config) -> list[Violation]:
    """I1: no two conflicting *protected* movements are ever simultaneously
    green. Deliberately checks `phase.protected_movements`, not
    `green_movements` -- see `Phase`'s docstring for why a permissive/yield
    movement (SUMO's lowercase 'g') is excluded rather than a hole in the
    invariant."""
    violations = []
    for step in plan.steps:
        phase = cfg.phases.get(step.phase_id)
        if phase is None:
            violations.append(
                Violation("I1", f"plan references unknown phase {step.phase_id!r}")
            )
            continue
        movements = sorted((phase.protected_movements or phase.green_movements)
                           | phase.overlap_movements)
        for i, a in enumerate(movements):
            for b in movements[i + 1 :]:
                if b in cfg.conflict_matrix.get(a, frozenset()):
                    violations.append(
                        Violation(
                            "I1",
                            f"phase {step.phase_id!r} makes conflicting movements "
                            f"{a!r} and {b!r} simultaneously green",
                            frozenset({a, b}),
                        )
                    )
    return violations


def min_green_satisfied(
    plan: SignalPlan, ctx: JunctionContext, cfg: Tier0Config
) -> list[Violation]:
    """I3: min_green is never truncated, by any requester, including
    preemption -- checked as "does the plan move away from a phase before
    that phase has accumulated its minimum green," for the currently-live
    phase (elapsed + any continuation step) and for every phase the plan
    itself later enters and then leaves again.

    Deliberate exception: a phase already in `ctx.faulted_phases` (C1 --
    e.g. a lamp failure) is exempt from this check on its way out. I3
    protects a *working* green from being cut short; a green that's already
    broken has nothing left to protect, and I6 ("fault reaches a defined
    safe state") is the invariant that governs what happens to it instead.
    """
    violations: list[Violation] = []
    steps = plan.steps
    if not steps:
        return violations  # empty-plan case is check()'s job, not this predicate's

    current_is_faulted = ctx.current_phase_id in ctx.faulted_phases

    first = steps[0]
    if first.phase_id != ctx.current_phase_id and not current_is_faulted:
        required = cfg.min_green_s.get(ctx.current_phase_id, 0.0)
        if ctx.current_phase_elapsed_s < required:
            violations.append(
                Violation(
                    "I3",
                    f"plan ends phase {ctx.current_phase_id!r} after "
                    f"{ctx.current_phase_elapsed_s}s, but its min_green is {required}s",
                    frozenset({ctx.current_phase_id}),
                )
            )

    for i, step in enumerate(steps):
        is_last = i == len(steps) - 1
        next_is_same_phase = (not is_last) and steps[i + 1].phase_id == step.phase_id
        if is_last or next_is_same_phase:
            continue  # not yet truncated by anything this plan actually does
        if i == 0 and step.phase_id == ctx.current_phase_id and current_is_faulted:
            continue  # faulted exit -- see docstring
        served = step.green_s
        if i == 0 and step.phase_id == ctx.current_phase_id:
            served += ctx.current_phase_elapsed_s
        required = cfg.min_green_s.get(step.phase_id, 0.0)
        if served < required:
            violations.append(
                Violation(
                    "I3",
                    f"phase {step.phase_id!r} would get only {served}s before "
                    f"the plan moves on, below its {required}s min_green",
                    frozenset({step.phase_id}),
                )
            )
    return violations


def clearance_intervals_present(plan: SignalPlan, cfg: Tier0Config) -> list[Violation]:
    """I2: every green->green transition on conflicting movements passes
    through yellow + all-red >= the geometry minimum. Only checked between
    consecutive steps *within* the plan -- see this module's docstring for
    why steps[0] representing the current phase makes that sufficient."""
    violations = []
    for current, nxt in zip(plan.steps, plan.steps[1:], strict=False):
        current_phase = cfg.phases.get(current.phase_id)
        next_phase = cfg.phases.get(nxt.phase_id)
        if current_phase is None or next_phase is None:
            continue  # unknown-phase violations are no_conflicting_greens's job
        conflicts = any(
            b in cfg.conflict_matrix.get(a, frozenset())
            for a in current_phase.shown_movements
            for b in next_phase.shown_movements
        )
        if not conflicts:
            continue
        if current.yellow_s < cfg.yellow_s or current.all_red_s < cfg.all_red_s:
            violations.append(
                Violation(
                    "I2",
                    f"transition {current.phase_id!r} -> {nxt.phase_id!r} conflicts "
                    f"but only got yellow={current.yellow_s}s/all_red={current.all_red_s}s "
                    f"(need >= {cfg.yellow_s}s/{cfg.all_red_s}s)",
                    frozenset({current.phase_id, nxt.phase_id}),
                )
            )
    return violations


def pedestrian_clearance_respected(
    plan: SignalPlan, ctx: JunctionContext, cfg: Tier0Config
) -> list[Violation]:
    """I4: a pedestrian phase, once started, always completes its walk +
    clearance -- even against a preemption request arriving mid-walk."""
    violations: list[Violation] = []
    ped_phase = ctx.ped_phase_in_progress
    if ped_phase is None or not plan.steps:
        return violations

    required = cfg.ped_walk_s.get(ped_phase, 0.0) + cfg.ped_clearance_s.get(ped_phase, 0.0)
    already_complete = ctx.ped_phase_elapsed_s >= required
    if already_complete:
        return violations

    first = plan.steps[0]
    if first.phase_id != ped_phase:
        violations.append(
            Violation(
                "I4",
                f"pedestrian phase {ped_phase!r} only {ctx.ped_phase_elapsed_s}s into "
                f"its required {required}s, but plan switches away immediately",
                frozenset({ped_phase}),
            )
        )
    elif ctx.ped_phase_elapsed_s + first.green_s < required:
        violations.append(
            Violation(
                "I4",
                f"pedestrian phase {ped_phase!r} would end at "
                f"{ctx.ped_phase_elapsed_s + first.green_s}s, short of its required {required}s",
                frozenset({ped_phase}),
            )
        )
    return violations


def max_wait_not_exceeded(
    plan: SignalPlan, ctx: JunctionContext, cfg: Tier0Config
) -> list[Violation]:
    """I5: no movement waits longer than max_wait_s while it has demand.
    Once a movement has waited that long, the plan's very first step must
    serve it -- "eventually" is not good enough once the bound is hit."""
    violations: list[Violation] = []
    if not plan.steps:
        return violations
    first_phase = cfg.phases.get(plan.steps[0].phase_id)
    served_now = first_phase.shown_movements if first_phase else frozenset()

    for movement, waited in ctx.wait_times_s.items():
        if not ctx.has_demand.get(movement, False):
            continue
        if waited >= cfg.max_wait_s and movement not in served_now:
            violations.append(
                Violation(
                    "I5",
                    f"movement {movement!r} has waited {waited}s (>= {cfg.max_wait_s}s "
                    f"bound) with demand, but the plan doesn't serve it now",
                    frozenset({movement}),
                )
            )
    return violations


def preempt_budget_ok(
    plan: SignalPlan, ctx: JunctionContext, cfg: Tier0Config
) -> list[Violation]:
    """Tier-0 config guard: max_preempt_s_per_hour, per junction. Not one of
    the numbered I1-I7 invariants -- it's the interlock that stops a
    corridor-preemption requester (real ones arrive M6/M7) from
    monopolising a junction, regardless of how legitimate any single
    request looks."""
    if plan.source != "corridor_preemption":
        return []
    requested = sum(step.green_s for step in plan.steps)
    total = ctx.preempt_seconds_last_hour + requested
    if total > cfg.max_preempt_s_per_hour:
        return [
            Violation(
                "PREEMPT_BUDGET",
                f"plan requests {requested}s of preemption; combined with "
                f"{ctx.preempt_seconds_last_hour}s already used this hour, that's "
                f"{total}s > the {cfg.max_preempt_s_per_hour}s cap",
            )
        ]
    return []


def phase_reachable(plan: SignalPlan, ctx: JunctionContext) -> list[Violation]:
    """I6: on any fault, the junction reaches a defined safe state -- which
    starts with never being commanded INTO a phase a fault has made
    unusable (C1: a lamp failure takes the whole phase offline)."""
    violations = []
    for step in plan.steps:
        if step.phase_id in ctx.faulted_phases:
            violations.append(
                Violation(
                    "I6",
                    f"phase {step.phase_id!r} is faulted and cannot be commanded",
                    frozenset({step.phase_id}),
                )
            )
    return violations


def transition_legal(plan: SignalPlan, cfg: Tier0Config) -> list[Violation]:
    """Structural guard, not one of I1-I7: every phase the plan names must be
    a real, configured member of this junction's ring. This deliberately
    does NOT enforce ring *order* (build guide §3.7's skip-ahead ring logic
    is a strategy/optimiser concern, not a safety one) -- only that nothing
    can command a phase this junction doesn't actually have. A configured
    alternate of a ring phase (`Tier0Config.alternates`) counts as one.
    (Until 2026-10-04 only the first step was checked, and the first step is
    the phase already running: a plan could move on to a configured phase
    that was in neither the ring nor the alternates.)"""
    out = []
    for step in plan.steps:
        pid = step.phase_id
        if pid in cfg.ring_order:
            continue
        if pid not in cfg.alternates or pid not in cfg.phases:
            out.append(
                Violation(
                    "RING_INTEGRITY",
                    f"phase {pid!r} is not part of this intersection's configured ring",
                    frozenset({pid}),
                )
            )
        else:
            # an alternate is only as safe as its ring phase if it is the
            # ring phase with protected movements taken away and nothing
            # else changed (`Tier0Config.alternate_problems`)
            broken = cfg.alternate_problems(pid)
            if broken:
                out.append(Violation("RING_INTEGRITY", broken[0], frozenset({pid})))
    return out


def starts_at_current_phase(plan: SignalPlan, ctx: JunctionContext) -> list[Violation]:
    """Structural guard, not one of I1-I7: a plan's first step is the phase
    the junction is showing. Every other predicate reads the first step as
    "the green that is running" -- I3 judges its minimum green against
    `ctx.current_phase_elapsed_s`, I2 asks for a clearance only *between*
    steps -- so a one-step plan naming a different phase passed all of
    them, and the runner applies a one-step plan by relabelling the current
    phase with no change interval at all. No strategy here emits such a
    plan; the kernel is there for the one that does. Found by review,
    2026-10-04, when a phase and its alternate (`Tier0Config.alternates`)
    made the jump one typo away."""
    if not plan.steps or plan.steps[0].phase_id == ctx.current_phase_id:
        return []
    first = plan.steps[0].phase_id
    return [
        Violation(
            "PLAN_CONTINUITY",
            f"plan starts at phase {first!r} but the junction is in "
            f"{ctx.current_phase_id!r}",
            frozenset({first}),
        )
    ]


def check(plan: SignalPlan, ctx: JunctionContext, cfg: Tier0Config) -> list[Violation]:
    """Run every Layer-0 predicate against a proposed plan. Empty results
    means the plan is safe to command -- it says nothing about whether the
    plan is a *good* plan, only that it can't produce an unsafe junction."""
    if not plan.steps:
        return [Violation("EMPTY_PLAN", "a SignalPlan must propose at least one step")]

    violations: list[Violation] = []
    violations += starts_at_current_phase(plan, ctx)
    violations += no_conflicting_greens(plan, cfg)
    violations += min_green_satisfied(plan, ctx, cfg)
    violations += clearance_intervals_present(plan, cfg)
    violations += pedestrian_clearance_respected(plan, ctx, cfg)
    violations += max_wait_not_exceeded(plan, ctx, cfg)
    violations += preempt_budget_ok(plan, ctx, cfg)
    violations += phase_reachable(plan, ctx)
    violations += transition_legal(plan, cfg)
    return violations

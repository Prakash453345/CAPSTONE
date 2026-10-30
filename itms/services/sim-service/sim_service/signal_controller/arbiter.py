"""The arbitration ladder [ARCH §2.2]: the single chokepoint through which
every signal command passes. Optimisers and the corridor engine never
touch a cabinet directly -- they propose, this arbitrates.

Priority order (highest wins):
    1. Hardware/safety faults -> fall back to fixed failsafe plan
    2. Manual operator override            (no requester yet -- M6/E2)
    3. Green corridor preemption            (no requester yet -- M6/M7)
    4. Adaptive optimizer plan              (no requester yet -- M4 CA-MP)
    5. Fixed-timer fallback                 (this milestone's only real rung)

M2 builds the ladder's *shape* and rung 5 for real; rungs 2-4 are
deliberately absent rather than stubbed with fake data, because a stub
that always returns "no request" is indistinguishable from "this rung
doesn't exist yet" and would just be dead code to delete later. When M4/M6/
M7 land, each adds a real proposal source ahead of fixed-time in `tick()`'s
priority chain -- the chain itself doesn't change shape.

This module also implements I7 ("commanded state and read-back state
converge within T_ack, or commanding stops") -- the one invariant from
§3.3's table that can't be a pure predicate over a single `SignalPlan`,
because it's about a live command/ack/readback sequence over time, not a
proposal in isolation. `tick()` is where that reconciliation actually
happens, and the C1-C5 fault-injection tests exercise it directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from itms_domain import JunctionContext, SignalPlan, Tier0Config, Violation

from sim_service.control.safety import interlocks
from sim_service.control.strategies import fixed_time
from sim_service.signal_controller.cabinet import CabinetPort

Strategy = Callable[[Tier0Config, JunctionContext], SignalPlan]
# Rung 3 of the ladder: a corridor-preemption proposal source. Returns a
# `SignalPlan(source="corridor_preemption")` when an emergency vehicle needs
# this junction held right now, or None when it doesn't. The green corridor
# engine (`sim_service.live.green_corridor.CorridorController.preemption_plan`)
# is the first real implementation; before M7 this stayed `None` (rung absent,
# see module docstring).
PreemptSource = Callable[[Tier0Config, JunctionContext], "SignalPlan | None"]


class CorridorPort(Protocol):
    """Rung 3's requester interface, shaped like `CabinetPort`: this
    module depends on the protocol, not on `control/corridor/`, so the
    arbitration ladder stays ignorant of how preemption decides anything.

    `propose` returns None whenever no preemption applies, which is most
    ticks. That is the difference between this and a `Strategy`, which
    must always produce a plan.

    `begin_tick` and `preempt_seconds_last_hour` are corridor-scoped and
    are called by `control/runner.py`, not by this module -- see that
    function's docstring for why arbitration must be decided once per
    corridor rather than once per junction."""

    def propose(self, cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan | None: ...

    def denied(
        self, cfg: Tier0Config, ctx: JunctionContext, violations: list[Violation]
    ) -> None: ...

    def begin_tick(self, now_s: float) -> None: ...

    def preempt_seconds_last_hour(self, junction_id: str, now_s: float) -> float: ...

    def stats(self) -> dict[str, float]: ...


SUCCESS_MODES = frozenset({"fixed_time", "corridor_preemption"})
"""Modes in which a plan was actually commanded.

Named here rather than left as a literal at the call site, which is where
`control/runner.py` had it (`if decision.mode not in ("fixed_time",)`).
That literal duplicated knowledge this module owns, and adding a second
success mode without it would have made every successful preemption look
to the runner like a fault -- logged as one, and "recovered" from by
resetting the junction's context out from under a live preemption."""


@dataclass(frozen=True)
class Decision:
    """One tick's outcome. `plan` is None whenever commanding stopped for
    this tick (any fault branch) -- `mode` says which ladder rung / fault
    path produced the outcome, and `events` carries the
    SignalChanged/SignalFaulted payloads that path implies (shaped to match
    `contracts/events/signal_changed.avsc` / `signal_faulted.avsc` field-
    for-field). Publishing these onto the real event bus is
    `control/runner.py`'s job, not this module's -- `run_controlled_scenario`'s
    optional `bus` parameter does exactly that, straight encode-and-publish
    with no reshape, since the dicts built below already match their
    target schemas."""

    mode: str
    plan: SignalPlan | None
    events: list[dict] = field(default_factory=list)
    notes: tuple[str, ...] = ()
    """Non-fatal observations about this tick that aren't wire events -- used so
    far only to record that a rung-3 corridor-preemption proposal was rejected
    by the interlocks and the ladder fell through to the normal strategy. The
    junction is safe either way; this is just so `control/runner.py` can log and
    count corridor rejections without them looking like a fault."""
    violated_movements: frozenset[str] = frozenset()
    """Populated only for `mode == "failsafe_interlock_rejected"`: the union
    of every rejected `Violation.movements`. Deliberately NOT folded into
    `events` -- those dicts are schema-constrained (`signal_faulted.avsc`,
    see this class's own docstring), and this is Python-side routing
    information for whoever recovers from the fault (`control/runner.py`'s
    `_recover_from_fault`), not part of the wire event contract. Added
    alongside the starvation-override fix in `camp.py` (see PROGRESS.md's
    "Real saturation-flow calibration" section): recovery previously had no
    way to know *which* movement an I5 rejection was actually about, so it
    could only ever reset to the ring's first phase -- functionally
    correct (all-red is always safe) but blind to whether that phase was
    anywhere close to fixing the thing that got rejected."""


def _faulted_event(intersection_id: str, fault_type: str, detail: str) -> dict:
    return {
        "intersection_id": intersection_id,
        "fault_type": fault_type,
        "detail": detail,
    }


def _changed_event(intersection_id: str, plan: SignalPlan) -> dict:
    return {
        "intersection_id": intersection_id,
        "phase_id": plan.steps[0].phase_id,
        "source": plan.source,
    }


def tick(
    cfg: Tier0Config,
    ctx: JunctionContext,
    cabinet: CabinetPort,
    *,
    strategy: Strategy = fixed_time.propose,
    corridor: CorridorPort | None = None,
    preempt: PreemptSource | None = None,
) -> Decision:
    """Run one arbitration cycle for one intersection. Reconciles cabinet
    state first (I7), only proposes and commands a plan if that reconciles
    clean.

    `corridor` and `preempt` are two independent rung-3 requesters, checked
    in that order -- `corridor` (the `CorridorPort`-backed benchmark path,
    M7's green corridor engine) first, then `preempt` (a plain callable, the
    live command-driven service's path). No caller wires both at once today;
    if one did, a `corridor` proposal would win. Either way, once one
    returns a plan and that plan passes `interlocks.check`, it is commanded
    (mode ``"corridor_preemption"``). A plan the interlocks reject never
    forces a junction to all-red: `corridor`'s rejection calls back into
    `corridor.denied` and raises a `SignalFaulted` event (H1: never silent);
    `preempt`'s rejection is recorded in `Decision.notes`. Either way, the
    ladder then falls through to `strategy` unchanged.
    """
    readback = cabinet.read_state()
    iid = cfg.intersection_id
    notes: tuple[str, ...] = ()

    # C3: comms didn't reach the cabinet at all -- treat state as unknown,
    # stop commanding. (I7: "or commanding stops.")
    if not readback.comms_ok:
        return Decision(
            mode="degraded_comms_lost",
            plan=None,
            events=[_faulted_event(iid, "comms_lost", "cabinet did not acknowledge the last read")],
        )

    # C2: the cabinet's own hardware forced flash. Observe, alarm, never
    # fight it by commanding anyway.
    if readback.hardware_override:
        return Decision(
            mode="failsafe_hardware_override",
            plan=None,
            events=[
                _faulted_event(iid, "conflict_monitor_trip", "cabinet forced flash independently")
            ],
        )

    # C4: fresh boot, state unknown. Forced all-red startup sequence -- a
    # controller-issued failsafe, not the hardware fighting us -- then the
    # *next* tick gets a defined resume once this command lands.
    if readback.booting:
        cabinet.command_all_red()
        return Decision(
            mode="failsafe_boot_all_red",
            plan=None,
            events=[_faulted_event(iid, "power_restart", "forced all-red startup sequence")],
        )

    # C5 / E1: cabinet reports a phase we didn't (currently believe we)
    # command. Divergence is the signature of both hardware faults and a
    # human at the cabinet (E1) -- either way, yield immediately.
    if readback.phase_id is not None and readback.phase_id != ctx.current_phase_id:
        return Decision(
            mode="failsafe_divergence",
            plan=None,
            events=[
                _faulted_event(
                    iid,
                    "readback_divergence",
                    f"commanded/believed {ctx.current_phase_id!r}, "
                    f"cabinet reports {readback.phase_id!r}",
                )
            ],
        )

    # Rung 3: green corridor preemption. Rung 2 (manual operator
    # override) still has no requester -- deliberately absent, per this
    # module's docstring, rather than stubbed.
    #
    # The asymmetry below is the whole point of putting preemption on its
    # own rung instead of inside a strategy. A plan from rung 5 that
    # fails the interlocks is a *fault*: nothing sits below fixed-time, so
    # the junction has no legal option left and all-red is the correct
    # answer. A plan from rung 3 that fails is a *denial*: a perfectly
    # good adaptive controller is sitting one rung down, ready to run the
    # junction normally, and commanding all-red instead would strand the
    # emergency vehicle at a dark-red intersection with the cross street
    # stopped too -- the exact opposite of what the request was for.
    #
    # H1 in the hazard catalogue insists a denied emergency request must
    # never be silent ("alarm and log instead"), so `corridor`'s denial
    # raises a `SignalFaulted` event and calls back into the requester;
    # `preempt`'s denial (see below) is recorded in `Decision.notes`
    # instead -- either way, control falls through as if no request had
    # been made.
    denial_events: list[dict] = []
    notes = ()
    if corridor is not None:
        preempt_plan = corridor.propose(cfg, ctx)
        if preempt_plan is not None and preempt_plan.steps:
            preempt_violations = interlocks.check(preempt_plan, ctx, cfg)
            if not preempt_violations:
                if not cabinet.command(preempt_plan.steps[0].phase_id):
                    return Decision(
                        mode="degraded_comms_lost",
                        plan=None,
                        events=[
                            _faulted_event(iid, "comms_lost", "command was not acknowledged")
                        ],
                    )
                return Decision(
                    mode="corridor_preemption",
                    plan=preempt_plan,
                    events=[_changed_event(iid, preempt_plan)],
                )
            corridor.denied(cfg, ctx, preempt_violations)
            denial_events.append(
                _faulted_event(
                    iid,
                    "preempt_denied",
                    "; ".join(f"{v.rule}: {v.message}" for v in preempt_violations),
                )
            )

    # Rung 3b: the live command-driven service's plain-callable requester
    # (see `tick`'s own docstring for why this is separate from `corridor`
    # rather than unified with it). A real requester as of M7 (the green
    # corridor); before that `preempt` was always None and the ladder went
    # straight to rung 5. A preemption plan is checked by the *same*
    # interlocks as any strategy plan -- rejected ones fall through, they
    # never force all-red.
    if preempt is not None:
        pre_plan = preempt(cfg, ctx)
        if pre_plan is not None and pre_plan.steps:
            pre_violations = interlocks.check(pre_plan, ctx, cfg)
            if pre_violations:
                notes = (
                    "corridor_preemption_rejected: "
                    + "; ".join(f"{v.rule}: {v.message}" for v in pre_violations),
                )
            else:
                acked = cabinet.command(pre_plan.steps[0].phase_id)
                if not acked:
                    return Decision(
                        mode="degraded_comms_lost",
                        plan=None,
                        events=[_faulted_event(iid, "comms_lost", "command was not acknowledged")],
                    )
                return Decision(
                    mode="corridor_preemption",
                    plan=pre_plan,
                    events=[_changed_event(iid, pre_plan)],
                )

    # Rung 4/5: whatever `strategy` is -- the adaptive optimizer when one
    # is wired, the fixed-timer fallback otherwise. Rung 2 (manual operator
    # override) still has no requester -- see module docstring.
    plan = strategy(cfg, ctx)
    if not plan.steps:
        cabinet.command_all_red()
        return Decision(
            mode="failsafe_no_legal_plan",
            plan=None,
            events=denial_events
            + [_faulted_event(iid, "no_legal_plan", "every phase in the ring is unusable")],
            notes=notes,
        )

    violations = interlocks.check(plan, ctx, cfg)
    if violations:
        cabinet.command_all_red()
        return Decision(
            mode="failsafe_interlock_rejected",
            plan=None,
            events=denial_events
            + [
                _faulted_event(
                    iid,
                    "interlock_rejected",
                    "; ".join(f"{v.rule}: {v.message}" for v in violations),
                )
            ],
            notes=notes,
            violated_movements=frozenset().union(*(v.movements for v in violations)),
        )

    acked = cabinet.command(plan.steps[0].phase_id)
    if not acked:
        return Decision(
            mode="degraded_comms_lost",
            plan=None,
            events=denial_events
            + [_faulted_event(iid, "comms_lost", "command was not acknowledged")],
            notes=notes,
        )

    return Decision(
        mode="fixed_time",
        plan=plan,
        events=denial_events + [_changed_event(iid, plan)],
        notes=notes,
    )

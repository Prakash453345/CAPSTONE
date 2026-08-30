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

from itms_domain import JunctionContext, SignalPlan, Tier0Config

from sim_service.control.safety import interlocks
from sim_service.control.strategies import fixed_time
from sim_service.signal_controller.cabinet import CabinetPort

Strategy = Callable[[Tier0Config, JunctionContext], SignalPlan]


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
) -> Decision:
    """Run one arbitration cycle for one intersection. Reconciles cabinet
    state first (I7), only proposes and commands a plan if that reconciles
    clean."""
    readback = cabinet.read_state()
    iid = cfg.intersection_id

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

    # Rungs 2-4 have no requester in M2 (see module docstring) -- proceed
    # straight to rung 5.
    plan = strategy(cfg, ctx)
    if not plan.steps:
        cabinet.command_all_red()
        return Decision(
            mode="failsafe_no_legal_plan",
            plan=None,
            events=[_faulted_event(iid, "no_legal_plan", "every phase in the ring is unusable")],
        )

    violations = interlocks.check(plan, ctx, cfg)
    if violations:
        cabinet.command_all_red()
        return Decision(
            mode="failsafe_interlock_rejected",
            plan=None,
            events=[
                _faulted_event(
                    iid,
                    "interlock_rejected",
                    "; ".join(f"{v.rule}: {v.message}" for v in violations),
                )
            ],
            violated_movements=frozenset().union(*(v.movements for v in violations)),
        )

    acked = cabinet.command(plan.steps[0].phase_id)
    if not acked:
        return Decision(
            mode="degraded_comms_lost",
            plan=None,
            events=[_faulted_event(iid, "comms_lost", "command was not acknowledged")],
        )

    return Decision(mode="fixed_time", plan=plan, events=[_changed_event(iid, plan)])

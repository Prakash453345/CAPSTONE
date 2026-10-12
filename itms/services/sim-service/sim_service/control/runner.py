"""Drives a real SUMO scenario with the arbitration ladder actually
governing every signal-controlled junction, via `TraCICabinet` -- the
piece `signal_controller/cabinet.py` and `traci_cabinet.py` both flagged
as M3's job.

Event-bus publishing is now wired but optional (the `bus` parameter,
added after M3's baselines/bench work was otherwise complete): pass a
`RedisStreamsSyncBus` to have every `arbiter.tick()` decision published as
a real `SignalChanged`/`SignalFaulted` event on `signal.changed` /
`signal.faulted`, the same ADR-003 bus contract `traci_loop.py`'s live
dashboard path already publishes through. Left `None` (the default),
behaviour is unchanged from before this wiring existed -- the smoke
scripts and `scripts/bench.py` don't pass one, since a 30-run bench sweep
publishing to a bus no one's consuming during it would just be noise.
`signal.faulted` is this module's own choice, not something ARCH §6.2's
topic table names explicitly (only `signal.changed`,
`signal.plan-proposed`, and `signal.override.*` are listed there) --
inferred from the same `signal.<verb>` convention those follow.

Per-tick shape, once a junction is "settled" (not mid-clearance):
call `arbiter.tick()`, which either extends the current phase (a 1-step
plan) or approves a transition (a 2-step plan). This module owns the
mechanical yellow -> all-red -> next-green sequencing a transition implies
-- `CabinetPort` has no notion of "hold yellow for N seconds" as a single
command, and reasonably so: that's clearance-interval bookkeeping the
build guide's own pseudocode [§3.3] treats as the plan's business, not the
cabinet's. While a junction is mid-transition, `arbiter.tick()` isn't
called for it at all: the transition was already approved (it passed
`interlocks.check()` before this module ever set the yellow state), so
there's nothing left to arbitrate until it completes.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import traci
from itms_common.bus import RedisStreamsSyncBus
from itms_common.events import encode_envelope
from itms_domain import JunctionContext, SignalPlan, Tier0Config

from sim_service.adapters.sumo.traci_loop import publish_traffic_state as _publish_traffic_state
from sim_service.control.anomaly.graph_features import AnomalyGraph, LinkFeatureSampler
from sim_service.control.anomaly.injector import IncidentInjector
from sim_service.control.memory import DemandMemory
from sim_service.control.online_calibration import OnlineCalibration
from sim_service.signal_controller import arbiter
from sim_service.signal_controller.detectors import ActuationDetector
from sim_service.signal_controller.discharge_observer import DischargeObserver
from sim_service.signal_controller.lane_cache import LaneCache
from sim_service.signal_controller.queue_state import QueueStateSampler
from sim_service.signal_controller.spillback import SpillbackTracker
from sim_service.signal_controller.traci_cabinet import TraCICabinet

log = logging.getLogger("sim-service.control.runner")

_SIGNAL_CHANGED_TOPIC = "signal.changed"
_SIGNAL_FAULTED_TOPIC = "signal.faulted"


def _publish_decision_events(bus: RedisStreamsSyncBus, decision: arbiter.Decision) -> None:
    """`_changed_event`/`_faulted_event` (private to arbiter.py) already
    build these dicts to match `contracts/events/signal_changed.avsc` /
    `signal_faulted.avsc` field-for-field, so this is a straight
    encode-and-publish, not a reshape.

    Routed per event rather than per decision, which it was not before
    M7. The old form read the *mode* and typed every event in the
    decision the same way, which was exact while a decision could only
    ever carry one event. Rung 3 broke that: a denied preemption
    (`preempt_denied`) rides along with whatever the strategy below it
    then produced, so one successful decision can carry a fault event.
    Typing that pair by mode would have published a `SignalFaulted`
    payload onto `signal.changed` under a `SignalChanged` header -- a
    schema mismatch that a consumer would decode as garbage rather than
    reject. The payloads are distinguishable by shape, so they are
    distinguished by shape."""
    for payload in decision.events:
        faulted = "fault_type" in payload
        raw = encode_envelope(
            event_type="SignalFaulted" if faulted else "SignalChanged",
            source="sim-service",
            payload=payload,
            partition_key=payload["intersection_id"],
        )
        bus.publish(_SIGNAL_FAULTED_TOPIC if faulted else _SIGNAL_CHANGED_TOPIC, raw)

Strategy = Callable[[Tier0Config, JunctionContext], SignalPlan]
# A single Strategy applies uniformly to every junction (fine for
# fixed_time -- M2's ring-at-min-green floor is identical in shape at every
# junction). Webster (M3) breaks that assumption on purpose: its whole
# point is a *different* tuned cycle/split per junction, computed from that
# junction's own measured flows. Widening to also accept a per-junction
# mapping is the minimal change that supports it without forcing every
# caller to route through a mapping even when one strategy really is
# uniform (fixed_time's own smoke test keeps passing a bare callable).
StrategySource = Strategy | Mapping[str, Strategy]


def _ensure_sumo_home() -> None:
    if os.environ.get("SUMO_HOME"):
        return
    try:
        import sumo

        os.environ["SUMO_HOME"] = os.path.dirname(sumo.__file__)
        return
    except ImportError:
        pass
    if os.path.isdir("/usr/share/sumo"):
        os.environ["SUMO_HOME"] = "/usr/share/sumo"


def _resolve_sumo_binary() -> str:
    explicit = os.environ.get("SUMO_BINARY")
    if explicit:
        return explicit
    found = shutil.which("sumo")
    if found:
        return found
    candidate = Path(sys.executable).parent / "sumo"
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("could not find the 'sumo' binary -- set SUMO_BINARY explicitly")


@dataclass
class _Transition:
    outgoing_phase: str
    incoming_phase: str
    remaining_yellow_s: float
    remaining_all_red_s: float
    stage: str  # "yellow" | "all_red"
    red_state: str | None = None  # the all-red stage's state when links are carried through


@dataclass
class _JunctionState:
    cfg: Tier0Config
    cabinet: TraCICabinet
    ctx: JunctionContext
    transition: _Transition | None = None
    detector: ActuationDetector | None = None
    queue_sampler: QueueStateSampler | None = None
    discharge: DischargeObserver | None = None


def _recover_from_fault(
    js: _JunctionState, tls_id: str, violated_movements: frozenset[str] = frozenset()
) -> None:
    """A real, previously-unpatched gap the M4 bottleneck ablation
    surfaced: every failsafe branch in `arbiter.tick()` that isn't
    cabinet-fault-flag-gated (`failsafe_interlock_rejected`,
    `failsafe_no_legal_plan` -- the only two `TraCICabinet` can ever
    actually reach, since `comms_ok`/`hardware_override`/`booting` stay
    at their healthy defaults for a real SUMO-backed cabinet, see its own
    module docstring) ends by commanding all-red and leaving `js.ctx`
    completely untouched. All-red is genuinely safe on its own -- zero
    conflicting greens -- but `TraCICabinet._phase_id_for_state` can't
    map an all-red raw state back to any known green phase, so
    `readback.phase_id` reads as `None` forever afterward, `arbiter.tick`'s
    C5 divergence check never fires (it only compares when
    `readback.phase_id is not None`), and the *same* frozen
    `current_phase_id`/`current_phase_elapsed_s` gets re-proposed against
    on every subsequent tick. Observed in practice: once one interlock
    rejection happens for any reason, every other movement's own
    `wait_times_s` (still being sampled live) keeps climbing while the
    frozen `current_phase_id` can structurally never equal a genuinely
    different starved movement's phase -- so I5 (`max_wait_not_exceeded`)
    starts rejecting every subsequent proposal too, and the junction is
    stuck in solid all-red for the rest of the run, a fault that looks
    "handled" (commanding never fights the safe state) but never
    recovers.

    The fix mirrors the exact precedent `run_controlled_scenario`'s own
    startup already uses for "state doesn't match a known phase" (a
    defined resume, not an assumed one): command a phase directly and
    reset `current_phase_elapsed_s` to 0.0, so the next tick starts from a
    clean, current snapshot instead of an ever-more-stale one. Commanding
    straight into a green with no yellow first is safe here specifically
    because nothing is currently green to clear from (the junction is
    already sitting in all-red) -- the same reasoning that makes the
    cold-boot resume path safe without one either. Not maximally rigorous:
    a real deployment would likely want to enforce a minimum all-red dwell
    before resuming, to guarantee physical clearance for anything still
    moving from before the fault, rather than resuming on the very next
    tick. Flagged as a real simplification rather than silently matched to
    the boot-resume precedent's own rigor level.

    Which phase to resume into is `violated_movements`-aware as of the same
    fix this docstring's "Observed in practice" paragraph anticipated
    (PROGRESS.md's "Real saturation-flow calibration" section): resetting
    to `ring_order[0]` unconditionally, regardless of which movement an I5
    rejection actually named, is exactly how the gap above turns into an
    unrecoverable loop -- if `ring_order[0]` doesn't serve the flagged
    movement either, recovery lands right back where the *next* proposal
    fails the *same* way, forever. Given `arbiter.Decision.violated_
    movements` (populated only for `failsafe_interlock_rejected`), resume
    into whichever ring phase actually serves one of those movements
    instead, falling back to `ring_order[0]` only when there isn't one
    (every other fault mode, or a violation naming no specific movement).

    **Recovery now goes through the same yellow -> all-red -> green
    sequence every nominal transition uses**, closing the "not maximally
    rigorous" gap the paragraph above admitted to. The earlier version
    called `cabinet.command(recovery_phase)` directly, in the same tick
    in which `arbiter.tick` had just called `command_all_red()`. Both
    writes landed before the next `simulationStep`, so the signal heads
    never displayed either the yellow or the all-red: physically, the
    junction jumped straight from the outgoing green to the recovery
    green. When those two phases conflict -- the normal case, since the
    recovery phase is chosen precisely because it serves a movement the
    outgoing phase did not -- that is an I1/I2 violation on the road,
    committed by the fail-safe path itself, on every single interlock
    rejection. The safety kernel could not see it because it checks
    *plans*, and no plan was involved.

    So: if the recovery phase differs from the phase that was green,
    re-assert that phase's yellow (overriding the arbiter's snap-to-red,
    which is strictly less safe for a vehicle already committed to the
    stop line) and schedule an ordinary `_Transition` carrying the
    junction's full `yellow_s` + `all_red_s`; `_advance_transition` then
    commands the recovery green and resets `elapsed` to 0.0 exactly as it
    does for every other switch. Only when the recovery phase *is* the
    phase that was already green -- nothing to clear from -- is the green
    re-commanded immediately, as before."""
    recovery_phase = js.cfg.ring_order[0]
    if violated_movements:
        recovery_phase = next(
            (
                p
                for p in js.cfg.ring_order
                if js.cfg.phases[p].shown_movements & violated_movements
            ),
            recovery_phase,
        )
    outgoing = js.ctx.current_phase_id
    if outgoing != recovery_phase and outgoing in js.cfg.phases:
        js.cabinet.set_raw_state(js.cabinet.yellow_state_for(outgoing))
        js.transition = _Transition(
            outgoing_phase=outgoing,
            incoming_phase=recovery_phase,
            remaining_yellow_s=js.cfg.yellow_s,
            remaining_all_red_s=js.cfg.all_red_s,
            stage="yellow",
        )
        # The stale context is kept until `_advance_transition` rebuilds
        # it: while mid-transition the runner does not arbitrate this
        # junction, so nothing reads it, and the incoming phase must not
        # be reported as "current" before the cabinet actually shows it.
        js.ctx = JunctionContext(
            intersection_id=tls_id, current_phase_id=outgoing, current_phase_elapsed_s=0.0
        )
        return
    js.cabinet.command(recovery_phase)
    js.ctx = JunctionContext(
        intersection_id=tls_id, current_phase_id=recovery_phase, current_phase_elapsed_s=0.0
    )


def _apply_decision(
    js: _JunctionState, tls_id: str, plan: SignalPlan, step_length: float
) -> None:
    """Apply one commanded plan to the junction's bookkeeping: either
    extend the current green by one tick, or begin the yellow -> all-red
    -> next-green transition.

    Factored out of the main loop so the *contract between a plan and
    what the runner physically does with it* can be unit-tested without
    SUMO. That contract was previously implicit, and two places relied on
    it being something it was not:

    1. **A one-step plan's `green_s` is not time that elapses.** The loop
       used to advance `current_phase_elapsed_s` by `steps[0].green_s`.
       Every strategy returns `green_s == tick_s` for an extend, so this
       was invisible -- until `corridor/junction.py`'s ENTRY_HOLD branch
       returned `green_s = max(tick_s, remaining_ped_s)` (a *commitment*
       for the budget interlock to price, not a claim about the clock).
       One tick then inflated `elapsed` by the whole remaining pedestrian
       interval, and every later I3 check (`elapsed >= min_green`) was
       made against a green the junction had not actually shown. Only
       `step_length` of simulated time passes per tick, so only
       `step_length` is added.

    2. **A two-step plan whose first step asks for more green than one
       tick is a request to hold, not to clear.** `interlocks.
       min_green_satisfied` accepts a transition plan when
       `elapsed + steps[0].green_s >= min_green` -- i.e. it reads
       `steps[0].green_s` as "how much longer the current phase will be
       held before the yellow starts". The loop ignored that number and
       set the yellow immediately. `live/green_corridor.py`'s
       `preemption_plan` builds exactly such a plan (`green_s =
       min_green - elapsed`, documented as "a corridor can delay a green,
       never truncate one"), the interlock passed it, and the runner then
       truncated the green anyway -- an I3 violation that the plan-level
       checker structurally cannot see, on the emergency-preemption path.
       `tests/live/test_green_corridor.py::test_interlocks_reject_a_switch_
       that_would_truncate_min_green` asserts the plan is legal, which it
       is; nothing asserted the runner honoured it. Now it does: when
       `steps[0].green_s` exceeds one tick, the current phase is held this
       tick and the requester is asked again next tick, exactly as the
       plan said.

    Every strategy in `control/strategies/` already emits `green_s ==
    tick_s` on extends and either `tick_s` or `0.0` (faulted exit) as the
    first step of a transition, so their behaviour under this function is
    identical to before."""
    if len(plan.steps) == 1:
        js.ctx = replace(
            js.ctx,
            current_phase_id=plan.steps[0].phase_id,
            current_phase_elapsed_s=js.ctx.current_phase_elapsed_s + step_length,
        )
        return

    step0, step1 = plan.steps[0], plan.steps[1]
    if step0.green_s > step_length + 1e-9:
        # The plan promised the interlocks this green would run longer
        # before clearing. Keep that promise: hold, and let the requester
        # re-propose next tick with a larger `elapsed`.
        js.ctx = replace(
            js.ctx, current_phase_elapsed_s=js.ctx.current_phase_elapsed_s + step_length
        )
        return

    # A change from a ring phase into one of its alternates (the ring phase
    # with some protected streams stopped, `Tier0Config.alternates`) keeps
    # every green that continues and puts only the stopped streams through
    # the change interval -- when the cabinet confirms the change stops
    # protected links and does nothing else (`TraCICabinet.can_carry`).
    # Every other change, the way back included, is the ordinary one:
    # everything through yellow and all-red, so whatever starts, starts
    # into an empty junction.
    red_state = None
    a, b = step0.phase_id, step1.phase_id
    if js.cfg.alternates.get(b) == a and js.cabinet.can_carry(a, b):
        yellow_state, red_state = js.cabinet.carried_clearance_states(a, b)
    else:
        yellow_state = js.cabinet.yellow_state_for(a)
    js.cabinet.set_raw_state(yellow_state)
    js.transition = _Transition(
        outgoing_phase=step0.phase_id,
        incoming_phase=step1.phase_id,
        remaining_yellow_s=step0.yellow_s,
        remaining_all_red_s=step0.all_red_s,
        stage="yellow",
        red_state=red_state,
    )


def run_controlled_scenario(
    sumocfg_path: str,
    configs: Mapping[str, Tier0Config],
    strategy: StrategySource,
    *,
    seed: int | None = None,
    step_length: float = 1.0,
    max_steps: int | None = None,
    tripinfo_output: str | None = None,
    link_lanes: Mapping[str, Mapping[str, str]] | None = None,
    bus: RedisStreamsSyncBus | None = None,
    spillback_lane_ids: Iterable[str] | None = None,
    receiving_lanes: Mapping[str, Mapping[str, str]] | None = None,
    vtype_pcu: Mapping[str, float] | None = None,
    bottleneck_lane_speeds_mps: Mapping[str, float] | None = None,
    demand_memory: DemandMemory | None = None,
    calibration: OnlineCalibration | None = None,
    incident_injector: IncidentInjector | None = None,
    anomaly_graph: AnomalyGraph | None = None,
    anomaly_feature_sink: Callable[[int, float, list[list[float]]], None] | None = None,
    corridor: arbiter.CorridorPort | None = None,
    ev_reporter: Callable[[float], None] | None = None,
    extra_sumo_args: Iterable[str] | None = None,
    traci_retries: int | None = None,
    publish_traffic_state: bool = False,
    realtime_factor: float | None = None,
    on_tick: Callable[[int, float], None] | None = None,
    pace_realtime_factor: float | None = None,
    preempt_source: arbiter.PreemptSource | None = None,
    lane_chains: tuple[Mapping, Mapping] | None = None,
    lane_vias: Mapping[str, list[tuple[str, float]]] | None = None,
    detector_upstream: bool = True,
    internal_links: Mapping[str, Mapping[str, str]] | None = None,
) -> dict:
    """Run one full scenario with `strategy` governing every junction in
    `configs`. Returns run stats: step count, how many times the arbiter
    took a failsafe/degraded branch (should be 0 for a property-tested
    strategy -- the guide's own metric table calls interlock violations
    out as "must be exactly zero, always"), where, and (if requested)
    queue-spillback episodes.

    `link_lanes` (`scenarios/networks/vijayawada/link_lanes.link_to_lane_map()`'s
    output, keyed by tls_id) wires a live `ActuationDetector` per junction
    that has an entry, populating `JunctionContext.has_demand`/
    `wait_times_s` from real lane occupancy every tick -- required for any
    demand-aware strategy (`semi_actuated`). Left `None` (the default),
    every junction's context keeps those fields at their empty defaults,
    exactly fixed_time's/webster's original demand-blind behaviour --
    this parameter is additive, not a behaviour change for either.

    `bus`, if given, gets every tick's arbiter decision published as a
    real `SignalChanged`/`SignalFaulted` event (see module docstring).
    `spillback_lane_ids`, if given, wires a `SpillbackTracker`
    (`signal_controller/spillback.py`) over exactly those lanes -- pass
    every controlled junction's approach lanes flattened
    (`link_lanes.link_to_lane_map()`'s values, not its per-junction keys)
    to count queue-spillback episodes [build guide §8.1] over the whole
    run. Both default to `None`/off, so existing callers (every M3 smoke
    script, `scripts/bench.py`) are unaffected.

    `receiving_lanes` (`link_lanes.link_to_receiving_lane_map()`'s
    output) and `vtype_pcu` (`queue_state.load_vtype_pcu()`'s output)
    together wire a live `QueueStateSampler` per junction that has an
    entry in *both* `link_lanes` and `receiving_lanes`, populating
    `JunctionContext.queue_pcu`/`receiving_occupancy` from real TraCI
    state every tick -- required for `camp.propose` (M4) to see anything
    other than empty defaults. All three of `link_lanes`/
    `receiving_lanes`/`vtype_pcu` default to `None`, so this is additive
    for every M2/M3 caller exactly like `link_lanes` alone already was.

    `bottleneck_lane_speeds_mps`, if given, is applied once right after
    TraCI starts via `traci.lane.setMaxSpeed` -- a synthetic, deliberately
    engineered downstream capacity reduction for the M4 gate's own
    required theta_m ablation (build guide §7: "with and without the
    theta_m blocking term ... under a downstream bottleneck"). This is
    infrastructure for that one experiment, not a feature any other
    caller needs: raising demand alone does not reliably saturate any of
    this corridor's 7 junctions' own receiving lanes (see PROGRESS.md's
    M4 section), so the ablation needs a lane whose capacity is capped on
    purpose, independent of how much demand a scenario happens to carry.
    Left `None` (the default), every caller's behaviour is unchanged.

    `demand_memory` (M5), if given, has every tick's *live* per-movement
    queue and inbound-platoon reading recorded into it, and `end_run()`
    called once the scenario finishes -- so one call of this function is
    one "day" folded into the across-run profile
    (`control/memory.py` explains why a seed is a legitimate day). Only
    recorded for junctions whose strategy is time-aware, since a strategy
    that cannot read the profile has no use for one and would only be
    paying the sampling cost. Note this is orthogonal to whether the
    strategy *uses* memory: a training run records without blending, and
    an evaluation run against a frozen profile blends without recording,
    depending on what the caller passes where.

    `incident_injector` (M6), if given, has `tick(step)` called once per
    simulation step -- right after the step advances, before any sampler
    reads -- and `finalize(step)` called once the loop ends, so a scheduled
    stall / lane-block is applied, maintained and cleanly reversed inside the
    run, with the exact tick window recorded for
    `scripts/m6_incident_injection_gate.py` to score recall and detection
    latency against. Left `None` (the default), no incident is injected and
    every existing caller is unaffected -- the same additive pattern as every
    parameter above it.

    `anomaly_graph` + `anomaly_feature_sink` (M6), given together, wire a
    `LinkFeatureSampler` over the anomaly graph and call
    `anomaly_feature_sink(step, sim_time, feature_matrix)` once per tick,
    after every junction's decision, where `feature_matrix` is the
    `[num_nodes][N_FEATURES]` list for that tick. This is the one stream both
    `scripts/m6_record_features.py` (recording normal traffic to train on) and
    the live detector (Phase 5) consume. Either left `None` and no feature
    sampling happens.

    `corridor` (M7), if given, wires the Green Corridor Engine
    (`control/corridor/`, the benchmarked path) as one of the two rung-3
    requesters `arbiter.tick` accepts (see its own docstring for why there
    are two). Two things happen here that the arbiter cannot do for
    itself, because both are about the corridor rather than about one
    junction:

    - `begin_tick` is called once per simulation step, before any
      junction is arbitrated, so "which vehicle holds which junction" is
      decided from one consistent view. Deciding it per junction as each
      is reached is exactly how D11 happens -- neighbouring junctions
      granting conflicting emergency vehicles, each correct on its own
      information.
    - `JunctionContext.preempt_seconds_last_hour` is populated from the
      engine's rolling-hour ledger. That field has existed since M2 and
      has been zero in every run ever made, so `interlocks.
      preempt_budget_ok` -- written specifically for this requester --
      was correct and structurally unable to fire. It fires now.

    `ev_reporter` is called once per step with the simulation time,
    before `begin_tick`, and is how emergency-vehicle observations reach
    the engine. A callback rather than something the engine does itself,
    so this function stays ignorant of how vehicles are detected: the
    benchmark's TraCI-derived reporter and a real detection feed are the
    same shape from here.

    `preempt_source` is the *other* rung-3 requester: a plain callable
    (`arbiter.PreemptSource`) rather than a `CorridorPort`, wired by the
    live command-driven service (`sim_service.live`) instead of the
    benchmark path -- the green corridor's
    `CorridorController.preemption_plan` is what it passes here. No
    caller wires both `corridor` and `preempt_source` at once today. Left
    `None`, that rung-3 path is absent exactly as before. A commanded
    preemption from either is `mode == "corridor_preemption"` (a success
    branch, not a fault); an interlock-rejected `preempt_source` proposal
    shows up in `Decision.notes` while the junction keeps running its
    normal strategy (a rejected `corridor` proposal instead raises a
    `SignalFaulted` event -- see `arbiter.tick`'s docstring for why the two
    requesters record a denial differently).

    `publish_traffic_state`, given together with `bus`, additionally
    publishes `VehiclePositionUpdated`/`ApproachState` every tick --
    `traci_loop.publish_traffic_state`, the same function and the same
    event shapes `traci_loop.run` (the M1-only, no-control live loop) has
    always published. This is what lets both `sim_service/main.py`'s
    A-CA-MP demo and the live command-driven service call this function
    instead of `traci_loop.run` and keep the live map working while
    *also* getting real signal control, `bus`'s
    `SignalChanged`/`SignalFaulted` events, and (via `anomaly_feature_sink`)
    live incident detection -- one stepping loop owning the TraCI
    connection, not two competing for it. `False` by default because every
    gate/bench script publishes tripinfo-scored KPIs instead and has no use
    for a live map. `realtime_factor` paces the loop the same way
    `traci_loop.run`'s does (1.0 = roughly real time); `None` (the default)
    runs as fast as TraCI allows, which is what every gate/bench script
    wants and a live demo does not. `pace_realtime_factor` is the live
    service's own equivalent pacing knob (see below) -- callers use one or
    the other, never both.

    `lane_chains` (`itms_domain.lane_chains`' `(upstream, downstream)`),
    if given, lets each `QueueStateSampler` measure a road SUMO has split
    into several edges as the whole road rather than the last edge before
    the stop line (see `queue_state`'s module docstring). `None` (the
    default) and a network without such splits behave exactly as before.

    `internal_links` (`strategies.hol.internal_links(net)`), if given, lets
    each `QueueStateSampler` report head-of-line blocking
    (`JunctionContext.blocked_by`): a lane whose front vehicle stands behind a
    turner waiting inside the junction. Only `hol_camp.HolAwareCamp` reads
    it; left `None`, the field stays empty and nothing else changes.

    `on_tick(step, sim_time)`, if given, is called once per step after any
    injector tick and before this tick's sampling -- the live service
    drains its `commands.*` topic and applies operator actions
    (anomaly create/clear, emergency vehicle, green corridor) there. Left
    `None` for every batch caller (gates, smoke scripts), so this is
    additive exactly like every parameter above it.
    """
    _ensure_sumo_home()
    sumo_binary = _resolve_sumo_binary()
    args = [
        sumo_binary,
        "-c",
        sumocfg_path,
        "--step-length",
        str(step_length),
        "--no-step-log",
        "true",
        "--time-to-teleport",
        "300",
    ]
    if seed is not None:
        args += ["--seed", str(seed)]
    else:
        args += ["--random"]
    if tripinfo_output is not None:
        args += ["--tripinfo-output", tripinfo_output]
    if extra_sumo_args is not None:
        # Appended last so a caller can override any default above --
        # SUMO takes the final occurrence of a repeated option. Exists for
        # `scripts/m7_demo.py`, which needs sumo-gui's `--start`,
        # `--delay` and `--gui-settings-file`; every other caller leaves
        # it None and gets exactly the argument list it always had.
        args += list(extra_sumo_args)

    # `traci.start` defaults to 60 retries, one per second, and its
    # failure message names only the port it could not reach -- the
    # simulator's own complaint is discarded. That is a reasonable
    # default for a batch run on a machine where SUMO is known good, and
    # a bad one for an interactive session where the binary may simply
    # not start: a minute of "Connection refused" says nothing about why.
    # Callers that would rather fail fast pass a smaller count.
    traci.start(args, **({} if traci_retries is None else {"numRetries": traci_retries}))
    if bottleneck_lane_speeds_mps is not None:
        for lane_id, speed_mps in bottleneck_lane_speeds_mps.items():
            traci.lane.setMaxSpeed(lane_id, speed_mps)
    junctions: dict[str, _JunctionState] = {}
    # One shared lane cache for the whole corridor: every sampler on a
    # given tick reads each lane at most once between them. See
    # `lane_cache.LaneCache` for the profile that made this necessary --
    # 972 TraCI round-trips per simulation step, 90% of run wall-clock.
    lane_cache = LaneCache(vtype_pcu or {})
    # M6 feature stream: built only when a caller wants the per-link anomaly
    # feature matrix recorded/scored, and only if `vtype_pcu` is available for
    # the PCU terms. Shares `lane_cache` so it adds almost no TraCI traffic.
    feature_sampler: LinkFeatureSampler | None = None
    if anomaly_graph is not None and anomaly_feature_sink is not None and vtype_pcu:
        feature_sampler = LinkFeatureSampler(
            anomaly_graph, configs, vtype_pcu, lane_cache=lane_cache
        )
    spillback = SpillbackTracker(spillback_lane_ids) if spillback_lane_ids is not None else None
    try:
        for tls_id, cfg in configs.items():
            # What makes an alternate as safe as its ring phase is a property
            # of the configuration (`Tier0Config.validate`); a junction whose
            # alternates do not have it is not run.
            broken = cfg.alternate_problems()
            if broken:
                raise ValueError(f"{tls_id}: {'; '.join(broken)}")
            live_state = traci.trafficlight.getRedYellowGreenState(tls_id)
            cabinet = TraCICabinet(tls_id, cfg.phases, state_len=len(live_state))
            # A defined start, not an assumed one (same spirit as C4's forced
            # resume, M2): if the live state doesn't match one of our known
            # green phases (e.g. SUMO booted mid-yellow), just start the ring
            # at its first phase rather than guessing.
            phase_id = cabinet._phase_id_for_state(live_state) or cfg.ring_order[0]  # noqa: SLF001
            cabinet.command(phase_id)
            ctx = JunctionContext(
                intersection_id=tls_id, current_phase_id=phase_id, current_phase_elapsed_s=0.0
            )
            detector = None
            if link_lanes is not None and tls_id in link_lanes:
                # with `lane_vias`: a split road is watched whole -- its upstream
                # lanes and the internal lanes between them, not only its last piece
                # (`detector_upstream=False`: the internal lanes only -- the road
                # before the split still counts toward the queue, not as a call)
                same_road = None
                if lane_vias is not None:
                    up = lane_chains[0] if lane_chains else {}
                    same_road = {
                        lane: [*((x for x, _, _ in up.get(lane, ())) if detector_upstream else ()),
                               *(x for x, _ in lane_vias.get(lane, ()))]
                        for lane in set(link_lanes[tls_id].values())
                    }
                detector = ActuationDetector(link_lanes[tls_id], extra_lanes=same_road)
            queue_sampler = None
            if (
                link_lanes is not None
                and tls_id in link_lanes
                and receiving_lanes is not None
                and tls_id in receiving_lanes
                and vtype_pcu is not None
            ):
                queue_sampler = QueueStateSampler(
                    link_lanes[tls_id], receiving_lanes[tls_id], vtype_pcu,
                    lane_cache=lane_cache,
                    upstream=lane_chains[0] if lane_chains else None,
                    downstream=lane_chains[1] if lane_chains else None,
                    internal_links=internal_links.get(tls_id) if internal_links else None,
                    vias=lane_vias,
                )
            discharge = None
            if calibration is not None and link_lanes is not None and tls_id in link_lanes:
                discharge = DischargeObserver(
                    link_lanes[tls_id], vtype_pcu or {}, lane_cache=lane_cache
                )
            junctions[tls_id] = _JunctionState(
                cfg=cfg,
                cabinet=cabinet,
                ctx=ctx,
                detector=detector,
                queue_sampler=queue_sampler,
                discharge=discharge,
            )

        step = 0
        # The longest wait against its bound, measured where the kernel cannot
        # (`ActuationDetector.longest_wait_s`): the worst excess over
        # `max_wait_s` in seconds (negative: never reached) and the number of
        # junction-ticks at which some call was past it.
        longest_wait_excess_s = -math.inf
        waits_over_bound = 0
        # Where and after which phases a wait passed its bound: one entry per
        # (junction, waiting call) episode, the first 30 of a run, with the
        # junction's last phases and when each began.
        wait_overruns: list[dict] = []
        phase_log: dict[str, list[tuple[float, str]]] = {}
        fault_events: list[tuple[str, int, str]] = []
        # Gridlock measures, reported beside delay: vehicles SUMO removed from
        # a jam ("teleports" -- they flatter the delay of the arm that jams)
        # and vehicles still in the network when the run-length cap ends it.
        teleports = 0
        unfinished = 0
        # Only ever populated when publish_traffic_state is set -- see that
        # parameter's docstring. A vehicle's vType never changes over its
        # life, so this is one getTypeID call per vehicle for the whole run.
        vtype_cache: dict[str, str] = {}

        pace_budget_s = (
            step_length / pace_realtime_factor
            if pace_realtime_factor and pace_realtime_factor > 0
            else 0.0
        )

        while traci.simulation.getMinExpectedNumber() > 0:
            tick_start = time.monotonic()
            traci.simulationStep()
            step += 1
            teleports += traci.simulation.getStartingTeleportNumber()
            # Invalidate the per-tick memo exactly once, right after the
            # simulation advances and before any sampler reads.
            lane_cache.advance(float(step))

            if incident_injector is not None:
                # Applied right after the step advances and before any
                # sampler/detector reads, so an injected stall/lane-block is
                # visible to the same tick's feature vector -- the injection
                # tick and the detection tick share one clock, which is what
                # makes the M6 gate's latency figure exact.
                incident_injector.tick(step)

            if on_tick is not None:
                # The live command hook: the command-driven service drains its
                # `commands.*` topic here and applies operator actions
                # (anomaly create/clear, emergency vehicle, green corridor)
                # against the live TraCI connection, before this tick's
                # sampling and before the state is published downstream. Left
                # `None` for every batch caller (gates, smoke scripts), so
                # this is additive exactly like every parameter above it.
                on_tick(step, traci.simulation.getTime())

            if spillback is not None:
                spillback.sample()

            # `ev_reporter` runs whether or not a corridor engine is
            # wired, and that independence is load-bearing for the
            # benchmark rather than incidental: the control arm has to
            # put the *same* emergency vehicles into the *same* traffic
            # and simply not preempt for them. Gating the reporter on
            # `corridor is not None`, as this first did, silently gave
            # the no-preemption arm no emergency vehicles at all and an
            # emergency travel time of zero -- a comparison against
            # nothing, reported as if it were a comparison against
            # something.
            if ev_reporter is not None:
                ev_reporter(traci.simulation.getTime())
            if corridor is not None:
                corridor.begin_tick(traci.simulation.getTime())

            for tls_id, js in junctions.items():
                if js.transition is not None:
                    _advance_transition(js, step_length)
                    continue

                junction_strategy = strategy[tls_id] if isinstance(strategy, Mapping) else strategy
                # A strategy that owns state advertises it by exposing
                # `set_sim_time` (M5's `acamp.AdaptiveCamp`). Duck-typed
                # rather than gated on a new `run_controlled_scenario`
                # parameter, so a caller mixing a stateful strategy at one
                # junction with a pure one at another -- which the
                # per-junction `Mapping` form already allows -- cannot get
                # the pairing wrong.
                time_aware = hasattr(junction_strategy, "set_sim_time")
                if time_aware:
                    junction_strategy.set_sim_time(  # type: ignore[attr-defined]
                        traci.simulation.getTime()
                    )

                if js.detector is not None or js.queue_sampler is not None:
                    has_demand: Mapping[str, bool] = {}
                    wait_times_s: Mapping[str, float] = {}
                    if js.detector is not None:
                        waited_s = js.detector.longest_wait_s(traci.simulation.getTime())
                        longest_wait_excess_s = max(longest_wait_excess_s,
                                                    waited_s - js.cfg.max_wait_s)
                        waits_over_bound += waited_s > js.cfg.max_wait_s
                        log = phase_log.setdefault(tls_id, [])
                        if not log or log[-1][1] != js.ctx.current_phase_id:
                            log.append((traci.simulation.getTime(), js.ctx.current_phase_id))
                            del log[:-8]
                        if waited_s > js.cfg.max_wait_s:
                            waiter = getattr(js.detector, "longest_waiter", None)
                            who = waiter(traci.simulation.getTime())[0] if waiter else None
                            last = wait_overruns[-1] if wait_overruns else None
                            if last and last["tls"] == tls_id and last["who"] == who:
                                last["excess_s"] = round(waited_s - js.cfg.max_wait_s, 1)
                            elif len(wait_overruns) < 30:
                                wait_overruns.append({
                                    "tls": tls_id, "who": who,
                                    "t": traci.simulation.getTime(),
                                    "excess_s": round(waited_s - js.cfg.max_wait_s, 1),
                                    "phases": list(log)})
                        served_movements = js.cfg.phases[js.ctx.current_phase_id].shown_movements
                        has_demand, wait_times_s = js.detector.sample(
                            traci.simulation.getTime(), served_movements
                        )
                    queue_pcu: Mapping[str, float] = {}
                    receiving_occupancy: Mapping[str, float] = {}
                    receiving_queue_pcu: Mapping[str, float] = {}
                    approaching_pcu: Mapping[str, float] = {}
                    blocked_by: Mapping[str, str] = {}
                    if js.queue_sampler is not None:
                        if time_aware:
                            # Strictly more TraCI work per tick -- only paid
                            # for a strategy that reads the extra fields, so
                            # M4's own gate arm is unaffected in both
                            # behaviour and runtime.
                            sample = js.queue_sampler.sample_extended()
                            queue_pcu = sample.queue_pcu
                            receiving_occupancy = sample.receiving_occupancy
                            receiving_queue_pcu = sample.receiving_queue_pcu
                            approaching_pcu = sample.approaching_pcu
                            blocked_by = sample.blocked_by
                        else:
                            queue_pcu, receiving_occupancy = js.queue_sampler.sample()
                    js.ctx = JunctionContext(
                        intersection_id=js.ctx.intersection_id,
                        current_phase_id=js.ctx.current_phase_id,
                        current_phase_elapsed_s=js.ctx.current_phase_elapsed_s,
                        has_demand=has_demand,
                        wait_times_s=wait_times_s,
                        queue_pcu=queue_pcu,
                        receiving_occupancy=receiving_occupancy,
                        receiving_queue_pcu=receiving_queue_pcu,
                        approaching_pcu=approaching_pcu,
                        blocked_by=blocked_by,
                        preempt_seconds_last_hour=js.ctx.preempt_seconds_last_hour,
                    )
                    if js.discharge is not None and calibration is not None:
                        # Driven from the *live* sample, and only for a
                        # settled junction -- a mid-transition junction is
                        # skipped by the `continue` above, which is correct:
                        # nothing discharges during yellow or all-red, so
                        # those seconds belong to neither green's window.
                        served = js.cfg.phases[js.ctx.current_phase_id].shown_movements
                        for movement, pcu, eff_green, remained in js.discharge.tick(
                            served, step_length, approaching_pcu
                        ):
                            calibration.observe_green(
                                tls_id,
                                movement,
                                baseline_sat_flow=js.cfg.sat_flow_pcu_s.get(movement, 0.5),
                                discharged_pcu=pcu,
                                effective_green_s=eff_green,
                                queue_remained=remained,
                            )
                        for movement, predicted, arrived in js.discharge.expired_cohorts():
                            calibration.observe_arrivals(
                                tls_id,
                                movement,
                                baseline_sat_flow=js.cfg.sat_flow_pcu_s.get(movement, 0.5),
                                predicted_pcu=predicted,
                                arrived_pcu=arrived,
                            )

                    if demand_memory is not None and time_aware:
                        # Recorded from the *live* sample, before any
                        # blending the strategy may apply -- a memory fed
                        # its own blended output would converge on itself
                        # rather than on what the corridor actually does.
                        demand_memory.observe_tick(
                            tls_id, traci.simulation.getTime(), queue_pcu, approaching_pcu
                        )

                if corridor is not None:
                    # Set on the context the interlocks will actually be
                    # checked against, immediately before the check, so
                    # the budget the plan is measured against is the one
                    # that is true at the moment of the decision. Written
                    # via `replace` rather than by threading another
                    # argument through both context-construction paths
                    # above -- there are two of them (sampled and
                    # unsampled) and only one is on the M4/M5 hot path.
                    js.ctx = replace(
                        js.ctx,
                        preempt_seconds_last_hour=corridor.preempt_seconds_last_hour(
                            tls_id, traci.simulation.getTime()
                        ),
                    )

                decision = arbiter.tick(
                    js.cfg, js.ctx, js.cabinet,
                    strategy=junction_strategy, corridor=corridor, preempt=preempt_source,
                )
                if bus is not None:
                    _publish_decision_events(bus, decision)
                for note in decision.notes:
                    log.info("junction %s at step %d: %s", tls_id, step, note)
                if decision.mode not in arbiter.SUCCESS_MODES:
                    fault_events.append((tls_id, step, decision.mode))
                    log.warning("junction %s took %s at step %d", tls_id, decision.mode, step)
                    _recover_from_fault(js, tls_id, decision.violated_movements)
                    continue
                assert decision.plan is not None  # a commanding mode always carries a plan
                _apply_decision(js, tls_id, decision.plan, step_length)

            if feature_sampler is not None:
                # Sampled after every junction's decision for the tick, so the
                # phase state the detector sees is the one now commanded --
                # exactly what a live consumer of the signal.changed stream
                # would have. `assert` narrows the Optional for the type
                # checker; the outer guard already established it is not None.
                assert anomaly_feature_sink is not None
                sim_time = traci.simulation.getTime()
                phase_by_tls = {
                    tls_id: (js.ctx.current_phase_id, js.ctx.current_phase_elapsed_s)
                    for tls_id, js in junctions.items()
                }
                anomaly_feature_sink(
                    step, sim_time, feature_sampler.sample(sim_time, phase_by_tls)
                )

            if publish_traffic_state and bus is not None:
                # Emit the M1 stream (VehiclePositionUpdated / ApproachState)
                # so this controlled loop is a drop-in producer for the
                # api-service fan-out -- byte-for-byte the same events
                # `adapters/sumo/traci_loop.run` publishes. Only paid when a
                # caller explicitly asks (the live service and the A-CA-MP
                # demo do; no gate does).
                _publish_traffic_state(bus, step_length=step_length, vtype_cache=vtype_cache)

            if realtime_factor is not None:
                # Same pacing traci_loop.run uses: sleep off whatever's left
                # of this tick's wall-clock budget, or log a dropped tick if
                # the tick's own work (control decisions, publishing) already
                # ran over it. No-op cost when unset (every gate/bench
                # script), which is why this isn't the default.
                target_wall_s = step_length / realtime_factor if realtime_factor else 0.0
                elapsed = time.monotonic() - tick_start
                if elapsed > target_wall_s:
                    log.warning(
                        "step %d took %.3fs, budget was %.3fs at %.1fx real time -- "
                        "dropped tick",
                        step,
                        elapsed,
                        target_wall_s,
                        realtime_factor,
                    )
                elif target_wall_s > 0:
                    time.sleep(target_wall_s - elapsed)
            elif pace_budget_s:
                # Live-service pacing only: hold each tick to roughly
                # step_length / pace_realtime_factor seconds of wall clock so
                # the operator watches it unfold. A tick that already ran over
                # budget is simply not slept on (never sped up). No batch
                # caller sets this, so gate/smoke throughput is unchanged.
                slack = pace_budget_s - (time.monotonic() - tick_start)
                if slack > 0:
                    time.sleep(slack)

            if max_steps is not None and step >= max_steps:
                unfinished = traci.simulation.getMinExpectedNumber()
                break

        if incident_injector is not None:
            # Inside the `try`, before `traci.close()`: `finalize` restores
            # any lane still throttled and releases any vehicle still frozen,
            # which needs the TraCI connection live. A run that raised mid-
            # loop skips this and closes with SUMO about to exit anyway.
            incident_injector.finalize(step)
    finally:
        traci.close()

    if demand_memory is not None:
        # After `traci.close()`, deliberately: committing the run's bins
        # into the across-run EWMA is bookkeeping on data already
        # gathered, and doing it inside the `try` would skip it on the
        # very runs (an exception mid-scenario) whose partial data is
        # least trustworthy to fold in anyway.
        demand_memory.end_run()

    interlock_violations = sum(
        1 for _, _, mode in fault_events if mode == "failsafe_interlock_rejected"
    )
    return {
        "steps": step,
        "lane_cache": lane_cache.stats(),
        "interlock_violations": interlock_violations,
        "fault_events": fault_events,
        "spillback_events": spillback.episode_count if spillback is not None else None,
        "teleports": teleports,
        "longest_wait_excess_s": (round(longest_wait_excess_s, 1)
                                  if math.isfinite(longest_wait_excess_s) else None),
        "waits_over_bound": waits_over_bound,
        "wait_overruns": wait_overruns,
        "unfinished_at_cap": unfinished,
        "corridor": corridor.stats() if corridor is not None else None,
    }


def _advance_transition(js: _JunctionState, step_length: float) -> None:
    t = js.transition
    assert t is not None
    if t.stage == "yellow":
        t.remaining_yellow_s -= step_length
        if t.remaining_yellow_s <= 1e-9:
            js.cabinet.set_raw_state(t.red_state or js.cabinet.all_red_state())
            t.stage = "all_red"
    elif t.stage == "all_red":
        t.remaining_all_red_s -= step_length
        if t.remaining_all_red_s <= 1e-9:
            js.cabinet.command(t.incoming_phase)
            js.ctx = JunctionContext(
                intersection_id=js.ctx.intersection_id,
                current_phase_id=t.incoming_phase,
                current_phase_elapsed_s=0.0,
            )
            js.transition = None

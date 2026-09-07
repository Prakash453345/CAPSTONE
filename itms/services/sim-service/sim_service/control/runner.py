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
import os
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import traci
from itms_common.bus import RedisStreamsSyncBus
from itms_common.events import encode_envelope
from itms_domain import JunctionContext, SignalPlan, Tier0Config

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
    """`decision.mode == "fixed_time"` is arbiter.tick()'s only success
    branch (see its own docstring's priority list) -- every other mode is
    a fault/degraded branch. `_changed_event`/`_faulted_event` (private to
    arbiter.py) already build these dicts to match
    `contracts/events/signal_changed.avsc` / `signal_faulted.avsc` field-
    for-field, so this is a straight encode-and-publish, not a reshape."""
    event_type = "SignalChanged" if decision.mode == "fixed_time" else "SignalFaulted"
    topic = _SIGNAL_CHANGED_TOPIC if event_type == "SignalChanged" else _SIGNAL_FAULTED_TOPIC
    for payload in decision.events:
        raw = encode_envelope(
            event_type=event_type,
            source="sim-service",
            payload=payload,
            partition_key=payload["intersection_id"],
        )
        bus.publish(topic, raw)

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
    (every other fault mode, or a violation naming no specific movement)."""
    recovery_phase = js.cfg.ring_order[0]
    if violated_movements:
        recovery_phase = next(
            (
                p
                for p in js.cfg.ring_order
                if js.cfg.phases[p].green_movements & violated_movements
            ),
            recovery_phase,
        )
    js.cabinet.command(recovery_phase)
    js.ctx = JunctionContext(
        intersection_id=tls_id, current_phase_id=recovery_phase, current_phase_elapsed_s=0.0
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

    traci.start(args)
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
                detector = ActuationDetector(link_lanes[tls_id])
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
        fault_events: list[tuple[str, int, str]] = []

        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step += 1
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

            if spillback is not None:
                spillback.sample()

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
                    junction_strategy.set_sim_time(traci.simulation.getTime())

                if js.detector is not None or js.queue_sampler is not None:
                    has_demand: Mapping[str, bool] = {}
                    wait_times_s: Mapping[str, float] = {}
                    if js.detector is not None:
                        served_movements = js.cfg.phases[js.ctx.current_phase_id].green_movements
                        has_demand, wait_times_s = js.detector.sample(
                            traci.simulation.getTime(), served_movements
                        )
                    queue_pcu: Mapping[str, float] = {}
                    receiving_occupancy: Mapping[str, float] = {}
                    receiving_queue_pcu: Mapping[str, float] = {}
                    approaching_pcu: Mapping[str, float] = {}
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
                    )
                    if js.discharge is not None and calibration is not None:
                        # Driven from the *live* sample, and only for a
                        # settled junction -- a mid-transition junction is
                        # skipped by the `continue` above, which is correct:
                        # nothing discharges during yellow or all-red, so
                        # those seconds belong to neither green's window.
                        served = js.cfg.phases[js.ctx.current_phase_id].green_movements
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

                decision = arbiter.tick(js.cfg, js.ctx, js.cabinet, strategy=junction_strategy)
                if bus is not None:
                    _publish_decision_events(bus, decision)
                if decision.mode not in ("fixed_time",):
                    fault_events.append((tls_id, step, decision.mode))
                    log.warning("junction %s took %s at step %d", tls_id, decision.mode, step)
                    _recover_from_fault(js, tls_id, decision.violated_movements)
                    continue
                assert decision.plan is not None  # "fixed_time" mode always carries a plan

                if len(decision.plan.steps) == 1:
                    step0 = decision.plan.steps[0]
                    js.ctx = JunctionContext(
                        intersection_id=tls_id,
                        current_phase_id=step0.phase_id,
                        current_phase_elapsed_s=js.ctx.current_phase_elapsed_s + step0.green_s,
                    )
                else:
                    step0, step1 = decision.plan.steps
                    js.cabinet.set_raw_state(js.cabinet.yellow_state_for(step0.phase_id))
                    js.transition = _Transition(
                        outgoing_phase=step0.phase_id,
                        incoming_phase=step1.phase_id,
                        remaining_yellow_s=step0.yellow_s,
                        remaining_all_red_s=step0.all_red_s,
                        stage="yellow",
                    )

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

            if max_steps is not None and step >= max_steps:
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
    }


def _advance_transition(js: _JunctionState, step_length: float) -> None:
    t = js.transition
    assert t is not None
    if t.stage == "yellow":
        t.remaining_yellow_s -= step_length
        if t.remaining_yellow_s <= 1e-9:
            js.cabinet.set_raw_state(js.cabinet.all_red_state())
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

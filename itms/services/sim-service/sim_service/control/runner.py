"""Drives a real SUMO scenario with the arbitration ladder actually
governing every signal-controlled junction, via `TraCICabinet` -- the
piece `signal_controller/cabinet.py` and `traci_cabinet.py` both flagged
as M3's job. No event bus involved: this is for benchmarking/offline runs
(`bench/`), not the live dashboard (`sim_service/main.py`'s TraCI loop,
M1, is unaffected and still what backs `make dev`).

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import traci
from itms_domain import JunctionContext, SignalPlan, Tier0Config

from sim_service.signal_controller import arbiter
from sim_service.signal_controller.detectors import ActuationDetector
from sim_service.signal_controller.traci_cabinet import TraCICabinet

log = logging.getLogger("sim-service.control.runner")

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
) -> dict:
    """Run one full scenario with `strategy` governing every junction in
    `configs`. Returns run stats: step count, how many times the arbiter
    took a failsafe/degraded branch (should be 0 for a property-tested
    strategy -- the guide's own metric table calls interlock violations
    out as "must be exactly zero, always"), and where.

    `link_lanes` (`scenarios/networks/vijayawada/link_lanes.link_to_lane_map()`'s
    output, keyed by tls_id) wires a live `ActuationDetector` per junction
    that has an entry, populating `JunctionContext.has_demand`/
    `wait_times_s` from real lane occupancy every tick -- required for any
    demand-aware strategy (`semi_actuated`). Left `None` (the default),
    every junction's context keeps those fields at their empty defaults,
    exactly fixed_time's/webster's original demand-blind behaviour --
    this parameter is additive, not a behaviour change for either.
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
    junctions: dict[str, _JunctionState] = {}
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
            junctions[tls_id] = _JunctionState(
                cfg=cfg, cabinet=cabinet, ctx=ctx, detector=detector
            )

        step = 0
        fault_events: list[tuple[str, int, str]] = []

        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step += 1

            for tls_id, js in junctions.items():
                if js.transition is not None:
                    _advance_transition(js, step_length)
                    continue

                if js.detector is not None:
                    served_movements = js.cfg.phases[js.ctx.current_phase_id].green_movements
                    has_demand, wait_times_s = js.detector.sample(
                        traci.simulation.getTime(), served_movements
                    )
                    js.ctx = JunctionContext(
                        intersection_id=js.ctx.intersection_id,
                        current_phase_id=js.ctx.current_phase_id,
                        current_phase_elapsed_s=js.ctx.current_phase_elapsed_s,
                        has_demand=has_demand,
                        wait_times_s=wait_times_s,
                    )

                junction_strategy = strategy[tls_id] if isinstance(strategy, Mapping) else strategy
                decision = arbiter.tick(js.cfg, js.ctx, js.cabinet, strategy=junction_strategy)
                if decision.mode not in ("fixed_time",):
                    fault_events.append((tls_id, step, decision.mode))
                    log.warning("junction %s took %s at step %d", tls_id, decision.mode, step)
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

            if max_steps is not None and step >= max_steps:
                break
    finally:
        traci.close()

    interlock_violations = sum(
        1 for _, _, mode in fault_events if mode == "failsafe_interlock_rejected"
    )
    return {
        "steps": step,
        "interlock_violations": interlock_violations,
        "fault_events": fault_events,
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

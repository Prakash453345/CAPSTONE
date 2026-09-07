"""SUMO adapter -- the real traffic-state source for M1+, replacing the M0
heartbeat placeholder (sim_service.heartbeat, kept only for M0 regression).
[ARCH] service 17 (Simulation Adapter) and, in simplified form, service 3
(Traffic Service) -- see contracts/events/approach_state.avsc's `doc` field
for exactly what's simplified in this milestone and why.

Deliberately synchronous. traci.simulationStep() blocks on subprocess IPC to
the SUMO process each tick, so there's no concurrency to gain from asyncio
here -- the loop publishes through RedisStreamsSyncBus (same wire format,
same contracts/events schemas, same ADR-003 bus abstraction as the async
RedisStreamsBus api-service consumes with; only the transport call differs,
because the producer's concurrency need is zero).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from pathlib import Path

import traci
from itms_common.bus import RedisStreamsSyncBus
from itms_common.events import encode_envelope

log = logging.getLogger("sim-service.traci_loop")

_INTERNAL_EDGE_PREFIX = ":"
_VEHICLE_TOPIC = "traffic.vehicle-positions"
_APPROACH_TOPIC = "traffic.updated"


def _ensure_sumo_home() -> None:
    """SUMO's own binary wants SUMO_HOME on the environment to find its data/
    typemap files at runtime. traci itself doesn't need it (it's a standalone
    pip package now), but we set it defensively either way."""
    if os.environ.get("SUMO_HOME"):
        return
    try:
        import sumo  # the pip-installed 'eclipse-sumo' package, if present

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
    # pip installs put the sumo binary next to the interpreter (venv/bin/sumo)
    candidate = Path(sys.executable).parent / "sumo"
    if candidate.exists():
        return str(candidate)
    raise RuntimeError(
        "could not find the 'sumo' binary -- set SUMO_BINARY explicitly, or "
        "make sure it's on PATH"
    )


def run(
    sumocfg_path: str,
    bus: RedisStreamsSyncBus,
    *,
    step_length: float = 1.0,
    realtime_factor: float = 1.0,
    max_steps: int | None = None,
) -> dict:
    """Run the SUMO simulation described by sumocfg_path, publishing
    VehiclePositionUpdated (per vehicle) and ApproachState (per edge) once
    per simulated second [build guide M1 gate: 1 Hz, no dropped ticks at 2x
    real time].

    realtime_factor paces the loop for a watchable demo (1.0 = roughly
    real-time, matching step_length). It does not cap throughput -- pass a
    large value (or see max_steps) to run as fast as possible for tests.
    A "dropped tick" is logged whenever a step's actual processing time
    exceeds the wall-clock budget realtime_factor implies; that's the
    directly measurable form of the gate's "no dropped ticks" requirement.

    Returns a small summary dict (steps, dropped_ticks) for tests/logging.
    """
    _ensure_sumo_home()

    sumo_binary = _resolve_sumo_binary()
    log.info("starting SUMO: %s -c %s", sumo_binary, sumocfg_path)
    traci.start(
        [
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
    )

    target_wall_s = step_length / realtime_factor if realtime_factor else 0.0
    step = 0
    dropped_ticks = 0

    # A vehicle's vType never changes over its life, so `getTypeID` is looked
    # up once per vehicle and reused every tick after -- the same reasoning
    # (and the measured cost) that `signal_controller/lane_cache.py` documents
    # for the identical call on the control path.
    vtype_cache: dict[str, str] = {}

    def vtype_of(veh_id: str) -> str:
        cached = vtype_cache.get(veh_id)
        if cached is None:
            cached = vtype_cache[veh_id] = traci.vehicle.getTypeID(veh_id)
        return cached

    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            tick_start = time.monotonic()

            traci.simulationStep()
            step += 1
            sim_time = traci.simulation.getTime()

            for veh_id in traci.vehicle.getIDList():
                x, y = traci.vehicle.getPosition(veh_id)
                lon, lat = traci.simulation.convertGeo(x, y)
                raw = encode_envelope(
                    event_type="VehiclePositionUpdated",
                    source="sim-service",
                    payload={
                        "vehicle_id": veh_id,
                        "vehicle_type": vtype_of(veh_id),
                        "lat": lat,
                        "lon": lon,
                        "speed_mps": traci.vehicle.getSpeed(veh_id),
                        "heading_deg": traci.vehicle.getAngle(veh_id),
                        "edge_id": traci.vehicle.getRoadID(veh_id),
                        "source": "sumo",
                    },
                    partition_key=veh_id,
                )
                bus.publish(_VEHICLE_TOPIC, raw)

            for edge_id in traci.edge.getIDList():
                if edge_id.startswith(_INTERNAL_EDGE_PREFIX):
                    continue
                count = traci.edge.getLastStepVehicleNumber(edge_id)
                raw = encode_envelope(
                    event_type="ApproachState",
                    source="sim-service",
                    payload={
                        "movement_id": edge_id,
                        "q_pcu": float(count),
                        "occupancy": traci.edge.getLastStepOccupancy(edge_id) / 100.0,
                        "arrival_rate_pcu_s": count / step_length,
                        "queue_truncated": False,
                        "confidence": 1.0,
                        "model": "ground_truth_sim",
                        "source": "sumo",
                    },
                    partition_key=edge_id,
                )
                bus.publish(_APPROACH_TOPIC, raw)

            elapsed = time.monotonic() - tick_start
            if elapsed > target_wall_s:
                dropped_ticks += 1
                log.warning(
                    "step %d (sim t=%.0fs) took %.3fs, budget was %.3fs at "
                    "%.1fx real time -- counted as a dropped tick",
                    step,
                    sim_time,
                    elapsed,
                    target_wall_s,
                    realtime_factor,
                )
            elif target_wall_s > 0:
                time.sleep(target_wall_s - elapsed)

            if max_steps is not None and step >= max_steps:
                break
    finally:
        traci.close()

    log.info(
        "SUMO run finished: %d steps, %d dropped ticks (realtime_factor=%.1f)",
        step,
        dropped_ticks,
        realtime_factor,
    )
    return {"steps": step, "dropped_ticks": dropped_ticks}

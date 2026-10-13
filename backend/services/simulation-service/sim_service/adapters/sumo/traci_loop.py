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
from collections.abc import Callable
from pathlib import Path

import traci
import traci.constants as tc
from itms_common.bus import RedisStreamsSyncBus
from itms_common.events import encode_envelope

log = logging.getLogger("sim-service.traci_loop")

_INTERNAL_EDGE_PREFIX = ":"
_VEHICLE_TOPIC = "traffic.vehicle-positions"
_APPROACH_TOPIC = "traffic.updated"
_VEHICLE_VARS = (tc.VAR_POSITION, tc.VAR_SPEED, tc.VAR_ANGLE, tc.VAR_ROAD_ID)
_EDGE_VARS = (tc.LAST_STEP_VEHICLE_NUMBER, tc.LAST_STEP_OCCUPANCY)


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


def _vtype_lookup(vtype_cache: dict[str, str]) -> Callable[[str], str]:
    def vtype_of(veh_id: str) -> str:
        cached = vtype_cache.get(veh_id)
        if cached is None:
            cached = vtype_cache[veh_id] = traci.vehicle.getTypeID(veh_id)
        return cached

    return vtype_of


def publish_traffic_state(
    bus: RedisStreamsSyncBus, *, step_length: float, vtype_cache: dict[str, str]
) -> None:
    """`VehiclePositionUpdated` (per vehicle) + `ApproachState` (per edge) for
    the current TraCI tick -- the exact event shapes this module has
    published since M1. Pulled out to a function (rather than left inline in
    `run`) so `control/runner.py`'s live-demo path can publish the identical
    events from its own per-tick loop instead of a second, drifting copy --
    one `run_controlled_scenario` call now does what `run` below does plus
    real signal control, for the live demo (`sim_service/main.py`).

    `vtype_cache` is the caller's dict, kept across ticks: a vehicle's vType
    never changes over its life, so this is one `getTypeID` call per vehicle
    for the whole run rather than one per vehicle per tick -- the same
    reasoning `signal_controller/lane_cache.py` documents for the identical
    call on the control path.
    """
    vtype_of = _vtype_lookup(vtype_cache)
    out: list[tuple[str, bytes]] = []

    # Values come from TraCI variable subscriptions: SUMO returns every
    # subscribed value with the step itself, instead of one socket round trip
    # per vehicle per variable (on the district, ~1300 round trips a tick).
    # A vehicle subscribed this tick has no results until the next step, so
    # it is read directly once.
    vehicles = traci.vehicle.getAllSubscriptionResults()
    for veh_id in traci.vehicle.getIDList():
        sub = vehicles.get(veh_id)
        if sub is None:
            traci.vehicle.subscribe(veh_id, _VEHICLE_VARS)
            x, y = traci.vehicle.getPosition(veh_id)
            speed = traci.vehicle.getSpeed(veh_id)
            angle = traci.vehicle.getAngle(veh_id)
            road = traci.vehicle.getRoadID(veh_id)
        else:
            x, y = sub[tc.VAR_POSITION]
            speed, angle, road = sub[tc.VAR_SPEED], sub[tc.VAR_ANGLE], sub[tc.VAR_ROAD_ID]
        lon, lat = traci.simulation.convertGeo(x, y)
        raw = encode_envelope(
            event_type="VehiclePositionUpdated",
            source="sim-service",
            payload={
                "vehicle_id": veh_id,
                "vehicle_type": vtype_of(veh_id),
                "lat": lat,
                "lon": lon,
                "speed_mps": speed,
                "heading_deg": angle,
                "edge_id": road,
                "source": "sumo",
            },
            partition_key=veh_id,
        )
        out.append((_VEHICLE_TOPIC, raw))

    edges = traci.edge.getAllSubscriptionResults()
    for edge_id in traci.edge.getIDList():
        if edge_id.startswith(_INTERNAL_EDGE_PREFIX):
            continue
        sub = edges.get(edge_id)
        if sub is None:
            traci.edge.subscribe(edge_id, _EDGE_VARS)
            count = traci.edge.getLastStepVehicleNumber(edge_id)
            occupancy = traci.edge.getLastStepOccupancy(edge_id)
        else:
            count, occupancy = sub[tc.LAST_STEP_VEHICLE_NUMBER], sub[tc.LAST_STEP_OCCUPANCY]
        raw = encode_envelope(
            event_type="ApproachState",
            source="sim-service",
            payload={
                "movement_id": edge_id,
                "q_pcu": float(count),
                # Already a fraction in [0, 1] -- see queue_state.py's unit note.
                "occupancy": occupancy,
                "arrival_rate_pcu_s": count / step_length,
                "queue_truncated": False,
                "confidence": 1.0,
                "model": "ground_truth_sim",
                "source": "sumo",
            },
            partition_key=edge_id,
        )
        out.append((_APPROACH_TOPIC, raw))

    # One pipelined round trip for the whole tick when the bus supports it.
    publish_many = getattr(bus, "publish_many", None)
    if publish_many is not None:
        publish_many(out)
    else:
        for topic, raw in out:
            bus.publish(topic, raw)


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

    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            tick_start = time.monotonic()

            traci.simulationStep()
            step += 1
            sim_time = traci.simulation.getTime()

            publish_traffic_state(bus, step_length=step_length, vtype_cache=vtype_cache)

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

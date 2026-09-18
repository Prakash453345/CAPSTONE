"""Publish the M1 traffic-state events for the current SUMO tick --
`VehiclePositionUpdated` (one per vehicle) and `ApproachState` (one per real
edge), onto `traffic.vehicle-positions` / `traffic.updated`.

Extracted so the live command-driven controlled loop
(`control/runner.run_controlled_scenario(publish_traffic_state=True)`) emits
the exact same stream the M1 adapter (`adapters/sumo/traci_loop.run`) does --
the api-service fan-out and the web clients don't know or care which loop is
producing. `traci_loop.run` keeps its own inline copy for now (it is the
untouched M1-gate path); this module is byte-for-byte equivalent to it and is
where that logic consolidates once the M1 path grows a fast test.
"""

from __future__ import annotations

import traci
from itms_common.bus import RedisStreamsSyncBus
from itms_common.events import encode_envelope

_INTERNAL_EDGE_PREFIX = ":"
VEHICLE_TOPIC = "traffic.vehicle-positions"
APPROACH_TOPIC = "traffic.updated"


def publish_traffic_state(bus: RedisStreamsSyncBus, *, step_length: float) -> None:
    """Call once per simulation step, after `traci.simulationStep()`. Mirrors
    `adapters/sumo/traci_loop.run`'s per-tick publishing exactly: same event
    types, same payload fields, same topics, same partition keys."""
    for veh_id in traci.vehicle.getIDList():
        x, y = traci.vehicle.getPosition(veh_id)
        lon, lat = traci.simulation.convertGeo(x, y)
        bus.publish(
            VEHICLE_TOPIC,
            encode_envelope(
                event_type="VehiclePositionUpdated",
                source="sim-service",
                payload={
                    "vehicle_id": veh_id,
                    "lat": lat,
                    "lon": lon,
                    "speed_mps": traci.vehicle.getSpeed(veh_id),
                    "heading_deg": traci.vehicle.getAngle(veh_id),
                    "edge_id": traci.vehicle.getRoadID(veh_id),
                    "source": "sumo",
                },
                partition_key=veh_id,
            ),
        )

    for edge_id in traci.edge.getIDList():
        if edge_id.startswith(_INTERNAL_EDGE_PREFIX):
            continue
        count = traci.edge.getLastStepVehicleNumber(edge_id)
        bus.publish(
            APPROACH_TOPIC,
            encode_envelope(
                event_type="ApproachState",
                source="sim-service",
                payload={
                    "movement_id": edge_id,
                    "q_pcu": float(count),
                    # Already a fraction in [0, 1] -- see queue_state.py's unit note.
                    "occupancy": traci.edge.getLastStepOccupancy(edge_id),
                    "arrival_rate_pcu_s": count / step_length,
                    "queue_truncated": False,
                    "confidence": 1.0,
                    "model": "ground_truth_sim",
                    "source": "sumo",
                },
                partition_key=edge_id,
            ),
        )

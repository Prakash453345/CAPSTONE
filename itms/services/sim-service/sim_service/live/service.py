"""`run_live` -- the live, command-driven simulation service.

It is `control/runner.run_controlled_scenario` with its live hooks turned on:
publish the M1 traffic stream, pace to real time, and drain a `commands.*`
topic each tick. The arbitration ladder governs every junction exactly as in
the offline gates, so a green-corridor `SignalPlan` (M7) or an operator signal
override (M6) added later goes through `arbiter.tick` + `interlocks.check`
untouched -- this module never commands a signal itself.

Phase 3 wires the operator-anomaly path: `AnomalyCreateRequested` /
`AnomalyClearRequested` on `commands.operator` are applied to SUMO by
`OperatorAnomalyController`, which emits `AnomalyUpdated` on `anomaly.updated`.
Phase 6 adds the green corridor: `EmergencyCommand`'s `ACTIVATE_CORRIDOR` arms a
`CorridorController` corridor whose `preemption_plan` is handed to
`run_controlled_scenario` as the arbiter's rung-3 proposal source -- the arbiter
still runs every preemption through `interlocks.check`, this module never
commands a signal.

`IncidentResponseOrchestrator` (`live/incident_response.py`) sits on top of
`anomalies` and `emergency`: it watches for a newly-active, sufficiently
severe anomaly and turns it into an `EmergencyDispatched` alert (type + GPS +
which authorities) plus one `EmergencyRequest`/corridor per responding
authority kind -- the same `handle_create` + `ACTIVATE_CORRIDOR` path an
operator would drive by hand, just called automatically and once per
authority instead of once per operator click.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from itms_common.bus import RedisStreamsSyncBus, RedisStreamsSyncConsumer
from itms_common.events import decode_envelope, encode_envelope

from sim_service.control.runner import run_controlled_scenario
from sim_service.live.anomaly_control import OperatorAnomalyController
from sim_service.live.corridor import NET_PATH, load_corridor
from sim_service.live.emergency_control import EmergencyController
from sim_service.live.green_corridor import CorridorController
from sim_service.live.incident_response import IncidentResponseOrchestrator
from sim_service.routing import RoadGraph

log = logging.getLogger("sim-service.live")

# (envelope dict, sim step, sim time seconds) -> None
CommandHandler = Callable[[dict, int, float], None]

DEFAULT_COMMAND_TOPICS = ["commands.operator"]
CONSUMER_GROUP = "sim-service-live"
ANOMALY_TOPIC = "anomaly.updated"
EMERGENCY_REQUEST_TOPIC = "emergency.request-updated"
EMERGENCY_VEHICLE_TOPIC = "emergency.vehicle-updated"
GREEN_CORRIDOR_TOPIC = "emergency.corridor-updated"
INCIDENT_ALERT_TOPIC = "emergency.dispatched"


def run_live(
    *,
    redis_url: str = "redis://localhost:6379/0",
    demand: str = "medium",
    realtime_factor: float = 1.0,
    step_length: float = 1.0,
    seed: int | None = None,
    max_steps: int | None = None,
    command_topics: list[str] | None = None,
    command_handler: CommandHandler | None = None,
) -> dict:
    """Run the corridor live until its demand clears (or `max_steps`).

    `command_handler` overrides the built-in dispatch (operator anomaly). It is
    called once per drained command with the decoded envelope, the sim step and
    the sim time, and must not block for long -- it runs inside the tick loop.
    Anything it does to SUMO should be a plain TraCI call (or, for signals, a
    proposal fed to the arbiter -- never a direct cabinet command).
    """
    topics = command_topics or DEFAULT_COMMAND_TOPICS
    bus = RedisStreamsSyncBus(redis_url)
    consumer = RedisStreamsSyncConsumer(
        topics, group=CONSUMER_GROUP, consumer="live-1", url=redis_url
    )
    setup = load_corridor(demand)
    graph = RoadGraph.from_network(NET_PATH)
    anomalies = OperatorAnomalyController()
    corridor = CorridorController(graph)
    emergency = EmergencyController(graph, anomalies, corridor_controller=corridor)
    incident_response = IncidentResponseOrchestrator(anomalies, emergency)
    handler = command_handler or _build_dispatch(anomalies, emergency, incident_response)

    drained = 0

    def publish(topic: str, event_type: str, payload: dict, key: str) -> None:
        bus.publish(
            topic,
            encode_envelope(
                event_type=event_type, source="sim-service", payload=payload, partition_key=key
            ),
        )

    def on_tick(step: int, sim_time: float) -> None:
        nonlocal drained
        for msg in consumer.drain():
            try:
                envelope = decode_envelope(msg.raw)
            except Exception:
                log.exception(
                    "undecodable command on %s (%s) -- acking to skip", msg.topic, msg.message_id
                )
                consumer.ack(msg.topic, msg.message_id)
                continue
            try:
                handler(envelope, step, sim_time)
            except Exception:
                log.exception("command handler raised for %s", envelope.get("event_type"))
            finally:
                consumer.ack(msg.topic, msg.message_id)
                drained += 1
        # One controller raising must not abort the tick: the others still owe
        # the command center their events, and SUMO is mid-step.
        try:
            anomalies.tick(step, sim_time)
        except Exception:
            log.exception("anomaly controller tick raised at step %s", step)
        try:
            emergency.tick(step, sim_time)
        except Exception:
            log.exception("emergency controller tick raised at step %s", step)
        try:
            incident_response.tick(step, sim_time)
        except Exception:
            log.exception("incident response tick raised at step %s", step)
        for p in anomalies.drain_events():
            publish(ANOMALY_TOPIC, "AnomalyUpdated", p, p["edge_id"])
        for p in emergency.drain_events():
            publish(EMERGENCY_REQUEST_TOPIC, "EmergencyRequestUpdated", p, p["request_id"])
        for p in emergency.drain_vehicle_events():
            publish(EMERGENCY_VEHICLE_TOPIC, "EmergencyVehicleUpdated", p, p["vehicle_id"])
        for p in corridor.drain_events():
            publish(GREEN_CORRIDOR_TOPIC, "GreenCorridorUpdated", p, p["request_id"])
        for p in incident_response.drain_events():
            publish(INCIDENT_ALERT_TOPIC, "EmergencyDispatched", p, p["anomaly_id"])

    log.info(
        "live corridor starting: demand=%s realtime_factor=%.1f, draining %s, publishing "
        "traffic.vehicle-positions / traffic.updated / signal.changed / %s / %s / %s / %s / %s",
        demand,
        realtime_factor,
        topics,
        ANOMALY_TOPIC,
        EMERGENCY_REQUEST_TOPIC,
        EMERGENCY_VEHICLE_TOPIC,
        GREEN_CORRIDOR_TOPIC,
        INCIDENT_ALERT_TOPIC,
    )
    try:
        summary = run_controlled_scenario(
            setup.sumocfg_path,
            setup.configs,
            setup.strategy,
            seed=seed,
            step_length=step_length,
            max_steps=max_steps,
            link_lanes=setup.link_lanes,
            receiving_lanes=setup.receiving_lanes,
            vtype_pcu=setup.vtype_pcu,
            bus=bus,
            publish_traffic_state=True,
            on_tick=on_tick,
            pace_realtime_factor=realtime_factor,
            preempt_source=corridor.preemption_plan,
        )
    finally:
        anomalies.restore_all()
        consumer.close()
        bus.close()

    summary["commands_drained"] = drained
    log.info("live corridor finished: %s", summary)
    return summary


def _build_dispatch(
    anomalies: OperatorAnomalyController,
    emergency: EmergencyController,
    incident_response: IncidentResponseOrchestrator | None = None,
) -> CommandHandler:
    """The built-in command handler. `EmergencyCommand`'s ACTIVATE_CORRIDOR is
    routed to `EmergencyController.handle_command`, which arms the corridor and
    spawns the vehicle."""

    def dispatch(envelope: dict, step: int, sim_time: float) -> None:
        etype = envelope.get("event_type")
        payload = envelope.get("payload", {})
        if etype == "AnomalyCreateRequested":
            anomalies.handle_create(payload, step=step, sim_time_s=sim_time)
        elif etype == "AnomalyClearRequested":
            anomalies.handle_clear(payload, step=step, sim_time_s=sim_time)
        elif etype == "EmergencyRequestCreated":
            if incident_response is not None and not payload.get("vehicle_id"):
                # no unit named: dispatch finds the nearest free crew of the kind
                incident_response.handle_nearest_request(
                    payload, step=step, sim_time_s=sim_time, create=emergency.handle_create
                )
            else:
                emergency.handle_create(payload, step=step, sim_time_s=sim_time)
        elif etype == "EmergencyCommand":
            emergency.handle_command(payload, step=step, sim_time_s=sim_time)
        else:
            log.info("no live handler for command %s (step %d) -- ignored", etype, step)

    return dispatch

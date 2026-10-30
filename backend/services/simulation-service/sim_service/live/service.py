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
import os
from collections.abc import Callable

from itms_common.bus import RedisStreamsSyncBus, RedisStreamsSyncConsumer
from itms_common.events import decode_envelope, encode_envelope
from itms_domain import EmergencyKind

from sim_service.control.runner import run_controlled_scenario
from sim_service.live.anomaly_control import OperatorAnomalyController
from sim_service.live.corridor import load_corridor, network_path
from sim_service.live.crew_dispatch import (
    DEFAULT_OFFER_TIMEOUT_S,
    CrewDispatcher,
    CrewRoster,
    units_from_accounts,
)
from sim_service.live.crew_missions import CrewMissions
from sim_service.live.emergency_control import EmergencyController
from sim_service.live.green_corridor import CorridorController
from sim_service.live.incident_response import IncidentResponseOrchestrator
from sim_service.routing import RoadGraph
from sim_service.routing.hexgrid import HexIndex
from sim_service.signal_controller.ev_routing import edge_latlon, traci_route_fn

log = logging.getLogger("sim-service.live")

# (envelope dict, sim step, sim time seconds) -> None
CommandHandler = Callable[[dict, int, float], None]

# `crew.roster` is api-service republishing the crew accounts; it is drained
# in the same loop as operator commands because it is just another thing the
# tick needs to know before it matches an incident to a crew.
DEFAULT_COMMAND_TOPICS = ["commands.operator", "crew.roster"]
CONSUMER_GROUP = "sim-service-live"
ANOMALY_TOPIC = "anomaly.updated"
EMERGENCY_REQUEST_TOPIC = "emergency.request-updated"
EMERGENCY_VEHICLE_TOPIC = "emergency.vehicle-updated"
GREEN_CORRIDOR_TOPIC = "emergency.corridor-updated"
INCIDENT_ALERT_TOPIC = "emergency.dispatched"
CREW_OFFER_TOPIC = "crew.offer"
_CREW_KIND = {
    "AMBULANCE": EmergencyKind.AMBULANCE,
    "FIRE_TRUCK": EmergencyKind.FIRE_TRUCK,
    "POLICE": EmergencyKind.POLICE,
}


def run_live(
    *,
    redis_url: str = "redis://localhost:6379/0",
    demand: str = "medium",
    network: str | None = None,  # None: the configured scenario (itms_domain.scenario)
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
    setup = load_corridor(demand, network=network)
    graph = RoadGraph.from_network(network_path(network))
    anomalies = OperatorAnomalyController()
    corridor = CorridorController(graph)
    emergency = EmergencyController(graph, anomalies, corridor_controller=corridor)
    roster = CrewRoster()
    # A crew answers in wall-clock seconds, but offers expire on the sim
    # clock: with the sim paced 3x faster than real time a 25 s offer gave a
    # driver about 8 s. Scale the timeout so it is 25 real seconds.
    crew = CrewDispatcher(
        roster, emergency.planner, graph, hex_index=HexIndex(graph),
        offer_timeout_s=DEFAULT_OFFER_TIMEOUT_S * max(1.0, realtime_factor),
        # Assign the nearest crew at once (default) or ask them first
        # (CREW_AUTO_ACCEPT=false: the crew page shows Accept / Decline).
        auto_accept=os.environ.get("CREW_AUTO_ACCEPT", "true").strip().lower()
        not in {"0", "false", "no", "off"},
    )
    # The accept callback fires inside the tick, so it needs the tick's clock;
    # the alternative, dispatching an emergency at sim time 0, makes every
    # accepted call look like it started when the run did.
    clock = {"step": 0, "sim_time": 0.0}

    def _on_crew_accept(offer) -> None:
        """A crew took the call: now it becomes a real dispatch, from where
        that crew actually is to the incident, and the unit sets off at once
        (the crew accepting *is* the go-ahead; nobody else has to press
        dispatch)."""
        unit = roster.get(offer.unit_id)
        ok = incident_response._create_and_activate(  # noqa: SLF001
            request_id=offer.incident_id, vehicle_id=offer.unit_id, kind=offer.kind,
            source_edge=unit.edge_id if unit and unit.edge_id else offer.edge_id,
            dest_edge=offer.edge_id, step=clock["step"], sim_time_s=clock["sim_time"],  # type: ignore[arg-type]
        )
        if not ok:
            crew.release(offer.unit_id)

    # Road midpoints, so a trip to a stretch of road the extract cut off from
    # everything else goes to the nearest connected road instead of nowhere.
    try:
        emergency.planner.edge_points = _edge_points(network_path(network))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 -- only a fallback; routing works without it
        log.exception("could not read road midpoints from %s", network_path(network))
    crew.on_accept = _on_crew_accept
    incident_response = IncidentResponseOrchestrator(anomalies, emergency, crew_dispatcher=crew)
    # Where crew units live while idle: ambulances at hospitals, police at
    # police stations, fire trucks at police stations too (this OSM extract
    # has no fire stations).
    # Only depots on the connected road network: a hospital the map extract
    # snapped onto a cut-off stretch of road would park a crew where no call
    # can ever reach it.
    def _connected(edge: str) -> bool:
        start = emergency.planner.usable_ends(edge, edge)[0]  # dead ends drive out
        reach = emergency.planner._reachable(start)  # noqa: SLF001
        return len(reach) >= 0.5 * len(graph.edges)

    depots = {
        k: [u.depot.edge for u in us if _connected(u.depot.edge)]
        for k, us in incident_response._units.items()  # noqa: SLF001
    }
    depots[EmergencyKind.FIRE_TRUCK] = depots.get(EmergencyKind.FIRE_TRUCK) or depots.get(
        EmergencyKind.POLICE, []
    )
    missions = CrewMissions(
        crew,
        facility_index=incident_response._facility_index,  # noqa: SLF001
        home_edges=depots,
        create_leg=lambda rid, uid, src, dst: incident_response._create_and_activate(  # noqa: SLF001
            request_id=rid, vehicle_id=uid, kind=EmergencyKind.AMBULANCE,
            source_edge=src, dest_edge=dst, step=clock["step"], sim_time_s=clock["sim_time"],  # type: ignore[arg-type]
        ),
        cancel=lambda rid: emergency.handle_command(
            {"request_id": rid, "action": "CANCEL", "operator": "system:crew",
             "reason": "crew changed hospital"},
            step=clock["step"], sim_time_s=clock["sim_time"],  # type: ignore[arg-type]
        ),
        vehicle_edges=emergency.vehicle_edges,
        edge_latlon=edge_latlon,
        route_fn=_route_from_scene(traci_route_fn()),
        # 45 s of real time for the crew to choose, then the fastest hospital.
        auto_choose_after_s=float(os.environ.get("CREW_HOSPITAL_CHOICE_SECONDS", "45"))
        * max(1.0, realtime_factor),
    )
    _orchestrator_arrival = emergency.on_arrival

    def _on_arrival(request, vehicle, step, sim_time_s) -> None:
        if _orchestrator_arrival is not None:
            _orchestrator_arrival(request, vehicle, step, sim_time_s)
        missions.on_arrival(request.request_id, request.vehicle_id, request.destination_edge)

    emergency.on_arrival = _on_arrival
    handler = command_handler or _build_dispatch(
        anomalies, emergency, crew, missions, incident_response
    )

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
        clock["step"], clock["sim_time"] = step, sim_time
        for msg in consumer.drain():
            try:
                envelope = decode_envelope(msg.raw)
            except Exception:
                log.exception(
                    "undecodable command on %s (%s) -- acking to skip", msg.topic, msg.message_id
                )
                consumer.ack(msg.topic, msg.message_id)
                continue
            if msg.topic == "crew.roster":
                try:
                    for unit in units_from_accounts(
                        envelope.get("payload", {}).get("units", [])
                    ):
                        roster.upsert(unit)
                    missions.place_new_units()
                except Exception:
                    log.exception("bad crew roster payload")
                finally:
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
        try:
            # Expire offers nobody answered and pass them to the next crew.
            crew.tick(sim_time)
            missions.tick(sim_time)
        except Exception:
            log.exception("crew dispatcher tick raised at step %s", step)
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
        for e in [*crew.drain_events(), *missions.drain_events()]:
            payload = e["payload"]
            publish(
                CREW_OFFER_TOPIC, e["event_type"], payload,
                payload.get("unit_id") or payload.get("incident_id", "crew"),
            )

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
    crew: CrewDispatcher | None = None,
    missions: CrewMissions | None = None,
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
            # Cleared before any crew took it: take the offers back, or a crew
            # could still accept a call for an incident that no longer exists.
            if crew is not None:
                aid = str(payload.get("anomaly_id", ""))
                for kind in EmergencyKind:
                    crew.withdraw(f"resp-{aid}-{kind.value}", now_s=sim_time)
        elif etype == "EmergencyRequestCreated":
            # No vehicle named: the operator asked for *a kind* of unit, which
            # is the normal case now -- the console offers "an ambulance", not
            # "Ambulance 12". Try a real crew account first; the dispatcher
            # finds the nearest one of that kind and the call becomes a
            # request when they accept. With no real crew of that kind free,
            # fall back to the nearest depot-based unit.
            if (crew is not None or incident_response is not None) and not str(
                payload.get("vehicle_id", "")
            ).strip():
                offer = None
                if crew is not None:
                    kind = _CREW_KIND.get(
                        str(payload.get("vehicle_kind", "")).upper(), EmergencyKind.AMBULANCE
                    )
                    offer = crew.request(
                        str(payload.get("request_id", "")),
                        kind,
                        str(payload.get("destination_edge", "")),
                        now_s=sim_time,
                    )
                if offer is None and incident_response is not None:
                    incident_response.handle_nearest_request(
                        payload, step=step, sim_time_s=sim_time, create=emergency.handle_create
                    )
            else:
                emergency.handle_create(payload, step=step, sim_time_s=sim_time)
        elif etype == "EmergencyCommand" and str(payload.get("action")) == "REASSIGN":
            # The operator confirmed moving a unit to a more severe waiting
            # call; request_id carries the suggestion id (incident_response).
            if incident_response is not None:
                incident_response.accept_reassignment(
                    str(payload.get("request_id", "")), step=step, sim_time_s=sim_time
                )
        elif etype == "EmergencyCommand":
            emergency.handle_command(payload, step=step, sim_time_s=sim_time)
            # An operator standing a crew's call down frees that crew; one
            # stood down before anyone accepted takes the offer back.
            if crew is not None and str(payload.get("action")) == "CANCEL":
                crew.withdraw(str(payload.get("request_id", "")), now_s=sim_time)
                req = emergency.get_request(str(payload.get("request_id", "")))
                if req is not None and crew.roster.get(req.vehicle_id) is not None:
                    crew.release(req.vehicle_id)
        elif etype == "CrewHospitalChoice":
            # An ambulance crew at the scene: patient on board, go here.
            if missions is not None:
                missions.choose_hospital(
                    str(payload.get("unit_id", "")), str(payload.get("facility_id", ""))
                )
        elif etype == "CrewOfferResponse":
            # A crew answered the call on their own page.
            if crew is not None:
                crew.respond(
                    str(payload.get("offer_id", "")),
                    accept=bool(payload.get("accept")),
                    now_s=sim_time,
                )
        else:
            log.info("no live handler for command %s (step %d) -- ignored", etype, step)

    return dispatch


def _edge_points(net_path) -> dict[str, tuple[float, float]]:
    """{edge id: (x, y) midpoint} in the network's own metres."""
    import sumolib

    net = sumolib.net.readNet(str(net_path))
    out: dict[str, tuple[float, float]] = {}
    for e in net.getEdges():
        if e.getFunction():
            continue
        shape = e.getShape()
        x, y = shape[len(shape) // 2]
        out[e.getID()] = (float(x), float(y))
    return out


def _route_from_scene(route_fn):
    """Travel time from a unit already standing on `from_edge`: SUMO counts
    that whole road, and on a BLOCKED one (crawl speed) it alone came to over
    an hour, so every hospital looked an hour away. The unit leaves past the
    obstruction (see EmergencyController._spawn_ev), so it is left out."""
    import traci

    def route(from_edge: str, to_edge: str):
        routed = route_fn(from_edge, to_edge)
        if routed is None:
            return None
        edges, t = routed
        if len(edges) > 1:
            try:
                t -= float(traci.edge.getTraveltime(from_edge))
            except Exception:  # noqa: BLE001 -- keep SUMO's estimate as it is
                pass
        return edges, max(0.0, t)

    return route

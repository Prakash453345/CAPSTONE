"""Emergency requests + routing, applied to the live simulation.

Bridges the pure `sim_service.routing` planner to live SUMO: `sample_conditions`
reads per-edge occupancy / mean speed from TraCI and folds in the active
operator anomalies, producing the `EdgeConditions` the planner consumes. The
`EmergencyRequest` state machine (`itms_domain.emergency`) tracks each dispatch;
every transition is queued as an `EmergencyRequestUpdated` payload.

Phase 5 scope: create -> route -> preview, plus manual recalculate and cancel.
Phase 6 (green corridor) adds the rest: `ACTIVATE_CORRIDOR` arms a
`CorridorController` corridor and spawns the vehicle in SUMO, `tick` tracks its
live position (publishing `EmergencyVehicleUpdated`), drives the
GREEN_CORRIDOR_ACTIVE -> IN_TRANSIT -> COMPLETED transitions, and feeds the
corridor its route progress so junctions are released as the EV clears them.
Phase 7 adds continuous monitoring: `_monitor_routes` re-evaluates each active
route on a fixed interval and triggers an automatic reroute when a BLOCKED /
severe anomaly lands on the road ahead, or when replanning from the vehicle's
current position is materially cheaper (`EmergencyRoutingConfig.reroute_*`
thresholds) -- with a cooldown and a minimum-progress gate so it never
oscillates or recomputes every tick.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

import traci
from itms_domain import (
    AnomalySeverity,
    EmergencyKind,
    EmergencyRequest,
    EmergencyRequestAction,
    EmergencyRequestState,
    EmergencyRoutingConfig,
    EmergencyVehicle,
    EmergencyVehicleStatus,
    RouteResult,
)

from sim_service.live.anomaly_control import OperatorAnomalyController
from sim_service.live.green_corridor import CorridorController
from sim_service.live.timeparse import epoch_ms
from sim_service.routing import EdgeConditions, NoRouteError, RoadGraph, RoutePlanner

log = logging.getLogger("sim-service.live.emergency")

_REPUBLISH_INTERVAL_S = 10.0
_MONITOR_INTERVAL_S = 3.0  # how often a live route is re-evaluated for rerouting
_EV_TYPE_ID = "DEFAULT_VEHTYPE"
_EV_COLOR = (233, 72, 77, 255)
_SEVERE = (AnomalySeverity.HIGH, AnomalySeverity.BLOCKED)

_KIND_MAP = {
    "AMBULANCE": EmergencyKind.AMBULANCE,
    "FIRE_TRUCK": EmergencyKind.FIRE_TRUCK,
    "POLICE": EmergencyKind.POLICE,
}

OnArrivalHook = Callable[[EmergencyRequest, EmergencyVehicle | None, int, float], None]


@dataclass
class _EvRun:
    """Book-keeping for one emergency vehicle actually driving in SUMO."""

    request_id: str
    veh_id: str
    route_edges: tuple[str, ...]
    dist_to_edge_start: dict[str, float]
    total_length_m: float
    spawned: bool = False
    seen_moving: bool = False
    last_progress_m: float = 0.0
    current_edge: str = ""  # last real (non-internal) route edge the EV was on


class EmergencyController:
    def __init__(
        self,
        graph: RoadGraph,
        anomaly_controller: OperatorAnomalyController,
        config: EmergencyRoutingConfig | None = None,
        corridor_controller: CorridorController | None = None,
        on_arrival: OnArrivalHook | None = None,
    ):
        self.graph = graph
        self.config = config or EmergencyRoutingConfig()
        self.planner = RoutePlanner(graph, self.config)
        self.anomalies = anomaly_controller
        self.corridor = corridor_controller
        # Optional `(request, vehicle, step, sim_time_s) -> None`, called at the
        # end of `_on_arrival` once the request is COMPLETED and the vehicle is
        # released. `IncidentResponseOrchestrator` sets this (after construction,
        # as a plain attribute) to chain an ambulance straight to a hospital
        # instead of leaving it idle -- see `live/incident_response.py`.
        self.on_arrival = on_arrival
        self._requests: dict[str, EmergencyRequest] = {}
        self._vehicles: dict[str, EmergencyVehicle] = {}
        self._alt_cache: dict[str, list[RouteResult]] = {}
        self._ev_runs: dict[str, _EvRun] = {}
        self._events: list[dict] = []
        self._vehicle_events: list[dict] = []
        self._last_republish_s = 0.0
        # continuous-monitoring bookkeeping (Phase 7)
        self._last_route_s: dict[str, float] = {}       # when each route was last (re)set
        self._progress_at_route: dict[str, float] = {}  # route-distance covered at that moment
        self._last_monitor_s: dict[str, float] = {}
        self._severe_anomalies_seen: set[str] = set()

    # ---- command handling --------------------------------------------

    def handle_create(self, payload: Mapping, *, step: int, sim_time_s: float) -> None:
        request_id = str(payload["request_id"])
        if request_id in self._requests:
            log.warning("emergency request %s already exists -- ignoring", request_id)
            return
        vehicle_id = str(payload["vehicle_id"])
        kind = _KIND_MAP.get(str(payload.get("vehicle_kind", "AMBULANCE")), EmergencyKind.AMBULANCE)
        source_edge = str(payload["source_edge"])
        dest_edge = str(payload["destination_edge"])
        operator = str(payload.get("operator", "operator:console"))
        at_ms = epoch_ms(payload.get("requested_at"), sim_time_s * 1000)

        req = EmergencyRequest.create(
            request_id=request_id,
            vehicle_id=vehicle_id,
            source_edge=source_edge,
            destination_edge=dest_edge,
            at_ms=at_ms,
            operator=operator,
        ).apply(EmergencyRequestAction.START_ROUTING, at_ms=at_ms, actor="system:router")
        self._vehicles[vehicle_id] = EmergencyVehicle(
            vehicle_id=vehicle_id,
            kind=kind,
            status=EmergencyVehicleStatus.ASSIGNED,
            priority=int(payload.get("priority", 1)),
            home_edge=source_edge,
            current_edge=source_edge,
            active_request_id=request_id,
        )
        self._requests[request_id] = req
        self._route_and_transition(
            request_id, at_ms=at_ms, step=step, sim_time_s=sim_time_s,
            action=EmergencyRequestAction.ROUTE_READY,
        )

    def handle_command(self, payload: Mapping, *, step: int, sim_time_s: float) -> None:
        request_id = str(payload["request_id"])
        req = self._requests.get(request_id)
        if req is None:
            log.warning("command for unknown emergency request %s -- ignoring", request_id)
            return
        action = str(payload["action"])
        at_ms = epoch_ms(payload.get("requested_at"), sim_time_s * 1000)
        actor = str(payload.get("operator", "operator:console"))

        if action == "CANCEL":
            self._requests[request_id] = req.apply(
                EmergencyRequestAction.CANCEL, at_ms=at_ms, actor=actor,
                detail=str(payload.get("reason", "")),
            )
            self._teardown(request_id, reason="request cancelled", step=step)
            self._release_vehicle(req.vehicle_id)
            self._queue(request_id, step=step, actor=actor)
            log.info("emergency request %s CANCELLED by %s", request_id, actor)
        elif action == "RECALCULATE":
            reroutable = (EmergencyRequestState.ROUTE_READY, EmergencyRequestState.IN_TRANSIT)
            if req.state not in reroutable:
                log.warning("recalculate ignored: request %s is %s", request_id, req.state.value)
                return
            run = self._ev_runs.get(request_id)
            from_edge = (
                run.current_edge
                if req.state is EmergencyRequestState.IN_TRANSIT and run and run.current_edge
                else None
            )
            self._route_and_transition(
                request_id, at_ms=at_ms, step=step, sim_time_s=sim_time_s,
                action=EmergencyRequestAction.REROUTE, actor=actor,
                detail=str(payload.get("reason", "operator recalculated")),
                from_edge=from_edge,
            )
        elif action == "ACTIVATE_CORRIDOR":
            self._activate_corridor(
                request_id, at_ms=at_ms, step=step, sim_time_s=sim_time_s, actor=actor
            )
        else:
            log.warning("unknown emergency action %s", action)

    def _activate_corridor(
        self, request_id: str, *, at_ms: int, step: int, sim_time_s: float, actor: str
    ) -> None:
        req = self._requests[request_id]
        if self.corridor is None:
            log.info("ACTIVATE_CORRIDOR for %s but no corridor controller configured", request_id)
            return
        if req.state is not EmergencyRequestState.ROUTE_READY or req.route is None:
            log.warning(
                "ACTIVATE_CORRIDOR ignored: request %s is %s with route=%s",
                request_id, req.state.value, req.route is not None,
            )
            return
        corridor_id = self.corridor.activate(
            request_id=request_id,
            vehicle_id=req.vehicle_id,
            route_edges=req.route.edges,
            now_ms=int(sim_time_s * 1000),  # corridor windows live in sim time
            step=step,
        )
        if corridor_id is None:
            # No junction to preempt, but the vehicle still needs to actually
            # drive there -- ROUTE_READY has no DEPART transition, so without
            # this the request (and the vehicle) would sit forever and never
            # reach _on_arrival. EmergencyRequestAction.DISPATCH exists in the
            # domain state machine for exactly this (ROUTE_READY -> IN_TRANSIT,
            # no corridor) and was never invoked anywhere before this.
            self._requests[request_id] = req.apply(
                EmergencyRequestAction.DISPATCH, at_ms=at_ms, actor=actor,
            )
            v = self._vehicles.get(req.vehicle_id)
            if v is not None:
                self._vehicles[req.vehicle_id] = replace(v, status=EmergencyVehicleStatus.EN_ROUTE)
            self._spawn_ev(request_id)
            self._queue(
                request_id, step=step, actor=actor,
                detail="route crosses no signal-controlled junction -- no corridor needed",
            )
            log.info("emergency request %s -> IN_TRANSIT (no corridor needed)", request_id)
            return
        self._requests[request_id] = req.apply(
            EmergencyRequestAction.ACTIVATE_CORRIDOR, at_ms=at_ms, actor=actor,
            green_corridor_id=corridor_id,
        )
        self._spawn_ev(request_id)
        self._queue(
            request_id, step=step, actor=actor,
            detail=f"green corridor {corridor_id} armed",
        )
        log.info("emergency request %s -> GREEN_CORRIDOR_ACTIVE (%s)", request_id, corridor_id)

    # ---- per-tick --------------------------------------------------

    def tick(self, step: int, sim_time_s: float) -> None:
        progress_by_request = self._advance_vehicles(step, sim_time_s)
        if self.corridor is not None:
            self.corridor.tick(step, sim_time_s, progress_by_request=progress_by_request)

        self._monitor_routes(step, sim_time_s, progress_by_request)

        if sim_time_s - self._last_republish_s >= _REPUBLISH_INTERVAL_S:
            self._last_republish_s = sim_time_s
            # a request already emitted this tick (depart / arrive / auto-reroute)
            # doesn't also need a heartbeat copy
            already = {e["request_id"] for e in self._events}
            for rid, req in self._requests.items():
                if not req.is_terminal and rid not in already:
                    self._queue(rid, step=step, actor="system:monitor")

    def drain_events(self) -> list[dict]:
        out, self._events = self._events, []
        return out

    def drain_vehicle_events(self) -> list[dict]:
        out, self._vehicle_events = self._vehicle_events, []
        return out

    def active_requests(self) -> list[EmergencyRequest]:
        return [r for r in self._requests.values() if not r.is_terminal]

    def get_request(self, request_id: str) -> EmergencyRequest | None:
        return self._requests.get(request_id)

    # ---- live vehicle tracking -----------------------------------

    def _advance_vehicles(self, step: int, sim_time_s: float) -> dict[str, float]:
        """Read each spawned EV's live SUMO state, drive its request's
        depart/arrive transitions, emit `EmergencyVehicleUpdated`, and return
        `{request_id: route_progress_m}` for the corridor."""
        if not self._ev_runs:
            return {}
        try:
            live_ids = set(traci.vehicle.getIDList())
        except Exception:  # noqa: BLE001 -- TraCI down / between steps
            return {}

        progress: dict[str, float] = {}
        for request_id, run in list(self._ev_runs.items()):
            req = self._requests.get(request_id)
            if req is None or req.is_terminal:
                self._ev_runs.pop(request_id, None)
                continue

            if run.veh_id not in live_ids:
                if run.seen_moving:
                    self._on_arrival(request_id, run, step=step, sim_time_s=sim_time_s)
                continue

            try:
                edge_id = traci.vehicle.getRoadID(run.veh_id)
                lane_pos = traci.vehicle.getLanePosition(run.veh_id)
                speed = traci.vehicle.getSpeed(run.veh_id)
                x, y = traci.vehicle.getPosition(run.veh_id)
                lon, lat = traci.simulation.convertGeo(x, y)
            except Exception:  # noqa: BLE001
                continue

            if edge_id and not edge_id.startswith(":"):
                run.current_edge = edge_id
            covered = run.dist_to_edge_start.get(edge_id, run.last_progress_m) + max(0.0, lane_pos)
            covered = max(run.last_progress_m, min(covered, run.total_length_m))
            run.last_progress_m = covered
            progress[request_id] = covered
            frac = covered / run.total_length_m if run.total_length_m else 0.0

            if not run.seen_moving and (speed > 0.1 or covered > 1.0):
                run.seen_moving = True
                self._depart(request_id, step=step, sim_time_s=sim_time_s)

            eta_s = (
                max(0.0, (run.total_length_m - covered) / max(1.0, speed))
                if speed > 0.1
                else None
            )
            self._vehicle_events.append(
                emergency_vehicle_payload(
                    self._requests[request_id], self._vehicles.get(req.vehicle_id),
                    lat=lat, lon=lon, edge_id=edge_id or None, speed_mps=speed,
                    eta_s=eta_s, route_progress=round(frac, 3), step=step,
                )
            )
        return progress

    def _depart(self, request_id: str, *, step: int, sim_time_s: float) -> None:
        req = self._requests[request_id]
        if req.state is not EmergencyRequestState.GREEN_CORRIDOR_ACTIVE:
            return
        at_ms = int(sim_time_s * 1000)
        self._requests[request_id] = req.apply(
            EmergencyRequestAction.DEPART, at_ms=at_ms, actor="system:monitor",
            detail="vehicle en route",
        )
        v = self._vehicles.get(req.vehicle_id)
        if v is not None:
            self._vehicles[req.vehicle_id] = replace(
                v, status=EmergencyVehicleStatus.EN_ROUTE
            )
        self._queue(request_id, step=step, actor="system:monitor")

    def _on_arrival(self, request_id: str, run: _EvRun, *, step: int, sim_time_s: float) -> None:
        req = self._requests[request_id]
        at_ms = int(sim_time_s * 1000)
        self._requests[request_id] = req.apply(
            EmergencyRequestAction.ARRIVE, at_ms=at_ms, actor="system:monitor",
            detail="vehicle reached destination",
        )
        self._teardown(request_id, reason="arrived", step=step)
        v = self._vehicles.get(req.vehicle_id)
        if v is not None:
            self._vehicles[req.vehicle_id] = v.released()
        self._vehicle_events.append(
            emergency_vehicle_payload(
                self._requests[request_id], self._vehicles.get(req.vehicle_id),
                lat=None, lon=None, edge_id=req.destination_edge, speed_mps=0.0,
                eta_s=0.0, route_progress=1.0, step=step, status="ARRIVED",
            )
        )
        self._queue(request_id, step=step, actor="system:monitor")
        log.info("emergency request %s COMPLETED -- vehicle arrived", request_id)
        if self.on_arrival is not None:
            try:
                self.on_arrival(
                    self._requests[request_id], self._vehicles.get(req.vehicle_id),
                    step, sim_time_s,
                )
            except Exception:  # noqa: BLE001 -- a hook failure must not break the tick loop
                log.exception("on_arrival hook raised for request %s", request_id)

    # ---- SUMO vehicle spawn / teardown ------------------------

    def _spawn_ev(self, request_id: str) -> None:
        req = self._requests[request_id]
        if req.route is None:
            return
        edges = tuple(req.route.edges)
        dist_to_start: dict[str, float] = {}
        acc = 0.0
        for eid in edges:
            dist_to_start[eid] = acc
            acc += self.graph.edges[eid].length_m if eid in self.graph.edges else 0.0
        run = _EvRun(
            request_id=request_id, veh_id=req.vehicle_id, route_edges=edges,
            dist_to_edge_start=dist_to_start, total_length_m=acc,
        )
        route_id = f"ev-route-{request_id}"
        try:
            traci.route.add(route_id, list(edges))
            traci.vehicle.add(req.vehicle_id, route_id, typeID=_EV_TYPE_ID, departSpeed="max")
            traci.vehicle.setColor(req.vehicle_id, _EV_COLOR)
            run.spawned = True
        except Exception:  # noqa: BLE001
            log.exception("could not spawn emergency vehicle %s in SUMO", req.vehicle_id)
        self._ev_runs[request_id] = run

    def _teardown(self, request_id: str, *, reason: str, step: int) -> None:
        if self.corridor is not None:
            self.corridor.deactivate(request_id, reason=reason, step=step)
        run = self._ev_runs.pop(request_id, None)
        if run is None or not run.spawned:
            return
        try:
            if run.veh_id in set(traci.vehicle.getIDList()):
                traci.vehicle.remove(run.veh_id)
        except Exception:  # noqa: BLE001
            pass

    # ---- routing --------------------------------------------------

    def _route_and_transition(
        self,
        request_id: str,
        *,
        at_ms: int,
        step: int,
        sim_time_s: float,
        action: EmergencyRequestAction,
        actor: str = "system:router",
        detail: str = "",
        from_edge: str | None = None,
        conditions: Mapping[str, EdgeConditions] | None = None,
    ) -> None:
        """Plan (or replan, when `from_edge` is set) and apply `action`.

        `from_edge` is the vehicle's current edge for an in-flight reroute --
        the plan starts there, the request's own `source_edge` is unchanged, and
        on success the SUMO route and any active green corridor are re-pointed
        at the new path. A planning failure during an in-flight reroute keeps
        the current route (a moving vehicle is never abandoned mid-road); only
        the *initial* routing failure cancels the request.
        """
        req = self._requests[request_id]
        origin = from_edge or req.source_edge
        cond = dict(conditions) if conditions is not None else self.sample_conditions()
        try:
            routes = self.planner.plan(origin, req.destination_edge, cond)
        except NoRouteError as exc:
            if from_edge is not None:
                self._last_route_s[request_id] = sim_time_s  # cool down before retry
                self._queue(
                    request_id, step=step, actor="system:monitor",
                    detail=f"reroute held: {exc.reason}",
                )
                log.warning("emergency request %s reroute failed, holding route: %s",
                            request_id, exc.reason)
                return
            self._requests[request_id] = req.apply(
                EmergencyRequestAction.ROUTE_FAILED, at_ms=at_ms, actor="system:router",
                detail=exc.reason,
            )
            self._release_vehicle(req.vehicle_id)
            self._queue(request_id, step=step, actor="system:router")
            log.warning("emergency request %s route failed: %s", request_id, exc.reason)
            return

        best = routes[0]
        edges = tuple(best.edges)

        # re-point SUMO + green corridor first (in-flight reroute only), so the
        # single state transition below carries the new corridor id
        new_corridor_id: str | None = None
        if from_edge is not None:
            self._repoint_sumo_route(request_id, edges)
            req_now = self._requests[request_id]
            if self.corridor is not None and req_now.green_corridor_id:
                new_corridor_id = self.corridor.activate(
                    request_id=request_id, vehicle_id=req_now.vehicle_id,
                    route_edges=edges, now_ms=int(sim_time_s * 1000), step=step,
                )

        self._requests[request_id] = req.apply(
            action, at_ms=at_ms, actor=actor, detail=detail,
            route=best, eta_s=best.eta_s, green_corridor_id=new_corridor_id,
        )
        self._alt_cache[request_id] = routes[1:]
        self._last_route_s[request_id] = sim_time_s
        self._progress_at_route[request_id] = 0.0 if from_edge is not None else (
            self._ev_runs[request_id].last_progress_m if request_id in self._ev_runs else 0.0
        )
        log.info(
            "emergency request %s %s: %d-edge route, ETA %.0fs, score %.2f%s",
            request_id, self._requests[request_id].state.value,
            len(edges), best.eta_s, best.score,
            " (rerouted in flight)" if from_edge is not None else "",
        )
        self._queue(request_id, step=step, actor=actor, detail=detail)

    def _repoint_sumo_route(self, request_id: str, edges: tuple[str, ...]) -> None:
        """Push a new edge list to a driving EV and rebuild its progress table."""
        run = self._ev_runs.get(request_id)
        if run is None:
            return
        try:
            traci.vehicle.setRoute(run.veh_id, list(edges))
        except Exception:  # noqa: BLE001
            log.exception("could not update SUMO route for %s", run.veh_id)
        acc = 0.0
        dist_to_start: dict[str, float] = {}
        for eid in edges:
            dist_to_start[eid] = acc
            acc += self.graph.edges[eid].length_m if eid in self.graph.edges else 0.0
        run.route_edges = edges
        run.dist_to_edge_start = dist_to_start
        run.total_length_m = acc
        run.last_progress_m = 0.0

    # ---- continuous monitoring (Phase 7) ---------------------------

    def _monitor_routes(
        self, step: int, sim_time_s: float, progress_by_request: Mapping[str, float]
    ) -> None:
        """Re-evaluate every active route on a fixed interval; trigger an
        automatic reroute on a blocked/severe anomaly ahead or a materially
        cheaper replan. Cooldown + minimum-progress gates keep it from
        recomputing every tick or oscillating between near-equal routes."""
        monitorable = (EmergencyRequestState.ROUTE_READY, EmergencyRequestState.IN_TRANSIT)
        conditions: dict[str, EdgeConditions] | None = None

        for request_id, req in list(self._requests.items()):
            if req.state not in monitorable or req.route is None:
                continue
            if sim_time_s - self._last_monitor_s.get(request_id, -1e18) < _MONITOR_INTERVAL_S:
                continue
            self._last_monitor_s[request_id] = sim_time_s
            if (
                sim_time_s - self._last_route_s.get(request_id, -1e18)
                < self.config.reroute_cooldown_s
            ):
                continue

            run = self._ev_runs.get(request_id)
            in_transit = req.state is EmergencyRequestState.IN_TRANSIT
            if run is not None and run.total_length_m > 0:
                since_frac = (
                    run.last_progress_m - self._progress_at_route.get(request_id, 0.0)
                ) / run.total_length_m
                if since_frac < self.config.reroute_min_progress_frac:
                    continue

            current_edge = (
                run.current_edge if run is not None and run.current_edge else req.source_edge
            )
            remaining = self._remaining_edges(tuple(req.route.edges), current_edge)
            if len(remaining) < 2:
                continue

            reason = self._blocked_or_severe_ahead(remaining)
            if conditions is None:
                conditions = self.sample_conditions()
            if reason is None:
                reason = self._cheaper_replan(
                    current_edge, req.destination_edge, remaining, conditions
                )
            if reason is None:
                continue

            log.info("auto-reroute for %s (%s): %s", request_id, req.state.value, reason)
            self._route_and_transition(
                request_id,
                at_ms=int(sim_time_s * 1000),
                step=step,
                sim_time_s=sim_time_s,
                action=EmergencyRequestAction.REROUTE,
                actor="system:monitor",
                detail=f"auto-reroute — {reason}",
                from_edge=current_edge if in_transit else None,
                conditions=conditions,
            )

    @staticmethod
    def _remaining_edges(
        route_edges: tuple[str, ...], current_edge: str
    ) -> tuple[str, ...]:
        try:
            i = route_edges.index(current_edge)
        except ValueError:
            return route_edges  # EV drifted off-route -- treat the whole thing as ahead
        return route_edges[i:]

    def _blocked_or_severe_ahead(self, remaining: tuple[str, ...]) -> str | None:
        ahead = set(remaining)
        for a in self.anomalies.active_anomalies():
            if a.edge_id not in ahead:
                continue
            if self.config.reroute_on_blocked_edge and a.severity == AnomalySeverity.BLOCKED:
                return f"road blocked ahead on {a.edge_id}"
            if (
                self.config.reroute_on_new_severe_anomaly
                and a.severity in _SEVERE
                and a.anomaly_id not in self._severe_anomalies_seen
            ):
                self._severe_anomalies_seen.add(a.anomaly_id)
                return f"new {a.severity.value} anomaly ahead on {a.edge_id}"
        return None

    def _cheaper_replan(
        self,
        current_edge: str,
        dest_edge: str,
        remaining: tuple[str, ...],
        conditions: Mapping[str, EdgeConditions],
    ) -> str | None:
        try:
            current_eval = self.planner.evaluate(remaining, conditions)
        except NoRouteError as exc:
            return f"current route no longer viable ({exc.reason})"
        try:
            candidates = self.planner.plan(current_edge, dest_edge, conditions)
        except NoRouteError:
            return None  # nothing better on offer -- hold the current route
        best = candidates[0]
        if tuple(best.edges) == tuple(remaining):
            return None
        if current_eval.score > best.score * (1.0 + self.config.reroute_cost_increase_frac):
            return f"faster path available (score {current_eval.score:.1f} vs {best.score:.1f})"
        return None

    def sample_conditions(self) -> dict[str, EdgeConditions]:
        """Per graph edge: live occupancy + mean-speed fraction from TraCI,
        plus any active operator anomaly on that edge."""
        anomaly_by_edge: dict[str, tuple[str, float]] = {}
        for a in self.anomalies.active_anomalies():
            anomaly_by_edge[a.edge_id] = (a.severity.value, float(a.estimated_impact))

        out: dict[str, EdgeConditions] = {}
        for edge_id, info in self.graph.edges.items():
            try:
                # TraCI returns the occupied fraction of the edge, not a
                # percentage -- the `/ 100` this line used to apply pinned every
                # `congestion` value under 0.01 (see queue_state.py's unit note).
                occ = traci.edge.getLastStepOccupancy(edge_id)
                mean_speed = traci.edge.getLastStepMeanSpeed(edge_id)
            except traci.TraCIException:
                occ, mean_speed = 0.0, -1.0
            speed_frac = (
                1.0
                if mean_speed < 0
                else min(1.0, mean_speed / max(0.1, info.speed_limit_mps))
            )
            sev_impact = anomaly_by_edge.get(edge_id)
            out[edge_id] = EdgeConditions(
                congestion=max(0.0, min(1.0, occ)),
                mean_speed_frac=speed_frac,
                anomaly_severity=sev_impact[0] if sev_impact else None,
                anomaly_impact=sev_impact[1] if sev_impact else 0.0,
            )
        return out

    # ---- internals ---------------------------------------------

    def _release_vehicle(self, vehicle_id: str) -> None:
        v = self._vehicles.get(vehicle_id)
        if v is not None:
            self._vehicles[vehicle_id] = v.released()

    def _queue(self, request_id: str, *, step: int, actor: str, detail: str = "") -> None:
        req = self._requests[request_id]
        vehicle = self._vehicles.get(req.vehicle_id)
        kind = vehicle.kind.value if vehicle else "ambulance"
        self._events.append(
            emergency_request_payload(
                req, kind, self._alt_cache.get(request_id, []),
                step=step, actor=actor or req.history[-1].actor, detail=detail,
            )
        )


# ---------------------------------------------------------------------------
# payload builders  (match contracts/events/emergency_request_updated.avsc)
# ---------------------------------------------------------------------------


def route_summary(route: RouteResult) -> dict:
    c = route.cost
    return {
        "edges": list(route.edges),
        "rank": route.rank,
        "total_distance_m": route.total_distance_m,
        "total_travel_time_s": route.total_travel_time_s,
        "eta_s": route.eta_s,
        "n_intersections": route.n_intersections,
        "signalised_intersections": list(route.signalised_intersections),
        "congested_segments": list(route.congested_segments),
        "anomalous_segments_avoided": list(route.anomalous_segments_avoided),
        "reliable": route.reliable,
        "cost_travel_time_s": c.travel_time_s,
        "cost_congestion": c.congestion_cost,
        "cost_anomaly": c.anomaly_cost,
        "cost_signal_delay_s": c.signal_delay_s,
        "cost_disruption": c.disruption_cost,
        "cost_reliability": c.reliability_cost,
        "route_score": c.total_score,
        "weights_used": dict(route.weights_used),
    }


def emergency_request_payload(
    req: EmergencyRequest,
    vehicle_kind: str,
    alternatives: list[RouteResult],
    *,
    step: int | None = None,
    actor: str = "system:router",
    detail: str = "",
) -> dict:
    last = req.history[-1] if req.history else None
    return {
        "request_id": req.request_id,
        "vehicle_id": req.vehicle_id,
        "vehicle_kind": vehicle_kind,
        "state": req.state.name,
        "source_edge": req.source_edge,
        "destination_edge": req.destination_edge,
        "eta_s": req.eta_s,
        "green_corridor_id": req.green_corridor_id,
        "route": route_summary(req.route) if req.route is not None else None,
        "alternatives": [route_summary(r) for r in alternatives],
        "chain_hash": req.chain_head,
        "actor": actor,
        "detail": detail or (last.detail if last else ""),
        "sim_tick": step,
        "updated_at": last.at_ms if last else 0,
    }


def emergency_vehicle_payload(
    req: EmergencyRequest,
    vehicle: EmergencyVehicle | None,
    *,
    lat: float | None,
    lon: float | None,
    edge_id: str | None,
    speed_mps: float,
    eta_s: float | None,
    route_progress: float,
    step: int | None = None,
    status: str | None = None,
) -> dict:
    """Matches contracts/events/emergency_vehicle_updated.avsc."""
    if status is None:
        status = vehicle.status.name if vehicle else "EN_ROUTE"
    return {
        "vehicle_id": req.vehicle_id,
        "request_id": req.request_id,
        "vehicle_kind": vehicle.kind.value if vehicle else "ambulance",
        "status": status,
        "lat": lat,
        "lon": lon,
        "edge_id": edge_id,
        "speed_mps": float(speed_mps),
        "eta_s": eta_s,
        "route_progress": float(route_progress),
        "sim_tick": step,
    }

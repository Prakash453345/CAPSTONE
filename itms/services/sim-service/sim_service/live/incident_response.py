"""Turns a sufficiently severe `Anomaly` into an alert (with GPS) and one
`EmergencyRequest` + green corridor per responding authority kind, then --
for an ambulance -- a chained dispatch to the nearest hospital once it
arrives at the incident, if one is needed.

This is the missing *caller*, not new dispatch or routing logic. Everything
it does is compose pieces that already existed and were never wired
together: `EmergencyController.handle_create` + `ACTIVATE_CORRIDOR` already
run one request through routing and a green corridor end to end -- it was
just never called more than once per incident. `control.dispatch.dispatcher.
choose` already picks the nearest capable hospital by live travel time --
nothing called it. `signal_controller.ev_routing.traci_route_fn` /
`edge_latlon` are the live `RouteFn` / GPS lookup `dispatcher.choose` was
written to be injected with -- nothing had wired those in either.

**Depot data.** Police units are drawn from `responder_depots.json`
(`extract_responder_depots.py`, real OSM `amenity=police` nodes). Ambulances
are drawn from the existing `facilities.json` hospitals -- an ambulance is
assumed to be based at a hospital, which needs no new data. Fire trucks have
no real depot data in this corridor's OSM extract (see
`extract_responder_depots.py`'s docstring); the response map still names
`FIRE_TRUCK` for an accident, it just never finds a unit to send until real
data exists, and that shows up as `undispatched_kinds` on the alert.

**Anomaly -> authority mapping.** `itms_domain.anomaly.AnomalyType` has no
`FIRE` value -- its values are road-network disruptions (accident, lane
blockage, ...), not incident categories. `ACCIDENT` is the closest analog to
a fire-accident scenario, so it is the one type that pages all three
authorities; the rest page police only, and pure congestion pages no one.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from itms_domain import (
    Anomaly,
    AnomalySeverity,
    AnomalyType,
    EmergencyKind,
    EmergencyRequest,
    EmergencyRequestState,
    EmergencyVehicle,
)

from sim_service.control.dispatch.crew_index import (
    Candidate,
    Crew,
    CrewIndex,
    rank_by_road_time,
)
from sim_service.control.dispatch.dispatcher import IncidentRequest, choose
from sim_service.control.dispatch.facilities import GENERAL, FacilityIndex
from sim_service.live.anomaly_control import OperatorAnomalyController
from sim_service.live.emergency_control import EmergencyController
from sim_service.signal_controller.ev_routing import edge_latlon, traci_route_fn

log = logging.getLogger("sim-service.live.incident_response")

# the scenario's own facilities (itms_domain.scenario: the Vijayawada corridor
# unless ITMS_SCENARIO names another network); a network without the files
# gets no hospitals and no police depots, and the incident layer says so
from itms_domain.scenario import current as _current_scenario  # noqa: E402

_SCEN = _current_scenario().directory
FACILITIES_PATH = _SCEN / "facilities.json"
DEPOTS_PATH = _SCEN / "responder_depots.json"

_KIND_BY_NAME = {k.name: k for k in EmergencyKind}

_RESPONDING_SEVERITIES = frozenset(
    {AnomalySeverity.MEDIUM, AnomalySeverity.HIGH, AnomalySeverity.BLOCKED}
)
"""LOW-severity anomalies don't page anyone -- a minor blip isn't an
emergency. Configurable by editing this set."""

_RESPONSE_MAP: dict[AnomalyType, tuple[EmergencyKind, ...]] = {
    AnomalyType.ACCIDENT: (
        EmergencyKind.POLICE, EmergencyKind.AMBULANCE, EmergencyKind.FIRE_TRUCK,
    ),
    AnomalyType.VEHICLE_BREAKDOWN: (EmergencyKind.POLICE,),
    AnomalyType.STALLED_VEHICLE: (EmergencyKind.POLICE,),
    AnomalyType.LANE_BLOCKAGE: (EmergencyKind.POLICE,),
    AnomalyType.ROAD_OBSTRUCTION: (EmergencyKind.POLICE,),
    AnomalyType.HEAVY_CONGESTION: (),
    AnomalyType.FIRE: (EmergencyKind.FIRE_TRUCK, EmergencyKind.POLICE),
    AnomalyType.UNKNOWN: (EmergencyKind.POLICE,),
}


@dataclass(frozen=True)
class _Depot:
    depot_id: str
    name: str
    edge: str
    lat: float
    lon: float


@dataclass
class _Unit:
    """A responding unit. Where it is and whether it is free live on its
    `Crew` record, which is what the hex index searches; `busy` is just the
    inverse of `crew.available`, kept so the rest of this module reads the
    same as before."""

    vehicle_id: str
    kind: EmergencyKind
    depot: _Depot
    crew: Crew

    @property
    def busy(self) -> bool:
        return not self.crew.available

    @busy.setter
    def busy(self, value: bool) -> None:
        self.crew.available = not value


SHORTLIST = 5
"""How many nearby crews of a kind are considered (and notified) per call.
The nearest by *road time* among them is the one sent."""

# ---- waiting calls (added 2026-10-27) -------------------------------
# A call whose kind had no free unit used to be logged ("skipping") and then
# forgotten: the anomaly was marked seen, so when a unit came free nothing went
# back for it. Now it waits in a queue, and each tick the waiting calls are
# served in priority order by whichever units are free.
_SEVERITY_RANK = {
    AnomalySeverity.HIGH: 3,
    AnomalySeverity.BLOCKED: 3,
    AnomalySeverity.MEDIUM: 2,
}
QUEUE_AGING_S = 600.0
"""A waiting call gains one priority step per this many seconds, so a
medium-severity call is not starved by a stream of high-severity ones."""

_EN_ROUTE = (
    EmergencyRequestState.ROUTE_READY,
    EmergencyRequestState.GREEN_CORRIDOR_ACTIVE,
    EmergencyRequestState.IN_TRANSIT,
)


@dataclass
class _Call:
    """One need -- one unit of one kind -- for one anomaly."""

    anomaly_id: str
    anomaly_type: str
    severity: AnomalySeverity
    kind: EmergencyKind
    edge_id: str
    since_s: float
    lat: float | None = None
    lon: float | None = None
    dispatches: int = field(default=0)
    failed_units: set[str] = field(default_factory=set)  # units with no road to it

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK.get(self.severity, 1)

    def priority(self, now_s: float) -> float:
        return self.rank + max(0.0, now_s - self.since_s) / QUEUE_AGING_S


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def load_police_depots(path: Path = DEPOTS_PATH) -> list[_Depot]:
    import json

    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [
        _Depot(depot_id=d["id"], name=d["name"], edge=d["edge"], lat=d["lat"], lon=d["lon"])
        for d in raw["depots"]
        if d["kind"] == "police"
    ]


def load_hospital_depots(index: FacilityIndex) -> list[_Depot]:
    return [
        _Depot(depot_id=f.id, name=f.name, edge=f.edge, lat=f.lat, lon=f.lon)
        for f in index.all
        if f.kind == "hospital"
    ]


class IncidentResponseOrchestrator:
    """Watches `anomalies` for newly-active, sufficiently severe anomalies;
    for each, dispatches one unit per `_RESPONSE_MAP` authority kind through
    `emergency`, and registers itself as `emergency.on_arrival` so an
    ambulance that finishes at the incident gets chained to the nearest
    hospital instead of just going idle."""

    def __init__(
        self,
        anomalies: OperatorAnomalyController,
        emergency: EmergencyController,
        *,
        facility_index: FacilityIndex | None = None,
        police_depots: list[_Depot] | None = None,
        crew_dispatcher=None,
    ):
        self.anomalies = anomalies
        self.emergency = emergency
        # When a real crew of the needed kind exists (a signed-in account with
        # a vehicle), the call is *offered* to the nearest one and only becomes
        # a dispatch when they accept -- `crew_dispatch.CrewDispatcher`. The
        # depot units below stay as the fallback for kinds nobody crews, so a
        # scenario with no crew accounts behaves exactly as it did before.
        self.crew_dispatcher = crew_dispatcher
        if facility_index is None:
            if FACILITIES_PATH.exists():
                facility_index = FacilityIndex.from_json(FACILITIES_PATH)
            else:
                log.warning("no %s: this scenario has no hospitals to dispatch to",
                            FACILITIES_PATH)
                facility_index = FacilityIndex([])
        self._facility_index = facility_index
        self._crews = CrewIndex()
        self._units: dict[EmergencyKind, list[_Unit]] = {
            EmergencyKind.POLICE: [
                self._unit(f"unit-police-{i}", EmergencyKind.POLICE, d)
                for i, d in enumerate(
                    police_depots if police_depots is not None else load_police_depots()
                )
            ],
            EmergencyKind.AMBULANCE: [
                self._unit(f"unit-ambulance-{i}", EmergencyKind.AMBULANCE, d)
                for i, d in enumerate(load_hospital_depots(self._facility_index))
            ],
            EmergencyKind.FIRE_TRUCK: [],  # no real depot data yet
        }
        self._unit_by_vehicle_id: dict[str, _Unit] = {
            u.vehicle_id: u for units in self._units.values() for u in units
        }
        self._seen_anomalies: set[str] = set()
        self._waiting: dict[tuple[str, EmergencyKind], _Call] = {}
        self._call_of_request: dict[str, _Call] = {}  # incident request -> what it serves
        self._suggestions: dict[str, dict] = {}       # open reassignment suggestions
        self._suggested: set[tuple[str, str]] = set()  # (vehicle, anomaly) already suggested
        self._seq = 0
        self._pending_hospital: set[str] = set()  # vehicle_id awaiting a chained hospital leg
        self._events: list[dict] = []
        emergency.on_arrival = self._on_emergency_arrival

    def _unit(self, vehicle_id: str, kind: EmergencyKind, depot: _Depot) -> _Unit:
        crew = Crew(
            crew_id=vehicle_id, kind=kind.name, lat=depot.lat, lon=depot.lon,
            edge=depot.edge, label=depot.name,
        )
        self._crews.add(crew)
        return _Unit(vehicle_id=vehicle_id, kind=kind, depot=depot, crew=crew)

    # ---- the crew roster ---------------------------------------------

    @property
    def crews(self) -> CrewIndex:
        """The hex index of every known crew (depot-based simulated units today;
        a crew with live GPS is registered through `register_crew`)."""
        return self._crews

    def register_crew(
        self, vehicle_id: str, kind: EmergencyKind, *, lat: float, lon: float, edge: str,
        name: str = "",
    ) -> None:
        """Add (or re-home) a crew so it can be found and dispatched."""
        depot = _Depot(depot_id=vehicle_id, name=name or vehicle_id, edge=edge, lat=lat, lon=lon)
        existing = self._unit_by_vehicle_id.get(vehicle_id)
        if existing is not None:
            self._crews.move(vehicle_id, lat, lon, edge=edge)
            existing.depot = depot
            return
        unit = self._unit(vehicle_id, kind, depot)
        self._units.setdefault(kind, []).append(unit)
        self._unit_by_vehicle_id[vehicle_id] = unit

    def update_crew_position(self, vehicle_id: str, lat: float, lon: float,
                             edge: str | None = None) -> None:
        """A live position for a crew; cheap unless it crossed into another cell."""
        if vehicle_id in self._crews:
            self._crews.move(vehicle_id, lat, lon, edge=edge)

    # ---- per-tick --------------------------------------------------

    def tick(self, step: int, sim_time_s: float) -> None:
        self._free_idle_crews()
        new = []
        for anomaly in self.anomalies.active_anomalies():
            if anomaly.anomaly_id in self._seen_anomalies:
                continue
            self._seen_anomalies.add(anomaly.anomaly_id)
            if anomaly.severity in _RESPONDING_SEVERITIES:
                new.append(anomaly)
        # several new calls in one tick: the most severe gets the free unit
        # first (stable, so equal severities keep their reporting order)
        new.sort(key=lambda a: -_SEVERITY_RANK.get(a.severity, 1))
        for anomaly in new:
            self._dispatch(anomaly, step=step, sim_time_s=sim_time_s)
        self._serve_queue(step=step, sim_time_s=sim_time_s)
        self._suggest_reassignments(step=step, sim_time_s=sim_time_s)

    def drain_events(self) -> list[dict]:
        out, self._events = self._events, []
        return out

    def _free_idle_crews(self) -> None:
        """A request can end without the vehicle arriving (an operator cancels it,
        or routing fails), which never reaches `on_arrival`. Without this the
        crew would stay marked busy and never be offered another call."""
        working = {r.vehicle_id for r in self.emergency.active_requests()}
        for unit in self._unit_by_vehicle_id.values():
            if unit.vehicle_id not in working:
                unit.busy = False
                # a trip that ended without arriving (cancelled, reassigned
                # away, failed) must not leave a hospital leg armed for the
                # unit's *next* trip, which may not be an incident at all
                self._pending_hospital.discard(unit.vehicle_id)
        # trips that have ended no longer need their call on record
        for rid in [rid for rid in self._call_of_request
                    if (r := self.emergency.get_request(rid)) is None or r.is_terminal]:
            del self._call_of_request[rid]

    # ---- initial dispatch -------------------------------------------

    def _dispatch(self, anomaly: Anomaly, *, step: int, sim_time_s: float) -> None:
        kinds = _RESPONSE_MAP.get(anomaly.anomaly_type, ())
        if not kinds:
            return
        try:
            lat, lon = edge_latlon(anomaly.edge_id)
        except Exception:  # noqa: BLE001 -- TraCI down / edge has no lanes
            log.exception(
                "could not resolve GPS for anomaly %s on %s", anomaly.anomaly_id, anomaly.edge_id
            )
            lat, lon = None, None

        dispatched: list[dict] = []
        undispatched: list[str] = []
        queued: list[str] = []
        offered: list[str] = []
        notified: list[dict] = []
        for kind in kinds:
            call = _Call(
                anomaly_id=anomaly.anomaly_id, anomaly_type=anomaly.anomaly_type.value,
                severity=anomaly.severity, kind=kind, edge_id=anomaly.edge_id,
                since_s=sim_time_s, lat=lat, lon=lon,
            )
            if self._offer_to_crew(anomaly, kind, sim_time_s=sim_time_s):
                offered.append(kind.value)
                continue
            if any(k is kind for (_, k) in self._waiting):
                # older calls of this kind are already waiting: join the
                # queue, which is served in priority order right after this
                # (a unit that just came free must not go to the newest call
                # ahead of a more urgent one that has been waiting)
                self._waiting[(anomaly.anomaly_id, kind)] = call
                undispatched.append(kind.value)
                queued.append(kind.value)
                continue
            unit, shortlist = self._nearest_available(kind, lat, lon, anomaly.edge_id)
            notified.extend(shortlist)
            if unit is None:
                undispatched.append(kind.value)
                if self._units.get(kind):
                    # units of this kind exist, all busy: wait for one
                    self._waiting[(anomaly.anomaly_id, kind)] = call
                    queued.append(kind.value)
                    log.info(
                        "no free %s unit for anomaly %s -- queued (%d waiting)",
                        kind.value, anomaly.anomaly_id, len(self._waiting),
                    )
                else:
                    log.info(
                        "no %s units exist for anomaly %s -- skipping",
                        kind.value, anomaly.anomaly_id,
                    )
                continue
            request_id = f"resp-{anomaly.anomaly_id}-{kind.value}"
            unit.busy = True
            ok = self._create_and_activate(
                request_id=request_id, vehicle_id=unit.vehicle_id, kind=kind,
                source_edge=unit.depot.edge, dest_edge=anomaly.edge_id,
                step=step, sim_time_s=sim_time_s,
            )
            if not ok:
                unit.busy = False
                undispatched.append(kind.value)
                call.failed_units.add(unit.vehicle_id)
                if self._reachable_by_some(call):
                    # this unit has no road there; another one might
                    self._waiting[(anomaly.anomaly_id, kind)] = call
                    queued.append(kind.value)
                continue
            call.dispatches += 1
            self._call_of_request[request_id] = call
            if kind is EmergencyKind.AMBULANCE:
                self._pending_hospital.add(unit.vehicle_id)
            dispatched.append(
                {"vehicle_kind": kind.name, "vehicle_id": unit.vehicle_id, "request_id": request_id}
            )

        self._events.append({
            "anomaly_id": anomaly.anomaly_id,
            "anomaly_type": anomaly.anomaly_type.value,
            "severity": anomaly.severity.value,
            "edge_id": anomaly.edge_id,
            "lat": lat,
            "lon": lon,
            "dispatched": dispatched,
            # Offered to a real crew and waiting on their answer: not yet a
            # dispatch, and not a failure to find anyone either.
            "offered_kinds": offered,
            "undispatched_kinds": undispatched,
            "queued_kinds": queued,
            "notified": notified,
            "at_ms": int(sim_time_s * 1000),
            "sim_tick": step,
        })
        log.info(
            "incident response for anomaly %s (%s/%s): dispatched %s, no unit for %s",
            anomaly.anomaly_id, anomaly.anomaly_type.value, anomaly.severity.value,
            [d["vehicle_kind"] for d in dispatched], undispatched,
        )

    # ---- the waiting queue -----------------------------------------

    @property
    def waiting(self) -> list[dict]:
        """Calls waiting for a unit, most severe first, then longest waiting
        (for the console; the queue itself also ages calls, see `_Call.priority`)."""
        return [
            {"anomaly_id": c.anomaly_id, "kind": c.kind.value, "severity": c.severity.value,
             "since_s": c.since_s}
            for c in sorted(self._waiting.values(), key=lambda c: (-c.rank, c.since_s))
        ]

    def _serve_queue(self, *, step: int, sim_time_s: float) -> None:
        """Send free units to waiting calls, highest priority first. A call
        whose anomaly has been resolved or cancelled meanwhile is dropped."""
        if not self._waiting:
            return
        active = {a.anomaly_id for a in self.anomalies.active_anomalies()}
        for key, call in list(self._waiting.items()):
            if call.anomaly_id not in active:
                del self._waiting[key]
                log.info("waiting %s call for %s dropped: anomaly no longer active",
                         call.kind.value, call.anomaly_id)
        order = sorted(
            self._waiting.values(), key=lambda c: (-c.priority(sim_time_s), c.since_s)
        )
        for call in order:
            while any(not u.busy and u.vehicle_id not in call.failed_units
                      for u in self._units.get(call.kind, ())):
                unit, notified = self._nearest_available(
                    call.kind, call.lat, call.lon, call.edge_id, exclude=call.failed_units)
                if unit is None:
                    break
                if self._send(call, unit, source_edge=unit.depot.edge, step=step,
                              sim_time_s=sim_time_s, notified=notified):
                    break
            if (call.anomaly_id, call.kind) in self._waiting and not self._reachable_by_some(call):
                self._drop_unreachable(call, step=step, sim_time_s=sim_time_s)

    def _reachable_by_some(self, call: _Call) -> bool:
        """Whether any unit of the call's kind has not yet failed to route there."""
        return any(u.vehicle_id not in call.failed_units for u in self._units.get(call.kind, ()))

    def _drop_unreachable(self, call: _Call, *, step: int, sim_time_s: float) -> None:
        """No unit of this kind has a road to the call: retrying every tick
        would only create a failed trip per tick. Say so once and stop."""
        self._waiting.pop((call.anomaly_id, call.kind), None)
        log.warning("waiting %s call for %s dropped: no %s unit can reach %s",
                    call.kind.value, call.anomaly_id, call.kind.value, call.edge_id)
        self._events.append({
            "anomaly_id": call.anomaly_id,
            "anomaly_type": call.anomaly_type,
            "severity": call.severity.value,
            "edge_id": call.edge_id,
            "lat": call.lat,
            "lon": call.lon,
            "dispatched": [],
            "undispatched_kinds": [call.kind.value],
            "queued_kinds": [],
            "notified": [],
            "at_ms": int(sim_time_s * 1000),
            "sim_tick": step,
        })

    def _send(
        self, call: _Call, unit: _Unit, *, source_edge: str, step: int, sim_time_s: float,
        notified: list[dict] | None = None, reassigned_from: str | None = None,
        depart_pos_m: float | None = None,
    ) -> bool:
        """Dispatch `unit` to a waiting `call` and announce it. A routing
        failure from the unit's depot marks the unit as unable to reach the
        call; one from wherever a reassigned unit happens to be does not."""
        self._seq += 1
        request_id = f"resp-{call.anomaly_id}-{call.kind.value}-q{self._seq}"
        unit.busy = True
        ok = self._create_and_activate(
            request_id=request_id, vehicle_id=unit.vehicle_id, kind=call.kind,
            source_edge=source_edge, dest_edge=call.edge_id, step=step, sim_time_s=sim_time_s,
            depart_pos_m=depart_pos_m,
        )
        if not ok:
            unit.busy = False
            if source_edge == unit.depot.edge:
                call.failed_units.add(unit.vehicle_id)
            return False
        self._waiting.pop((call.anomaly_id, call.kind), None)
        call.dispatches += 1
        self._call_of_request[request_id] = call
        if call.kind is EmergencyKind.AMBULANCE:
            self._pending_hospital.add(unit.vehicle_id)
        waited = round(sim_time_s - call.since_s, 1)
        self._events.append({
            "anomaly_id": call.anomaly_id,
            "anomaly_type": call.anomaly_type,
            "severity": call.severity.value,
            "edge_id": call.edge_id,
            "lat": call.lat,
            "lon": call.lon,
            "dispatched": [{"vehicle_kind": call.kind.name, "vehicle_id": unit.vehicle_id,
                            "request_id": request_id}],
            "undispatched_kinds": [],
            "notified": notified or [],
            "waited_s": waited,
            "reassigned_from": reassigned_from,
            "at_ms": int(sim_time_s * 1000),
            "sim_tick": step,
        })
        log.info("waiting %s call for %s served by %s after %.0f s%s", call.kind.value,
                 call.anomaly_id, unit.vehicle_id, waited,
                 f" (reassigned from {reassigned_from})" if reassigned_from else "")
        return True

    # ---- reassignment suggestions ------------------------------------

    def _suggest_reassignments(self, *, step: int, sim_time_s: float) -> None:
        """For a waiting call, find a unit of its kind still on its way to a
        call of *lower severity* and suggest moving it. Never done
        automatically: the operator confirms (`accept_reassignment`), because
        the crew may already be close to people who need them."""
        # A suggestion stops applying once the unit's trip has ended (arrived,
        # cancelled) or the call it was for is no longer waiting (served by a
        # unit that came free, or resolved). Left open, it would block every
        # later suggestion for that unit.
        for sid, s in list(self._suggestions.items()):
            req = self.emergency.get_request(s["request_id"])
            if req is None or req.state not in _EN_ROUTE or s["to"] not in self._waiting:
                del self._suggestions[sid]
        if not self._waiting:
            return
        route_fn = None
        open_vehicles = {v["vehicle_id"] for v in self._suggestions.values()}
        open_calls = {v["to"] for v in self._suggestions.values()}
        for call in sorted(self._waiting.values(), key=lambda c: (-c.rank, c.since_s)):
            if (call.anomaly_id, call.kind) in open_calls:
                continue  # one suggestion at a time per call
            best: tuple[float, _Unit, str, _Call] | None = None
            for rid, served in self._call_of_request.items():
                if served.kind is not call.kind or served.rank >= call.rank:
                    continue
                req = self.emergency.get_request(rid)
                if req is None or req.state not in _EN_ROUTE:
                    continue
                if (req.vehicle_id, call.anomaly_id) in self._suggested:
                    continue
                if req.vehicle_id in open_vehicles:
                    continue  # one open suggestion per unit: the most severe call asks first
                unit = self._unit_by_vehicle_id.get(req.vehicle_id)
                here = self.emergency.current_edge(rid)
                if unit is None or here is None:
                    continue
                eta = None
                try:
                    route_fn = route_fn or traci_route_fn()
                    routed = route_fn(here, call.edge_id)
                    eta = routed[1] if routed is not None else None
                except Exception:  # noqa: BLE001 -- no SUMO (tests): rank unknown
                    eta = None
                key = eta if eta is not None else math.inf
                if best is None or key < best[0]:
                    best = (key, unit, rid, served)
            if best is None:
                continue
            eta, unit, rid, served = best
            self._seq += 1
            sid = f"reassign-{self._seq}"
            self._suggested.add((unit.vehicle_id, call.anomaly_id))
            open_vehicles.add(unit.vehicle_id)
            self._suggestions[sid] = {"vehicle_id": unit.vehicle_id, "request_id": rid,
                                      "to": (call.anomaly_id, call.kind)}
            self._events.append({
                "anomaly_id": call.anomaly_id,
                "anomaly_type": call.anomaly_type,
                "severity": call.severity.value,
                "edge_id": call.edge_id,
                "lat": call.lat,
                "lon": call.lon,
                "dispatched": [],
                "undispatched_kinds": [call.kind.value],
                "queued_kinds": [call.kind.value],
                "notified": [],
                "reassign_suggestions": [{
                    "suggestion_id": sid,
                    "vehicle_id": unit.vehicle_id,
                    "from_anomaly_id": served.anomaly_id,
                    "from_severity": served.severity.value,
                    "eta_s": None if not math.isfinite(eta) else round(eta, 1),
                }],
                "at_ms": int(sim_time_s * 1000),
                "sim_tick": step,
            })
            log.info("suggest moving %s from %s (%s) to %s (%s)", unit.vehicle_id,
                     served.anomaly_id, served.severity.value, call.anomaly_id,
                     call.severity.value)

    def accept_reassignment(self, suggestion_id: str, *, step: int, sim_time_s: float) -> bool:
        """The operator confirmed a suggestion: cancel the unit's current trip,
        put that call back in the queue (keeping its original waiting time),
        and send the unit from where it is now to the more severe call."""
        s = self._suggestions.pop(suggestion_id, None)
        if s is None:
            log.warning("unknown or already used reassignment %s", suggestion_id)
            return False
        call = self._waiting.get(s["to"])
        old = self._call_of_request.get(s["request_id"])
        req = self.emergency.get_request(s["request_id"])
        unit = self._unit_by_vehicle_id.get(s["vehicle_id"])
        if call is None or old is None or unit is None or req is None or req.state not in _EN_ROUTE:
            log.info("reassignment %s no longer applies", suggestion_id)
            return False
        here = self.emergency.current_edge(s["request_id"]) or req.source_edge
        pos = self.emergency.current_lane_pos(s["request_id"])
        self.emergency.handle_command(
            {"request_id": s["request_id"], "action": "CANCEL",
             "operator": "system:incident-response",
             "reason": f"reassigned to {call.anomaly_id}"},
            step=step, sim_time_s=sim_time_s,
        )
        self._call_of_request.pop(s["request_id"], None)
        if any(a.anomaly_id == old.anomaly_id for a in self.anomalies.active_anomalies()):
            self._waiting[(old.anomaly_id, old.kind)] = old  # back in line, original wait kept
        ok = self._send(call, unit, source_edge=here, step=step, sim_time_s=sim_time_s,
                        reassigned_from=old.anomaly_id, depart_pos_m=pos)
        if not ok:
            unit.busy = False
        return ok

    def _offer_to_crew(self, anomaly: Anomaly, kind: EmergencyKind, *, sim_time_s: float) -> bool:
        """Offer this call to the nearest real crew of `kind`. True if an offer
        went out -- the dispatch then happens on their accept, not here."""
        if self.crew_dispatcher is None:
            return False
        offer = self.crew_dispatcher.request(
            f"resp-{anomaly.anomaly_id}-{kind.value}",
            kind,
            anomaly.edge_id,
            now_s=sim_time_s,
        )
        if offer is None:
            return False
        log.info(
            "offered anomaly %s (%s) to %s", anomaly.anomaly_id, kind.value, offer.unit_id
        )
        return True

    def _nearest_available(
        self, kind: EmergencyKind, lat: float | None, lon: float | None, dest_edge: str,
        exclude: set[str] | frozenset[str] = frozenset(),
    ) -> tuple[_Unit | None, list[dict]]:
        """The unit to send, and the shortlist that was weighed (every crew on
        it is told about the call; only the first is sent).

        Hex-index shortlist by straight line, then re-ranked by live road
        travel time (a crew across the river is not "near"). With no GPS for
        the call there is nothing to search around, so the first free crew
        of the kind is used."""
        free = [u for u in self._units.get(kind, ()) if not u.busy and u.vehicle_id not in exclude]
        if lat is None or lon is None:
            return (free[0] if free else None), []
        # last resort when nobody is within the hex search radius: the free
        # unit nearest in a straight line, however far
        free.sort(key=lambda u: _haversine_m(lat, lon, u.crew.lat, u.crew.lon))
        shortlist = [c for c in self._crews.nearest(lat, lon, kind.name, k=SHORTLIST + len(exclude))
                     if c.crew.crew_id not in exclude][:SHORTLIST]
        if not shortlist:
            return (free[0] if free else None), []
        ranked = self._rank(shortlist, dest_edge)
        chosen = self._unit_by_vehicle_id[ranked[0].crew.crew_id]
        return chosen, [_notified(c, selected=c is ranked[0]) for c in ranked]

    def _rank(self, shortlist: list[Candidate], dest_edge: str) -> list[Candidate]:
        try:
            route_fn = traci_route_fn()
        except Exception:  # noqa: BLE001 -- TraCI not up: air order stands
            return shortlist

        def road_time(crew: Crew) -> float | None:
            if crew.edge is None:
                return None
            try:
                routed = route_fn(crew.edge, dest_edge)
            except Exception:  # noqa: BLE001
                return None
            return routed[1] if routed is not None else None

        return rank_by_road_time(shortlist, road_time)

    def assign_nearest(self, kind: EmergencyKind, dest_edge: str) -> _Unit | None:
        """For an operator's "send me the nearest <kind>" request: pick the crew,
        mark it busy, and return it (None if no crew of that kind is free)."""
        try:
            lat, lon = edge_latlon(dest_edge)
        except Exception:  # noqa: BLE001
            lat, lon = None, None
        unit, _ = self._nearest_available(kind, lat, lon, dest_edge)
        if unit is not None:
            unit.busy = True
        return unit

    def handle_nearest_request(
        self, payload: dict, *, step: int, sim_time_s: float, create
    ) -> None:
        """An operator asked dispatch for "the nearest <kind>" to a destination
        (an `EmergencyRequestCreated` with an empty `vehicle_id`). Picks the crew
        the same way an anomaly does, then hands the completed payload to
        `create` (normally `EmergencyController.handle_create`). With no free
        crew of that kind it raises the same alert an anomaly would, with the
        kind under `undispatched_kinds`, so the console says so instead of
        silently doing nothing."""
        kind = _KIND_BY_NAME.get(str(payload.get("vehicle_kind", "AMBULANCE")),
                                 EmergencyKind.AMBULANCE)
        dest_edge = str(payload["destination_edge"])
        unit = self.assign_nearest(kind, dest_edge)
        try:
            lat, lon = edge_latlon(dest_edge)
        except Exception:  # noqa: BLE001
            lat, lon = None, None
        request_id = str(payload["request_id"])
        event: dict[str, object] = {
            "anomaly_id": request_id,
            "anomaly_type": "operator_request",
            "severity": "high",
            "edge_id": dest_edge,
            "lat": lat,
            "lon": lon,
            "dispatched": [],
            "undispatched_kinds": [],
            "notified": [],
            "at_ms": int(sim_time_s * 1000),
            "sim_tick": step,
        }
        if unit is None:
            event["undispatched_kinds"] = [kind.value]
            self._events.append(event)
            log.info("no free %s crew for operator request %s", kind.value, request_id)
            return
        create(
            {**payload, "vehicle_id": unit.vehicle_id, "source_edge": unit.depot.edge,
             "vehicle_kind": kind.name},
            step=step, sim_time_s=sim_time_s,
        )
        event["dispatched"] = [
            {"vehicle_kind": kind.name, "vehicle_id": unit.vehicle_id, "request_id": request_id}
        ]
        self._events.append(event)

    def release(self, vehicle_id: str) -> None:
        """Give a crew back to the pool (its request ended without arriving)."""
        unit = self._unit_by_vehicle_id.get(vehicle_id)
        if unit is not None:
            unit.busy = False

    def _create_and_activate(
        self, *, request_id: str, vehicle_id: str, kind: EmergencyKind,
        source_edge: str, dest_edge: str, step: int, sim_time_s: float,
        depart_pos_m: float | None = None,
    ) -> bool:
        """Create the request and (if routing succeeded) activate its
        corridor. Returns whether the vehicle is actually on its way --
        False means routing failed and the request went straight to
        CANCELLED (no vehicle spawned, nothing further to free later)."""
        self.emergency.handle_create(
            {
                "request_id": request_id,
                "vehicle_id": vehicle_id,
                "vehicle_kind": kind.name,
                "source_edge": source_edge,
                "destination_edge": dest_edge,
                "operator": "system:incident-response",
                **({"depart_pos_m": depart_pos_m} if depart_pos_m is not None else {}),
            },
            step=step, sim_time_s=sim_time_s,
        )
        req = self.emergency.get_request(request_id)
        if req is None or req.state is not EmergencyRequestState.ROUTE_READY:
            log.info(
                "dispatch %s could not be routed (state=%s) -- not activating a corridor",
                request_id, req.state.value if req is not None else "unknown",
            )
            return False
        self.emergency.handle_command(
            {
                "request_id": request_id,
                "action": "ACTIVATE_CORRIDOR",
                "operator": "system:incident-response",
            },
            step=step, sim_time_s=sim_time_s,
        )
        return True

    # ---- chained dispatch (ambulance -> hospital) --------------------

    def _on_emergency_arrival(
        self, request: EmergencyRequest, vehicle: EmergencyVehicle | None,
        step: int, sim_time_s: float,
    ) -> None:
        unit = self._unit_by_vehicle_id.get(request.vehicle_id)
        chained = False
        if request.vehicle_id in self._pending_hospital:
            self._pending_hospital.discard(request.vehicle_id)
            chained = self._chain_to_hospital(request, step=step, sim_time_s=sim_time_s)
        if unit is not None and not chained:
            unit.busy = False  # back to normal (idle at its depot) -- spec #4/#6

    def _chain_to_hospital(
        self, request: EmergencyRequest, *, step: int, sim_time_s: float
    ) -> bool:
        try:
            lat, lon = edge_latlon(request.destination_edge)
        except Exception:  # noqa: BLE001
            log.exception(
                "could not resolve GPS for chained hospital dispatch from %s",
                request.destination_edge,
            )
            return False

        route_fn = traci_route_fn()
        incident_request = IncidentRequest(
            incident_id=request.request_id, origin_edge=request.destination_edge,
            origin_lat=lat, origin_lon=lon, required_capability=GENERAL,
        )
        decision = choose(incident_request, self._facility_index, route_fn)
        if decision is None:
            log.info(
                "no reachable hospital for ambulance %s -- releasing, no chained corridor",
                request.vehicle_id,
            )
            return False

        new_request_id = f"{request.request_id}-hospital"
        ok = self._create_and_activate(
            request_id=new_request_id, vehicle_id=request.vehicle_id, kind=EmergencyKind.AMBULANCE,
            source_edge=request.destination_edge, dest_edge=decision.facility.edge,
            step=step, sim_time_s=sim_time_s,
        )
        if not ok:
            return False
        log.info(
            "ambulance %s chained to %s (request %s)",
            request.vehicle_id, decision.facility.name, new_request_id,
        )
        return True


def _notified(cand: Candidate, *, selected: bool) -> dict:
    return {
        "vehicle_id": cand.crew.crew_id,
        "vehicle_kind": cand.crew.kind,
        "distance_m": round(cand.distance_m, 1),
        "road_time_s": None if cand.road_time_s is None else round(cand.road_time_s, 1),
        "cell": cand.cell,
        "selected": selected,
    }

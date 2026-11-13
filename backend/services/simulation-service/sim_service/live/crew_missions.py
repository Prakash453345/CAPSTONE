"""What happens to a crew between "accepted" and "free again".

`crew_dispatch` decides *who* takes a call. This module keeps the fleet honest
afterwards, all in simulation time:

- **Where each unit is.** A crew account carries no position, so a unit that
  joins the roster is parked at a home depot of its kind (ambulances at a
  hospital, police at a police station; fire trucks at a police station too,
  since this OSM extract has no fire stations). While it drives, its position
  is its SUMO vehicle's road, so the next call is matched from where it really
  is -- the "GPS" of a simulated fleet. A real deployment replaces this with
  the device's location; nothing downstream would change.
- **When it is free.** Police and fire units are free again when they reach
  the scene. An ambulance is not: it has a patient to take somewhere.
- **The hospital leg.** When an ambulance reaches the scene the crew is given
  the hospitals it can reach, fastest first by live travel time, with the
  first one picked (`CrewHospitalOptions`). The crew confirms it or picks
  another (`CrewHospitalChoice`); choosing again while driving reroutes from
  where the ambulance is. Delivered = free again, parked at that hospital.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from itms_domain import EmergencyKind

from sim_service.control.dispatch.facilities import GENERAL, FacilityIndex
from sim_service.live.crew_dispatch import CrewDispatcher

log = logging.getLogger(__name__)

# How often (simulated seconds) the live fleet is republished for the maps.
ROSTER_EVERY_S = 5.0
# How long an operator has to answer a crew's corridor request (simulated s).
CORRIDOR_ASK_TTL_S = 120.0
# Who may ask: police and traffic police. Ambulances and fire trucks are sent
# by dispatch, which already gives them a corridor.
CORRIDOR_ASK_KINDS = (EmergencyKind.POLICE, EmergencyKind.TRAFFIC_POLICE)
# How many hospitals the crew is offered, and how many are routed to rank them.
HOSPITAL_CHOICES = 4
HOSPITAL_SHORTLIST = 8


@dataclass
class _Mission:
    unit_id: str
    scene_request_id: str
    scene_edge: str
    options: list[dict] = field(default_factory=list)
    recommended_id: str = ""
    chosen_id: str = ""
    leg_request_id: str = ""
    legs: int = 0
    state: str = "at_scene"  # at_scene | to_hospital | done
    at_scene_since_s: float | None = None


class CrewMissions:
    """Positions, release and the ambulance's hospital leg for crew units.

    `create_leg(request_id, unit_id, source_edge, dest_edge) -> bool` starts a
    driving leg (the orchestrator's create-and-activate); `cancel(request_id)`
    stands one down; `vehicle_edges()` maps vehicle ids to the road they are
    on; `edge_latlon` and `route_fn` come from TraCI in the live service and
    are injected so this can be tested without SUMO.
    """

    def __init__(
        self,
        dispatcher: CrewDispatcher,
        *,
        facility_index: FacilityIndex,
        home_edges: dict[EmergencyKind, list[str]],
        create_leg: Callable[[str, str, str, str], bool],
        cancel: Callable[[str], None],
        vehicle_edges: Callable[[], dict[str, str]],
        edge_latlon: Callable[[str], tuple[float, float]],
        route_fn: Callable[[str, str], tuple[list[str], float] | None],
        auto_choose_after_s: float | None = None,
        create_return: Callable[[str, str, str, str, EmergencyKind], bool] | None = None,
        create_ask: Callable[[str, str, str, str, EmergencyKind, str], bool] | None = None,
        annotate: Callable[[str, str, str], None] | None = None,
        scene_active: Callable[[str, str, EmergencyKind], bool] | None = None,
        unit_homes: dict[str, str] | None = None,
        driver_releases: bool = False,
    ) -> None:
        # True: nothing leaves a scene on a clock or because the incident
        # ended. A police or fire unit stays, busy, until its driver says it
        # is leaving (`leave_scene`); an ambulance until its crew picks the
        # hospital. False (unattended runs): units leave by themselves when
        # the incident is over.
        self.driver_releases = driver_releases
        # unit_id -> the road its own base is on (crew_homes.json: this
        # ambulance belongs to that hospital, this car to that station). A
        # unit not named there is spread over the depots of its kind.
        self.unit_homes = unit_homes or {}
        # `scene_active(request_id, scene_edge, kind)`: is the incident a
        # police or fire unit was sent to still going? Such a unit stays at
        # the scene, busy, until it is not (a fire crew does not leave a fire
        # that is still burning), then drives home. None = leave at once.
        self._scene_active = scene_active
        self._on_scene: dict[str, tuple[str, str]] = {}  # unit_id -> (request_id, scene_edge)
        # Plans a route and holds it for an operator (no corridor yet).
        self._create_ask = create_ask
        self._annotate = annotate
        self._asks: dict[str, tuple[str, float]] = {}  # request id -> (unit_id, expires_at_s)
        # Starts a trip back to a station (no green corridor). None = units
        # simply stay where they finished.
        self._create_return = create_return
        self._returning: dict[str, str] = {}  # unit_id -> its return trip's request id
        # Nobody chose a hospital this long after reaching the scene: take the
        # fastest one, so an ambulance with no one at the crew page still
        # delivers its patient instead of standing at the scene forever.
        self.auto_choose_after_s = auto_choose_after_s
        self.dispatcher = dispatcher
        self.roster = dispatcher.roster
        self.facilities = facility_index
        self.home_edges = home_edges
        self._create_leg = create_leg
        self._cancel = cancel
        self._vehicle_edges = vehicle_edges
        self._edge_latlon = edge_latlon
        self._route_fn = route_fn
        self._missions: dict[str, _Mission] = {}  # unit_id -> its open hospital mission
        self._events: list[dict] = []
        self._next_roster_s = 0.0

    # ---- fleet ----------------------------------------------------------

    def place_new_units(self) -> None:
        """Park every unit that has no position yet at its own base when it
        has one (`unit_homes`), else at a home depot of its kind, spreading
        those units over the depots in a fixed order so the same accounts
        always start in the same places."""
        by_kind: dict[EmergencyKind, int] = {}
        for unit in sorted(self.roster.all(), key=lambda u: u.unit_id):
            homes = self.home_edges.get(unit.kind) or []
            i = by_kind.get(unit.kind, 0)
            by_kind[unit.kind] = i + 1
            if unit.edge_id:
                continue
            own = self.unit_homes.get(unit.unit_id)
            if own:
                self.roster.set_position(unit.unit_id, own)
            elif homes:
                self.roster.set_position(unit.unit_id, homes[i % len(homes)])

    def tick(self, sim_time_s: float) -> None:
        """Follow driving units, pick hospitals nobody picked, and republish
        the fleet every few seconds."""
        for mission in list(self._missions.values()):
            if mission.state != "at_scene" or not mission.options:
                continue
            if mission.at_scene_since_s is None:
                mission.at_scene_since_s = sim_time_s
            elif (
                self.auto_choose_after_s is not None
                and sim_time_s - mission.at_scene_since_s >= self.auto_choose_after_s
            ):
                log.info("no hospital chosen for %s: taking the fastest", mission.unit_id)
                self.choose_hospital(mission.unit_id, "")
        driving = self._vehicle_edges()
        for rid, (unit_id, expires_s) in list(self._asks.items()):
            if unit_id in driving:
                del self._asks[rid]  # approved: the unit is on its way
            elif sim_time_s >= expires_s:
                log.info("corridor request %s from %s unanswered: stood down", rid, unit_id)
                del self._asks[rid]
                self._cancel(rid)
                self.dispatcher.release(unit_id)
        for vehicle_id, edge in driving.items():
            if edge and self.roster.get(vehicle_id) is not None:
                self.roster.set_position(vehicle_id, edge)
        self._leave_finished_scenes()
        if sim_time_s >= self._next_roster_s:
            self._next_roster_s = sim_time_s + ROSTER_EVERY_S
            self._events.append({"event_type": "CrewRosterUpdated", "payload": self.fleet()})

    def fleet(self) -> dict:
        units = []
        for u in sorted(self.roster.all(), key=lambda u: u.unit_id):
            entry = u.public()
            entry["lat"], entry["lon"] = self._latlon(u.edge_id)
            units.append(entry)
        return {"units": units}

    def _latlon(self, edge: str) -> tuple[float | None, float | None]:
        if not edge:
            return None, None
        try:
            lat, lon = self._edge_latlon(edge)
            return lat, lon
        except Exception:  # noqa: BLE001 -- an unknown edge just has no dot on the map
            return None, None

    def drain_events(self) -> list[dict]:
        out, self._events = self._events, []
        return out

    # ---- arrivals ---------------------------------------------------------

    def on_arrival(self, request_id: str, vehicle_id: str, destination_edge: str) -> None:
        """A crew unit reached the end of a leg."""
        unit = self.roster.get(vehicle_id)
        if unit is None:
            return
        self.roster.set_position(vehicle_id, destination_edge)
        if self._returning.get(vehicle_id) == request_id:
            del self._returning[vehicle_id]  # back at its station
            return
        mission = self._missions.get(vehicle_id)
        if mission is not None and request_id != mission.leg_request_id:
            return  # a leg that was replaced by a later choice: not the one that counts
        if mission is not None:
            mission.state = "done"
            self._publish(mission)
            del self._missions[vehicle_id]
            self.dispatcher.release(vehicle_id)
            log.info("ambulance %s delivered its patient to %s", vehicle_id, mission.chosen_id)
            return
        if unit.kind is EmergencyKind.AMBULANCE:
            mission = _Mission(vehicle_id, request_id, destination_edge)
            mission.options = self.hospital_options(destination_edge)
            mission.recommended_id = mission.options[0]["facility_id"] if mission.options else ""
            if not mission.options:
                # Nowhere to take the patient by road: say so and free the crew
                # rather than leave it "busy" forever.
                log.warning("ambulance %s at the scene but no hospital is reachable", vehicle_id)
                mission.state = "done"
                self._publish(mission)
                self.dispatcher.release(vehicle_id)
                return
            self._missions[vehicle_id] = mission
            self._publish(mission)
            return
        if self.driver_releases or (
            self._scene_active is not None
            and self._scene_active(request_id, destination_edge, unit.kind)
        ):
            # the driver has not said they are leaving / still burning or
            # blocked: the crew stays and stays busy
            self._on_scene[vehicle_id] = (request_id, destination_edge)
            log.info("%s on scene at %s until the incident is over", vehicle_id, destination_edge)
            return
        self.dispatcher.release(vehicle_id)
        self._head_home(unit, destination_edge, request_id)

    def is_on_scene(self, unit_id: str) -> bool:
        return unit_id in self._on_scene

    def leave_scene(self, unit_id: str) -> bool:
        """The driver of a police or fire unit says the work at the scene is
        done: the unit is free for calls again and drives back to a station.
        False when that unit is not at a scene."""
        held = self._on_scene.pop(unit_id, None)
        unit = self.roster.get(unit_id)
        if held is None or unit is None:
            return False
        request_id, edge = held
        log.info("%s leaves the scene at %s (its driver said so)", unit_id, edge)
        self.dispatcher.release(unit_id)
        self._head_home(unit, edge, request_id)
        return True

    def _leave_finished_scenes(self) -> None:
        """Units whose incident has been resolved (or has expired) are free
        again and drive home from the scene. Not when the driver decides."""
        if self._scene_active is None or self.driver_releases:
            return
        for unit_id, (request_id, edge) in list(self._on_scene.items()):
            unit = self.roster.get(unit_id)
            if unit is None:
                del self._on_scene[unit_id]
                continue
            if self._scene_active(request_id, edge, unit.kind):
                continue
            del self._on_scene[unit_id]
            log.info("incident at %s is over: %s leaves the scene", edge, unit_id)
            self.dispatcher.release(unit_id)
            self._head_home(unit, edge, request_id)

    def _head_home(self, unit, from_edge: str, request_id: str) -> None:
        """Police and fire units drive back to the nearest station by road.
        They are free the whole way: a new call is matched from wherever they
        are (their position follows the vehicle) and `stop_return` ends the
        trip when one is accepted."""
        homes = self.home_edges.get(unit.kind) or []
        if self._create_return is None or not homes or from_edge in homes:
            return
        timed = []
        for h in homes:
            try:
                routed = self._route_fn(from_edge, h)
            except Exception:  # noqa: BLE001
                routed = None
            if routed is not None:
                timed.append((routed[1], h))
        if not timed:
            return
        rid = f"{request_id}-return"
        if self._create_return(rid, unit.unit_id, from_edge, min(timed)[1], unit.kind):
            self._returning[unit.unit_id] = rid
            log.info("%s heading back to its station (%s)", unit.unit_id, min(timed)[1])

    def is_returning(self, unit_id: str) -> bool:
        return unit_id in self._returning

    def end_return(
        self,
        unit_id: str,
        *,
        edge_of: Callable[[str], str | None],
        pos_of: Callable[[str], float | None],
    ) -> tuple[str | None, float | None]:
        """A unit on its way home was given a call: end the trip home and say
        where the next trip starts -- the road the vehicle is on and how far
        along it (metres). Both are read *before* the trip is cancelled,
        because cancelling forgets them; without the position the next trip
        starts at the beginning of that road and the vehicle jumps backwards.
        (None, None) when the unit was not driving home."""
        rid = self._returning.get(unit_id)
        if rid is None:
            return None, None
        edge, pos = edge_of(rid), pos_of(rid)
        self.stop_return(unit_id)
        return edge, (pos if edge else None)

    def ask_corridor(
        self, unit_id: str, dest_edge: str, reason: str, *, now_s: float, step: int
    ) -> str | None:
        """A police crew asks for a green corridor to `dest_edge`.

        The route is planned from where the unit is and held at ROUTE_READY: an
        operator approves it (ACTIVATE_CORRIDOR, which also sends the unit) or
        refuses it (CANCEL), and an unanswered ask is stood down after
        `CORRIDOR_ASK_TTL_S`. Returns the request id, or None if refused."""
        unit = self.roster.get(unit_id)
        if unit is None or self._create_ask is None:
            log.warning("corridor request from unknown unit %r -- ignored", unit_id)
            return None
        if unit.kind not in CORRIDOR_ASK_KINDS:
            log.warning("corridor request from %s (%s) -- only police ask", unit_id,
                        unit.kind.value)
            return None
        if not unit.edge_id or not dest_edge:
            return None
        if any(u == unit_id for u, _ in self._asks.values()):
            log.info("%s already has a corridor request open -- ignored", unit_id)
            return None
        returning = self.is_returning(unit_id)
        if unit.busy and not returning:
            log.info("%s is on a call -- corridor request ignored", unit_id)
            return None
        rid = f"crewreq-{unit_id}-{int(now_s * 1000)}"
        source = unit.edge_id
        if returning:
            self.stop_return(unit_id)  # the trip home is replaced by this one
        self.roster.set_busy(unit_id, True)
        if not self._create_ask(rid, unit_id, source, dest_edge, unit.kind, f"crew:{unit_id}"):
            log.info("corridor request %s: no route from %s to %s", rid, source, dest_edge)
            self.dispatcher.release(unit_id)
            return None
        self._asks[rid] = (unit_id, now_s + CORRIDOR_ASK_TTL_S)
        if self._annotate is not None:
            note = f" Reason: {reason}." if reason else ""
            self._annotate(
                rid, f"crew:{unit_id}",
                f"Crew asked for a green corridor.{note} Approve to send them with the "
                "corridor, or stand down to refuse.",
            )
        log.info("%s asked for a green corridor to %s (%s)", unit_id, dest_edge, rid)
        return rid

    def forget_ask(self, request_id: str) -> None:
        self._asks.pop(request_id, None)

    def stop_return(self, unit_id: str) -> None:
        """A unit on its way home was given a call: end the trip home. Its
        position is where it had got to, so the call starts from there."""
        rid = self._returning.pop(unit_id, None)
        if rid is not None:
            self._cancel(rid)

    def hospital_options(self, from_edge: str) -> list[dict]:
        """Hospitals reachable from `from_edge`, fastest first by live travel time."""
        try:
            lat, lon = self._edge_latlon(from_edge)
        except Exception:  # noqa: BLE001
            return []
        scored = []
        for f in self.facilities.nearest_by_air(lat, lon, GENERAL, HOSPITAL_SHORTLIST):
            routed = self._route_fn(from_edge, f.edge)
            if routed is None or not routed[0]:
                continue
            scored.append((routed[1], f))
        scored.sort(key=lambda row: (row[0], row[1].id))
        return [
            {"facility_id": f.id, "name": f.name, "edge_id": f.edge, "eta_s": round(t, 1),
             "lat": f.lat, "lon": f.lon}
            for t, f in scored[:HOSPITAL_CHOICES]
        ]

    # ---- the crew's choice --------------------------------------------------

    def choose_hospital(self, unit_id: str, facility_id: str) -> bool:
        """Patient on board: go to `facility_id` (empty: the recommended one).
        Again while driving: reroute there from where the ambulance is."""
        mission = self._missions.get(unit_id)
        if mission is None:
            log.warning("hospital choice from %s, which is not at a scene", unit_id)
            return False
        fid = facility_id or mission.recommended_id
        option = next((o for o in mission.options if o["facility_id"] == fid), None)
        if option is None:
            facility = next((f for f in self.facilities.all if f.id == fid), None) if fid else None
            if facility is None:
                log.warning("unknown hospital %r chosen by %s", fid, unit_id)
                return False
            option = {"facility_id": facility.id, "name": facility.name, "edge_id": facility.edge,
                      "eta_s": 0.0, "lat": facility.lat, "lon": facility.lon}
        unit = self.roster.get(unit_id)
        source = unit.edge_id if unit is not None and unit.edge_id else mission.scene_edge
        if mission.leg_request_id:
            self._cancel(mission.leg_request_id)
        mission.legs += 1
        leg_id = f"{mission.scene_request_id}-hospital-{mission.legs}"
        if not self._create_leg(leg_id, unit_id, source, option["edge_id"]):
            log.warning("could not route %s to %s", unit_id, option["name"])
            return False
        mission.leg_request_id = leg_id
        mission.chosen_id = option["facility_id"]
        mission.state = "to_hospital"
        self._publish(mission)
        return True

    def _publish(self, mission: _Mission) -> None:
        self._events.append({
            "event_type": "CrewHospitalOptions",
            "payload": {
                "unit_id": mission.unit_id,
                "request_id": mission.scene_request_id,
                "scene_edge": mission.scene_edge,
                "state": mission.state,
                "recommended_id": mission.recommended_id,
                "chosen_id": mission.chosen_id,
                "options": mission.options,
            },
        })

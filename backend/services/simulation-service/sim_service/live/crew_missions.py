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
    ) -> None:
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
        """Park every unit that has no position yet at a home depot of its
        kind, spreading units of one kind over the depots in a fixed order so
        the same accounts always start in the same places."""
        by_kind: dict[EmergencyKind, int] = {}
        for unit in sorted(self.roster.all(), key=lambda u: u.unit_id):
            homes = self.home_edges.get(unit.kind) or []
            i = by_kind.get(unit.kind, 0)
            by_kind[unit.kind] = i + 1
            if unit.edge_id or not homes:
                continue
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
        for vehicle_id, edge in self._vehicle_edges().items():
            if edge and self.roster.get(vehicle_id) is not None:
                self.roster.set_position(vehicle_id, edge)
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
        self.dispatcher.release(vehicle_id)

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

"""`CrewMissions`: crew units start at a depot of their kind, follow their SUMO
vehicle, are freed on arrival (police/fire) or after the hospital leg
(ambulance), and the crew can pick or change the hospital."""

from __future__ import annotations

from itms_domain import EmergencyKind
from sim_service.control.dispatch.facilities import GENERAL, Facility, FacilityIndex
from sim_service.live.crew_dispatch import CrewDispatcher, CrewRoster, CrewUnit
from sim_service.live.crew_missions import CrewMissions


class _Planner:
    def plan(self, *a, **k):  # pragma: no cover - not used here
        return None


def _unit(unit_id: str, kind: EmergencyKind, user: str, call_sign: str) -> CrewUnit:
    return CrewUnit(unit_id, kind, "", crew_username=user, on_duty=True, call_sign=call_sign)


def _setup():
    roster = CrewRoster()
    roster.upsert(_unit("AMB-2", EmergencyKind.AMBULANCE, "ambulance2", "Ambulance 2"))
    roster.upsert(_unit("AMB-1", EmergencyKind.AMBULANCE, "ambulance1", "Ambulance 1"))
    roster.upsert(_unit("POL-1", EmergencyKind.POLICE, "police1", "Police 1"))
    dispatcher = CrewDispatcher(roster, _Planner(), None)
    facilities = FacilityIndex([
        Facility("H1", "Near Hospital", "hospital", "h1", 0.0, 16.50, 80.60, frozenset({GENERAL})),
        Facility("H2", "Far Hospital", "hospital", "h2", 0.0, 16.60, 80.70, frozenset({GENERAL})),
    ])
    legs: list[tuple] = []
    cancelled: list[str] = []
    eta = {"h1": 120.0, "h2": 300.0}
    missions = CrewMissions(
        dispatcher,
        facility_index=facilities,
        home_edges={EmergencyKind.AMBULANCE: ["dA", "dB"], EmergencyKind.POLICE: ["dP"]},
        create_leg=lambda *a: legs.append(a) or True,
        cancel=cancelled.append,
        vehicle_edges=lambda: {"AMB-1": "road7"},
        edge_latlon=lambda e: (16.5, 80.6),
        route_fn=lambda a, b: ((a, b), eta[b]),
    )
    return roster, missions, legs, cancelled


def test_units_start_at_depots_of_their_kind_in_a_fixed_order() -> None:
    roster, missions, *_ = _setup()
    missions.place_new_units()
    assert roster.get("AMB-1").edge_id == "dA"
    assert roster.get("AMB-2").edge_id == "dB"
    assert roster.get("POL-1").edge_id == "dP"


def test_a_unit_with_its_own_base_starts_there_and_the_rest_are_spread() -> None:
    roster, missions, *_ = _setup()
    missions.unit_homes = {"AMB-1": "dB"}
    missions.place_new_units()
    assert roster.get("AMB-1").edge_id == "dB"
    assert roster.get("AMB-2").edge_id == "dB"  # still the second depot in the rotation
    assert roster.get("POL-1").edge_id == "dP"


def test_a_driving_unit_is_where_its_vehicle_is_and_the_fleet_is_published() -> None:
    roster, missions, *_ = _setup()
    missions.place_new_units()
    missions.tick(0.0)
    assert roster.get("AMB-1").edge_id == "road7"
    events = missions.drain_events()
    assert events[0]["event_type"] == "CrewRosterUpdated"
    assert [u["unit_id"] for u in events[0]["payload"]["units"]] == ["AMB-1", "AMB-2", "POL-1"]
    missions.tick(1.0)
    assert missions.drain_events() == []  # republished every few seconds, not every tick


def test_police_are_free_on_arrival() -> None:
    roster, missions, *_ = _setup()
    roster.set_busy("POL-1", True)
    missions.on_arrival("r1", "POL-1", "scene")
    assert not roster.get("POL-1").busy
    assert roster.get("POL-1").edge_id == "scene"


def test_ambulance_gets_hospitals_fastest_first_and_stays_busy_until_delivered() -> None:
    roster, missions, legs, cancelled = _setup()
    roster.set_busy("AMB-1", True)
    missions.on_arrival("r1", "AMB-1", "scene")
    assert roster.get("AMB-1").busy
    ev = missions.drain_events()[-1]
    assert ev["event_type"] == "CrewHospitalOptions"
    assert [o["facility_id"] for o in ev["payload"]["options"]] == ["H1", "H2"]
    assert ev["payload"]["recommended_id"] == "H1"

    assert missions.choose_hospital("AMB-1", "")  # confirm the recommended one
    assert legs[-1] == ("r1-hospital-1", "AMB-1", "scene", "h1")
    assert missions.choose_hospital("AMB-1", "H2")  # changed mind on the way
    assert cancelled == ["r1-hospital-1"]
    assert legs[-1][0] == "r1-hospital-2" and legs[-1][3] == "h2"

    missions.on_arrival("r1-hospital-1", "AMB-1", "h1")  # the cancelled leg: ignored
    assert roster.get("AMB-1").busy
    missions.on_arrival("r1-hospital-2", "AMB-1", "h2")
    assert not roster.get("AMB-1").busy
    assert missions.drain_events()[-1]["payload"]["state"] == "done"


def test_a_choice_from_a_unit_not_at_a_scene_is_ignored() -> None:
    _, missions, legs, _ = _setup()
    assert not missions.choose_hospital("AMB-2", "H1")
    assert legs == []


def test_any_known_hospital_can_be_chosen_and_an_unknown_one_is_refused() -> None:
    roster, missions, legs, _ = _setup()
    missions.home_edges = {}
    missions._route_fn = lambda a, b: ((a, b), 120.0) if b == "h1" else None  # noqa: SLF001
    roster.set_busy("AMB-1", True)
    missions.on_arrival("r1", "AMB-1", "scene")
    assert [o["facility_id"] for o in missions.drain_events()[-1]["payload"]["options"]] == ["H1"]
    assert not missions.choose_hospital("AMB-1", "H9")
    assert missions.choose_hospital("AMB-1", "H2")  # not offered, but a real hospital
    assert legs[-1][3] == "h2"


def test_an_ambulance_with_no_reachable_hospital_is_freed() -> None:
    roster, missions, legs, _ = _setup()
    missions._route_fn = lambda a, b: None  # noqa: SLF001
    roster.set_busy("AMB-1", True)
    missions.on_arrival("r1", "AMB-1", "scene")
    assert not roster.get("AMB-1").busy
    assert missions.drain_events()[-1]["payload"]["state"] == "done"


def test_a_hospital_nobody_chooses_is_chosen_for_them():
    roster, missions, legs, _ = _setup()
    missions.auto_choose_after_s = 30.0
    roster.set_busy("AMB-1", True)
    missions.on_arrival("r1", "AMB-1", "scene")
    missions.tick(100.0)
    assert legs == []
    missions.tick(125.0)
    assert legs == []
    missions.tick(131.0)
    assert legs[-1][0] == "r1-hospital-1" and legs[-1][3] == "h1"  # the fastest


def _with_return():
    roster = CrewRoster()
    roster.upsert(_unit("POL-1", EmergencyKind.POLICE, "police1", "Police 1"))
    roster.upsert(_unit("AMB-1", EmergencyKind.AMBULANCE, "ambulance1", "Ambulance 1"))
    returns: list[tuple] = []
    cancelled: list[str] = []
    missions = CrewMissions(
        CrewDispatcher(roster, _Planner(), None),
        facility_index=FacilityIndex([]),
        home_edges={EmergencyKind.POLICE: ["far", "near"]},
        create_leg=lambda *a: True,
        cancel=cancelled.append,
        vehicle_edges=lambda: {},
        edge_latlon=lambda e: (16.5, 80.6),
        route_fn=lambda a, b: ((a, b), {"far": 500.0, "near": 90.0}[b]),
        create_return=lambda *a: returns.append(a) or True,
    )
    return roster, missions, returns, cancelled


def test_police_head_back_to_the_nearest_station_and_are_free_on_the_way() -> None:
    roster, missions, returns, _ = _with_return()
    roster.set_busy("POL-1", True)
    missions.on_arrival("req-1", "POL-1", "scene")
    assert not roster.get("POL-1").busy
    assert returns == [("req-1-return", "POL-1", "scene", "near", EmergencyKind.POLICE)]
    # reaching the station ends the trip and is not mistaken for a new scene
    missions.on_arrival("req-1-return", "POL-1", "near")
    assert roster.get("POL-1").edge_id == "near" and not roster.get("POL-1").busy
    assert missions._returning == {}


def test_a_unit_already_at_a_station_does_not_drive_anywhere() -> None:
    _, missions, returns, _ = _with_return()
    missions.on_arrival("req-1", "POL-1", "near")
    assert returns == []


def test_a_call_accepted_on_the_way_home_ends_the_trip_home() -> None:
    _, missions, _, cancelled = _with_return()
    missions.on_arrival("req-1", "POL-1", "scene")
    missions.stop_return("POL-1")
    assert cancelled == ["req-1-return"]
    missions.stop_return("POL-1")  # nothing left to stop
    assert cancelled == ["req-1-return"]


def test_a_call_taken_on_the_way_home_starts_where_the_vehicle_is_on_the_road() -> None:
    """Fire 1 drove home from one fire and took a second call 140 m along a
    road: the new trip must start there, not at the road's beginning (the
    truck jumped backwards on the map). The position is read before the trip
    home is cancelled, because cancelling forgets it."""
    _, missions, _, cancelled = _with_return()
    missions.on_arrival("req-1", "POL-1", "scene")
    seen: list[str] = []

    def edge_of(rid: str) -> str | None:
        seen.append(f"edge:{rid}:cancelled={rid in cancelled}")
        return "road9"

    def pos_of(rid: str) -> float | None:
        seen.append(f"pos:{rid}:cancelled={rid in cancelled}")
        return 140.0

    assert missions.end_return("POL-1", edge_of=edge_of, pos_of=pos_of) == ("road9", 140.0)
    assert seen == ["edge:req-1-return:cancelled=False", "pos:req-1-return:cancelled=False"]
    assert cancelled == ["req-1-return"]
    # not on its way home: nothing to read, nothing to cancel
    assert missions.end_return("POL-1", edge_of=edge_of, pos_of=pos_of) == (None, None)
    assert cancelled == ["req-1-return"]


def _asking(vehicles=None, ok=True):
    roster = CrewRoster()
    roster.upsert(_unit("POL-1", EmergencyKind.POLICE, "police1", "Police 1"))
    roster.upsert(_unit("AMB-1", EmergencyKind.AMBULANCE, "ambulance1", "Ambulance 1"))
    roster.set_position("POL-1", "here")
    roster.set_position("AMB-1", "here")
    asks: list[tuple] = []
    notes: list[tuple] = []
    cancelled: list[str] = []
    drivers = vehicles if vehicles is not None else {}
    missions = CrewMissions(
        CrewDispatcher(roster, _Planner(), None),
        facility_index=FacilityIndex([]),
        home_edges={},
        create_leg=lambda *a: True,
        cancel=cancelled.append,
        vehicle_edges=lambda: drivers,
        edge_latlon=lambda e: (16.5, 80.6),
        route_fn=lambda a, b: None,
        create_ask=lambda *a: asks.append(a) or ok,
        annotate=lambda *a: notes.append(a),
    )
    return roster, missions, asks, notes, cancelled, drivers


def test_a_police_crew_can_ask_for_a_corridor_and_waits_for_an_operator() -> None:
    roster, missions, asks, notes, cancelled, _ = _asking()
    rid = missions.ask_corridor("POL-1", "far", "pursuit", now_s=10.0, step=1)
    assert rid == "crewreq-POL-1-10000"
    assert asks == [(rid, "POL-1", "here", "far", EmergencyKind.POLICE, "crew:POL-1")]
    assert roster.get("POL-1").busy  # no other call is offered meanwhile
    assert "pursuit" in notes[0][2] and notes[0][1] == "crew:POL-1"
    assert cancelled == []


def test_only_police_ask_and_only_one_ask_at_a_time() -> None:
    roster, missions, asks, *_ = _asking()
    roster.upsert(_unit("FIRE-1", EmergencyKind.FIRE_TRUCK, "fire1", "Fire 1"))
    roster.set_position("FIRE-1", "here")
    assert missions.ask_corridor("FIRE-1", "far", "", now_s=1.0, step=1) is None
    assert missions.ask_corridor("AMB-1", "far", "", now_s=1.0, step=1) is None
    assert missions.ask_corridor("NOPE", "far", "", now_s=1.0, step=1) is None
    assert missions.ask_corridor("POL-1", "far", "", now_s=1.0, step=1) is not None
    assert missions.ask_corridor("POL-1", "far2", "", now_s=2.0, step=1) is None
    assert len(asks) == 1


def test_a_unit_on_a_call_cannot_ask() -> None:
    roster, missions, asks, *_ = _asking()
    roster.set_busy("POL-1", True)
    assert missions.ask_corridor("POL-1", "far", "", now_s=1.0, step=1) is None
    assert asks == []


def test_an_ask_with_no_route_frees_the_unit() -> None:
    roster, missions, *_ = _asking(ok=False)
    assert missions.ask_corridor("POL-1", "far", "", now_s=1.0, step=1) is None
    assert not roster.get("POL-1").busy


def test_an_unanswered_ask_is_stood_down_and_an_approved_one_is_kept() -> None:
    roster, missions, _, _, cancelled, drivers = _asking()
    rid = missions.ask_corridor("POL-1", "far", "", now_s=0.0, step=1)
    missions.tick(60.0)
    assert cancelled == []
    missions.tick(130.0)
    assert cancelled == [rid] and not roster.get("POL-1").busy

    roster.set_busy("POL-1", False)
    rid2 = missions.ask_corridor("POL-1", "far", "", now_s=200.0, step=2)
    drivers["POL-1"] = "road9"  # an operator approved: the vehicle is on the road
    missions.tick(400.0)
    assert cancelled == [rid] and roster.get("POL-1").busy and rid2


def _on_scene_setup(active: set[str]):
    """A fire unit and a police unit; `active` holds the request ids whose
    incident is still going."""
    roster = CrewRoster()
    roster.upsert(_unit("FIRE-1", EmergencyKind.FIRE_TRUCK, "fire1", "Fire 1"))
    roster.upsert(_unit("POL-1", EmergencyKind.POLICE, "police1", "Police 1"))
    returns: list[tuple] = []
    missions = CrewMissions(
        CrewDispatcher(roster, _Planner(), None),
        facility_index=FacilityIndex([]),
        home_edges={EmergencyKind.FIRE_TRUCK: ["station"], EmergencyKind.POLICE: ["station"]},
        create_leg=lambda *a: True,
        cancel=lambda rid: None,
        vehicle_edges=lambda: {},
        edge_latlon=lambda e: (16.5, 80.6),
        route_fn=lambda a, b: ((a, b), 60.0),
        create_return=lambda *a: returns.append(a) or True,
        scene_active=lambda rid, edge, kind: rid in active,
    )
    return roster, missions, returns


def test_a_fire_crew_stays_at_a_fire_that_is_still_burning_then_drives_home() -> None:
    active = {"resp-an-1-fire_truck"}
    roster, missions, returns = _on_scene_setup(active)
    roster.set_busy("FIRE-1", True)
    missions.on_arrival("resp-an-1-fire_truck", "FIRE-1", "scene")
    missions.tick(10.0)
    assert roster.get("FIRE-1").busy and missions.is_on_scene("FIRE-1")
    assert returns == []                      # not heading home yet
    active.clear()                            # the fire is out (resolved or expired)
    missions.tick(20.0)
    assert not roster.get("FIRE-1").busy and not missions.is_on_scene("FIRE-1")
    assert returns == [("resp-an-1-fire_truck-return", "FIRE-1", "scene", "station",
                        EmergencyKind.FIRE_TRUCK)]
    missions.tick(30.0)
    assert len(returns) == 1                  # sent home once, not every tick


def test_a_unit_whose_incident_is_already_over_leaves_at_once() -> None:
    roster, missions, returns = _on_scene_setup(set())
    roster.set_busy("POL-1", True)
    missions.on_arrival("resp-an-2-police", "POL-1", "scene")
    assert not roster.get("POL-1").busy and not missions.is_on_scene("POL-1")
    assert returns and returns[0][1] == "POL-1"


def test_when_the_driver_decides_a_unit_stays_until_they_say_they_are_leaving() -> None:
    roster, missions, returns = _on_scene_setup(set())   # no incident going at all
    missions.driver_releases = True
    roster.set_busy("POL-1", True)
    missions.on_arrival("resp-an-2-police", "POL-1", "scene")
    missions.tick(10_000.0)                              # no clock moves it
    assert roster.get("POL-1").busy and missions.is_on_scene("POL-1") and returns == []
    assert missions.leave_scene("POL-1")
    assert not roster.get("POL-1").busy and not missions.is_on_scene("POL-1")
    assert returns[0][1] == "POL-1"
    assert not missions.leave_scene("POL-1")             # only once


    active = {"resp-an-1-fire_truck", "resp-an-1-fire_truck-return"}
    roster, missions, returns = _on_scene_setup(active)
    missions.on_arrival("resp-an-1-fire_truck", "FIRE-1", "scene")
    active.discard("resp-an-1-fire_truck")
    missions.tick(1.0)
    missions.on_arrival("resp-an-1-fire_truck-return", "FIRE-1", "station")
    assert not missions.is_on_scene("FIRE-1") and not roster.get("FIRE-1").busy

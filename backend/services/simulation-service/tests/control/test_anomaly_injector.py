"""`IncidentInjector` unit tests. Like `test_queue_state.py`, these
monkeypatch the handful of TraCI calls the injector makes so a full
schedule can be driven tick-by-tick with a deterministic scripted fleet --
no SUMO process. The real-SUMO exercise is `scripts/smoke_m6_injector.py`.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from sim_service.control.anomaly import injector as injector_module
from sim_service.control.anomaly.injector import (
    IncidentInjector,
    IncidentWindow,
    PlannedIncident,
    random_schedule,
)

# {tls: {L{i}: lane}} -- two controlled approaches, plus one lane below is
# deliberately absent so "not a signal-controlled approach" is covered.
_LINK_LANES = {
    "J1": {"L0": "app_a_0", "L1": "app_a_0"},  # one lane feeds two link indices
    "J2": {"L4": "app_b_0"},
}


class _FakeSim:
    """A scripted world. The test sets `lane_vehicles` / `speeds` / `positions`
    / `id_list` / `lane_max` for the current tick before calling
    `injector.tick(step)`, and reads `set_speed_calls` / `set_maxspeed_calls`
    after."""

    def __init__(self, monkeypatch):
        self.lane_vehicles: dict[str, list[str]] = {}
        self.speeds: dict[str, float] = {}
        self.positions: dict[str, float] = {}
        self.id_list: list[str] = []
        self.lane_max: dict[str, float] = {}
        self.set_speed_calls: list[tuple[str, float]] = []
        self.set_maxspeed_calls: list[tuple[str, float]] = []
        self.lc_mode: dict[str, int] = {}

        t = injector_module.traci
        monkeypatch.setattr(
            t.lane, "getLastStepVehicleIDs",
            lambda lane_id: tuple(self.lane_vehicles.get(lane_id, [])),
        )
        monkeypatch.setattr(t.vehicle, "getSpeed", lambda v: self.speeds[v])
        monkeypatch.setattr(t.vehicle, "getLanePosition", lambda v: self.positions.get(v, 0.0))
        monkeypatch.setattr(t.vehicle, "getIDList", lambda: tuple(self.id_list))
        monkeypatch.setattr(
            t.vehicle, "setSpeed",
            lambda v, s: self.set_speed_calls.append((v, s)),
        )
        monkeypatch.setattr(t.vehicle, "getLaneChangeMode",
                            lambda v: self.lc_mode.get(v, 1621))
        monkeypatch.setattr(t.vehicle, "setLaneChangeMode",
                            lambda v, m: self.lc_mode.__setitem__(v, m))
        monkeypatch.setattr(t.lane, "getMaxSpeed", lambda lane_id: self.lane_max[lane_id])
        monkeypatch.setattr(
            t.lane, "setMaxSpeed",
            lambda lane_id, s: self.set_maxspeed_calls.append((lane_id, s)),
        )

    def put_vehicle(self, lane_id: str, veh: str, *, speed: float, pos: float = 50.0):
        self.lane_vehicles.setdefault(lane_id, []).append(veh)
        self.speeds[veh] = speed
        self.positions[veh] = pos
        if veh not in self.id_list:
            self.id_list.append(veh)

    def clear_lane(self, lane_id: str):
        for v in self.lane_vehicles.pop(lane_id, []):
            self.speeds.pop(v, None)
            self.positions.pop(v, None)

    def remove_vehicle(self, veh: str):
        for lane in list(self.lane_vehicles):
            self.lane_vehicles[lane] = [v for v in self.lane_vehicles[lane] if v != veh]
        self.speeds.pop(veh, None)
        self.positions.pop(veh, None)
        self.id_list = [v for v in self.id_list if v != veh]


@pytest.fixture
def sim(monkeypatch):
    return _FakeSim(monkeypatch)


# ---- stall --------------------------------------------------------------


def test_stall_freezes_at_start_reasserts_each_tick_then_releases(sim):
    sim.put_vehicle("app_a_0", "veh1", speed=8.0)
    inj = IncidentInjector(
        [PlannedIncident("stall", "app_a_0", start_tick=5, duration_ticks=4)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 15):
        inj.tick(step)
    inj.finalize(15)

    # frozen at tick 5, held 5..8, released at tick 9 (start 5 + duration 4)
    assert (("veh1", 0.0)) in sim.set_speed_calls
    freeze_count = sum(1 for v, s in sim.set_speed_calls if v == "veh1" and s == 0.0)
    assert freeze_count == 5  # ticks 5,6,7,8, plus the initial start at 5? -> 5..8 maintain + start
    assert ("veh1", -1.0) in sim.set_speed_calls  # released

    (w,) = inj.ground_truth()
    assert w.kind == "stall"
    assert w.actual_start_tick == 5
    assert w.end_tick == 9
    assert w.ended_reason == "released"
    assert w.vehicle_id == "veh1"
    assert w.intersection_id == "J1"
    assert set(w.link_ids) == {"L0", "L1"}
    assert w.realised


def test_a_stalled_vehicle_cannot_change_lanes_until_released(sim):
    """setSpeed(0) alone lets SUMO keep moving a stopped car sideways; a
    breakdown stays in its lane."""
    sim.put_vehicle("app_a_0", "veh1", speed=8.0)
    inj = IncidentInjector(
        [PlannedIncident("stall", "app_a_0", start_tick=5, duration_ticks=4)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 7):
        inj.tick(step)
    assert sim.lc_mode["veh1"] == 0
    for step in range(7, 12):
        inj.tick(step)
    assert sim.lc_mode["veh1"] == 1621  # its own mode back


def test_stall_defers_start_until_a_vehicle_is_on_the_lane(sim):
    inj = IncidentInjector(
        [PlannedIncident("stall", "app_a_0", start_tick=5, duration_ticks=20)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 8):
        inj.tick(step)  # lane empty ticks 1..7
    sim.put_vehicle("app_a_0", "late", speed=6.0)
    for step in range(8, 40):
        inj.tick(step)
    inj.finalize(40)

    (w,) = inj.ground_truth()
    assert w.actual_start_tick == 8
    assert w.requested_start_tick == 5
    assert w.realised


def test_stall_that_never_finds_a_vehicle_is_recorded_unrealised(sim):
    inj = IncidentInjector(
        [PlannedIncident("stall", "app_a_0", start_tick=5, duration_ticks=10)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 20):
        inj.tick(step)  # lane empty the whole time
    inj.finalize(20)

    (w,) = inj.ground_truth()
    assert w.actual_start_tick is None
    assert w.ended_reason == "never_started"
    assert not w.realised
    assert inj.realised_windows() == []


def test_stall_ends_when_sumo_removes_the_frozen_vehicle(sim):
    sim.put_vehicle("app_a_0", "veh1", speed=8.0)
    inj = IncidentInjector(
        [PlannedIncident("stall", "app_a_0", start_tick=3, duration_ticks=50)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 7):
        inj.tick(step)
    sim.remove_vehicle("veh1")  # teleported out of a jam, say
    for step in range(7, 12):
        inj.tick(step)
    inj.finalize(12)

    (w,) = inj.ground_truth()
    assert w.end_tick == 7
    assert w.ended_reason == "vehicle_gone"
    # no release call for a vehicle SUMO already removed
    assert ("veh1", -1.0) not in sim.set_speed_calls


def test_moving_vehicle_furthest_along_the_lane_is_chosen(sim):
    sim.put_vehicle("app_a_0", "back", speed=5.0, pos=10.0)
    sim.put_vehicle("app_a_0", "front", speed=5.0, pos=90.0)
    sim.put_vehicle("app_a_0", "stopped", speed=0.0, pos=95.0)  # already halted -> skip
    inj = IncidentInjector(
        [PlannedIncident("stall", "app_a_0", start_tick=2, duration_ticks=3)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 8):
        inj.tick(step)
    inj.finalize(8)
    (w,) = inj.ground_truth()
    assert w.vehicle_id == "front"


# ---- lane block -------------------------------------------------------


def test_lane_block_throttles_then_restores_original_limit(sim):
    sim.lane_max["app_b_0"] = 13.9
    inj = IncidentInjector(
        [PlannedIncident("lane_block", "app_b_0", start_tick=4, duration_ticks=6)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 15):
        inj.tick(step)
    inj.finalize(15)

    assert ("app_b_0", pytest.approx(0.1)) in sim.set_maxspeed_calls
    assert ("app_b_0", 13.9) in sim.set_maxspeed_calls
    # restore comes after throttle
    throttle_i = sim.set_maxspeed_calls.index(("app_b_0", pytest.approx(0.1)))
    restore_i = sim.set_maxspeed_calls.index(("app_b_0", 13.9))
    assert restore_i > throttle_i

    (w,) = inj.ground_truth()
    assert w.kind == "lane_block"
    assert w.actual_start_tick == 4
    assert w.end_tick == 10
    assert w.ended_reason == "released"
    assert w.intersection_id == "J2"
    assert w.link_ids == ("L4",)


def test_lane_block_still_open_at_run_end_is_restored_and_recorded(sim):
    sim.lane_max["app_b_0"] = 12.0
    inj = IncidentInjector(
        [PlannedIncident("lane_block", "app_b_0", start_tick=2, duration_ticks=999)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 6):
        inj.tick(step)
    inj.finalize(6)

    assert ("app_b_0", 12.0) in sim.set_maxspeed_calls  # restored despite no natural release
    (w,) = inj.ground_truth()
    assert w.ended_reason == "run_ended"
    assert w.end_tick == 6


def test_lane_with_no_controlled_link_resolves_to_empty_metadata(sim):
    sim.lane_max["random_lane_9"] = 10.0
    inj = IncidentInjector(
        [PlannedIncident("lane_block", "random_lane_9", start_tick=2, duration_ticks=3)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 10):
        inj.tick(step)
    inj.finalize(10)
    (w,) = inj.ground_truth()
    assert w.intersection_id is None
    assert w.link_ids == ()


# ---- IncidentWindow.contains ----------------------------------------


def test_incident_window_contains_is_half_open():
    w = IncidentWindow(
        kind="stall", lane_id="l", intersection_id="J1", link_ids=("L0",),
        requested_start_tick=10, actual_start_tick=10, end_tick=20,
        vehicle_id="v", ended_reason="released",
    )
    assert not w.contains(9)
    assert w.contains(10)
    assert w.contains(19)
    assert not w.contains(20)


def test_unrealised_window_contains_nothing():
    w = IncidentWindow(
        kind="stall", lane_id="l", intersection_id=None, link_ids=(),
        requested_start_tick=10, actual_start_tick=None, end_tick=None,
        vehicle_id=None, ended_reason="never_started",
    )
    assert not w.contains(12)


# ---- random_schedule ------------------------------------------------


def test_random_schedule_is_deterministic_for_a_seed():
    lanes = ["a", "b", "c", "d"]
    s1 = random_schedule(lanes, seed=7, n_incidents=4, run_ticks=6000)
    s2 = random_schedule(lanes, seed=7, n_incidents=4, run_ticks=6000)
    assert s1 == s2


def test_random_schedule_respects_count_gap_and_kinds():
    s = random_schedule(
        ["a", "b"], seed=1, n_incidents=5, run_ticks=8000,
        kinds=("stall",), min_gap_ticks=100,
    )
    assert len(s) == 5
    assert all(p.kind == "stall" for p in s)
    starts = sorted(p.start_tick for p in s)
    assert all(b - a >= 100 for a, b in pairwise(starts))


def test_random_schedule_rejects_a_run_too_short_to_hold_the_incidents():
    with pytest.raises(ValueError):
        random_schedule(["a"], seed=1, n_incidents=3, run_ticks=400)


def test_random_schedule_rejects_empty_lane_set():
    with pytest.raises(ValueError):
        random_schedule([], seed=1, n_incidents=1, run_ticks=6000)


# ---- collision ----------------------------------------------------------


def _patch_collision_calls(sim, monkeypatch):
    t = injector_module.traci
    sim.speed_mode = {}
    monkeypatch.setattr(t.vehicle, "getLength", lambda v: 4.2)
    monkeypatch.setattr(t.vehicle, "getSpeedMode", lambda v: sim.speed_mode.get(v, 31))
    monkeypatch.setattr(t.vehicle, "setSpeedMode", lambda v, m: sim.speed_mode.__setitem__(v, m))
    monkeypatch.setattr(t.simulation, "getDeltaT", lambda: 1.0)


def test_collision_window_starts_at_contact_not_at_the_request(sim, monkeypatch):
    _patch_collision_calls(sim, monkeypatch)
    sim.put_vehicle("app_a_0", "lead", speed=9.0, pos=50.0)
    sim.put_vehicle("app_a_0", "fol", speed=9.0, pos=40.0)  # 5.8 m bumper gap
    inj = IncidentInjector(
        [PlannedIncident("collision", "app_a_0", start_tick=5, duration_ticks=6)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 8):
        inj.tick(step)
    # closing: the follower ignores the leader but is clamped to land on its bumper
    assert sim.speed_mode["fol"] == 0
    assert any(v == "fol" and abs(s - 5.8) < 1e-6 for v, s in sim.set_speed_calls)
    sim.positions["fol"] = 45.7  # bumpers meet
    for step in range(8, 20):
        inj.tick(step)
    inj.finalize(20)
    (w,) = inj.ground_truth()
    assert w.kind == "collision" and w.realised
    assert w.actual_start_tick == 8 and w.end_tick == 14 and w.ended_reason == "released"
    assert sim.speed_mode["fol"] == 31  # restored


def test_collision_that_never_makes_contact_is_unrealised(sim, monkeypatch):
    _patch_collision_calls(sim, monkeypatch)
    sim.put_vehicle("app_a_0", "lead", speed=9.0, pos=50.0)
    sim.put_vehicle("app_a_0", "fol", speed=9.0, pos=40.0)
    inj = IncidentInjector(
        [PlannedIncident("collision", "app_a_0", start_tick=5, duration_ticks=6)],
        link_lanes=_LINK_LANES,
    )
    for step in range(1, 40):
        inj.tick(step)
    inj.finalize(40)
    (w,) = inj.ground_truth()
    assert not w.realised and w.ended_reason == "never_started"

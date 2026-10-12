"""`DischargeObserver` measured against a known ground truth.

The whole value of this observer is that the number it produces is the
real discharge rate, so the tests that matter are the ones that construct
a queue discharging at an exactly known rate and check the observer
recovers it. A synthetic TraCI is the only way to have a ground truth at
all -- against SUMO the "true" saturation flow is precisely the unknown
being estimated.

This file exists because the first implementation was wrong by +11.8% at
a 20s green and +40% at an 8s green, and nothing caught it: the unit
tests checked the *learner* against synthetic residuals and the
integration runs had nothing to compare against. The bug was a
numerator/denominator mismatch -- start-up lost time subtracted from the
green duration while the start-up wave's own crossings stayed in the
count.
"""

from __future__ import annotations

import sys
import types

import pytest

_STATE = {"ids": [], "pos": {}, "halting": 0, "teleports": [], "speed": 5.0}


def _install_fake_traci():
    """A minimal TraCI stand-in. Installed into `sys.modules` before the
    observer imports it, and torn down afterwards so no other test in the
    suite can see it."""

    class _Lane:
        @staticmethod
        def getLength(lane_id): return 100.0
        @staticmethod
        def getLastStepVehicleIDs(lane_id): return list(_STATE["ids"])
        @staticmethod
        def getLastStepHaltingNumber(lane_id): return _STATE["halting"]

    class _Veh:
        @staticmethod
        def getLanePosition(v): return _STATE["pos"][v]
        @staticmethod
        def getTypeID(v): return "car"
        @staticmethod
        def getSpeed(v): return _STATE["speed"]

    class _Sim:
        @staticmethod
        def getStartingTeleportIDList(): return list(_STATE["teleports"])

    fake = types.ModuleType("traci")
    fake.lane, fake.vehicle, fake.simulation = _Lane, _Veh, _Sim
    fake.TraCIException = type("TraCIException", (Exception,), {})
    return fake


@pytest.fixture
def observer_cls(monkeypatch):
    monkeypatch.setitem(sys.modules, "traci", _install_fake_traci())
    for mod in [m for m in sys.modules if "discharge_observer" in m]:
        del sys.modules[mod]
    from sim_service.signal_controller.discharge_observer import DischargeObserver
    return DischargeObserver


def _discharge_run(observer_cls, *, green_s, rate_per_s, startup_lost_s=2.0, queued=200):
    """Queue `queued` vehicles, hold green for `green_s`, discharge exactly
    `rate_per_s` per second. Returns the observer's completed observation."""
    obs = observer_cls({"m0": "lane0"}, {"car": 1.0}, startup_lost_s=startup_lost_s)
    veh = [f"v{i}" for i in range(queued)]
    _STATE["ids"] = list(veh)
    _STATE["pos"] = {v: 100.0 - i * 5.0 for i, v in enumerate(veh)}
    _STATE["halting"] = queued
    _STATE["teleports"] = []
    served = frozenset({"m0"})

    for _ in range(green_s):
        obs.tick(served, 1.0)
        for _ in range(rate_per_s):
            if _STATE["ids"]:
                _STATE["pos"].pop(_STATE["ids"].pop(0), None)
        _STATE["pos"] = {v: 100.0 - i * 5.0 for i, v in enumerate(_STATE["ids"])}
        _STATE["halting"] = len(_STATE["ids"])

    completed = obs.tick(frozenset(), 1.0)
    assert completed, "the green ending must produce exactly one observation"
    return completed[0]


@pytest.mark.parametrize("green_s", [8, 10, 15, 20, 30, 45, 60])
def test_measured_rate_matches_ground_truth_at_every_green_duration(observer_cls, green_s):
    """The regression that motivated this file. A constant 1.0 PCU/s queue
    must measure as 1.0 PCU/s regardless of how long the green was.

    The pre-fix implementation returned 1.400 at an 8s green and 1.118 at
    20s -- a bias that shrinks with green length, so it was largest
    exactly where greens are shortest, and invisible in any test that did
    not know the true rate."""
    _, pcu, effective, _ = _discharge_run(observer_cls, green_s=green_s, rate_per_s=1)
    assert effective > 0
    assert pcu / effective == pytest.approx(1.0, abs=1e-9), (
        f"green={green_s}s measured {pcu / effective:.3f} PCU/s against a true 1.000"
    )


@pytest.mark.parametrize("rate", [1, 2, 3])
def test_measured_rate_scales_with_the_real_rate(observer_cls, rate):
    _, pcu, effective, _ = _discharge_run(observer_cls, green_s=30, rate_per_s=rate)
    assert pcu / effective == pytest.approx(float(rate), abs=1e-9)


def test_effective_green_excludes_exactly_the_startup_wave(observer_cls):
    """Denominator check, isolated: a 20s green with 2s start-up lost time
    yields 18s of effective green, not 20 and not 17."""
    _, _, effective, _ = _discharge_run(observer_cls, green_s=20, rate_per_s=1, startup_lost_s=2.0)
    assert effective == pytest.approx(18.0)


def test_teleported_vehicles_are_not_counted_as_discharge(observer_cls):
    """A teleport removes a vehicle from the lane without it crossing.
    Counting it would inflate the measured capacity of exactly the
    movements performing worst, which is the opposite of useful."""
    obs = observer_cls({"m0": "lane0"}, {"car": 1.0}, startup_lost_s=0.0)
    _STATE["ids"] = ["a", "b"]
    _STATE["pos"] = {"a": 98.0, "b": 93.0}
    _STATE["halting"] = 2
    _STATE["teleports"] = []
    served = frozenset({"m0"})
    obs.tick(served, 1.0)

    _STATE["ids"] = ["b"]
    _STATE["pos"] = {"b": 98.0}
    _STATE["teleports"] = ["a"]          # 'a' vanished by teleport, not by crossing
    obs.tick(served, 1.0)

    _STATE["teleports"] = []
    completed = obs.tick(frozenset(), 1.0)
    assert completed[0][1] == 0.0, "a teleported vehicle must not count as discharge"


def test_a_vehicle_leaving_from_far_back_is_not_counted(observer_cls):
    """Leaving the lane from well behind the stop line is a lane change,
    not a crossing."""
    obs = observer_cls({"m0": "lane0"}, {"car": 1.0}, startup_lost_s=0.0)
    _STATE["ids"] = ["far"]
    _STATE["pos"] = {"far": 10.0}        # 90m from the stop line
    _STATE["halting"] = 1
    _STATE["teleports"] = []
    served = frozenset({"m0"})
    obs.tick(served, 1.0)

    _STATE["ids"] = []
    _STATE["pos"] = {}
    obs.tick(served, 1.0)
    completed = obs.tick(frozenset(), 1.0)
    assert completed[0][1] == 0.0


def test_arrival_cohorts_do_not_grow_without_bound(observer_cls):
    """`_track_arrivals` opens a cohort per movement per tick. They must
    retire on their horizon, or a long run accumulates one dict of live
    vehicle ids per second for the whole run."""
    obs = observer_cls({"m0": "lane0"}, {"car": 1.0}, arrival_horizon_s=8.0)
    _STATE["ids"] = ["a", "b", "c"]
    _STATE["pos"] = {"a": 90.0, "b": 80.0, "c": 70.0}
    _STATE["halting"] = 0
    _STATE["teleports"] = []
    served = frozenset({"m0"})

    for _ in range(500):
        obs.tick(served, 1.0, approaching_pcu={"m0": 3.0})
        obs.expired_cohorts()

    open_cohorts = sum(len(v) for v in obs._cohorts.values())  # noqa: SLF001
    assert open_cohorts <= 10, f"cohorts grew to {open_cohorts} over 500 ticks"

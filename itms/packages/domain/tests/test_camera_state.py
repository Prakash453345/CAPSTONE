"""`itms_domain.camera`: the camera state both controller adapters use."""

from __future__ import annotations

import pytest
from itms_domain import JunctionContext
from itms_domain.camera import BlindCameraCheck, confidence_policy, with_camera_state


def _ctx() -> JunctionContext:
    return JunctionContext(intersection_id="J", current_phase_id="P0",
                           current_phase_elapsed_s=3.0, has_demand={"L0": True, "L1": True},
                           wait_times_s={"L0": 9.0, "L1": 2.0},
                           queue_pcu={"L0": 0.0, "L1": 0.0},
                           receiving_occupancy={"L0": 0.0, "L1": 0.0},
                           receiving_queue_pcu={"L0": 0.0, "L1": 0.0},
                           approaching_pcu={"L0": 0.0, "L1": 0.0})


def test_confidence_policies() -> None:
    conf = {"L0": 0.7, "L1": 0.3}
    assert confidence_policy(conf, "honest") == conf
    assert confidence_policy(conf, "failsafe") == {"L1": 0.3}
    assert confidence_policy(conf, "trust") == {}
    with pytest.raises(ValueError):
        confidence_policy(conf, "hopeful")


def test_the_swap_changes_the_queue_state_and_nothing_the_safety_kernel_reads() -> None:
    fields = {"queue_pcu": {"L0": 4.0}, "approaching_pcu": {"L0": 1.0, "L1": 2.0},
              "receiving_occupancy": {"L0": 0.2}, "receiving_queue_pcu": {}}
    new = with_camera_state(_ctx(), fields, {"L0": 0.9, "L1": 0.9}, mode="failsafe",
                            blind={"L1"})
    assert new.queue_pcu == {"L0": 4.0, "L1": 0.0} and new.approaching_pcu["L1"] == 2.0
    assert dict(new.confidence) == {"L1": 0.0}              # blind beats a healthy 0.9
    assert new.has_demand == _ctx().has_demand and new.wait_times_s == _ctx().wait_times_s


def test_vehicles_at_the_stop_bar_the_camera_cannot_see_are_blindness() -> None:
    check = BlindCameraCheck(hold_s=20.0, gap_s=10.0)
    fired = None
    for t in range(1, 40):                                       # a queue creeping over the loop
        if check.update(float(t), {"L0": t % 4 != 0}, {"L0": 0}) and fired is None:
            fired = t
    assert fired is not None and 24 <= fired <= 30               # 20 s of loop time, not 20 s
    assert not check.update(41.0, {"L0": True}, {"L0": 1})       # it saw a car: working again
    assert not check.update(42.0, {"L0": True}, {"L0": 0})       # and the evidence restarts


def test_a_short_miss_or_an_empty_road_is_not_blindness() -> None:
    check = BlindCameraCheck(hold_s=20.0, gap_s=10.0)
    for t in range(280):
        seen = {"L0": 0 if t % 30 < 15 else 2}                   # missed for 15 s at a time
        assert not check.update(float(t), {"L0": True}, seen)
    for t in range(280, 600):                                    # the last car leaves; the camera
        assert not check.update(float(t), {"L0": t < 285}, {"L0": 0})   # rightly sees nothing


def test_a_link_the_camera_does_not_report_on_is_not_judged() -> None:
    check = BlindCameraCheck(hold_s=5.0)
    for t in range(60):
        assert not check.update(float(t), {"L0": True}, {"L0": -1})
        assert not check.update(float(t), {"L1": True}, {})


def test_a_caught_camera_stays_failed_until_it_sees_a_vehicle() -> None:
    check = BlindCameraCheck(hold_s=5.0, gap_s=3.0)
    for t in range(6):
        check.update(float(t), {"L0": True}, {"L0": 0})
    assert check.update(6.0, {"L0": True}, {"L0": 0}) == {"L0"}
    for t in range(7, 60):                                       # the loop goes quiet: still failed
        assert check.update(float(t), {"L0": False}, {"L0": 0}) == {"L0"}
    assert not check.update(60.0, {"L0": False}, {"L0": 1})     # it sees a car: working again

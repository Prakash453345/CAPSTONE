"""`vision_feed`: the controller running on camera state (M8), live."""

from __future__ import annotations

import pytest
from itms_domain import JunctionContext
from sim_service.control.vision_feed import VisionFedStrategy, VisionFeed


class _Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _payload(conf: dict[str, float], q: float = 4.0) -> dict:
    return {"intersection_id": "J", "links": [
        {"link_id": link, "queue_pcu": q, "approaching_pcu": 1.0, "receiving_occupancy": 0.2,
         "receiving_queue_pcu": 0.5, "confidence": c} for link, c in conf.items()]}


def _ctx() -> JunctionContext:
    return JunctionContext(intersection_id="J", current_phase_id="P0",
                           current_phase_elapsed_s=3.0, has_demand={"L0": True, "L1": True},
                           wait_times_s={"L0": 9.0, "L1": 2.0},
                           queue_pcu={"L0": 0.0, "L1": 0.0},
                           receiving_occupancy={"L0": 0.0, "L1": 0.0},
                           receiving_queue_pcu={"L0": 0.0, "L1": 0.0},
                           approaching_pcu={"L0": 0.0, "L1": 0.0})


class _Inner:
    def __init__(self):
        self.seen = None
        self.stats = {"ticks": 0}

    def __call__(self, cfg, ctx):
        self.seen = ctx
        return "plan"


def test_the_controller_sees_the_camera_state_and_only_hard_failures() -> None:
    clock = _Clock()
    feed = VisionFeed(clock=clock)
    feed.on_payload(_payload({"L0": 0.7, "L1": 0.3}))
    inner = _Inner()
    assert VisionFedStrategy(inner, feed, "J")(None, _ctx()) == "plan"
    got = inner.seen
    assert got.queue_pcu == {"L0": 4.0, "L1": 4.0}
    assert got.receiving_occupancy == {"L0": 0.2, "L1": 0.2}
    assert dict(got.confidence) == {"L1": 0.3}           # failsafe: 0.7 is useful, 0.3 is not
    assert got.wait_times_s == {"L0": 9.0, "L1": 2.0}    # safety inputs stay stop-bar truth


@pytest.mark.parametrize(("mode", "expected"), [("honest", {"L0": 0.7, "L1": 0.3}),
                                                ("trust", {})])
def test_other_confidence_modes(mode, expected) -> None:
    feed = VisionFeed(clock=_Clock())
    feed.on_payload(_payload({"L0": 0.7, "L1": 0.3}))
    inner = _Inner()
    VisionFedStrategy(inner, feed, "J", mode)(None, _ctx())
    assert dict(inner.seen.confidence) == expected


def test_stale_or_missing_camera_state_is_a_hard_failure() -> None:
    clock = _Clock()
    feed = VisionFeed(max_age_s=3.0, clock=clock)
    feed.on_payload(_payload({"L0": 0.95}))
    clock.t += 10.0                                       # the vision service went quiet
    inner = _Inner()
    VisionFedStrategy(inner, feed, "J")(None, _ctx())
    assert dict(inner.seen.confidence) == {"L0": 0.0, "L1": 0.0}   # L1 was never reported
    assert inner.seen.queue_pcu["L0"] == 4.0                      # last values, not believed
    assert (feed.junction_ticks, feed.failed_junction_ticks) == (1, 1)


def test_a_replayed_backlog_is_not_mistaken_for_now() -> None:
    clock = _Clock(t=10_000.0)
    feed = VisionFeed(clock=clock)
    feed.on_envelope({"event_type": "LinkStateEstimated", "occurred_at": 1_000_000,
                      "payload": _payload({"L0": 0.95, "L1": 0.95})})   # from long ago
    _, conf = feed.junction("J", ["L0", "L1"])
    assert conf == {"L0": 0.0, "L1": 0.0}
    feed.on_envelope({"event_type": "LinkStateEstimated", "occurred_at": 9_999_000,
                      "payload": _payload({"L0": 0.95, "L1": 0.95}, q=7.0)})
    fields, conf = feed.junction("J", ["L0", "L1"])
    assert conf == {"L0": 0.95, "L1": 0.95} and fields["queue_pcu"]["L0"] == 7.0


def test_an_out_of_order_message_does_not_overwrite_a_newer_one() -> None:
    feed = VisionFeed(clock=_Clock(t=100.0))
    feed.on_payload(_payload({"L0": 0.9}, q=5.0), at=99.0)
    feed.on_payload(_payload({"L0": 0.9}, q=1.0), at=98.0)
    fields, _ = feed.junction("J", ["L0"])
    assert fields["queue_pcu"]["L0"] == 5.0


def test_a_real_envelope_off_the_bus_is_read() -> None:
    # through the real Avro encoding: `occurred_at` comes back as a datetime
    import time

    from itms_common.events import decode_envelope, encode_envelope

    payload = {"intersection_id": "J", "sim_time_s": 12.0, "model": "vision-m8", "links": [
        {"link_id": "L0", "queue_pcu": 3.0, "approaching_pcu": 1.0, "receiving_occupancy": 0.1,
         "receiving_queue_pcu": 0.0, "confidence": 0.9, "c_coverage": 1.0, "c_health": 1.0,
         "c_visibility": 0.9, "c_truncation": 1.0, "queue_truncated": False,
         "hidden_queue_m": 0.0, "vision_score": 0.0, "cameras": ["camJ"]}]}
    env = decode_envelope(encode_envelope("LinkStateEstimated", "vision-service", payload))
    feed = VisionFeed(clock=time.time)
    feed.on_envelope(env)
    fields, conf = feed.junction("J", ["L0"])
    assert conf == {"L0": 0.9} and fields["queue_pcu"]["L0"] == 3.0


def test_a_camera_that_sees_nothing_on_an_occupied_lane_is_treated_as_failed() -> None:
    clock = _Clock()
    feed = VisionFeed(clock=clock)
    inner = _Inner()
    s = VisionFedStrategy(inner, feed, "J",                 # failsafe: the check is on
                          stopbar=lambda: {"L0": True, "L1": True})   # both loops occupied
    for t in range(0, 61):
        clock.t = 1000.0 + t
        feed.on_payload({"intersection_id": "J", "links": [
            {"link_id": k, "queue_pcu": 0.0, "approaching_pcu": 0.0, "receiving_occupancy": 0.0,
             "receiving_queue_pcu": 0.0, "confidence": 0.95, "vehicles_seen": 0}
            for k in ("L0", "L1")]})
        s.set_sim_time(float(t))
        s(None, _ctx())
    assert dict(inner.seen.confidence) == {"L0": 0.0, "L1": 0.0} and s.blind_ticks > 0
    trusting = VisionFedStrategy(_Inner(), feed, "J", "trust", stopbar=lambda: {})
    assert trusting.check is None                           # trust means believing the camera
    assert VisionFedStrategy(_Inner(), feed, "J").check is None   # no loops, nothing to check

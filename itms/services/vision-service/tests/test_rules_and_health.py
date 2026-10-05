"""Incident rules fire on the incident and stay quiet on its look-alikes;
camera health notices frozen, blind and bumped cameras."""

from __future__ import annotations

import numpy as np
import pytest
from vision_service.classes import VClass
from vision_service.health import CameraStatus, DriftMonitor, PixelHealthMonitor
from vision_service.incidents import IncidentEngine, RuleConfig, StaticSignalState
from vision_service.records import GroundTrack
from vision_service.state import LinkStateEstimator


def _gt(network, lane_id="in_0", s=196.0, **kw) -> GroundTrack:
    lane = network.lanes[lane_id]
    base = dict(camera_id="camJ", track_id=1, t=0.0, xy=lane.point_at(s)[0],
                velocity=np.zeros(2), vclass=VClass.CAR, pcu=1.0, length_m=4.2,
                resolution_m_per_px=0.1, coasting=False, stopped=True, stopped_since=0.0,
                born_t=-30.0, moved_m=40.0, lane_id=lane_id, s=s,
                heading_deg=float(lane.heading_at(s)[0]))
    base.update(kw)
    return GroundTrack(**base)


def _moving(network, lane_id, s, tid, speed=8.0):
    lane = network.lanes[lane_id]
    h = float(lane.heading_at(s)[0])
    v = speed * np.array([np.sin(np.radians(h)), np.cos(np.radians(h))])
    return _gt(network, lane_id, s, track_id=tid, stopped=False, stopped_since=None,
               velocity=v)


def _engine(rig, links, signal, **cfg):
    approach, receiving = links
    return IncidentEngine(rig, approach, receiving, RuleConfig(**cfg), signal), \
        LinkStateEstimator(rig, approach, receiving)


def _run(engine, est, frames):
    for t, tracks in frames:
        for g in tracks:
            g.t = t
        est.update(t, tracks)
        engine.update(t, tracks, est)
    return engine


def test_stuck_on_green_while_the_sibling_lane_flows(network, rig, links) -> None:
    sig = StaticSignalState({("J", "L0"): "G", ("J", "L1"): "G"},
                            {("J", "L0"): 0.0, ("J", "L1"): 0.0})
    eng, est = _engine(rig, links, sig)
    frames = []
    for t in range(0, 30):
        stuck = _gt(network, "in_0", 196.0, stopped_since=-5.0)
        flow = _moving(network, "in_1", 170.0 + (t % 5) * 5, tid=10 + t)
        frames.append((float(t), [stuck, flow]))
    _run(eng, est, frames)
    rules = {c.rule for c in eng.active.values()}
    assert "stuck_on_green" in rules


def test_waiting_on_a_permissive_green_is_not_an_incident(network, rig, links) -> None:
    sig = StaticSignalState({("J", "L0"): "g", ("J", "L1"): "G"},
                            {("J", "L0"): 0.0, ("J", "L1"): 0.0})
    eng, est = _engine(rig, links, sig)
    frames = [(float(t), [_gt(network, "in_0", 196.0, stopped_since=-5.0),
                          _moving(network, "in_1", 170.0 + (t % 5) * 5, tid=10 + t)])
              for t in range(0, 60)]
    _run(eng, est, frames)
    assert not eng.active


def test_a_red_light_queue_is_not_an_incident(network, rig, links) -> None:
    sig = StaticSignalState({("J", "L0"): "r"}, {})
    eng, est = _engine(rig, links, sig)
    frames = [(float(t), [_gt(network, "in_0", 196.0, stopped_since=-5.0)]) for t in range(90)]
    _run(eng, est, frames)
    assert not eng.active


def test_furniture_never_raises_a_stall(network, rig, links) -> None:
    """A detector hotspot is 'stopped' forever -- but it never arrived."""
    sig = StaticSignalState({("J", "L0"): "G", ("J", "L1"): "G"},
                            {("J", "L0"): 0.0, ("J", "L1"): 0.0})
    eng, est = _engine(rig, links, sig)
    frames = [(float(t), [_gt(network, "in_0", 120.0, moved_m=0.0, stopped_since=-100.0),
                          _moving(network, "in_1", 170.0, tid=10 + t)]) for t in range(120)]
    _run(eng, est, frames)
    assert not eng.active


def test_a_vehicle_that_crept_in_and_stalled_is_flagged(network, rig, links) -> None:
    """It never went fast (moved_m 0), but it made 8 m of progress: it
    arrived. A hotspot makes none (the test above)."""
    sig = StaticSignalState({("J", "L0"): "G", ("J", "L1"): "G"},
                            {("J", "L0"): 0.0, ("J", "L1"): 0.0})
    eng, est = _engine(rig, links, sig)
    frames = []
    for t in range(0, 30):
        crept = _gt(network, "in_0", 196.0, stopped_since=-5.0, moved_m=0.0, displaced_m=8.0)
        flow = _moving(network, "in_1", 170.0 + (t % 5) * 5, tid=10 + t)
        frames.append((float(t), [crept, flow]))
    _run(eng, est, frames)
    assert "stuck_on_green" in {c.rule for c in eng.active.values()}


def test_midblock_breakdown_sooner_when_it_blocks_traffic(network, rig, links) -> None:
    eng, est = _engine(rig, links, StaticSignalState())
    frames = []
    for t in range(0, 25):
        broken = _gt(network, "in_0", 130.0, stopped_since=0.0, track_id=1)
        behind = [_gt(network, "in_0", 122.0, stopped_since=2.0, track_id=2),
                  _gt(network, "in_0", 115.0, stopped_since=4.0, track_id=3)]
        frames.append((float(t), [broken, *behind]))
    _run(eng, est, frames)
    assert any(c.rule == "midblock_stop" for c in eng.active.values())


def test_an_auto_rickshaw_boarding_stop_is_not_a_breakdown(network, rig, links) -> None:
    eng, est = _engine(rig, links, StaticSignalState())
    frames = [(float(t), [_gt(network, "in_0", 130.0, stopped_since=0.0,
                              vclass=VClass.AUTO_RICKSHAW)]) for t in range(0, 60)]
    _run(eng, est, frames)
    assert not eng.active


def test_wrong_way(network, rig, links) -> None:
    eng, est = _engine(rig, links, StaticSignalState())
    frames = []
    for t in range(8):
        g = _gt(network, "in_0", 180.0 - 6.0 * t, stopped=False, stopped_since=None,
                velocity=np.array([-6.0, 0.0]), heading_deg=270.0, lane_agrees=False)
        frames.append((float(t), [g]))
    _run(eng, est, frames)
    assert any(c.rule == "wrong_way" for c in eng.active.values())


def test_two_tracks_on_one_vehicle_are_not_a_crash(network, rig, links) -> None:
    eng, est = _engine(rig, links, StaticSignalState())
    frames = []
    for t in range(40):
        a = _gt(network, "in_0", 130.0, track_id=1, stopped_since=0.0,
                history=[(float(k), *network.lanes["in_0"].point_at(130.0)[0]) for k in range(t)])
        b = _gt(network, "in_0", 130.5, track_id=2, stopped_since=0.0,
                history=[(float(k), *network.lanes["in_0"].point_at(130.5)[0]) for k in range(t)])
        frames.append((float(t), [a, b]))
    _run(eng, est, frames)
    assert not any(c.rule == "collision_cue" for c in eng.active.values())


def test_a_converging_pair_that_stops_is_a_collision_cue(network, rig, links) -> None:
    eng, est = _engine(rig, links, StaticSignalState())
    lane = network.lanes["in_0"]
    hist_a = [(float(k), *lane.point_at(60.0 + 12.0 * k)[0]) for k in range(6)]
    hist_b = [(float(k), *lane.point_at(128.0)[0]) for k in range(6)]
    frames = []
    for t in range(6, 30):
        a = _gt(network, "in_0", 130.0, track_id=1, stopped_since=6.0, history=list(hist_a))
        b = _gt(network, "in_0", 128.5, track_id=2, stopped_since=6.0, history=list(hist_b))
        hist_a.append((float(t), *lane.point_at(130.0)[0]))
        hist_b.append((float(t), *lane.point_at(128.5)[0]))
        frames.append((float(t), [a, b]))
    _run(eng, est, frames)
    assert any(c.rule == "collision_cue" for c in eng.active.values())


def test_one_vehicle_seen_by_two_cameras_is_not_a_crash(network, rig, links) -> None:
    """The same converging pair, but one track from each of two cameras --
    two cameras seeing one vehicle, not a collision."""
    eng, est = _engine(rig, links, StaticSignalState())
    lane = network.lanes["in_0"]
    hist_a = [(float(k), *lane.point_at(60.0 + 12.0 * k)[0]) for k in range(6)]
    hist_b = [(float(k), *lane.point_at(128.0)[0]) for k in range(6)]
    frames = []
    for t in range(6, 30):
        a = _gt(network, "in_0", 130.0, track_id=1, stopped_since=6.0, history=list(hist_a))
        b = _gt(network, "in_0", 128.5, track_id=2, stopped_since=6.0, history=list(hist_b),
                camera_id="camOther")
        hist_a.append((float(t), *lane.point_at(130.0)[0]))
        hist_b.append((float(t), *lane.point_at(128.5)[0]))
        frames.append((float(t), [a, b]))
    _run(eng, est, frames)
    assert not any(c.rule == "collision_cue" for c in eng.active.values())


def test_candidates_resolve_when_the_evidence_goes(network, rig, links) -> None:
    eng, est = _engine(rig, links, StaticSignalState(), clear_s=5.0)
    frames = [(float(t), [_gt(network, "in_0", 130.0, stopped_since=0.0)]) for t in range(0, 50)]
    frames += [(float(t), []) for t in range(50, 60)]
    _run(eng, est, frames)
    assert not eng.active


# ---- health --------------------------------------------------------------------------------


def _textured(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.random((360, 640, 3)) * 255).astype(np.uint8)


def test_frozen_feed_fails() -> None:
    mon = PixelHealthMonitor(frozen_failed_after=5)
    frame = _textured()
    for _ in range(8):
        mon.update(frame)
    assert mon.assess()[0] is CameraStatus.FAILED


def test_covered_lens_fails_and_blur_degrades() -> None:
    mon = PixelHealthMonitor(baseline_frames=5)
    for i in range(6):
        mon.update(_textured(i))
    mon.update(np.full((360, 640, 3), 128, dtype=np.uint8))
    assert mon.assess()[0] is CameraStatus.FAILED
    mon2 = PixelHealthMonitor(baseline_frames=5)
    for i in range(6):
        mon2.update(_textured(i))
    blurred = _textured(9).astype(float)
    for _ in range(6):  # crude box blur
        blurred = (blurred + np.roll(blurred, 1, 0) + np.roll(blurred, 1, 1)) / 3
    mon2.update(blurred.astype(np.uint8))
    assert mon2.assess()[0] is CameraStatus.DEGRADED


def test_drift_monitor_flags_a_bumped_camera() -> None:
    mon = DriftMonitor(baseline_s=60.0, window_s=30.0, min_samples=10)
    nadir = np.zeros(2)

    def tracks(t, heading_err):
        out = []
        for k in range(5):
            h = 90.0 + heading_err
            v = 10.0 * np.array([np.sin(np.radians(h)), np.cos(np.radians(h))])
            out.append(GroundTrack("c", k, t, np.array([30.0 + 5 * k, 0.0]), v, VClass.CAR, 1.0,
                                   4.2, 0.2, False, heading_deg=h, lane_id="x"))
        return out

    for t in range(0, 90):
        mon.observe(float(t), tracks(t, 1.0), nadir, lambda g: 90.0)
    assert not mon.drift
    for t in range(90, 150):
        mon.observe(float(t), tracks(t, 12.0), nadir, lambda g: 90.0)
    assert mon.drift


@pytest.mark.parametrize("brightness", [5, 250])
def test_bad_exposure_degrades(brightness) -> None:
    mon = PixelHealthMonitor(baseline_frames=1)
    mon.update(_textured())
    frame = np.clip(_textured(3).astype(int) // 10 + brightness, 0, 255).astype(np.uint8)
    mon.update(frame)
    assert mon.assess()[0] is not CameraStatus.OK


def test_a_low_texture_scene_is_healthy_but_fog_is_not() -> None:
    """Contrast is judged against the camera's own baseline: an empty grey
    car park is flat and fine; the same view going flat *further* is fog."""
    rng = np.random.default_rng(0)

    def flat(seed: int) -> np.ndarray:  # grey road, pixel std ~ 9
        r = np.random.default_rng(seed)
        return np.clip(128 + r.normal(0, 9, (360, 640, 3)), 0, 255).astype(np.uint8)

    mon = PixelHealthMonitor(baseline_frames=5)
    for i in range(20):
        mon.update(flat(i))
        if i >= 5:
            assert mon.assess()[0] is CameraStatus.OK
    fog = (flat(99).astype(float) * 0.3 + 200 * 0.7 + rng.normal(0, 0.5, (360, 640, 3)))
    mon.update(np.clip(fog, 0, 255).astype(np.uint8))
    status, _, reasons = mon.assess()
    assert status is not CameraStatus.OK and reasons  # low contrast / edge collapse


def test_operating_points_switch_rules_off() -> None:
    from vision_service.incidents import OPERATING_POINTS

    assert set(OPERATING_POINTS["hand_set"].enabled) == {
        "stuck_on_green", "midblock_stop", "wrong_way", "collision_cue", "flow_void"}
    assert OPERATING_POINTS["quiet"].enabled == ("midblock_stop",)
    for point in ("quiet", "assist"):   # fire on dense queues / never exercised
        assert not {"collision_cue", "wrong_way"} & set(OPERATING_POINTS[point].enabled)


def test_a_disabled_rule_never_fires(network, rig, links) -> None:
    from vision_service.incidents import OPERATING_POINTS

    eng, est = _engine(rig, links, StaticSignalState())
    eng.cfg = OPERATING_POINTS["quiet"]
    frames = []
    for t in range(8):  # the same wrong-way driver test_wrong_way catches
        g = _gt(network, "in_0", 180.0 - 6.0 * t, stopped=False, stopped_since=None,
                velocity=np.array([-6.0, 0.0]), heading_deg=270.0, lane_agrees=False)
        frames.append((float(t), [g]))
    _run(eng, est, frames)
    assert not eng.active and not eng.hits


def _arrivals(mon, t0, t1, every_s, start_id=0, moved=True):
    """A vehicle arriving every `every_s` seconds, each seen for ~20 s."""
    tid = start_id
    live: list[tuple[int, float]] = []
    for t in range(t0, t1):
        if (t - t0) % every_s == 0:
            live.append((tid, float(t)))
            tid += 1
        live = [(i, b) for i, b in live if t - b < 20]
        mon.observe(float(t), [GroundTrack("c", i, float(t), np.zeros(2), np.zeros(2), VClass.CAR,
                                           1.0, 4.2, 0.2, False,
                                           moved_m=30.0 if moved else 0.0)
                               for i, _ in live])
    return tid


def test_a_blind_camera_on_a_busy_road_is_flagged_and_recovers() -> None:
    from vision_service.health import ActivityMonitor

    mon = ActivityMonitor()
    nxt = _arrivals(mon, 0, 1200, every_s=6)          # 10 vehicles a minute
    assert not mon.silent
    for t in range(1200, 1400):                        # the detector goes blind
        mon.observe(float(t), [])
    assert mon.silent and "normal" in mon.reason
    _arrivals(mon, 1400, 1420, every_s=6, start_id=nxt)  # sight comes back
    assert not mon.silent


def test_a_quiet_road_or_a_jam_is_not_a_blind_camera() -> None:
    from vision_service.health import ActivityMonitor

    quiet = ActivityMonitor()
    nxt = _arrivals(quiet, 0, 1200, every_s=60)        # one vehicle a minute
    for t in range(1200, 1500):
        quiet.observe(float(t), [])
    assert not quiet.silent                            # 2 expected in 2 min: a lull
    jam = ActivityMonitor()
    _arrivals(jam, 0, 1200, every_s=6)
    stuck = [GroundTrack("c", 900 + k, 0.0, np.zeros(2), np.zeros(2), VClass.CAR, 1.0, 4.2,
                         0.2, False, stopped=True, moved_m=40.0) for k in range(6)]
    for t in range(1200, 1500):                        # nothing moves, but cars are there
        jam.observe(float(t), stuck)
    assert not jam.silent
    assert nxt > 0


def test_a_camera_that_never_sees_a_vehicle_is_flagged_after_commissioning() -> None:
    from vision_service.health import ActivityMonitor

    mon = ActivityMonitor(commission_s=600.0)
    hotspot = [GroundTrack("c", 1, 0.0, np.zeros(2), np.zeros(2), VClass.CAR, 1.0, 4.2, 0.2,
                           False, moved_m=0.0)]          # a billboard does not count
    for t in range(0, 590):
        mon.observe(float(t), hotspot)
    assert not mon.silent
    for t in range(590, 620):
        mon.observe(float(t), hotspot)
    assert mon.silent and "since start" in mon.reason


def test_a_car_sitting_in_a_long_jam_is_one_arrival() -> None:
    from vision_service.health import ActivityMonitor

    mon = ActivityMonitor()
    stuck = [GroundTrack("c", 7, 0.0, np.zeros(2), np.zeros(2), VClass.CAR, 1.0, 4.2, 0.2,
                         False, stopped=True, moved_m=40.0)]
    for t in range(0, 1500):                           # 25 minutes, the same car
        mon.observe(float(t), stuck)
    assert mon._rate * 60.0 < 0.1                      # not one "arrival" every 8 minutes


def test_a_silent_camera_is_reported_but_only_a_never_working_one_is_a_hard_failure() -> None:
    """Traffic that stops is not proof of a blind camera (the first version sent
    junctions to fixed-time at the end of every gate run, when the demand
    ends); a camera that has never seen a vehicle is."""
    from vision_service.health import ActivityMonitor, CameraHealth

    busy = CameraHealth("c")
    nxt = _arrivals(busy.activity, 0, 1200, every_s=6)
    for t in range(1200, 1400):                        # the road goes quiet
        busy.saw_frame(float(t))
        busy.activity.observe(float(t), [])
    status, score, reasons = busy.assess(1400.0)
    assert status is CameraStatus.DEGRADED and score == 1.0 and "normal" in reasons[-1]
    blind = CameraHealth("d", activity=ActivityMonitor(commission_s=600.0))
    for t in range(0, 620):
        blind.saw_frame(float(t))
        blind.activity.observe(float(t), [])
    status, score, _ = blind.assess(620.0)
    assert status is CameraStatus.DEGRADED and score == 0.3
    assert nxt > 0


_CONTACT = dict(collision_stop_s=10.0, collision_contact_m=1.0, collision_max_dt_stop=2.0,
                collision_max_neighbours=1, collision_min_v3=5.0, collision_skip_red=True,
                enabled=("collision_cue",))


def _pair_frames(network, s_a, s_b, stop_a=6.0, stop_b=6.0):
    lane = network.lanes["in_0"]
    hist_a = [(float(k), *lane.point_at(s_a - 12.0 * (6 - k))[0]) for k in range(6)]
    hist_b = [(float(k), *lane.point_at(s_b - 6.0 * (6 - k))[0]) for k in range(6)]
    frames = []
    for t in range(6, 30):
        a = _gt(network, "in_0", s_a, track_id=1, stopped_since=stop_a, history=list(hist_a))
        b = _gt(network, "in_0", s_b, track_id=2, stopped_since=stop_b, history=list(hist_b))
        hist_a.append((float(t), *lane.point_at(s_a)[0]))
        hist_b.append((float(t), *lane.point_at(s_b)[0]))
        frames.append((float(t), [a, b]))
    return frames


def test_contact_mode_fires_on_an_abrupt_pair_in_contact(network, rig, links) -> None:
    eng, est = _engine(rig, links, StaticSignalState(), **_CONTACT)
    _run(eng, est, _pair_frames(network, 130.0, 126.0))   # 4.0 m apart, 4.2 m long: touching
    assert any(c.rule == "collision_cue" for c in eng.active.values())


def test_contact_mode_ignores_a_queue_gap_and_a_staggered_stop(network, rig, links) -> None:
    eng, est = _engine(rig, links, StaticSignalState(), **_CONTACT)
    _run(eng, est, _pair_frames(network, 130.0, 123.0))   # 7 m apart: standing-queue gap
    assert not any(c.rule == "collision_cue" for c in eng.active.values())
    eng, est = _engine(rig, links, StaticSignalState(), **_CONTACT)
    _run(eng, est, _pair_frames(network, 130.0, 126.0, stop_a=6.0, stop_b=14.0))
    assert not any(c.rule == "collision_cue" for c in eng.active.values())


def test_accident_point_is_opt_in() -> None:
    from vision_service.incidents import DEFAULT_OPERATING_POINT, OPERATING_POINTS

    assert "collision_cue" in OPERATING_POINTS["accident"].enabled
    assert DEFAULT_OPERATING_POINT == "quiet"

"""Ground tracking and the per-link estimator against the synthetic road,
driven through the real pipeline with the ideal detector so every number has
an exact expected value."""

from __future__ import annotations

import numpy as np
import pytest
from vision_service.classes import VClass
from vision_service.pipeline import CameraFault, VisionSystem
from vision_service.records import GroundTrack
from vision_service.state import EstimatorConfig, LinkStateEstimator

from tests.test_simcam import vehicles_on


def _system(rig, links, **kw) -> VisionSystem:
    approach, receiving = links
    return VisionSystem(rig, approach, receiving, preset="ideal", seed=0, fps=5.0, **kw)


def _drive(vs: VisionSystem, snaps) -> None:
    prev = None
    for s in snaps:
        vs.step_world(prev, s)
        vs.tick(s.t, keep_tracks=True)
        prev = s


def _gt(**kw) -> GroundTrack:
    base = dict(camera_id="camJ", track_id=1, t=100.0, xy=np.zeros(2), velocity=np.zeros(2),
                vclass=VClass.CAR, pcu=1.0, length_m=4.2, resolution_m_per_px=0.1,
                coasting=False, stopped=True, stopped_since=90.0, born_t=10.0, moved_m=50.0,
                lane_id="in_0", s=190.0)
    base.update(kw)
    return GroundTrack(**base)


def test_speed_and_position_of_a_moving_vehicle(network, rig, links) -> None:
    vs = _system(rig, links)
    snaps = [vehicles_on(network, "in_0", [("a", VClass.CAR, 110.0 + 10.0 * k, 10.0)], t=k)
             for k in range(7)]
    _drive(vs, snaps)
    assert vs.last is not None
    g = [x for x in vs.last.tracks if x.truth_id == "a"][0]
    assert g.speed_known
    assert g.speed == pytest.approx(10.0, abs=0.6)
    assert np.hypot(*(g.xy - snaps[-1].xy[0])) < 1.5
    assert g.lane_id == "in_0" and not g.stopped


def test_a_queue_at_red_is_counted_in_pcu(network, rig, links) -> None:
    vs = _system(rig, links)
    queue = [("c1", VClass.CAR, 196.0, 0.0), ("m1", VClass.MOTORCYCLE, 190.0, 0.0),
             ("b1", VClass.BUS, 180.0, 0.0), ("a1", VClass.AUTO_RICKSHAW, 169.0, 0.0)]
    # they drive in first (so the tracks have velocity), then sit
    arrive = [vehicles_on(network, "in_0", [(v, c, s - 12 + 3 * k, 3.0) for v, c, s, _ in queue],
                          t=k) for k in range(5)]
    sit = [vehicles_on(network, "in_0", queue, t=5 + k) for k in range(6)]
    _drive(vs, arrive + sit)
    qs = vs.estimator.queue_sample("J")
    assert qs["queue_pcu"]["L0"] == pytest.approx(1.0 + 0.3 + 3.0 + 0.6)
    assert qs["queue_pcu"]["L1"] == 0.0
    assert qs["confidence"]["L0"] >= 0.8


def test_approaching_counts_only_what_arrives_within_the_horizon(network, rig, links) -> None:
    vs = _system(rig, links)
    # at 10 m/s after 5 s: 'near' is ~38 m out (4 s, counted), 'far' ~98 m out (10 s, not)
    snaps = [vehicles_on(network, "in_1", [("near", VClass.CAR, 110.0 + 10 * k, 10.0),
                                          ("far", VClass.CAR, 50.0 + 10 * k, 10.0)], t=k)
             for k in range(6)]
    _drive(vs, snaps)
    lane = vs.estimator.lanes["in_1"]
    assert lane.approaching_pcu == pytest.approx(1.0)


def test_an_unseen_lane_has_zero_confidence_not_zero_vehicles(network, rig, links) -> None:
    est = LinkStateEstimator(rig, {"J": {"L9": "back_0"}}, {"J": {"L9": "out_0"}})
    est.update(0.0, [])
    e = est.links[("J", "L9")]
    # back_0 runs the other way along the road, so the camera sees it from its far end
    assert e.confidence < 0.8 or e.c_coverage < 1.0


def test_offline_camera_drives_confidence_to_zero(network, rig, links) -> None:
    vs = _system(rig, links)
    vs.inject_fault("camJ", CameraFault("offline", t_start=3.0))
    snaps = [vehicles_on(network, "in_0", [("a", VClass.CAR, 150.0, 0.0)], t=k) for k in range(8)]
    _drive(vs, snaps)
    assert vs.last is not None
    assert vs.last.camera_status["camJ"][0] == "FAILED"
    assert vs.estimator.queue_sample("J")["confidence"]["L0"] == 0.0


def test_a_camera_back_from_an_outage_starts_tracking_afresh(network, rig, links) -> None:
    # a car drives in and queues; the camera goes dark for ten minutes; when
    # it comes back a car sits in the same spot. It must not inherit a stop
    # that began before the outage (that reads as a ten-minute stall).
    vs = _system(rig, links)
    vs.inject_fault("camJ", CameraFault("offline", t_start=10.0, t_end=610.0))
    arrive = [vehicles_on(network, "in_0", [("a", VClass.CAR, 170.0 + 3.0 * k, 3.0)], t=k)
              for k in range(5)]
    sit = [vehicles_on(network, "in_0", [("a", VClass.CAR, 185.0, 0.0)], t=5 + k)
           for k in range(5)]
    back = [vehicles_on(network, "in_0", [("b", VClass.CAR, 185.0, 0.0)], t=610 + k)
            for k in range(8)]
    _drive(vs, arrive + sit)
    assert vs.last is not None
    before = {g.track_id for g in vs.last.tracks}
    _drive(vs, back)
    assert vs.last is not None
    after = [g for g in vs.last.tracks if g.truth_id == "b"]
    assert after and after[0].track_id not in before
    assert after[0].born_t >= 610.0 and after[0].moved_m == 0.0
    assert after[0].stopped_since is None or after[0].stopped_since >= 610.0
    assert vs.pipelines["camJ"].resets == 1


def test_creeping_counts_as_arriving_and_standing_still_does_not(network, rig, links) -> None:
    vs = _system(rig, links)
    creep = [vehicles_on(network, "in_0", [("a", VClass.CAR, 176.0 + 1.0 * k, 1.0),
                                           ("p", VClass.CAR, 150.0, 0.0)], t=k)
             for k in range(12)]   # 1 m/s -- below the 1.5 m/s that counts as travel
    _drive(vs, creep)
    assert vs.last is not None
    got = {g.truth_id: g for g in vs.last.tracks}
    assert got["a"].moved_m < 5.0 <= got["a"].displaced_m
    assert got["p"].displaced_m < 1.0


def test_a_blind_camera_keeps_sending_frames_and_looks_healthy(network, rig, links) -> None:
    """The failure the stop-bar cross-check exists for: frames arrive, the
    detector finds nothing, and nothing inside the vision system can tell
    that "empty road" from a real one within the first minutes."""
    vs = _system(rig, links)
    vs.inject_fault("camJ", CameraFault("blind", t_start=5.0))
    snaps = [vehicles_on(network, "in_0", [("a", VClass.CAR, 185.0, 0.0)], t=k) for k in range(12)]
    _drive(vs, snaps)
    assert vs.last is not None
    assert vs.last.camera_status["camJ"][0] != "FAILED"
    sample = vs.estimator.queue_sample("J")
    assert sample["queue_pcu"]["L0"] == 0.0 and sample["confidence"]["L0"] > 0.5


def test_vehicles_seen_counts_the_whole_approach(network, rig, links) -> None:
    """The cross-check asks "does this camera see anything on this approach";
    a car the tracker put in the neighbouring lane still counts."""
    est = LinkStateEstimator(rig, links[0], links[1])
    lane = network.lanes["in_1"]
    car = _gt(track_id=3, xy=lane.point_at(190.0)[0], s=190.0, lane_id="in_1")
    est.update(100.0, [car])
    assert est.links[("J", "L0")].vehicles_seen == 1 == est.links[("J", "L1")].vehicles_seen
    assert est.queue_sample("J")["vehicles_seen"]["L0"] == 1.0


def test_furniture_is_not_queue(network, rig, links) -> None:
    est = LinkStateEstimator(rig, links[0], links[1])
    lane = network.lanes["in_0"]
    billboard = _gt(track_id=7, xy=lane.point_at(150.0)[0], s=150.0, moved_m=0.0, born_t=0.0,
                    stopped_since=0.0)
    car = _gt(track_id=8, xy=lane.point_at(196.0)[0], s=196.0, moved_m=40.0, born_t=80.0)
    for t in range(0, 130, 1):
        billboard.t = car.t = float(t)
        est.update(float(t), [billboard, car])
    assert est.lanes["in_0"].stopped_pcu == pytest.approx(1.0)


def test_cross_camera_duplicates_are_merged(network, rig, links) -> None:
    est = LinkStateEstimator(rig, links[0], links[1])
    lane = network.lanes["in_0"]
    a = _gt(camera_id="camJ", xy=lane.point_at(196.0)[0], s=196.0, resolution_m_per_px=0.3)
    b = _gt(camera_id="camOther", track_id=99, xy=lane.point_at(195.0)[0], s=195.0,
            resolution_m_per_px=0.1)
    est.update(100.0, [a, b])
    assert est.lanes["in_0"].stopped_pcu == pytest.approx(1.0)


def test_queue_past_the_view_is_extrapolated_and_trusted_less(network, rig, links) -> None:
    cfg = EstimatorConfig()
    est = LinkStateEstimator(rig, links[0], links[1], cfg)
    lane = network.lanes["in_0"]
    view = rig.coverage("in_0").covered_from_end_m
    spacing = 7.0

    def queue(n_back_m: float, t: float) -> list[GroundTrack]:
        out = []
        s = lane.length - 3.0
        k = 0
        while lane.length - s <= n_back_m and lane.length - s < view - 1.0:
            out.append(_gt(track_id=k, t=t, xy=lane.point_at(s)[0], s=s, born_t=t - 50))
            s -= spacing
            k += 1
        return out

    # the queue grows at 2 m/s until it reaches the edge of view...
    t = 0.0
    back = 10.0
    while back < view + 20.0:
        est.update(t, queue(back, t))
        t += 1.0
        back += 2.0
    le = est.lanes["in_0"]
    assert le.truncated
    assert le.hidden_m > 0
    assert le.queue_pcu > le.stopped_pcu
    first_conf = est.links[("J", "L0")].c_truncation
    for _ in range(120):
        est.update(t, queue(back, t))
        t += 1.0
    assert est.links[("J", "L0")].c_truncation < first_conf
    assert est.lanes["in_0"].hidden_m <= lane.length - view + 1e-6


def test_a_queue_hidden_by_occlusion_is_still_seen_as_truncated(network, rig, links) -> None:
    """Queues on this lane are only ever *seen* to 40 m -- the vehicles behind
    are hidden by the ones in front, well inside the covered length. Once the
    estimator has learned that horizon, a queue whose visible end sits at it
    is treated as running on past it."""
    lane = network.lanes["in_0"]
    view = rig.coverage("in_0").covered_from_end_m
    assert view > 60.0  # the camera covers far more than the queue it can see

    def queue(visible_to_m: float, t: float) -> list[GroundTrack]:
        out, s, k = [], lane.length - 3.0, 0
        while lane.length - s <= visible_to_m:
            out.append(_gt(track_id=k, t=t, xy=lane.point_at(s)[0], s=s, born_t=t - 50))
            s -= 7.0
            k += 1
        return out

    est = LinkStateEstimator(rig, links[0], links[1], EstimatorConfig(horizon_quantile=0.9))
    t = 0.0
    for _cycle in range(6):           # red phases: queues build to 20-40 m, then clear
        for back in np.linspace(10.0, 40.0, 30):
            est.update(t, queue(float(back), t))
            t += 1.0
        for _ in range(10):
            est.update(t, [])
            t += 1.0
    assert est.lanes["in_0"].truncated is False
    for back in np.linspace(10.0, 40.0, 30):   # a queue growing past what can be seen
        est.update(t, queue(float(back), t))
        t += 1.0
    for _ in range(20):
        est.update(t, queue(40.0, t))
        t += 1.0
    le = est.lanes["in_0"]
    assert le.truncated and le.hidden_m > 0 and le.queue_pcu > le.stopped_pcu

    off = LinkStateEstimator(rig, links[0], links[1])  # the default: off
    t = 0.0
    for _ in range(300):
        off.update(t, queue(40.0, t))
        t += 1.0
    assert not off.lanes["in_0"].truncated  # without the horizon: never "at the edge"


def test_vehicles_leaving_the_frame_do_not_count_as_unseen(network, rig, links) -> None:
    """ByteTrack coasts a vehicle past the frame edge for a moment; that is
    not an occlusion, and must not pull the link's confidence down. A car the
    detector keeps missing *inside* the frame must."""
    lane = network.lanes["in_0"]

    def run(at_border: bool, moved_m: float = 40.0) -> float:
        est = LinkStateEstimator(rig, links[0], links[1])
        car = _gt(track_id=5, xy=lane.point_at(190.0)[0], s=190.0, moved_m=moved_m, born_t=0.0,
                  stopped=False, stopped_since=None, coasting=True, at_border=at_border)
        for t in range(1, 120):
            car.t = float(t)
            est.update(float(t), [car])
        return est.links[("J", "L0")].c_visibility

    assert run(at_border=True) == pytest.approx(1.0)
    assert run(at_border=False) < 0.75
    # a flickering false positive that never drove anywhere says nothing either
    assert run(at_border=False, moved_m=0.0) == pytest.approx(1.0)


def test_a_failed_camera_does_not_blind_a_lane_another_camera_sees(network, camera) -> None:
    from vision_service.cameras import CameraRig, CameraSpec
    from vision_service.state import LinkStateEstimator

    rig = CameraRig.build(network, [CameraSpec("camA", camera, tls_id="J"),
                                    CameraSpec("camB", camera, tls_id="J")])
    approach, receiving = network.link_lane_maps()
    est = LinkStateEstimator(rig, approach, receiving)
    est.update(10.0, [], {"camA": 1.0, "camB": 1.0})
    both = est.links[("J", "L0")].confidence
    est.update(11.0, [], {"camA": 0.0, "camB": 1.0})
    assert est.links[("J", "L0")].confidence == pytest.approx(both)
    assert est.links[("J", "L0")].cameras == ("camB",)
    est.update(12.0, [], {"camA": 0.0, "camB": 0.0})
    assert est.links[("J", "L0")].confidence == 0.0


def test_a_stalled_vehicle_reacquired_keeps_its_history(network, rig, camera) -> None:
    """A stopped car the tracker loses and finds again is the same car: it
    keeps the metres it drove in and, once the new track confirms it is
    standing still, the time it has been stopped -- so it is neither
    mistaken for furniture nor restarted as a fresh stop. A car that drives
    through the spot a stopped one has just left is not stopped."""
    from vision_service.classes import ClassTable
    from vision_service.ground import GroundConfig, GroundTracker
    from vision_service.records import ImageTrack

    lane = network.lanes["in_0"]
    cal = rig.specs["camJ"].camera

    def box_at(s: float) -> np.ndarray:
        uv, _ = cal.ground_to_image(lane.point_at(s))
        u, v = uv[0]
        return np.array([u - 40, v - 60, u + 40, v])

    def stalled(stitch_s: float):
        gt = GroundTracker("camJ", cal, rig.locators.get("camJ"), ClassTable.default(),
                           GroundConfig(stitch_s=stitch_s))
        t, s = 0.0, 100.0
        for _ in range(40):  # drives in at 10 m/s ...
            gt.update(t, [ImageTrack(1, box_at(s), 0.9, VClass.CAR, 9, 9, False)])
            t, s = t + 0.2, s + 2.0
        for _ in range(30):  # ... and stalls
            out = gt.update(t, [ImageTrack(1, box_at(s), 0.9, VClass.CAR, 9, 9, False)])
            t += 0.2
        assert out[0].stopped and out[0].moved_m > 50
        first_stop = out[0].stopped_since
        other = box_at(s - 30.0)  # a second stopped car up the lane
        for _ in range(10):
            gt.update(t, [ImageTrack(1, box_at(s), 0.9, VClass.CAR, 9, 9, False),
                          ImageTrack(5, other, 0.9, VClass.CAR, 9, 9, False)])
            t += 0.2
        gt.update(t, [])  # both lost for a moment (a bus passed in front)
        t += 1.0
        for _ in range(12):  # found again, standing where it was
            back = gt.update(t, [ImageTrack(6, other, 0.9, VClass.CAR, 3, 3, False),
                                 ImageTrack(2, box_at(s), 0.9, VClass.CAR, 3, 3, False)])
            t += 0.2
        return [g for g in back if g.track_id == 2][0], first_stop

    again, first_stop = stalled(stitch_s=10.0)
    assert again.stopped and again.moved_m > 50 and again.born_t == 0.0
    assert again.stopped_since == pytest.approx(first_stop)
    fresh, _ = stalled(stitch_s=0.0)
    assert fresh.moved_m == 0.0  # the old behaviour: "never drove in"

    # a car driving through the spot the stalled one has just left
    gt = GroundTracker("camJ", cal, rig.locators.get("camJ"), ClassTable.default(),
                       GroundConfig(stitch_s=10.0))
    t = 0.0
    for _ in range(10):
        gt.update(t, [ImageTrack(1, box_at(150.0), 0.9, VClass.CAR, 9, 9, False)])
        t += 0.2
    for _ in range(10):
        out = gt.update(t, [ImageTrack(1, box_at(150.0), 0.9, VClass.CAR, 9, 9, False)])
        t += 0.2
    assert out[0].stopped
    gt.update(t, [])
    t += 0.2
    s = 149.0
    for _ in range(8):  # arrives at 10 m/s right where the other one stood
        passing = gt.update(t, [ImageTrack(3, box_at(s), 0.9, VClass.CAR, 3, 3, False)])[0]
        t, s = t + 0.2, s + 2.0
    assert not passing.stopped and passing.speed > 5.0

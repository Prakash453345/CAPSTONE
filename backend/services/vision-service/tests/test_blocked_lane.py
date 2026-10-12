"""A lane blocked at its head, seen by a junction-overview camera: the road
model's paths through the box, the camera planner, the rig's two camera
roles and the estimator's test (`state/estimator.py`, "A lane blocked at
its head").

The junction: one single-lane approach from the south (`s_0`, stop line at
y = -7.2) with a through link L0 to the north and a right turn L1 to the
east that has a waiting position 4 m into the box -- the geometry of the
single-lane grid the rule was built on."""

from __future__ import annotations

import numpy as np
import pytest
from itms_domain.signal import BLOCKER_UNKNOWN
from itms_geo.road import BOX_PATH_LEAD_M, RoadNetwork
from vision_service.cameras import CameraRig, CameraSpec, load_registry, save_registry
from vision_service.classes import ClassTable, VClass
from vision_service.pipeline import VisionSystem
from vision_service.placement import plan_approach_camera, plan_box_camera
from vision_service.records import GroundTrack
from vision_service.simcam.world import snapshot_from_records
from vision_service.state.estimator import LinkStateEstimator

_NET = """<net>
 <edge id=":J_0" function="internal">
  <lane id=":J_0_0" index="0" speed="13.89" length="14.40" shape="0,-7.2 0,7.2"/></edge>
 <edge id=":J_1" function="internal">
  <lane id=":J_1_0" index="0" speed="8" length="4.07" shape="0,-7.2 0.55,-3.35 0.64,-3.2"/></edge>
 <edge id=":J_2" function="internal">
  <lane id=":J_2_0" index="0" speed="8" length="10.13"
        shape="0.64,-3.2 2.2,-0.6 4.95,1.05 8.8,1.6"/></edge>
 <edge id="s" from="S" to="J">
  <lane id="s_0" index="0" speed="13.89" length="100" shape="0,-107.2 0,-7.2"/></edge>
 <edge id="n" from="J" to="N">
  <lane id="n_0" index="0" speed="13.89" length="100" shape="0,7.2 0,107.2"/></edge>
 <edge id="e" from="J" to="E">
  <lane id="e_0" index="0" speed="13.89" length="100" shape="8.8,1.6 108.8,1.6"/></edge>
 <connection from="s" to="n" fromLane="0" toLane="0" via=":J_0_0" tl="J" linkIndex="0" dir="s"/>
 <connection from="s" to="e" fromLane="0" toLane="0" via=":J_1_0" tl="J" linkIndex="1" dir="r"/>
 <connection from=":J_0" to="n" fromLane="0" toLane="0" dir="s"/>
 <connection from=":J_1" to="e" fromLane="0" toLane="0" via=":J_2_0" dir="r"/>
 <connection from=":J_2" to="e" fromLane="0" toLane="0" dir="r"/>
</net>"""
_STOP_Y = -7.2
_NOW = 5.0   # tracks in these tests were born at t = 0


@pytest.fixture(scope="module")
def net(tmp_path_factory) -> RoadNetwork:
    path = tmp_path_factory.mktemp("net") / "j.net.xml"
    path.write_text(_NET)
    return RoadNetwork.from_sumo_net(path)


@pytest.fixture(scope="module")
def rig(net) -> CameraRig:
    box = plan_box_camera(net, "J")
    approach = plan_approach_camera(net, "J", "s")
    assert box is not None
    return CameraRig.build(net, [approach.spec, box.spec])


def _track(tid: int, y: float, *, x: float = 0.0, stopped: bool = True, length: float = 4.2,
           heading: float = 0.0, coasting: bool = False, speed: float = 0.0,
           moved_m: float = 30.0, camera_id: str = "cam_J_box",
           born_t: float = 0.0) -> GroundTrack:
    """A vehicle that drove in and whose centre is now at (x, y), heading
    north unless told."""
    th = np.radians(heading)
    return GroundTrack(
        camera_id=camera_id, track_id=tid, t=0.0, xy=np.array([x, y]),
        velocity=speed * np.array([np.sin(th), np.cos(th)]), vclass=VClass.CAR, pcu=1.0,
        length_m=length, resolution_m_per_px=0.05, coasting=coasting, stopped=stopped,
        heading_deg=heading, moved_m=moved_m, born_t=born_t)


def _blocked(rig, net, tracks) -> dict:
    approach, receiving = net.link_lane_maps()
    est = LinkStateEstimator(rig, approach, receiving)
    est.update(_NOW, [], {}, box_tracks=tracks)
    return est.blocked


# ---- the road model -------------------------------------------------------------------


def test_each_signal_link_has_a_path_through_the_box(net) -> None:
    through, turn = net.box_paths["J"]["L0"], net.box_paths["J"]["L1"]
    # from 10 m before the stop line, through the box, to where the link leaves it
    assert through.path.shape[0].tolist() == pytest.approx([0.0, _STOP_Y - BOX_PATH_LEAD_M])
    assert through.path.shape[-1].tolist() == [0.0, 7.2]
    assert turn.path.shape[-1].tolist() == [8.8, 1.6]
    assert through.stop_s == pytest.approx(BOX_PATH_LEAD_M)        # s of the stop line
    assert turn.stop_s == pytest.approx(BOX_PATH_LEAD_M)
    assert through.length == pytest.approx(10.0 + 14.4)
    # the turn's path runs on through its waiting position onto the second internal lane
    assert turn.length == pytest.approx(10.0 + 4.07 + 10.13, abs=0.05)
    s, lat, _ = turn.path.project(np.array([[0.64, -3.2]]))
    assert s[0] == pytest.approx(10.0 + 4.07, abs=0.05) and abs(lat[0]) < 0.01


def test_a_network_without_internal_lanes_has_no_box_paths(network) -> None:
    assert network.box_paths == {}                                 # the conftest road


# ---- the camera and its role ----------------------------------------------------------


def test_the_overview_camera_stands_on_a_corner_and_sees_every_path(net) -> None:
    r = plan_box_camera(net, "J")
    assert r is not None and r.spec.role == "box" and r.spec.approach_edge is None
    cam = r.spec.camera
    # between two arms, not on a road: here the side with no arm, the west
    pole = np.array([[cam.x, cam.y]])
    assert min(abs(float(ln.project(pole)[1][0])) for ln in net.lanes.values()) > 5.0
    assert cam.x < -10.0
    for link, path in net.box_paths["J"].items():
        assert r.covered_from_stopline_m[path.path.lane_id] == pytest.approx(
            path.length, rel=0.05), link


def test_an_overview_camera_is_part_of_no_lanes_coverage(net, rig, tmp_path) -> None:
    alone = CameraRig.build(net, [rig.specs["cam_J_s"]])
    assert "cam_J_box" not in rig.coverage_by_camera
    assert rig.cameras_by_lane == alone.cameras_by_lane
    assert {k: v.covered_from_end_m for k, v in rig.coverage_by_lane.items()} == \
           {k: v.covered_from_end_m for k, v in alone.coverage_by_lane.items()}
    assert "cam_J_box" in rig.locators                              # it still places tracks
    # the role survives the registry file; a file written before roles existed reads as approach
    save_registry(tmp_path / "c.json", list(rig.specs.values()))
    specs, raw = load_registry(tmp_path / "c.json")
    assert {s.camera_id: s.role for s in specs} == {"cam_J_s": "approach", "cam_J_box": "box"}
    del raw["cameras"][1]["role"]
    assert CameraSpec.from_dict(raw["cameras"][1]).role == "approach"


# ---- the estimator's test -------------------------------------------------------------


def test_a_lane_is_blocked_when_its_front_vehicle_stands_behind_one_waiting_in_the_box(
        net, rig) -> None:
    # the turner's nose is 4 m past the stop line; the next vehicle's nose is
    # 0.5 m short of it, 2.3 m behind the turner's tail
    turner = _track(1, _STOP_Y + 4.0 - 2.1)
    follower = _track(2, _STOP_Y - 0.5 - 2.1)
    assert _blocked(rig, net, [turner, follower]) == {
        "J": {"L0": BLOCKER_UNKNOWN, "L1": BLOCKER_UNKNOWN}}


def test_what_is_not_a_blocked_lane(net, rig) -> None:
    turner = _track(1, _STOP_Y + 4.0 - 2.1)
    follower = _track(2, _STOP_Y - 0.5 - 2.1)
    # the vehicle in the box is driving through it
    assert _blocked(rig, net, [_track(1, turner.xy[1], stopped=False, speed=5.0), follower]) == {}
    # nobody behind it, or the next vehicle still rolling up, or well short of it
    assert _blocked(rig, net, [turner]) == {}
    assert _blocked(rig, net, [turner, _track(2, follower.xy[1], stopped=False, speed=3.0)]) == {}
    assert _blocked(rig, net, [turner, _track(2, follower.xy[1] - 6.0)]) == {}
    # a queue at the stop line with nothing in the box
    assert _blocked(rig, net, [follower, _track(3, follower.xy[1] - 6.7)]) == {}
    # a track the camera has lost and is only predicting
    assert _blocked(rig, net, [_track(1, turner.xy[1], coasting=True), follower]) == {}
    # a vehicle standing in the box on someone else's path: crossing (heading
    # west), or beside this lane's paths
    assert _blocked(rig, net, [_track(1, turner.xy[1], heading=270.0), follower]) == {}
    assert _blocked(rig, net, [_track(1, turner.xy[1], x=-3.2), follower]) == {}
    # one vehicle the tracker holds twice, 0.4 m apart: not a pair
    assert _blocked(rig, net, [turner, _track(2, turner.xy[1] - 0.4)]) == {}
    # something in the box that never moved (a shadow, a barrier the detector
    # keeps calling a car), or a track too young to be believed
    assert _blocked(rig, net, [_track(1, turner.xy[1], moved_m=0.0), follower]) == {}
    assert _blocked(rig, net, [_track(1, turner.xy[1], born_t=_NOW - 0.2), follower]) == {}
    # seen by the approach camera, which is not an overview camera of this
    # junction's box... the rule reads this junction's own cameras only
    other = CameraSpec("cam_K_box", rig.specs["cam_J_box"].camera, tls_id="K", role="box")
    rig2 = CameraRig.build(net, [*rig.specs.values(), other])
    assert _blocked(rig2, net, [_track(1, turner.xy[1], camera_id="cam_K_box"),
                                _track(2, follower.xy[1], camera_id="cam_K_box")]) == {}
    assert _blocked(rig2, net, [turner, follower]) != {}


def test_without_an_overview_camera_nothing_is_reported(net, rig) -> None:
    approach, receiving = net.link_lane_maps()
    est = LinkStateEstimator(rig, approach, receiving)
    est.update(0.0, [], {})
    assert est.blocked == {}


def test_the_whole_pipeline_reports_the_blocked_lane_from_the_overview_camera(net, rig) -> None:
    """SimCam films a car that drives 4 m into the box and waits, and one
    that stops behind it; only the overview camera sees the first once it
    stands there, and only its tracks decide."""
    approach, receiving = net.link_lane_maps()

    def world(t: float, *, turner: bool = True):
        def front_y(stop_y: float, start_y: float) -> tuple[float, float]:
            y = min(stop_y, start_y + 6.0 * t)
            return y, (6.0 if y < stop_y else 0.0)
        # the follower stops 2.5 m behind the turner's tail, or at the line
        y, v = front_y(_STOP_Y - 0.5 if not turner else _STOP_Y + 4.0 - 4.2 - 2.5, -55.0)
        recs = [{"id": "follower", "vclass": VClass.CAR, "x": 0.0, "y": y, "heading": 0.0,
                 "speed": v, "lane_id": "s_0", "lane_pos": 100.0 + (y - _STOP_Y)}]
        if turner:
            y, v = front_y(_STOP_Y + 4.0, -40.0)
            recs.append({"id": "turner", "vclass": VClass.CAR, "x": 0.0, "y": y,
                         "heading": 0.0, "speed": v, "lane_id": "s_0", "lane_pos": 99.0})
        return snapshot_from_records(t, recs, ClassTable.default())

    def run(camera_rig, *, turner: bool) -> dict:
        vs = VisionSystem(camera_rig, approach, receiving, preset="ideal", seed=1, fps=5.0)
        prev = None
        for t in range(16):
            snap = world(float(t), turner=turner)
            vs.step_world(prev, snap)
            vs.tick(float(t))
            prev = snap
        return vs.estimator.blocked

    assert set(run(rig, turner=True)["J"]) == {"L0", "L1"}
    assert run(rig, turner=False) == {}
    # the approach camera alone: the waiting car is under its frame
    alone = CameraRig.build(net, [rig.specs["cam_J_s"]])
    assert run(alone, turner=True) == {}

"""Lane geometry, nearest-lane queries, link maps and coverage, against the
real Vijayawada network."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
from itms_geo.camera import PinholeCamera
from itms_geo.coverage import camera_coverage, lane_coverage, merge_coverage
from itms_geo.road import Lane, LaneLocator, RoadNetwork, heading_diff

_ROOT = Path(__file__).resolve().parents[3]
_NET_DIR = _ROOT / "scenarios" / "networks" / "vijayawada"
_NET = _NET_DIR / "vijayawada_corridor.net.xml"


@pytest.fixture(scope="module")
def net() -> RoadNetwork:
    return RoadNetwork.from_sumo_net(_NET)


def _straight_lane(lane_id="e_0", edge="e", length=100.0, y=0.0, reverse=False) -> Lane:
    xs = np.array([0.0, length])
    if reverse:
        xs = xs[::-1]
    return Lane(lane_id, edge, 0, length, 3.2, 13.89, np.column_stack([xs, [y, y]]))


def test_project_and_point_at_roundtrip() -> None:
    lane = Lane("x_0", "x", 0, 70.0, 3.2, 13.9, np.array([[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]]))
    s = np.array([5.0, 29.0, 45.0, 69.0])
    for lat in (-1.2, 0.0, 1.0):
        pts = lane.point_at(s, lat)
        s2, lat2, _ = lane.project(pts)
        np.testing.assert_allclose(s2, s, atol=1e-6)
        np.testing.assert_allclose(lat2, lat, atol=1e-6)


def test_left_is_positive_lateral() -> None:
    lane = _straight_lane()  # runs east
    _, lat, hd = lane.project(np.array([[50.0, 1.0], [50.0, -1.0]]))
    assert lat[0] > 0 > lat[1]
    assert hd[0] == pytest.approx(90.0)


def test_locator_picks_the_lane_and_notices_direction() -> None:
    east = _straight_lane("east_0", "east", y=0.0)
    west = _straight_lane("west_0", "west", y=3.4, reverse=True)
    loc = LaneLocator([east, west])
    m = loc.locate(np.array([[40.0, 0.3], [40.0, 3.0], [40.0, 30.0]]),
                   headings=np.array([90.0, 270.0, 90.0]))
    assert list(m.lane) == [0, 1, -1]
    assert m.agrees[0] and m.agrees[1]
    # A vehicle driving west in the eastbound lane with no westbound lane in reach:
    wrong = LaneLocator([east]).locate(np.array([[40.0, 0.0]]), headings=np.array([270.0]))
    assert wrong.lane[0] == 0 and not wrong.agrees[0]


def test_link_maps_match_the_project_link_lanes_module(net) -> None:
    sys.path.insert(0, str(_NET_DIR))
    from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: PLC0415

    approach, receiving = net.link_lane_maps()
    assert approach == link_to_lane_map(_NET)
    assert receiving == link_to_receiving_lane_map(_NET)
    assert sum(len(v) for v in approach.values()) == 73


def test_every_link_lane_exists_with_geometry(net) -> None:
    approach, receiving = net.link_lane_maps()
    for m in (approach, receiving):
        for links in m.values():
            for lane_id in links.values():
                lane = net.lanes[lane_id]
                assert lane.geometric_length == pytest.approx(lane.length, rel=0.05, abs=2.0)


def test_heading_diff_wraps() -> None:
    assert heading_diff(350.0, 10.0) == pytest.approx(20.0)
    assert heading_diff(90.0, 270.0) == pytest.approx(180.0)


def test_a_camera_too_close_to_the_stop_line_cannot_see_it() -> None:
    lane = _straight_lane(length=300.0)
    cam = PinholeCamera(x=312.0, y=0.0, height_m=10.0, heading_deg=270.0, pitch_deg=12.0)
    cov = lane_coverage(cam, lane)
    assert cov.fraction > 0.2 and cov.covered_from_end_m == 0.0


def test_coverage_of_a_camera_looking_up_a_lane() -> None:
    lane = _straight_lane(length=300.0)  # runs east, stop line at x = 300
    # Set back 18 m past the stop line and pitched 20 deg down, so the bottom
    # of the frame reaches the ground just before the stop line.
    cam = PinholeCamera(x=318.0, y=0.0, height_m=10.0, heading_deg=270.0, pitch_deg=20.0)
    cov = lane_coverage(cam, lane, max_resolution_m_per_px=0.6)
    assert 0 < cov.fraction < 1
    assert cov.covered_from_end_m > 60          # sees the queue from the stop line back
    assert cov.covered_from_start_m == 0.0      # not the far end
    assert cov.covers(np.array([295.0]))[0] and not cov.covers(np.array([5.0]))[0]
    tighter = lane_coverage(cam, lane, max_resolution_m_per_px=0.3)
    assert tighter.covered_from_end_m < cov.covered_from_end_m


def test_merge_is_a_union() -> None:
    lane = _straight_lane(length=300.0)
    a = PinholeCamera(x=318.0, y=0.0, height_m=10.0, heading_deg=270.0, pitch_deg=20.0)
    b = PinholeCamera(x=-18.0, y=0.0, height_m=10.0, heading_deg=90.0, pitch_deg=20.0)
    ca, cb = lane_coverage(a, lane), lane_coverage(b, lane)
    both = merge_coverage([ca, cb])
    assert both.fraction == pytest.approx(min(1.0, ca.fraction + cb.fraction), abs=0.02)
    assert both.covered_from_start_m > 0 and both.covered_from_end_m > 0


def test_camera_coverage_drops_unseen_lanes() -> None:
    seen = _straight_lane("a_0", length=300.0)
    unseen = _straight_lane("b_0", "b", y=500.0, length=300.0)
    cam = PinholeCamera(x=312.0, y=0.0, height_m=10.0, heading_deg=270.0, pitch_deg=12.0)
    cov = camera_coverage(cam, [seen, unseen])
    assert set(cov) == {"a_0"}


def test_lonlat_roundtrip(net) -> None:
    pytest.importorskip("pyproj")
    xy = np.array([[1956.14, 725.89]])
    ll = net.xy_to_lonlat(xy)
    assert 80.6 < ll[0, 0] < 80.7 and 16.49 < ll[0, 1] < 16.52
    np.testing.assert_allclose(net.lonlat_to_xy(ll), xy, atol=1e-3)
    assert math.isfinite(ll[0, 0])

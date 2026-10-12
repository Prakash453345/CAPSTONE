"""Pinhole and homography cameras agree on the road plane, and both refuse
to 'see' things behind them."""

from __future__ import annotations

import math

import numpy as np
import pytest
from itms_geo.camera import (
    HomographyCamera,
    PinholeCamera,
    camera_from_dict,
    homography_camera_from_pinhole,
)
from itms_geo.homography import estimate_homography


def _cam(**kw) -> PinholeCamera:
    base = dict(x=1950.0, y=725.0, height_m=10.0, heading_deg=250.0, pitch_deg=18.0)
    base.update(kw)
    return PinholeCamera(**base)


def _ahead(cam: PinholeCamera, dist: float, lateral: float = 0.0) -> np.ndarray:
    th = math.radians(cam.heading_deg)
    fwd = np.array([math.sin(th), math.cos(th)])
    right = np.array([math.cos(th), -math.sin(th)])
    return cam.position_xy + dist * fwd + lateral * right


def test_point_on_the_optical_axis_projects_to_the_image_centre() -> None:
    cam = _cam()
    d = cam.height_m / math.tan(math.radians(cam.pitch_deg))
    uv, vis = cam.ground_to_image(_ahead(cam, d)[None])
    assert vis[0]
    np.testing.assert_allclose(uv[0], [cam.width_px / 2, cam.height_px / 2], atol=1e-6)


def test_right_of_the_road_is_right_of_the_image() -> None:
    cam = _cam()
    uv, _ = cam.ground_to_image(np.vstack([_ahead(cam, 50, -3), _ahead(cam, 50, 3)]))
    assert uv[1, 0] > uv[0, 0]


def test_further_is_higher_in_the_image() -> None:
    cam = _cam()
    uv, _ = cam.ground_to_image(np.vstack([_ahead(cam, 30), _ahead(cam, 80)]))
    assert uv[1, 1] < uv[0, 1]


def test_ground_image_roundtrip() -> None:
    cam = _cam(roll_deg=1.5)
    pts = np.vstack([_ahead(cam, d, lat) for d in (20, 45, 90) for lat in (-6, 0, 5)])
    uv, vis = cam.ground_to_image(pts)
    assert vis.all()
    np.testing.assert_allclose(cam.image_to_ground(uv), pts, atol=1e-6)


def test_pixels_above_the_horizon_do_not_reach_the_road() -> None:
    cam = _cam()
    v_h = cam.horizon_row()
    out = cam.image_to_ground(np.array([[960.0, v_h - 20], [960.0, v_h + 40]]))
    assert np.isnan(out[0]).all() and np.isfinite(out[1]).all()


def test_points_behind_the_camera_are_not_visible() -> None:
    cam = _cam()
    _, vis = cam.ground_to_image(_ahead(cam, -30)[None])
    assert not vis[0]


def test_ground_homography_matches_full_projection() -> None:
    cam = _cam()
    pts = np.vstack([_ahead(cam, d, 2.0) for d in (15, 60, 110)])
    uv_full, _ = cam.project_points(np.hstack([pts, np.zeros((3, 1))]))
    h = cam.ground_homography
    w = np.hstack([pts, np.ones((3, 1))]) @ h.T
    np.testing.assert_allclose(w[:, :2] / w[:, 2:], uv_full, atol=1e-6)


def test_resolution_grows_with_distance_and_matches_the_formula() -> None:
    cam = _cam()
    near, far = cam.ground_resolution(np.vstack([_ahead(cam, 20), _ahead(cam, 100)]))
    assert far > near
    # along-view m/px on the axis ~ (d^2 + h^2) / (f * h) for a camera pitched at the point
    d = 100.0
    approx = (d**2 + cam.height_m**2) / (cam.focal_px * cam.height_m)
    assert far == pytest.approx(approx, rel=0.35)


@pytest.mark.parametrize("heading", [0.0, 73.0, 181.0, 250.0, 359.0])
@pytest.mark.parametrize("xy", [(0.0, 0.0), (1950.0, 725.0), (-3000.0, 8000.0)])
def test_homography_camera_agrees_with_pinhole_whatever_the_sign(heading, xy) -> None:
    cam = _cam(x=xy[0], y=xy[1], heading_deg=heading)
    hc = homography_camera_from_pinhole(cam)
    pts = np.vstack([_ahead(cam, d, lat) for d in (-40, 20, 70, 140) for lat in (-5, 4)])
    uv_p, vis_p = cam.ground_to_image(pts)
    uv_h, vis_h = hc.ground_to_image(pts)
    assert (vis_p == vis_h).all()
    np.testing.assert_allclose(uv_h[vis_h], uv_p[vis_p], atol=1e-5)
    back = hc.image_to_ground(uv_p[vis_p])
    np.testing.assert_allclose(back, pts[vis_p], atol=1e-4)
    np.testing.assert_allclose(hc.ground_resolution(pts[vis_p]),
                               cam.ground_resolution(pts[vis_p]), rtol=1e-6)


def test_homography_camera_rejects_sky_pixels() -> None:
    cam = _cam()
    hc = homography_camera_from_pinhole(cam)
    out = hc.image_to_ground(np.array([[960.0, cam.horizon_row() - 30]]))
    assert np.isnan(out).all()


def test_calibration_from_clicked_points_reproduces_the_camera() -> None:
    cam = _cam()
    ground = np.vstack([_ahead(cam, d, lat) for d, lat in [(20, -5), (22, 6), (70, -6), (75, 5),
                                                          (40, 0), (100, -1)]])
    uv, _ = cam.ground_to_image(ground)
    h = estimate_homography(ground, uv)
    hc = HomographyCamera.from_matrix(h, cam.width_px, cam.height_px, cam.position_xy)
    probe = np.vstack([_ahead(cam, d, 1.0) for d in (30, 60, 90)])
    np.testing.assert_allclose(hc.ground_to_image(probe)[0], cam.ground_to_image(probe)[0],
                               atol=1e-3)


def test_dict_roundtrip_both_models() -> None:
    cam = _cam(camera_id="c1")
    assert camera_from_dict(cam.to_dict()) == cam
    hc = homography_camera_from_pinhole(cam)
    hc2 = camera_from_dict(hc.to_dict())
    np.testing.assert_allclose(hc2.matrix, hc.matrix)


def test_a_bumped_camera_moves_the_image() -> None:
    cam = _cam()
    p = _ahead(cam, 60)[None]
    moved = cam.perturbed(d_heading_deg=3.0).ground_to_image(p)[0]
    assert np.abs(moved - cam.ground_to_image(p)[0]).max() > 50

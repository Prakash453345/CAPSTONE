"""Lane-mark calibration recovers a known camera from what it would see."""

from __future__ import annotations

import numpy as np
import pytest
from itms_geo.camera import PinholeCamera
from itms_geo.homography import apply_homography
from itms_geo.lanecal import calibrate_from_lane_marks

PERIOD = 12.0
X0 = 6.0  # the first dash start, in the camera's world frame


def _camera(**kw) -> PinholeCamera:
    base = dict(x=-12.0, y=-1.0, height_m=9.0, heading_deg=95.0, pitch_deg=24.0,
                width_px=1280, height_px=720, hfov_deg=58.0, roll_deg=1.5)
    base.update(kw)
    return PinholeCamera(**base)


def _marks(cam: PinholeCamera, noise_px: float = 0.0, seed: int = 0):
    rng = np.random.default_rng(seed)

    def px(xy):
        uv, vis = cam.ground_to_image(np.asarray(xy, dtype=float))
        assert vis.all()
        return uv + rng.normal(0, noise_px, uv.shape)

    xs = np.linspace(8.0, 60.0, 5)
    lines = {y: px(np.c_[xs, np.full_like(xs, y)]) for y in (0.0, -3.5, -7.0)}
    dashes = px([[X0 + k * PERIOD, -3.5] for k in range(4)])
    bar = px([[40.0, y] for y in np.linspace(-0.3, -6.7, 5)])
    return lines, dashes, bar


def _probe_error_px(cam: PinholeCamera, cal) -> float:
    g = np.array([[x, y] for x in (10.0, 25.0, 45.0) for y in (-1.0, -5.0)])
    truth, _ = cam.ground_to_image(g)
    got = apply_homography(cal.h_ground_to_image, g - [X0, 0.0])
    return float(np.abs(got - truth).max())


def test_known_dash_period_and_crossbar_recover_the_homography() -> None:
    cam = _camera()
    lines, dashes, bar = _marks(cam)
    cal = calibrate_from_lane_marks(lines, dashes, -3.5, (1280, 720), crossbars=[bar],
                                    dash_period_m=PERIOD)
    assert cal.shear_fixed and cal.rms_m < 1e-6
    assert _probe_error_px(cam, cal) < 1e-3


def test_pinhole_route_recovers_scale_focal_and_position() -> None:
    cam = _camera()
    lines, dashes, bar = _marks(cam)
    cal = calibrate_from_lane_marks(lines, dashes, -3.5, (1280, 720), crossbars=[bar])
    assert cal.period_source == "pinhole"
    assert cal.dash_period_m == pytest.approx(PERIOD, rel=1e-4)
    assert cal.focal_px == pytest.approx(cam.focal_px, rel=1e-4)
    assert cal.hfov_deg == pytest.approx(58.0, abs=0.01)
    np.testing.assert_allclose(cal.camera_xyz, (cam.x - X0, cam.y, cam.height_m), atol=1e-3)
    assert _probe_error_px(cam, cal) < 1e-2


def test_known_period_is_robust_to_click_noise() -> None:
    """The recommended route: with a measured dash period, 1 px of clicking
    noise costs well under 2 % on distances along a lane."""
    cam = _camera()
    worst = 0.0
    for seed in range(5):
        lines, dashes, bar = _marks(cam, noise_px=1.0, seed=seed)
        cal = calibrate_from_lane_marks(lines, dashes, -3.5, (1280, 720), crossbars=[bar],
                                        dash_period_m=PERIOD)
        g_inv = np.linalg.inv(cal.h_ground_to_image)
        uv, _ = cam.ground_to_image(np.array([[12.0, -1.75], [42.0, -1.75]]))
        back = apply_homography(g_inv, uv)
        worst = max(worst, abs(np.hypot(*(back[1] - back[0])) / 30.0 - 1))
    assert worst < 0.02


def test_without_a_crossbar_along_lane_distances_are_still_right() -> None:
    """Shear is unobservable from lane lines and dashes alone -- and harmless
    to anything measured along one lane (speed, gaps, that lane's queue)."""
    cam = _camera()
    lines, dashes, _ = _marks(cam)
    cal = calibrate_from_lane_marks(lines, dashes, -3.5, (1280, 720), dash_period_m=PERIOD)
    assert not cal.shear_fixed
    g_inv = np.linalg.inv(cal.h_ground_to_image)
    for y in (-1.75, -5.25):
        a, _ = cam.ground_to_image(np.array([[15.0, y], [45.0, y]]))
        back = apply_homography(g_inv, a)
        assert np.hypot(*(back[1] - back[0])) == pytest.approx(30.0, abs=1e-3)
        assert back[:, 1] == pytest.approx([y, y], abs=1e-3)


def test_needs_enough_marks() -> None:
    cam = _camera()
    lines, dashes, _ = _marks(cam)
    with pytest.raises(ValueError, match="four dash"):
        calibrate_from_lane_marks(lines, dashes[:3], -3.5, (1280, 720), dash_period_m=12)
    with pytest.raises(ValueError, match="crossbar"):
        calibrate_from_lane_marks(lines, dashes, -3.5, (1280, 720))

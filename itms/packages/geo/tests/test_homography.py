"""Normalised DLT, RANSAC and reprojection error."""

from __future__ import annotations

import numpy as np
import pytest
from itms_geo.homography import (
    apply_homography,
    estimate_homography,
    estimate_homography_ransac,
    reprojection_error,
)

# A realistic ground->image homography: SUMO-scale ground coordinates
# (thousands of metres) mapping to a 1080p image.
_H_TRUE = np.array(
    [
        [1.2, -0.4, -1500.0],
        [0.1, -0.9, 1800.0],
        [0.0004, -0.0006, 1.0],
    ]
)


def _ground_points(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.column_stack([1950 + rng.uniform(-40, 40, n), 720 + rng.uniform(-60, 5, n)])


def test_exact_recovery_from_noise_free_points() -> None:
    g = _ground_points(12)
    img = apply_homography(_H_TRUE, g)
    h = estimate_homography(g, img)
    np.testing.assert_allclose(h, _H_TRUE / _H_TRUE[2, 2], rtol=1e-6, atol=1e-8)
    assert reprojection_error(h, g, img).rms < 1e-6


def test_four_points_is_enough() -> None:
    g = _ground_points(4, seed=3)
    img = apply_homography(_H_TRUE, g)
    h = estimate_homography(g, img)
    probe = _ground_points(20, seed=9)
    np.testing.assert_allclose(apply_homography(h, probe), apply_homography(_H_TRUE, probe),
                               atol=1e-5)


def test_noise_gives_proportionate_error() -> None:
    rng = np.random.default_rng(1)
    g = _ground_points(30)
    img = apply_homography(_H_TRUE, g) + rng.normal(0, 0.5, (30, 2))
    h = estimate_homography(g, img)
    rep = reprojection_error(h, g, img)
    assert rep.rms < 1.0  # about the injected pixel noise, not blown up by bad conditioning


def test_ransac_rejects_a_mis_clicked_point() -> None:
    g = _ground_points(10)
    img = apply_homography(_H_TRUE, g)
    img[3] += [140.0, -90.0]  # one blunder
    h_plain = estimate_homography(g, img)
    h, inliers = estimate_homography_ransac(g, img, threshold=2.0)
    assert not inliers[3] and inliers.sum() == 9
    clean = np.delete(np.arange(10), 3)
    assert reprojection_error(h, g[clean], img[clean]).rms < 1e-4
    assert reprojection_error(h_plain, g[clean], img[clean]).rms > 1.0


def test_collinear_points_are_refused() -> None:
    g = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0], [4.0, 4.0]])
    with pytest.raises(ValueError):
        estimate_homography(g, g * 2)


def test_too_few_points_are_refused() -> None:
    with pytest.raises(ValueError):
        estimate_homography([[0, 0], [1, 0], [0, 1]], [[0, 0], [1, 0], [0, 1]])


def test_points_on_the_horizon_map_to_nan() -> None:
    h = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, 0.0]])  # y = 0 maps to infinity
    out = apply_homography(h, [[5.0, 0.0], [5.0, 2.0]])
    assert np.isnan(out[0]).all() and np.isfinite(out[1]).all()

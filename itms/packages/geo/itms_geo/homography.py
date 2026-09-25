"""Planar homographies: estimation from point correspondences, application,
and the error measure a calibration is judged by (build guide §8.5,
"homography reprojection error").

A fixed CCTV camera looking at a flat road is, for everything on the road
surface, a homography: a 3x3 matrix `H` taking ground coordinates `(x, y)`
in metres to image pixels `(u, v)` up to scale. This module is the one place
that matrix is estimated, so every calibration in the project is produced and
scored the same way.

Estimation is the normalised Direct Linear Transform (Hartley & Zisserman,
*Multiple View Geometry*, alg. 4.2): translate and scale each point set so
its centroid is the origin and its mean distance is sqrt(2), solve the
homogeneous system by SVD, then undo the normalisation. Without the
normalisation the system mixes pixel values in the thousands with metre
values in the hundreds, and the SVD answer is dominated by whichever is
larger -- the unnormalised DLT is the textbook example of an algorithm that
works in a unit test and fails on a real calibration.

`estimate_homography_ransac` wraps it for correspondences that may contain
blunders (a mis-clicked lane marking), and returns which points it trusted.

numpy only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MIN_POINTS = 4


def _as_points(pts: np.ndarray | list, name: str) -> np.ndarray:
    a = np.asarray(pts, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != 2:
        raise ValueError(f"{name} must be an (N, 2) array of points, got shape {a.shape}")
    return a


def _normaliser(pts: np.ndarray) -> np.ndarray:
    """Similarity transform taking `pts` to zero mean, mean distance sqrt(2)."""
    centroid = pts.mean(axis=0)
    mean_dist = np.sqrt(((pts - centroid) ** 2).sum(axis=1)).mean()
    if mean_dist < 1e-12:
        raise ValueError("points are coincident -- a homography needs spread-out points")
    s = np.sqrt(2.0) / mean_dist
    return np.array(
        [[s, 0.0, -s * centroid[0]], [0.0, s, -s * centroid[1]], [0.0, 0.0, 1.0]]
    )


def _to_h(pts: np.ndarray) -> np.ndarray:
    return np.hstack([pts, np.ones((len(pts), 1))])


def apply_homography(h: np.ndarray, pts: np.ndarray | list) -> np.ndarray:
    """Map `(N, 2)` points through `h`. Points whose homogeneous scale is
    ~0 (the line at infinity -- e.g. the horizon) come back as NaN rather
    than as enormous finite numbers that look like real coordinates."""
    p = _as_points(pts, "pts")
    w = _to_h(p) @ np.asarray(h, dtype=np.float64).T
    scale = w[:, 2:3]
    out = np.full((len(p), 2), np.nan)
    ok = np.abs(scale[:, 0]) > 1e-12
    out[ok] = w[ok, :2] / scale[ok]
    return out


def estimate_homography(src: np.ndarray | list, dst: np.ndarray | list) -> np.ndarray:
    """Least-squares `H` with `dst ~ H @ src`, normalised DLT. Needs >= 4
    correspondences, no three of the first four collinear in practice.
    Returned with `H[2, 2] == 1`."""
    s = _as_points(src, "src")
    d = _as_points(dst, "dst")
    if len(s) != len(d):
        raise ValueError(f"src has {len(s)} points but dst has {len(d)}")
    if len(s) < _MIN_POINTS:
        raise ValueError(f"need at least {_MIN_POINTS} correspondences, got {len(s)}")

    ts, td = _normaliser(s), _normaliser(d)
    sn = _to_h(s) @ ts.T
    dn = _to_h(d) @ td.T

    rows = []
    for (x, y, w), (u, v, z) in zip(sn, dn, strict=True):
        rows.append([0, 0, 0, -z * x, -z * y, -z * w, v * x, v * y, v * w])
        rows.append([z * x, z * y, z * w, 0, 0, 0, -u * x, -u * y, -u * w])
    a = np.asarray(rows)
    _, sv, vt = np.linalg.svd(a)
    if len(sv) >= 8 and sv[7] < 1e-12 * max(1.0, sv[0]):
        raise ValueError("degenerate correspondences (collinear points?)")
    hn = vt[-1].reshape(3, 3)
    h = np.linalg.inv(td) @ hn @ ts
    if abs(h[2, 2]) < 1e-12:
        raise ValueError("degenerate homography (maps the origin to infinity)")
    return h / h[2, 2]


@dataclass(frozen=True)
class ReprojectionReport:
    """Per-point and summary transfer error, in `dst` units (pixels when
    `dst` is the image). `rms` is what a calibration is accepted or
    rejected on; `max` is what finds the one mis-clicked point."""

    errors: np.ndarray
    rms: float
    max: float
    n: int


def reprojection_error(h: np.ndarray, src: np.ndarray | list, dst: np.ndarray | list) -> (
    ReprojectionReport
):
    s = _as_points(src, "src")
    d = _as_points(dst, "dst")
    mapped = apply_homography(h, s)
    err = np.sqrt(((mapped - d) ** 2).sum(axis=1))
    return ReprojectionReport(
        errors=err,
        rms=float(np.sqrt(np.nanmean(err**2))),
        max=float(np.nanmax(err)),
        n=len(err),
    )


def estimate_homography_ransac(
    src: np.ndarray | list,
    dst: np.ndarray | list,
    *,
    threshold: float = 3.0,
    iterations: int = 500,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """RANSAC over minimal 4-point samples, refit on the largest inlier set.
    Returns `(H, inlier_mask)`. `threshold` is in `dst` units. Deterministic
    for a given `seed` -- a calibration that changes every time it is re-run
    cannot be audited."""
    s = _as_points(src, "src")
    d = _as_points(dst, "dst")
    n = len(s)
    if n < _MIN_POINTS:
        raise ValueError(f"need at least {_MIN_POINTS} correspondences, got {n}")
    if n == _MIN_POINTS:
        return estimate_homography(s, d), np.ones(n, dtype=bool)

    rng = np.random.default_rng(seed)
    best = np.zeros(n, dtype=bool)
    for _ in range(iterations):
        idx = rng.choice(n, _MIN_POINTS, replace=False)
        try:
            h = estimate_homography(s[idx], d[idx])
        except (ValueError, np.linalg.LinAlgError):
            continue
        err = reprojection_error(h, s, d).errors
        inliers = np.nan_to_num(err, nan=np.inf) < threshold
        if inliers.sum() > best.sum():
            best = inliers
            if best.all():
                break
    if best.sum() < _MIN_POINTS:
        raise ValueError("RANSAC found no consistent 4-point model")
    return estimate_homography(s[best], d[best]), best

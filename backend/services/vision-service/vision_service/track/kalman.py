"""The image-space constant-velocity Kalman filter ByteTrack uses: state
`(cx, cy, a, h, vcx, vcy, va, vh)` where `a` is width/height and `h` height,
noise scaled by box height so near and far vehicles are treated alike.
Vectorised over tracks: `predict_many` advances every track in one call."""

from __future__ import annotations

import numpy as np

_STD_POS = 1.0 / 20.0
_STD_VEL = 1.0 / 160.0

_F = np.eye(8)
for _i in range(4):
    _F[_i, 4 + _i] = 1.0
_H = np.eye(4, 8)


def box_to_xyah(box: np.ndarray) -> np.ndarray:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    return np.array([x1 + w / 2.0, y1 + h / 2.0, w / max(h, 1e-6), h])


def xyah_to_box(m: np.ndarray) -> np.ndarray:
    if m.ndim == 1:
        w = m[2] * m[3]
        return np.array([m[0] - w / 2.0, m[1] - m[3] / 2.0, m[0] + w / 2.0, m[1] + m[3] / 2.0])
    cx, cy, a, h = m[..., 0], m[..., 1], m[..., 2], m[..., 3]
    w = a * h
    return np.stack([cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0], axis=-1)


def initiate(measurement: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = np.r_[measurement, np.zeros(4)]
    h = measurement[3]
    std = np.array([
        2 * _STD_POS * h, 2 * _STD_POS * h, 1e-2, 2 * _STD_POS * h,
        10 * _STD_VEL * h, 10 * _STD_VEL * h, 1e-5, 10 * _STD_VEL * h,
    ])
    return mean, np.diag(std**2)


def predict_many(means: np.ndarray, covs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`(N, 8)`, `(N, 8, 8)` -> predicted, one step."""
    if len(means) == 0:
        return means, covs
    h = means[:, 3]
    std = np.stack([
        _STD_POS * h, _STD_POS * h, np.full_like(h, 1e-2), _STD_POS * h,
        _STD_VEL * h, _STD_VEL * h, np.full_like(h, 1e-5), _STD_VEL * h,
    ], axis=1)
    q = np.zeros((len(means), 8, 8))
    idx = np.arange(8)
    q[:, idx, idx] = std**2
    means = means @ _F.T
    covs = _F[None] @ covs @ _F.T[None] + q
    return means, covs


def update_many(means: np.ndarray, covs: np.ndarray, measurements: np.ndarray) -> tuple[
    np.ndarray, np.ndarray
]:
    """Batched `update`: `(K, 8)`, `(K, 8, 8)`, `(K, 4)`."""
    h = means[:, 3]
    r = np.zeros((len(means), 4, 4))
    d = np.stack([_STD_POS * h, _STD_POS * h, np.full_like(h, 1e-1), _STD_POS * h], axis=1) ** 2
    idx = np.arange(4)
    r[:, idx, idx] = d
    proj_mean = means[:, :4]
    proj_cov = covs[:, :4, :4] + r
    ph = covs[:, :, :4]  # cov @ H^T
    gain = np.linalg.solve(proj_cov, ph.transpose(0, 2, 1)).transpose(0, 2, 1)  # (K, 8, 4)
    innov = measurements - proj_mean
    new_means = means + np.einsum("kij,kj->ki", gain, innov)
    new_covs = covs - gain @ proj_cov @ gain.transpose(0, 2, 1)
    return new_means, new_covs


def update(mean: np.ndarray, cov: np.ndarray, measurement: np.ndarray) -> tuple[np.ndarray,
                                                                                  np.ndarray]:
    h = mean[3]
    r = np.diag(np.array([_STD_POS * h, _STD_POS * h, 1e-1, _STD_POS * h]) ** 2)
    proj_mean = _H @ mean
    proj_cov = _H @ cov @ _H.T + r
    gain = np.linalg.solve(proj_cov, (cov @ _H.T).T).T
    innov = measurement - proj_mean
    new_mean = mean + gain @ innov
    new_cov = cov - gain @ proj_cov @ gain.T
    return new_mean, new_cov

"""Calibrate a camera from the lane markings it can already see.

Surveying ground control points (the `calibrate.py` route) needs a person on
the road with a GNSS receiver, or a georeferenced orthophoto accurate to a
few decimetres. Most junction cameras can do without either: the road paints
its own calibration target. What an operator can click in one frame:

- **two or more lane lines** (kerb, lane dividers, the median edge), a few
  pixels along each, with its lateral offset in metres -- lane widths are a
  design standard (3.5 m on Indian urban arterials; a tape measure settles
  it);
- **the starts of 4+ equally spaced dashes** along one of those lines, in
  order of travel;
- **a crossbar** -- the stop line, or an edge of the zebra crossing: any
  painted line square to the lanes. Every signalised junction has one.

What each piece fixes. The lane lines give the lateral scale and the
vanishing point. The dashes give the projective stretch along the road, up
to one unknown number: how many metres a dash period is. The crossbar fixes
the *shear* -- without it, lines parallel to the road cannot tell "this
lane's x" from "that lane's x" (an `x + a*y` shear leaves every lane line
and every dash where it was). Shear never changes anything measured *along
one lane* -- speeds, gaps, a lane's own queue length -- but it does move one
lane's stop line relative to the next.

And the dash period, two ways:

1. `dash_period_m` -- from the marking standard or a tape measure;
2. `None` -- recovered from the camera itself, assuming square pixels and
   the principal point at the image centre (true of almost every CCTV
   sensor). A pinhole camera's ground homography is `K [r1 r2 t]`;
   `r1 ⟂ r2` gives the focal length and `|r1| = |r2|` the scale (Zhang
   2000, a single view of a plane). Needs the crossbar. The decomposition
   also gives the camera's position -- the nadir `HomographyCamera` wants --
   and a focal length an installer can check against the lens datasheet.

   **Use it as a cross-check, not as the calibration.** It is exact on
   clean marks but ill-conditioned for exactly the view an approach camera
   has: looking down the road puts the road's vanishing point near the
   image's centre column and the orthogonality equation loses its grip on
   the focal length. Measured with 1 px of clicking noise (10 draws each,
   `tests/test_lanecal.py` geometry): camera yawed 5 degrees off the road
   axis -> median scale error 32 % and 3/10 fits with no real solution;
   20 degrees -> 13 %; 35 degrees -> 5 % with occasional 40-50 % outliers.
   A dash period from the marking standard or a tape measure is worth more.

Ground frame: x along the road in the dash direction with the first dash at
x = 0, y to the left, metres; y = 0 is wherever the operator put it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from itms_geo.homography import apply_homography, estimate_homography


@dataclass(frozen=True)
class LaneCalibration:
    h_ground_to_image: np.ndarray
    dash_period_m: float
    period_source: str                 # "given" | "pinhole"
    shear_fixed: bool                  # a crossbar was given
    rms_m: float                       # residual over every constraint, metres
    max_m: float
    focal_px: float | None = None      # pinhole route only
    hfov_deg: float | None = None
    camera_xyz: tuple[float, float, float] | None = None

    @property
    def nadir_xy(self) -> tuple[float, float] | None:
        return None if self.camera_xyz is None else (self.camera_xyz[0], self.camera_xyz[1])


def _fit_line(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Total-least-squares line through image points: (point, unit direction)."""
    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c)
    return c, vt[0]


def _meet(p: np.ndarray, v: np.ndarray, line: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """Where the image ray p + s v crosses `line`."""
    c, d = line
    a = np.column_stack([v, -d])
    if abs(np.linalg.det(a)) < 1e-9:
        return c
    s, _ = np.linalg.solve(a, c - p)
    return p + s * v


@dataclass(frozen=True)
class _Marks:
    lines: list[tuple[float, np.ndarray]]
    dashes: np.ndarray
    dash_y: float
    crossbars: list[np.ndarray]
    gauge: np.ndarray | None           # used only when there is no crossbar


def _residuals(g: np.ndarray, m: _Marks, period: float) -> np.ndarray:
    res = [apply_homography(g, pts)[:, 1] - y for y, pts in m.lines]
    d = apply_homography(g, m.dashes)
    res.append(d[:, 0] - period * np.arange(len(m.dashes)))
    res.append(d[:, 1] - m.dash_y)
    for bar in m.crossbars:
        x = apply_homography(g, bar)[:, 0]
        res.append(x - x.mean())
    if m.gauge is not None:
        res.append(apply_homography(g, m.gauge[None])[:, 0])
    return np.concatenate(res)


def _refine(g0: np.ndarray, m: _Marks, iters: int = 200) -> np.ndarray:
    """Levenberg-Marquardt on the 8 free entries of the image->ground map."""
    p = (g0 / g0[2, 2]).ravel()[:8].copy()

    def f(q: np.ndarray) -> np.ndarray:
        return _residuals(np.append(q, 1.0).reshape(3, 3), m, 1.0)

    lam = 1e-3
    r = f(p)
    for _ in range(iters):
        jac = np.empty((len(r), 8))
        for i in range(8):
            step = 1e-7 * max(1.0, abs(p[i]))
            q = p.copy()
            q[i] += step
            jac[:, i] = (f(q) - r) / step
        a = jac.T @ jac
        grad = jac.T @ r
        dp = np.zeros(8)
        for _ in range(12):
            dp = np.linalg.solve(a + lam * np.diag(np.diag(a) + 1e-12), -grad)
            r_new = f(p + dp)
            if r_new @ r_new < r @ r:
                p, r, lam = p + dp, r_new, lam / 3
                break
            lam *= 4
        else:
            break
        if np.abs(dp).max() < 1e-13 * max(1.0, np.abs(p).max()):
            break
    return np.append(p, 1.0).reshape(3, 3)


def _pinhole(h: np.ndarray, width: int, height: int) -> tuple[float, float, np.ndarray]:
    """From a ground->image homography whose x axis has an unknown scale:
    focal length (px), metres per x unit, and the camera centre."""
    cx, cy = width / 2.0, height / 2.0
    h1, h2 = h[:, 0], h[:, 1]

    def a(c: np.ndarray) -> np.ndarray:
        return np.array([c[0] - cx * c[2], c[1] - cy * c[2]])

    f2 = -(a(h1) @ a(h2)) / (h1[2] * h2[2])
    if not np.isfinite(f2) or f2 <= 0:
        raise ValueError("these marks do not fit a pinhole camera with its principal point at "
                         "the image centre -- give dash_period_m instead")
    f = float(np.sqrt(f2))
    k_inv = np.linalg.inv(np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]]))
    scale = float(np.linalg.norm(k_inv @ h1) / np.linalg.norm(k_inv @ h2))
    mm = k_inv @ (h @ np.diag([1.0 / scale, 1.0, 1.0]))
    lam = 1.0 / np.linalg.norm(mm[:, 1])
    r1, r2, t = lam * mm[:, 0], lam * mm[:, 1], lam * mm[:, 2]
    u, _, vt = np.linalg.svd(np.column_stack([r1, r2, np.cross(r1, r2)]))
    centre = -(u @ vt).T @ t
    # the other sign of lambda mirrors the centre through the road plane
    return f, scale, np.array([centre[0], centre[1], abs(centre[2])])


def calibrate_from_lane_marks(
    lines: Mapping[float, np.ndarray | list],
    dashes: np.ndarray | list,
    dash_line_y: float,
    image_size: tuple[int, int],
    *,
    crossbars: Sequence[np.ndarray | list] = (),
    dash_period_m: float | None = None,
) -> LaneCalibration:
    """`lines`: lateral offset (m) -> image points along that line (>= 2).
    `dashes`: image points of successive, equally spaced dash starts on the
    line at `dash_line_y`, in order of increasing ground x. `crossbars`:
    image points along lines square to the road (>= 2 each). See the module
    docstring for what is fixed by what."""
    width, height = int(image_size[0]), int(image_size[1])
    line_list = [(float(y), np.asarray(p, dtype=np.float64).reshape(-1, 2))
                 for y, p in lines.items()]
    dash = np.asarray(dashes, dtype=np.float64).reshape(-1, 2)
    bars = [np.asarray(b, dtype=np.float64).reshape(-1, 2) for b in crossbars]
    if len(line_list) < 2 or len(dash) < 4:
        raise ValueError("need at least two lane lines and four dash starts")
    if dash_period_m is None and not bars:
        raise ValueError("recovering the dash period needs a crossbar (stop line or zebra "
                         "edge) -- or give dash_period_m")
    other = [(y, _fit_line(p)) for y, p in line_list if y != dash_line_y]
    # Iso-x lines through each dash, roughly: parallel to the crossbar when
    # there is one (it *is* an iso-x line), else square to the lanes in the
    # image. That pairs every dash with a point on every other line -- a
    # DLT on those pairs is the starting point for Levenberg-Marquardt.
    if bars:
        across = _fit_line(bars[0])[1]
    else:
        d = _fit_line(dash)[1]
        across = np.array([-d[1], d[0]])
    # Without a crossbar the shear is a free gauge: pin it by putting that
    # rough iso-x line of the first dash at x = 0 on the first other line.
    gauge = None if bars else _meet(dash[0], across, other[0][1])
    marks = _Marks(line_list, dash, float(dash_line_y), bars, gauge)
    src, dst = [], []
    for k, u in enumerate(dash):
        src.append(u)
        dst.append((float(k), dash_line_y))
        for y, line in other:
            src.append(_meet(u, across, line))
            dst.append((float(k), y))
    g = _refine(estimate_homography(np.array(src), np.array(dst)), marks)
    h_unit = np.linalg.inv(g)

    focal = hfov = None
    centre = None
    if dash_period_m is not None:
        period, source = float(dash_period_m), "given"
    else:
        focal, period, centre = _pinhole(h_unit, width, height)
        hfov = float(np.degrees(2 * np.arctan(width / (2 * focal))))
        source = "pinhole"
    h_metric = h_unit @ np.diag([1.0 / period, 1.0, 1.0])
    res = _residuals(np.linalg.inv(h_metric), marks, period)
    return LaneCalibration(
        h_ground_to_image=h_metric / h_metric[2, 2],
        dash_period_m=period,
        period_source=source,
        shear_fixed=bool(bars),
        rms_m=float(np.sqrt(np.mean(res**2))),
        max_m=float(np.abs(res).max()),
        focal_px=focal,
        hfov_deg=hfov,
        camera_xyz=None if centre is None else (float(centre[0]), float(centre[1]),
                                                float(centre[2])),
    )

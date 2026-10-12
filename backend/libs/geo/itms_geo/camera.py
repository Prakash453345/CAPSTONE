"""Camera models that map between image pixels and the road plane.

Two kinds, one interface (`GroundCamera`):

- `PinholeCamera` -- a full 3D camera from a physical pose (position, mount
  height, compass heading, downward pitch, roll) and intrinsics (image size,
  horizontal field of view). It can project any 3D point, which is what the
  digital-twin camera needs to turn a vehicle's cuboid into a bounding box.
  Its ground-plane homography falls out of the pose.
- `HomographyCamera` -- a real installed camera calibrated only from
  point correspondences on the road surface. It knows the ground plane and
  nothing above it, which is all the perception pipeline needs.

Everything downstream of detection talks to `GroundCamera` only, so a
camera calibrated by clicking four lane-marking corners and a camera
synthesised from a pose are interchangeable.

**Conventions.** World coordinates are SUMO network coordinates: metres, x
east, y north, z up. Headings are compass bearings in degrees (0 = north,
90 = east) -- the same convention SUMO's `vehicle.getAngle` and the
`VehiclePositionUpdated` event use, so no conversion happens at any
boundary. The camera frame is OpenCV's: x right, y down, z forward.
Pixel `(0, 0)` is the top-left corner; `(u, v)` is (column, row).

numpy only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace
from functools import cached_property
from typing import Protocol, runtime_checkable

import numpy as np

from itms_geo.homography import apply_homography

# Points closer to the camera plane than this are treated as not visible:
# they are either behind the camera or so close that the pinhole model is
# meaningless for a pole-mounted camera.
_NEAR_M = 0.5


@runtime_checkable
class GroundCamera(Protocol):
    """What the perception pipeline needs from a camera."""

    width_px: int
    height_px: int

    @property
    def position_xy(self) -> np.ndarray: ...

    def ground_to_image(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...

    def image_to_ground(self, uv: np.ndarray) -> np.ndarray: ...

    def ground_resolution(self, xy: np.ndarray) -> np.ndarray: ...


def _jacobian_resolution(g: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Metres per pixel along the worst image direction at pixel `uv`, for
    the image->ground homography `g`. The larger singular value of the
    2x2 Jacobian: along the viewing direction a pixel covers far more road
    than across it, and it is the along-view figure that limits how well a
    queue's length can be measured."""
    p = np.hstack([uv, np.ones((len(uv), 1))])
    w = p @ g.T  # (N, 3)
    w2 = w[:, 2]
    safe = np.abs(w2) > 1e-12
    out = np.full(len(uv), np.inf)
    if not safe.any():
        return out
    w, w2 = w[safe], w2[safe]
    # d(w[:2]/w2)/du and /dv
    du = (g[:2, 0][None, :] * w2[:, None] - w[:, :2] * g[2, 0]) / (w2**2)[:, None]
    dv = (g[:2, 1][None, :] * w2[:, None] - w[:, :2] * g[2, 1]) / (w2**2)[:, None]
    # Largest singular value of the 2x2 Jacobian [[a, b], [c, d]] in closed
    # form: s^2 = (T + sqrt(T^2 - 4 D^2)) / 2, T = a^2+b^2+c^2+d^2, D = ad - bc.
    a, c = du[:, 0], du[:, 1]
    b, d = dv[:, 0], dv[:, 1]
    tr = a * a + b * b + c * c + d * d
    det = a * d - b * c
    out[safe] = np.sqrt(np.maximum(0.0, (tr + np.sqrt(np.maximum(0.0, tr * tr - 4 * det * det)))
                                   / 2.0))
    return out


@dataclass(frozen=True)
class PinholeCamera:
    """A physical camera. `heading_deg` is where the optical axis points on
    the map; `pitch_deg` is how far it tilts *down* from horizontal;
    `roll_deg` rotates the image about the optical axis (0 for a level
    mount -- non-zero only to simulate a bumped camera)."""

    x: float
    y: float
    height_m: float
    heading_deg: float
    pitch_deg: float
    width_px: int = 1920
    height_px: int = 1080
    hfov_deg: float = 50.0
    roll_deg: float = 0.0
    camera_id: str = ""

    # ---- intrinsics / extrinsics ------------------------------------

    @cached_property
    def focal_px(self) -> float:
        return (self.width_px / 2.0) / math.tan(math.radians(self.hfov_deg) / 2.0)

    @property
    def vfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan((self.height_px / 2.0) / self.focal_px))

    @cached_property
    def intrinsics(self) -> np.ndarray:
        f = self.focal_px
        return np.array(
            [[f, 0.0, self.width_px / 2.0], [0.0, f, self.height_px / 2.0], [0.0, 0.0, 1.0]]
        )

    @cached_property
    def centre(self) -> np.ndarray:
        return np.array([self.x, self.y, self.height_m])

    @property
    def position_xy(self) -> np.ndarray:
        return np.array([self.x, self.y])

    @cached_property
    def rotation(self) -> np.ndarray:
        """World -> camera rotation; rows are the camera's right, down and
        forward axes expressed in world coordinates."""
        th = math.radians(self.heading_deg)
        ph = math.radians(self.pitch_deg)
        fwd = np.array([math.sin(th) * math.cos(ph), math.cos(th) * math.cos(ph), -math.sin(ph)])
        right = np.array([math.cos(th), -math.sin(th), 0.0])
        down = np.cross(fwd, right)
        if self.roll_deg:
            r = math.radians(self.roll_deg)
            right, down = (
                math.cos(r) * right + math.sin(r) * down,
                -math.sin(r) * right + math.cos(r) * down,
            )
        return np.vstack([right, down, fwd])

    @cached_property
    def projection(self) -> np.ndarray:
        r = self.rotation
        t = -r @ self.centre
        return self.intrinsics @ np.hstack([r, t[:, None]])

    @cached_property
    def ground_homography(self) -> np.ndarray:
        """Ground (x, y) -> image (u, v), the z = 0 slice of `projection`."""
        p = self.projection
        h = p[:, [0, 1, 3]]
        return h / h[2, 2]

    # ---- 3D projection ---------------------------------------------

    def project_points(self, xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """`(N, 3)` world points -> `(uv (N, 2), depth (N,))`. `depth` is
        the distance along the optical axis; points with depth <= 0 are
        behind the camera and their `uv` is NaN."""
        pts = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
        cam = (pts - self.centre) @ self.rotation.T
        depth = cam[:, 2]
        uv = np.full((len(pts), 2), np.nan)
        ok = depth > 1e-9
        f = self.focal_px
        uv[ok, 0] = f * cam[ok, 0] / depth[ok] + self.width_px / 2.0
        uv[ok, 1] = f * cam[ok, 1] / depth[ok] + self.height_px / 2.0
        return uv, depth

    # ---- ground plane ------------------------------------------------

    def ground_to_image(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """`(N, 2)` ground points -> `(uv, visible)`. `visible` means in
        front of the camera and inside the frame."""
        pts = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        xyz = np.hstack([pts, np.zeros((len(pts), 1))])
        uv, depth = self.project_points(xyz)
        inside = (
            (depth > _NEAR_M)
            & (uv[:, 0] >= 0)
            & (uv[:, 0] < self.width_px)
            & (uv[:, 1] >= 0)
            & (uv[:, 1] < self.height_px)
        )
        return uv, inside

    @cached_property
    def _k_inv(self) -> np.ndarray:
        return np.linalg.inv(self.intrinsics)

    @cached_property
    def _g(self) -> np.ndarray:
        return np.linalg.inv(self.ground_homography)

    def image_to_ground(self, uv: np.ndarray) -> np.ndarray:
        """`(N, 2)` pixels -> ground points. Pixels at or above the horizon
        (whose ray never meets the road ahead of the camera) come back NaN."""
        pts = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        k_inv = self._k_inv
        rays_cam = np.hstack([pts, np.ones((len(pts), 1))]) @ k_inv.T
        rays = rays_cam @ self.rotation  # camera -> world direction (R^T applied)
        dz = rays[:, 2]
        out = np.full((len(pts), 2), np.nan)
        ok = dz < -1e-9
        t = -self.height_m / dz[ok]
        out[ok] = self.centre[:2] + rays[ok, :2] * t[:, None]
        return out

    def ground_resolution(self, xy: np.ndarray) -> np.ndarray:
        pts = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        uv, _ = self.ground_to_image(pts)
        res = np.full(len(pts), np.inf)
        ok = np.isfinite(uv).all(axis=1)
        if ok.any():
            res[ok] = _jacobian_resolution(self._g, uv[ok])
        return res

    def horizon_row(self) -> float:
        """Image row of the horizon for a level (roll = 0) camera."""
        return self.height_px / 2.0 - self.focal_px * math.tan(math.radians(self.pitch_deg))

    # ---- misc -----------------------------------------------------------

    def perturbed(
        self, *, d_heading_deg: float = 0.0, d_pitch_deg: float = 0.0, d_roll_deg: float = 0.0
    ) -> PinholeCamera:
        """The same camera knocked slightly out of its calibrated pose --
        what the calibration-drift detector exists to notice."""
        return replace(
            self,
            heading_deg=self.heading_deg + d_heading_deg,
            pitch_deg=self.pitch_deg + d_pitch_deg,
            roll_deg=self.roll_deg + d_roll_deg,
        )

    def to_dict(self) -> dict:
        return {"model": "pinhole", **{f.name: getattr(self, f.name) for f in fields(self)}}

    @classmethod
    def from_dict(cls, d: dict) -> PinholeCamera:
        d = {k: v for k, v in d.items() if k != "model"}
        return cls(**d)


@dataclass(frozen=True)
class HomographyCamera:
    """A camera known only through its ground-plane homography -- the
    usual state of a real installation calibrated from point pairs.
    `nadir_xy` is where the pole stands (installers know this); it sets the
    viewing direction used for footprint correction and occlusion order."""

    h_ground_to_image: tuple[tuple[float, ...], ...]
    width_px: int
    height_px: int
    nadir_xy: tuple[float, float]
    camera_id: str = ""
    _h: np.ndarray = field(init=False, repr=False, compare=False)
    _g: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        h = np.asarray(self.h_ground_to_image, dtype=np.float64)
        if h.shape != (3, 3):
            raise ValueError("h_ground_to_image must be 3x3")
        g = np.linalg.inv(h)
        # A homography is only defined up to scale -- including sign -- but
        # "which side of the horizon is the road" is a sign question. Fix
        # the sign so that the bottom-centre pixel (always road, for a
        # downward-looking CCTV) back-projects with a positive scale; after
        # that, "positive scale" means "in front of the camera" everywhere.
        probe = g @ np.array([self.width_px / 2.0, self.height_px - 1.0, 1.0])
        if probe[2] < 0:
            h, g = -h, -g
        object.__setattr__(self, "_h", h)
        object.__setattr__(self, "_g", g)

    @classmethod
    def from_matrix(
        cls, h: np.ndarray, width_px: int, height_px: int, nadir_xy, camera_id: str = ""
    ) -> HomographyCamera:
        h = np.asarray(h, dtype=np.float64)
        return cls(
            h_ground_to_image=tuple(tuple(float(v) for v in row) for row in h / h[2, 2]),
            width_px=width_px,
            height_px=height_px,
            nadir_xy=(float(nadir_xy[0]), float(nadir_xy[1])),
            camera_id=camera_id,
        )

    @property
    def matrix(self) -> np.ndarray:
        return self._h

    @property
    def position_xy(self) -> np.ndarray:
        return np.asarray(self.nadir_xy, dtype=np.float64)

    def ground_to_image(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        pts = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        w = np.hstack([pts, np.ones((len(pts), 1))]) @ self.matrix.T
        uv = np.full((len(pts), 2), np.nan)
        front = w[:, 2] > 1e-12  # the side of the horizon the road is on
        uv[front] = w[front, :2] / w[front, 2:3]
        inside = (
            front
            & (uv[:, 0] >= 0)
            & (uv[:, 0] < self.width_px)
            & (uv[:, 1] >= 0)
            & (uv[:, 1] < self.height_px)
        )
        return uv, inside

    def image_to_ground(self, uv: np.ndarray) -> np.ndarray:
        pts = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        w = np.hstack([pts, np.ones((len(pts), 1))]) @ self._g.T
        out = np.full((len(pts), 2), np.nan)
        # A pixel whose back-projection lands behind the camera (above the
        # horizon) maps through the homography to a point with the opposite
        # sign of scale; reject it rather than return a mirrored road.
        ok = w[:, 2] > 1e-12
        out[ok] = w[ok, :2] / w[ok, 2:3]
        return out

    def ground_resolution(self, xy: np.ndarray) -> np.ndarray:
        pts = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        uv, _ = self.ground_to_image(pts)
        res = np.full(len(pts), np.inf)
        ok = np.isfinite(uv).all(axis=1)
        if ok.any():
            res[ok] = _jacobian_resolution(self._g, uv[ok])
        return res

    def to_dict(self) -> dict:
        return {
            "model": "homography",
            "h_ground_to_image": [list(r) for r in self.h_ground_to_image],
            "width_px": self.width_px,
            "height_px": self.height_px,
            "nadir_xy": list(self.nadir_xy),
            "camera_id": self.camera_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> HomographyCamera:
        return cls.from_matrix(
            np.asarray(d["h_ground_to_image"]),
            int(d["width_px"]),
            int(d["height_px"]),
            d["nadir_xy"],
            d.get("camera_id", ""),
        )


def camera_from_dict(d: dict) -> PinholeCamera | HomographyCamera:
    model = d.get("model", "pinhole")
    if model == "pinhole":
        return PinholeCamera.from_dict(d)
    if model == "homography":
        return HomographyCamera.from_dict(d)
    raise ValueError(f"unknown camera model {model!r}")


def homography_camera_from_pinhole(cam: PinholeCamera) -> HomographyCamera:
    """What a perfect point-correspondence calibration of `cam` would give."""
    return HomographyCamera.from_matrix(
        cam.ground_homography, cam.width_px, cam.height_px, cam.position_xy, cam.camera_id
    )


def ground_points_to_image(cam: GroundCamera, xy: np.ndarray) -> np.ndarray:
    """Convenience: just the pixel coordinates (NaN where not visible)."""
    uv, vis = cam.ground_to_image(xy)
    out = uv.copy()
    out[~vis] = np.nan
    return out


__all__ = [
    "GroundCamera",
    "HomographyCamera",
    "PinholeCamera",
    "apply_homography",
    "camera_from_dict",
    "ground_points_to_image",
    "homography_camera_from_pinhole",
]

"""Film a `WorldSnapshot` through a `PinholeCamera`: every vehicle becomes a
class-sized cuboid, its eight corners project to a bounding box, and each box
learns how much of it is actually visible.

**Occlusion.** Objects are ordered nearest-first by depth. Each box is
sampled on a small grid; a sample is hidden if it falls inside the
(slightly shrunk) box of any nearer object. The shrink approximates the
difference between a cuboid's true silhouette -- a hexagon -- and its
bounding rectangle, which would otherwise over-state occlusion at every
corner. Visibility is `1 - hidden samples / samples`. This is what makes a
bus hide the motorcycles behind it, which is the single most important
realism property for a queue-counting camera.

**Truncation.** A box cut by the frame edge keeps its clipped extent and
records what fraction of its area survived.

`rasterise` draws the scene (road, lane markings, vehicles) into an image
for demo video and for the pixel-level health checks. The detection path
never looks at those pixels.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from itms_geo.camera import PinholeCamera
from itms_geo.road import Lane

from vision_service.classes import VClass
from vision_service.simcam.world import WorldSnapshot

_MAX_RANGE_M = 260.0
_GRID = 6
_OCCLUDER_SHRINK = 0.12
_MIN_BOX_PX = 2.0


@dataclass(frozen=True)
class FilmedObjects:
    """Struct-of-arrays, one row per vehicle that lands in the frame."""

    ids: tuple[str, ...]
    vclass: tuple[VClass, ...]
    boxes: np.ndarray        # (N, 4) clipped x1 y1 x2 y2
    depth: np.ndarray        # (N,) optical-axis depth of the vehicle centre
    visible: np.ndarray      # (N,) fraction not hidden by nearer objects
    in_frame: np.ndarray     # (N,) fraction of the unclipped box inside the frame
    world_index: np.ndarray  # (N,) row in the source snapshot

    def __len__(self) -> int:
        return len(self.ids)


def _corners(snap: WorldSnapshot) -> np.ndarray:
    th = np.radians(snap.heading)
    fwd = np.stack([np.sin(th), np.cos(th)], axis=1)
    right = np.stack([np.cos(th), -np.sin(th)], axis=1)
    hl = (snap.length / 2.0)[:, None]
    hw = (snap.width / 2.0)[:, None]
    base = []
    for a, b in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
        base.append(snap.xy + a * hl * fwd + b * hw * right)
    base_xy = np.stack(base, axis=1)  # (N, 4, 2)
    n = len(snap)
    bottom = np.concatenate([base_xy, np.zeros((n, 4, 1))], axis=2)
    top = np.concatenate([base_xy, snap.height[:, None, None] * np.ones((n, 4, 1))], axis=2)
    return np.concatenate([bottom, top], axis=1)  # (N, 8, 3)


def film(cam: PinholeCamera, snap: WorldSnapshot) -> FilmedObjects:
    empty = FilmedObjects((), (), np.zeros((0, 4)), np.zeros(0), np.zeros(0), np.zeros(0),
                          np.zeros(0, dtype=int))
    if len(snap) == 0:
        return empty
    # cheap prefilter: in range and not behind the camera
    rel = snap.xy - cam.position_xy
    th = np.radians(cam.heading_deg)
    ahead = rel @ np.array([np.sin(th), np.cos(th)])
    near = (np.hypot(rel[:, 0], rel[:, 1]) <= _MAX_RANGE_M) & (ahead > -5.0)
    if not near.any():
        return empty
    idx = np.nonzero(near)[0]
    sub = snap.subset(near)

    corners = _corners(sub)
    n = len(sub)
    uv, depth = cam.project_points(corners.reshape(-1, 3))
    uv = uv.reshape(n, 8, 2)
    depth = depth.reshape(n, 8)
    front = (depth > 0.5).all(axis=1)
    if not front.any():
        return empty
    uv = np.where(front[:, None, None], uv, 0.0)  # rows behind the camera are dropped below
    x1, y1 = uv[..., 0].min(axis=1), uv[..., 1].min(axis=1)
    x2, y2 = uv[..., 0].max(axis=1), uv[..., 1].max(axis=1)
    raw_area = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    cx1, cy1 = np.clip(x1, 0, cam.width_px), np.clip(y1, 0, cam.height_px)
    cx2, cy2 = np.clip(x2, 0, cam.width_px), np.clip(y2, 0, cam.height_px)
    clip_area = np.maximum(0.0, cx2 - cx1) * np.maximum(0.0, cy2 - cy1)
    keep = front & (clip_area > 0) & ((cy2 - cy1) >= _MIN_BOX_PX) & ((cx2 - cx1) >= _MIN_BOX_PX)
    if not keep.any():
        return empty
    k = np.nonzero(keep)[0]
    boxes = np.stack([cx1[k], cy1[k], cx2[k], cy2[k]], axis=1)
    centre_depth = depth[k].mean(axis=1)
    in_frame = clip_area[k] / np.maximum(raw_area[k], 1e-9)

    visible = _visibility(boxes, centre_depth)
    return FilmedObjects(
        ids=tuple(sub.ids[i] for i in k),
        vclass=tuple(sub.vclass[i] for i in k),
        boxes=boxes,
        depth=centre_depth,
        visible=visible,
        in_frame=in_frame,
        world_index=idx[k],
    )


def _visibility(boxes: np.ndarray, depth: np.ndarray) -> np.ndarray:
    n = len(boxes)
    if n <= 1:
        return np.ones(n)
    g = (np.arange(_GRID) + 0.5) / _GRID
    gx, gy = np.meshgrid(g, g)
    gx, gy = gx.ravel(), gy.ravel()  # (G,)
    w = boxes[:, 2] - boxes[:, 0]
    h = boxes[:, 3] - boxes[:, 1]
    sx = boxes[:, 0:1] + gx[None] * w[:, None]  # (N, G)
    sy = boxes[:, 1:2] + gy[None] * h[:, None]
    sh = _OCCLUDER_SHRINK
    ox1 = boxes[:, 0] + sh * w
    ox2 = boxes[:, 2] - sh * w
    oy1 = boxes[:, 1] + sh * h
    oy2 = boxes[:, 3] - sh * h
    # inside[i, g, j]: sample g of box i is inside occluder j
    inside = (
        (sx[:, :, None] >= ox1[None, None])
        & (sx[:, :, None] <= ox2[None, None])
        & (sy[:, :, None] >= oy1[None, None])
        & (sy[:, :, None] <= oy2[None, None])
    )
    nearer = depth[None, :] < depth[:, None]  # [i, j]: j is in front of i
    hidden = (inside & nearer[:, None, :]).any(axis=2)
    return 1.0 - hidden.mean(axis=1)


# ---- optional raster -------------------------------------------------------

_CLASS_COLOUR = {
    VClass.MOTORCYCLE: (123, 201, 87),
    VClass.CAR: (255, 209, 127),
    VClass.AUTO_RICKSHAW: (58, 178, 232),
    VClass.BUS: (58, 112, 226),
    VClass.TRUCK: (90, 90, 200),
    VClass.BICYCLE: (200, 200, 90),
    VClass.PERSON: (200, 120, 200),
}


def rasterise(
    cam: PinholeCamera,
    snap: WorldSnapshot,
    lanes: Sequence[Lane],
    *,
    scale: float = 0.5,
) -> np.ndarray:
    """A BGR frame of the scene at `scale` x the camera resolution. Needs
    OpenCV (`vision-service[video]`)."""
    import cv2  # noqa: PLC0415

    w, h = int(cam.width_px * scale), int(cam.height_px * scale)
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (70, 90, 80)  # verge
    hr = int(max(0, min(h, cam.horizon_row() * scale)))
    img[:hr] = (200, 170, 140)  # sky

    def to_px(xy: np.ndarray) -> np.ndarray | None:
        uv, depth = cam.project_points(np.hstack([xy, np.zeros((len(xy), 1))]))
        ok = depth > 0.5
        if ok.sum() < 3:
            return None
        return (uv[ok] * scale).astype(np.int32)

    for lane in lanes:
        poly = to_px(lane.polygon())
        if poly is not None:
            cv2.fillPoly(img, [poly], (85, 85, 85))
    for lane in lanes:
        pts, _ = lane.sample(3.0)
        edge = to_px(lane.point_at(lane.sample(3.0)[1], lane.width / 2.0))
        if edge is not None:
            cv2.polylines(img, [edge], False, (230, 230, 230), 1)
        del pts

    filmed = film(cam, snap)
    order = np.argsort(-filmed.depth)  # far first, so near vehicles paint over
    corners = _corners(snap)
    for i in order:
        wi = filmed.world_index[i]
        uv, _ = cam.project_points(corners[wi])
        hull = cv2.convexHull((uv * scale).astype(np.int32))
        colour = _CLASS_COLOUR.get(filmed.vclass[i], (200, 200, 200))
        cv2.fillConvexPoly(img, hull, colour)
        cv2.polylines(img, [hull], True, (30, 30, 30), 1)
    return img

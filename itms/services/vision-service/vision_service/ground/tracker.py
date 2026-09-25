"""From image tracks to vehicles on the road, in metres.

Three steps per image track per frame:

1. **Footprint.** The bottom-centre of the box, back-projected through the
   camera's ground homography, is the vehicle's *nearest* ground edge, not its
   centre. The centre is further along the viewing ray by half the vehicle's
   extent in that direction -- `(L/2)|cos a| + (W/2)|sin a|`, where `a` is the
   angle between the vehicle's heading and the viewing ray and `L`, `W` are the
   class's typical dimensions. Without this every queue is short by half a
   car and every stop-line distance is biased, which matters because the
   controller's arrival term divides distance by speed.
2. **Ground Kalman filter.** Constant velocity in `(x, y)`, measurement noise
   scaled by the local ground resolution: at 100 m one pixel of box jitter is
   half a metre of road, at 20 m it is two centimetres, and treating them the
   same would make every distant vehicle look like it is accelerating.
3. **Frame edges.** A box cut by the edge of the frame is predicted, not
   measured: its bottom edge is the image border, not the road contact.
4. **Lane, heading and stop state.** Heading comes from the filtered
   velocity once the vehicle is moving; lane from `LaneLocator`, preferring
   lanes that run the same way. `stopped` has hysteresis (enter below
   0.8 m/s held for 1 s, leave above 2.0 m/s) because at camera resolution a
   single speed threshold chatters. SUMO's own 0.1 m/s halting threshold is
   not resolvable by any camera; the difference is a known, reported bias.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from itms_geo.camera import GroundCamera
from itms_geo.road import LaneLocator, heading_diff, heading_of

from vision_service.classes import ClassTable
from vision_service.records import GroundTrack, ImageTrack

_HISTORY_S = 30.0


@dataclass(frozen=True)
class GroundConfig:
    accel_sigma: float = 2.0          # m/s^2, process noise
    pixel_sigma_frac: float = 0.05    # box jitter as a fraction of box height
    min_pixel_sigma: float = 1.5
    min_meas_sigma_m: float = 0.15
    stop_enter_mps: float = 0.8
    stop_exit_mps: float = 2.0
    stop_hold_s: float = 1.0
    heading_min_speed_mps: float = 1.5
    travel_min_speed_mps: float = 1.5
    footprint_correction: bool = True
    border_px: float = 2.0
    seed_min_dt_s: float = 0.35
    # Stitching: a stopped or slow vehicle whose image track is lost (a bus
    # passes in front of it) and re-born within `stitch_s`, within
    # `stitch_radius_m` of where it was heading, is the same vehicle and
    # keeps its identity -- how far it drove to get there, when it was first
    # seen, and, once the new track itself confirms it is standing still,
    # since when it has been stopped. Without it, every re-acquisition of a
    # stalled car starts from moved_m = 0 -- "never drove in", furniture --
    # and no incident rule can ever see it stall. The new track is *not*
    # marked stopped on the strength of the old one: the first version did
    # that, and a car driving through the spot a stopped car had just left
    # was counted as queue (queue MAE 0.051 -> 0.063 PCU at medium demand).
    # 0 disables.
    stitch_s: float = 10.0
    stitch_radius_m: float = 3.0
    stitch_max_speed_mps: float = 2.0


def _predict_batch(x: np.ndarray, p: np.ndarray, dt: np.ndarray, accel_sigma: float) -> None:
    """In-place constant-velocity predict for `(K, 4)` states, `(K, 4, 4)`
    covariances and per-track `dt`."""
    k = len(x)
    f = np.tile(np.eye(4), (k, 1, 1))
    f[:, 0, 2] = f[:, 1, 3] = dt
    g = np.zeros((k, 4, 2))
    g[:, 0, 0] = g[:, 1, 1] = dt**2 / 2.0
    g[:, 2, 0] = g[:, 3, 1] = dt
    q = g @ g.transpose(0, 2, 1) * accel_sigma**2
    x[:] = np.einsum("kij,kj->ki", f, x)
    p[:] = f @ p @ f.transpose(0, 2, 1) + q


def _update_batch(x: np.ndarray, p: np.ndarray, z: np.ndarray, sigma: np.ndarray) -> None:
    """In-place position-measurement update, 2x2 innovation inverted in
    closed form."""
    s = p[:, :2, :2].copy()
    s[:, 0, 0] += sigma**2
    s[:, 1, 1] += sigma**2
    det = s[:, 0, 0] * s[:, 1, 1] - s[:, 0, 1] * s[:, 1, 0]
    inv = np.empty_like(s)
    inv[:, 0, 0] = s[:, 1, 1] / det
    inv[:, 1, 1] = s[:, 0, 0] / det
    inv[:, 0, 1] = -s[:, 0, 1] / det
    inv[:, 1, 0] = -s[:, 1, 0] / det
    gain = p[:, :, :2] @ inv  # (K, 4, 2)
    innov = z - x[:, :2]
    x += np.einsum("kij,kj->ki", gain, innov)
    p -= gain @ p[:, :2, :]


@dataclass
class _State:
    x: np.ndarray
    p: np.ndarray
    born_t: float
    first_xy: np.ndarray
    last_t: float
    moved_m: float = 0.0
    displaced_m: float = 0.0
    stopped: bool = False
    below_since: float | None = None
    stopped_since: float | None = None
    heading: float = float("nan")
    lane_id: str | None = None
    history: list = field(default_factory=list)
    last_hist_t: float = -1e9
    fresh: bool = True
    anchor: tuple | None = None
    inherited_stopped_since: float | None = None  # from a stitched predecessor


class GroundTracker:
    """One per camera. `update` runs every frame (vectorised over tracks);
    `assign_lanes` is separate because lane membership is only needed at the
    controller's 1 Hz tick, and it is the most expensive query."""

    def __init__(
        self,
        camera_id: str,
        camera: GroundCamera,
        locator: LaneLocator | None,
        classes: ClassTable | None = None,
        config: GroundConfig | None = None,
    ):
        self.camera_id = camera_id
        self.camera = camera
        self.locator = locator
        self.classes = classes or ClassTable.default()
        self.cfg = config or GroundConfig()
        self._states: dict[int, _State] = {}
        self._lost: list[_State] = []  # recently lost stopped/slow tracks, for stitching

    def reset(self) -> None:
        """Forget every track (after a gap in the video)."""
        self._states.clear()
        self._lost = []

    def _stitch(self, t: float, xy: np.ndarray) -> _State | None:
        cfg = self.cfg
        self._lost = [s for s in self._lost if t - s.last_t <= cfg.stitch_s]
        best, best_d = None, cfg.stitch_radius_m
        for s in self._lost:
            # where it would be now, if it kept creeping (at most 2 s of it)
            ahead = s.x[:2] + s.x[2:] * min(t - s.last_t, 2.0)
            d = float(np.hypot(*(ahead - xy)))
            if d <= best_d:
                best, best_d = s, d
        if best is not None:
            # by identity: _State holds arrays, so dataclass equality is ambiguous
            self._lost = [s for s in self._lost if s is not best]
        return best

    def _footprint(self, boxes: np.ndarray, tracks: list[ImageTrack]) -> tuple[np.ndarray,
                                                                               np.ndarray]:
        bottom = np.stack([(boxes[:, 0] + boxes[:, 2]) / 2.0, boxes[:, 3]], axis=1)
        g0 = self.camera.image_to_ground(bottom)
        res = self.camera.ground_resolution(g0)
        if not self.cfg.footprint_correction:
            return g0, res
        ray = g0 - self.camera.position_xy
        dist = np.hypot(ray[:, 0], ray[:, 1])
        ok = np.isfinite(dist) & (dist > 1e-6)
        u = np.zeros_like(ray)
        u[ok] = ray[ok] / dist[ok, None]
        length = np.array([self.classes[t.vclass].length_m for t in tracks])
        width = np.array([self.classes[t.vclass].width_m for t in tracks])
        hdg = np.array([
            self._states[t.track_id].heading if t.track_id in self._states else np.nan
            for t in tracks
        ])
        ray_hdg = heading_of(u)
        a = np.where(np.isfinite(hdg), np.radians(heading_diff(hdg, ray_hdg)), 0.0)
        c = (length / 2.0) * np.abs(np.cos(a)) + (width / 2.0) * np.abs(np.sin(a))
        out = g0.copy()
        out[ok] = g0[ok] + c[ok, None] * u[ok]
        return out, res

    def update(self, t: float, tracks: list[ImageTrack]) -> list[GroundTrack]:
        cfg = self.cfg
        live_ids = {tr.track_id for tr in tracks}
        for tid in [k for k in self._states if k not in live_ids]:
            gone = self._states.pop(tid)
            slow = not gone.fresh and math.hypot(*gone.x[2:]) < cfg.stitch_max_speed_mps
            if cfg.stitch_s > 0 and (gone.stopped or slow):
                self._lost.append(gone)
        if not tracks:
            return []
        boxes = np.stack([tr.box for tr in tracks])
        xy, res = self._footprint(boxes, tracks)
        finite = np.isfinite(xy).all(axis=1)
        box_h = boxes[:, 3] - boxes[:, 1]
        sigma_px = np.maximum(cfg.min_pixel_sigma, cfg.pixel_sigma_frac * box_h)
        sigma = np.maximum(cfg.min_meas_sigma_m, np.where(np.isfinite(res), res, 1.0) * sigma_px)

        # A box cut by the frame edge has lost the edge it would be measured by:
        # a vehicle leaving through the bottom of the frame keeps a bottom edge
        # pinned to the last image row, which projects to the same ground point
        # frame after frame -- a moving car that reads as stopped. Such boxes
        # are predicted, not measured.
        w_img, h_img = self.camera.width_px, self.camera.height_px
        b = cfg.border_px
        clean = ~((boxes[:, 3] >= h_img - b) | (boxes[:, 0] <= b) | (boxes[:, 2] >= w_img - b))

        idx = [i for i in range(len(tracks)) if finite[i]]
        old = [i for i in idx if tracks[i].track_id in self._states]
        new = [i for i in idx if tracks[i].track_id not in self._states]
        for i in new:
            sg = float(sigma[i]) if clean[i] else 4.0 * float(sigma[i])
            state = _State(
                x=np.array([xy[i, 0], xy[i, 1], 0.0, 0.0]),
                p=np.diag([sg**2, sg**2, 16.0, 16.0]),
                born_t=t,
                first_xy=xy[i].copy(),
                last_t=t,
                anchor=(t, xy[i].copy()) if clean[i] else None,
            )
            prior = self._stitch(t, xy[i]) if cfg.stitch_s > 0 and self._lost else None
            if prior is not None:
                # the same vehicle, re-acquired: keep its identity; its stop
                # carries over only once this track confirms it (below)
                state.born_t, state.moved_m = prior.born_t, prior.moved_m
                state.displaced_m = prior.displaced_m
                state.lane_id, state.history = prior.lane_id, list(prior.history)
                if prior.stopped:
                    state.inherited_stopped_since = prior.stopped_since
            self._states[tracks[i].track_id] = state
        frame_dt: dict[int, float] = {}
        if old:
            sts = [self._states[tracks[i].track_id] for i in old]
            x = np.stack([st.x for st in sts])
            p = np.stack([st.p for st in sts])
            dt = np.array([t - st.last_t for st in sts])
            for i, d in zip(old, dt, strict=True):
                frame_dt[tracks[i].track_id] = float(d)
            _predict_batch(x, p, dt, cfg.accel_sigma)
            meas = np.array([not tracks[i].coasting and bool(clean[i]) for i in old])
            if meas.any():
                oi = np.asarray(old)[meas]
                xm, pm = x[meas], p[meas]
                _update_batch(xm, pm, xy[oi], sigma[oi])
                x[meas], p[meas] = xm, pm
            for k, st in enumerate(sts):
                st.x, st.p, st.last_t = x[k], p[k], t
            # Two-point start: a track born with zero velocity takes seconds
            # to converge, and at 14 m/s a vehicle crosses a camera's view in
            # about seven -- every speed would read low. Seed the velocity from
            # the first two *clean* measurements.
            for i in old:
                st = self._states[tracks[i].track_id]
                if not st.fresh or tracks[i].coasting or not clean[i]:
                    continue
                if st.anchor is None:
                    st.anchor = (t, xy[i].copy())
                    continue
                dt0 = t - st.anchor[0]
                if dt0 >= cfg.seed_min_dt_s:
                    v = (xy[i] - st.anchor[1]) / dt0
                    sg = float(sigma[i])
                    st.x = np.array([xy[i, 0], xy[i, 1], v[0], v[1]])
                    vs = 2.0 * sg / dt0
                    st.p = np.diag([sg**2, sg**2, vs**2 + 1.0, vs**2 + 1.0])
                    st.fresh = False

        out: list[GroundTrack] = []
        for i in idx:
            tr = tracks[i]
            st = self._states[tr.track_id]
            pos = st.x[:2].copy()
            vel = st.x[2:].copy()
            speed = math.hypot(vel[0], vel[1])
            dt_frame = frame_dt.get(tr.track_id, 0.0)
            # Distance travelled *while actually moving*. Not displacement from
            # the first sighting: at 100 m, box jitter alone wanders a static
            # object's projected position by a metre or more, and a maximum
            # over time of that noise would call a billboard a vehicle.
            if speed >= cfg.travel_min_speed_mps and dt_frame > 0:
                st.moved_m += speed * dt_frame
            # Net progress, however slow: a vehicle that eased into a queue at
            # walking pace never reaches `travel_min_speed_mps`, and without
            # this it could never count as having arrived. Measured from the
            # first *clean* fix and only on measured frames, so a box pinned
            # to the frame edge or a coasting prediction cannot fake it; a
            # static false positive's jitter stays well under the 5 m the
            # rules ask for.
            if st.anchor is not None and not tr.coasting and clean[i]:
                st.displaced_m = max(st.displaced_m, math.hypot(*(pos - st.anchor[1])))
            if st.fresh:
                # Velocity not yet seeded from two clean measurements: the
                # filter's zero-velocity prior is not evidence of a stop.
                st.below_since = None
            elif st.stopped:
                if speed > cfg.stop_exit_mps:
                    st.stopped = False
                    st.stopped_since = None
                    st.below_since = None
            elif speed < cfg.stop_enter_mps:
                if st.below_since is None:
                    st.below_since = t
                if t - st.below_since >= cfg.stop_hold_s:
                    st.stopped = True
                    st.stopped_since = st.inherited_stopped_since if \
                        st.inherited_stopped_since is not None else st.below_since
                    st.inherited_stopped_since = None
            else:
                st.below_since = None
                st.inherited_stopped_since = None  # it moved: a new stop starts afresh
            if speed >= cfg.heading_min_speed_mps:
                st.heading = math.degrees(math.atan2(vel[0], vel[1])) % 360.0
            if t - st.last_hist_t >= 0.95:
                st.history.append((t, float(pos[0]), float(pos[1])))
                st.last_hist_t = t
                while st.history and st.history[0][0] < t - _HISTORY_S:
                    st.history.pop(0)
            info = self.classes[tr.vclass]
            out.append(
                GroundTrack(
                    camera_id=self.camera_id,
                    track_id=tr.track_id,
                    t=t,
                    xy=pos,
                    velocity=vel,
                    vclass=tr.vclass,
                    pcu=info.pcu,
                    length_m=info.length_m,
                    resolution_m_per_px=float(res[i]),
                    coasting=tr.coasting,
                    at_border=not bool(clean[i]),
                    stopped=st.stopped,
                    stopped_since=st.stopped_since,
                    born_t=st.born_t,
                    moved_m=st.moved_m,
                    displaced_m=st.displaced_m,
                    heading_deg=st.heading,
                    speed_known=not st.fresh,
                    lane_id=st.lane_id,
                    truth_id=tr.truth_id,
                    history=st.history,
                )
            )
        return out

    def assign_lanes(self, gts: list[GroundTrack]) -> None:
        """Fill `lane_id`, `s`, `lateral`, `lane_agrees` on `gts` (in place)."""
        self._assign_lanes(gts)

    def _assign_lanes(self, gts: list[GroundTrack]) -> None:
        if self.locator is None or not gts:
            return
        pts = np.stack([g.xy for g in gts])
        hdg = np.array([g.heading_deg for g in gts])
        m = self.locator.locate(pts, hdg)
        for i, g in enumerate(gts):
            st = self._states[g.track_id]
            j = int(m.lane[i])
            if j < 0:
                g.lane_id = None
                continue
            lane_id = self.locator.lane_ids[j]
            # A stopped vehicle keeps its lane: lateral jitter at range should
            # not hop it between adjacent lanes while it sits in a queue.
            if g.stopped and st.lane_id is not None and st.lane_id != lane_id:
                prev_idx = self.locator.index_of(st.lane_id) if st.lane_id in \
                    self.locator.lane_ids else -1
                if prev_idx >= 0:
                    lane = self.locator.lanes[prev_idx]
                    s, lat, _ = lane.project(pts[i:i + 1])
                    if abs(lat[0]) <= lane.width / 2.0 + 1.0:
                        g.lane_id = st.lane_id
                        g.s, g.lateral = float(s[0]), float(lat[0])
                        g.lane_agrees = True
                        continue
            g.lane_id = lane_id
            g.s = float(m.s[i])
            g.lateral = float(m.lateral[i])
            g.lane_agrees = bool(m.agrees[i])
            st.lane_id = lane_id
            if not math.isfinite(st.heading) and bool(m.agrees[i]):
                st.heading = float(m.lane_heading[i])

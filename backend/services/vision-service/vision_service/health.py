"""Is this camera telling the truth? Two independent kinds of evidence.

**Pixels** (`PixelHealthMonitor`, real frames only): sharpness (variance of a
3x3 Laplacian -- the standard focus measure; rain on the lens or a
defocused camera drops it), exposure (mean and spread of brightness),
frozen frames (an encoder that keeps re-sending the last frame produces
bit-identical images, which a digest catches), and sudden loss of edge
density against the camera's own learned baseline (a bag over the lens, a
bird, a sticker). Everything is relative to a baseline learned from the
camera's first frames, because "sharp" means different numbers for
different cameras.

**Traffic** (`DriftMonitor`, works for any source including the digital
twin): a camera knocked a few degrees out of calibration still produces
plausible-looking tracks, just in the wrong place. Moving vehicles should
travel along lane directions and stay on lanes. The monitor learns this
camera's normal heading error and off-lane rate for moving vehicles in its
well-resolved zone, then flags a sustained rise. No human has to look at
the camera for a bumped calibration to be noticed.

**Activity** (`ActivityMonitor`): a camera can deliver sharp, well-exposed
frames and still be blind -- a detector that does not recognise the view
(measured: stock COCO weights on an overhead clip found 1-3 vehicles in 43
frames that held traffic) reports an empty road, and an empty road is the
most dangerous thing a queue sensor can report, because the controller
believes it. The monitor learns how many vehicles this camera normally sees
and flags a silence that the learned rate makes implausible (Poisson: a
silence with 8 expected arrivals happens by chance about once in 3,000
windows), and a camera that has not seen a single vehicle since it started.
A jam is not a silence: stopped vehicles that drove in still count.

`CameraHealth` combines them, plus liveness (no frame for `offline_after_s`
means FAILED), into a status and a score in [0, 1] that multiplies into
every confidence the camera contributes to.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from itms_geo.road import heading_diff

from vision_service.records import GroundTrack


class CameraStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


# ---- pixels -------------------------------------------------------------------


def _gray_small(frame: np.ndarray, width: int = 320) -> np.ndarray:
    img = np.asarray(frame)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)
    step = max(1, img.shape[1] // width)
    return img[::step, ::step].astype(np.float64)


def laplacian_variance(gray: np.ndarray) -> float:
    g = gray
    lap = (-4.0 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def edge_density(gray: np.ndarray, thresh: float = 20.0) -> float:
    gx = np.abs(np.diff(gray, axis=1))[:-1, :]
    gy = np.abs(np.diff(gray, axis=0))[:, :-1]
    return float(((gx + gy) > thresh).mean())


@dataclass
class PixelMetrics:
    sharpness: float
    brightness: float
    contrast: float
    edge_density: float
    frozen_frames: int


@dataclass
class PixelHealthMonitor:
    baseline_frames: int = 50
    sharp_ratio_degraded: float = 0.35
    edge_ratio_failed: float = 0.25
    dark_below: float = 25.0
    bright_above: float = 235.0
    # Contrast is judged against the camera's own baseline, like sharpness:
    # a grey, empty parking lot has a pixel standard deviation of ~9 and is
    # perfectly healthy (an absolute floor of 12 flagged 474 of 597 frames of
    # a real clip). Fog and spray show up as a *collapse* from baseline.
    contrast_ratio_degraded: float = 0.45
    min_contrast: float = 3.0  # absolute floor: a featureless frame
    frozen_failed_after: int = 25
    _n: int = 0
    _sharp_base: float = 0.0
    _edge_base: float = 0.0
    _contrast_base: float = 0.0
    _last_digest: bytes = b""
    _frozen: int = 0
    last: PixelMetrics | None = None

    def update(self, frame: np.ndarray) -> PixelMetrics:
        gray = _gray_small(frame)
        digest = hashlib.blake2b(np.ascontiguousarray(frame).tobytes(), digest_size=16).digest()
        self._frozen = self._frozen + 1 if digest == self._last_digest else 0
        self._last_digest = digest
        m = PixelMetrics(
            sharpness=laplacian_variance(gray),
            brightness=float(gray.mean()),
            contrast=float(gray.std()),
            edge_density=edge_density(gray),
            frozen_frames=self._frozen,
        )
        if self._n < self.baseline_frames:
            k = self._n + 1
            self._sharp_base += (m.sharpness - self._sharp_base) / k
            self._edge_base += (m.edge_density - self._edge_base) / k
            self._contrast_base += (m.contrast - self._contrast_base) / k
        self._n += 1
        self.last = m
        return m

    def assess(self) -> tuple[CameraStatus, float, list[str]]:
        m = self.last
        if m is None:
            return CameraStatus.FAILED, 0.0, ["no frames"]
        reasons: list[str] = []
        status, score = CameraStatus.OK, 1.0
        if m.frozen_frames >= self.frozen_failed_after:
            return CameraStatus.FAILED, 0.0, [f"frozen for {m.frozen_frames} frames"]
        if self._n >= self.baseline_frames and self._edge_base > 0:
            if m.edge_density < self.edge_ratio_failed * self._edge_base:
                return CameraStatus.FAILED, 0.0, ["edge density collapsed (occluded or tampered)"]
            if self._sharp_base > 0 and m.sharpness < self.sharp_ratio_degraded * self._sharp_base:
                status, score = CameraStatus.DEGRADED, min(score, 0.6)
                reasons.append("blurred")
        if m.brightness < self.dark_below or m.brightness > self.bright_above:
            status, score = CameraStatus.DEGRADED, min(score, 0.6)
            reasons.append("exposure")
        low_rel = self._n >= self.baseline_frames and self._contrast_base > 0 and \
            m.contrast < self.contrast_ratio_degraded * self._contrast_base
        if m.contrast < self.min_contrast or low_rel:
            status, score = CameraStatus.DEGRADED, min(score, 0.6)
            reasons.append("low contrast")
        return status, score, reasons


# ---- traffic-based calibration drift ------------------------------------------------


@dataclass
class DriftMonitor:
    """Sliding-window heading error and off-lane rate of *moving* vehicles
    in the camera's well-resolved zone, against a learned baseline."""

    min_speed_mps: float = 3.0
    min_range_m: float = 15.0
    max_range_m: float = 90.0
    window_s: float = 120.0
    baseline_s: float = 300.0
    min_samples: int = 40
    heading_alarm_deg: float = 6.0     # rise over baseline median heading error
    offlane_alarm: float = 0.2         # rise over baseline off-lane rate
    _samples: deque = field(default_factory=deque)   # (t, heading_err or nan, off_lane)
    _t0: float | None = None
    _base_heading: float | None = None
    _base_offlane: float | None = None
    drift: bool = False
    heading_err_deg: float = float("nan")
    offlane_rate: float = float("nan")

    def observe(self, t: float, tracks: list[GroundTrack], nadir_xy: np.ndarray,
                lane_heading_of) -> None:
        """`lane_heading_of(track) -> float | None` gives the direction of the
        lane the track is on (NaN / None when on no lane)."""
        if self._t0 is None:
            self._t0 = t
        for g in tracks:
            if g.coasting or g.speed < self.min_speed_mps:
                continue
            r = float(np.hypot(*(g.xy - nadir_xy)))
            if not (self.min_range_m <= r <= self.max_range_m):
                continue
            lh = lane_heading_of(g)
            if lh is None or not np.isfinite(lh):
                self._samples.append((t, float("nan"), 1.0))
            else:
                err = float(heading_diff(g.heading_deg, lh)) if np.isfinite(g.heading_deg) \
                    else float("nan")
                self._samples.append((t, err, 0.0))
        while self._samples and self._samples[0][0] < t - self.window_s:
            self._samples.popleft()
        if len(self._samples) < self.min_samples:
            return
        errs = np.array([s[1] for s in self._samples])
        off = np.array([s[2] for s in self._samples])
        valid = errs[np.isfinite(errs)]
        self.heading_err_deg = float(np.median(valid)) if len(valid) else float("nan")
        self.offlane_rate = float(off.mean())
        if self._base_heading is None:
            if t - self._t0 >= self.baseline_s:
                self._base_heading = self.heading_err_deg
                self._base_offlane = self.offlane_rate
            return
        rise_h = self.heading_err_deg - self._base_heading \
            if np.isfinite(self.heading_err_deg) else 0.0
        rise_o = self.offlane_rate - (self._base_offlane or 0.0)
        self.drift = rise_h > self.heading_alarm_deg or rise_o > self.offlane_alarm


# ---- activity: a blind detector reports an empty road ---------------------------------


@dataclass
class ActivityMonitor:
    """Vehicles seen per second, learned; a silence the rate makes
    implausible, or no vehicle at all since start-up, is flagged.

    A vehicle "counts" once it has driven (`moved_m` past the furniture
    limit), so a jammed approach full of stopped cars is active and a
    detector hotspot that never moves is not."""

    window_s: float = 120.0          # how long a silence must last to be judged
    min_expected: float = 8.0        # expected arrivals in that window before silence is suspicious
    tau_s: float = 900.0             # memory of the arrival rate
    commission_s: float = 600.0      # a camera that has seen nothing for this long since start
    moved_m: float = 1.5
    _rate: float = 0.0               # arrivals per second, EWMA
    _t0: float | None = None
    _t_prev: float | None = None
    _last_active_t: float | None = None
    _ever_active: bool = False
    _counted: dict = field(default_factory=dict)   # track id -> t first counted
    silent: bool = False
    never_worked: bool = False      # the commissioning case: nothing seen since start
    reason: str = ""

    def observe(self, t: float, tracks: list[GroundTrack]) -> None:
        if self._t0 is None:
            self._t0 = self._t_prev = t
        dt = max(0.0, t - (self._t_prev if self._t_prev is not None else t))
        self._t_prev = t
        active = [g for g in tracks if g.moved_m >= self.moved_m]
        if active:
            self._last_active_t = t
            self._ever_active = True
        arrivals = 0
        for g in active:
            if g.track_id not in self._counted:
                self._counted[g.track_id] = t
                arrivals += 1
        # forget vehicles long gone -- but not one still in view: a car that
        # sits in a jam for ten minutes is one arrival, not two
        in_view = {g.track_id for g in tracks}
        for k in [k for k, v in self._counted.items()
                  if t - v > 4 * self.window_s and k not in in_view]:
            del self._counted[k]
        quiet_for = t - (self._last_active_t if self._last_active_t is not None else self._t0)
        if dt > 0:
            # during a suspicious silence the learned rate is held (slow decay),
            # or a blind camera would talk itself into "a quiet road" in minutes
            tau = self.tau_s * (4.0 if quiet_for >= self.window_s else 1.0)
            a = min(1.0, dt / tau)
            self._rate += a * (arrivals / dt - self._rate)
        expected = self._rate * self.window_s
        self.never_worked = not self._ever_active and t - self._t0 >= self.commission_s
        if self.never_worked:
            self.silent = True
            self.reason = f"no vehicle seen in {t - self._t0:.0f} s since start"
        elif quiet_for >= self.window_s and expected >= self.min_expected:
            self.silent = True
            self.reason = (f"no vehicle for {quiet_for:.0f} s where "
                           f"{60.0 * self._rate:.1f}/min is normal")
        else:
            self.silent = False
            self.reason = ""


# ---- combined ------------------------------------------------------------------------


@dataclass
class CameraHealth:
    camera_id: str
    offline_after_s: float = 2.0
    pixels: PixelHealthMonitor | None = None
    drift: DriftMonitor = field(default_factory=DriftMonitor)
    activity: ActivityMonitor = field(default_factory=ActivityMonitor)
    last_frame_t: float | None = None
    forced_offline: bool = False

    def saw_frame(self, t: float, frame: np.ndarray | None = None) -> None:
        self.last_frame_t = t
        if frame is not None:
            if self.pixels is None:
                self.pixels = PixelHealthMonitor()
            self.pixels.update(frame)

    def assess(self, t: float) -> tuple[CameraStatus, float, list[str]]:
        if self.forced_offline or self.last_frame_t is None or \
                t - self.last_frame_t > self.offline_after_s:
            return CameraStatus.FAILED, 0.0, ["offline"]
        reasons: list[str] = []
        status, score = CameraStatus.OK, 1.0
        if self.pixels is not None:
            status, score, reasons = self.pixels.assess()
            if status is CameraStatus.FAILED:
                return status, score, reasons
        if self.drift.drift:
            status = CameraStatus.DEGRADED
            score = min(score, 0.5)
            reasons = [*reasons, "calibration drift"]
        if self.activity.silent:
            # Frames arrive but nothing is recognised. Told to an operator
            # always; told to the controller only when the camera has *never*
            # seen a vehicle -- then its "empty road" has never been shown to
            # mean anything, and 0.3 puts every link it alone covers below the
            # adapter's hard-failure line (0.5). A camera that saw traffic and
            # then sees none may be blind, or the traffic may really have
            # stopped (a closure upstream; the end of the gates' demand, where
            # the first version sent junctions to fixed-time for no reason):
            # one camera cannot tell the two apart. Stop-bar detection can,
            # and that cross-check belongs where both are known -- the
            # controller adapter; not built.
            status = CameraStatus.DEGRADED
            if self.activity.never_worked:
                score = min(score, 0.3)
            reasons = [*reasons, self.activity.reason]
        return status, score, reasons

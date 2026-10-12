"""How much of each lane a camera actually sees -- the geometric half of every
vision confidence value.

A lane point counts as *covered* by a camera when it projects inside the
frame, in front of the camera, at a ground resolution no coarser than
`max_resolution_m_per_px` along the worst image direction. Past that
resolution a stopped car is a handful of pixels tall, and a detector that
"sees" it is guessing.

Two summaries matter to the controller, because its quantities live at
opposite ends of different lanes:

- approach lanes: metres covered **contiguously upstream from the stop
  line** (`covered_from_end_m`) -- the queue grows from the stop line back,
  so a camera that sees 80 m of lane starting 40 m upstream of the stop line
  cannot measure a queue at all;
- receiving lanes: metres covered **from the lane's upstream start**
  (`covered_from_start_m`) -- spillback into the junction starts there.

numpy only.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from itms_geo.camera import GroundCamera
from itms_geo.road import Lane

DEFAULT_MAX_RESOLUTION_M_PER_PX = 0.6
DEFAULT_STEP_M = 2.0


@dataclass(frozen=True)
class LaneCoverage:
    lane_id: str
    length: float
    s: np.ndarray            # sample positions along the lane (m)
    covered: np.ndarray      # bool per sample
    resolution: np.ndarray   # best m/px among contributing cameras, inf if unseen

    @property
    def fraction(self) -> float:
        return float(self.covered.mean()) if len(self.covered) else 0.0

    @property
    def covered_m(self) -> float:
        return self.fraction * self.length

    def _run_from(self, order: np.ndarray) -> float:
        run = 0
        for c in self.covered[order]:
            if not c:
                break
            run += 1
        if run == 0:
            return 0.0
        if run == len(self.s):
            return self.length
        step = self.length / max(1, len(self.s) - 1)
        return min(self.length, run * step)

    @property
    def covered_from_end_m(self) -> float:
        return self._run_from(np.arange(len(self.s))[::-1])

    @property
    def covered_from_start_m(self) -> float:
        return self._run_from(np.arange(len(self.s)))

    def covers(self, s: np.ndarray) -> np.ndarray:
        """Whether positions `s` fall on a covered sample (nearest sample)."""
        s_arr = np.asarray(s, dtype=np.float64)
        if len(self.s) == 0:
            return np.zeros(s_arr.shape, dtype=bool)
        idx = np.clip(np.searchsorted(self.s, s_arr), 0, len(self.s) - 1)
        prev = np.clip(idx - 1, 0, len(self.s) - 1)
        nearest = np.where(np.abs(self.s[prev] - s_arr) < np.abs(self.s[idx] - s_arr), prev, idx)
        return self.covered[nearest]


def lane_coverage(
    cam: GroundCamera,
    lane: Lane,
    *,
    max_resolution_m_per_px: float = DEFAULT_MAX_RESOLUTION_M_PER_PX,
    step_m: float = DEFAULT_STEP_M,
) -> LaneCoverage:
    pts, s = lane.sample(step_m)
    _, visible = cam.ground_to_image(pts)
    res = cam.ground_resolution(pts)
    res = np.where(visible, res, np.inf)
    covered = visible & (res <= max_resolution_m_per_px)
    return LaneCoverage(lane.lane_id, lane.length, s, covered, res)


def camera_coverage(
    cam: GroundCamera,
    lanes: Iterable[Lane],
    *,
    max_resolution_m_per_px: float = DEFAULT_MAX_RESOLUTION_M_PER_PX,
    step_m: float = DEFAULT_STEP_M,
    min_fraction: float = 0.0,
) -> dict[str, LaneCoverage]:
    """Coverage of every lane in `lanes` by one camera, keeping lanes with
    coverage above `min_fraction` (strictly, so the default drops unseen
    lanes)."""
    out = {}
    for lane in lanes:
        cov = lane_coverage(
            cam, lane, max_resolution_m_per_px=max_resolution_m_per_px, step_m=step_m
        )
        if cov.fraction > min_fraction:
            out[lane.lane_id] = cov
    return out


def merge_coverage(parts: Sequence[LaneCoverage]) -> LaneCoverage:
    """Union of several cameras' coverage of the same lane."""
    if not parts:
        raise ValueError("nothing to merge")
    first = parts[0]
    covered = np.zeros_like(first.covered)
    res = np.full_like(first.resolution, np.inf)
    for p in parts:
        if p.lane_id != first.lane_id or len(p.s) != len(first.s):
            raise ValueError("can only merge coverage of the same lane at the same sampling")
        covered |= p.covered
        res = np.minimum(res, p.resolution)
    return LaneCoverage(first.lane_id, first.length, first.s, covered, res)

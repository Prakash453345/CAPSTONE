"""Screen-space motion checks on tracked vehicles: a stalled vehicle, and
heavy congestion.

An uploaded clip has no camera calibration and no signal state, so the
lane-level rules in `incidents/rules.py` (which work in metres on a known
lane, and know when the light is green) cannot run on it. These checks use
only what the picture gives: tracked boxes moving or not. Distances are
measured in box heights, so the same thresholds hold whether a car is near
the camera or far from it.

- **moving**: the box's bottom-centre moved more than `MOVE_FRAC` box heights
  over the last `MOVE_WINDOW_S` seconds.
- **stalled vehicle**: a vehicle that *drove in* (was seen moving) stops, and
  stays stopped for `STALL_S` while at least `MIN_PASSERS` other vehicles
  move *in the direction it was travelling*. Both guards matter:
  - "drove in" excludes vehicles parked from the start of the clip;
  - "traffic its own way keeps passing" excludes a queue at a red light,
    where every vehicle going its way is stopped too, while cross traffic
    moves.
- **heavy congestion**: at least `JAM_MIN_VEHICLES` in view with at most
  `JAM_MAX_MOVING_SHARE` of them moving, for `JAM_MIN_S` seconds in a row --
  long enough that an ordinary red-light queue does not count.

**None of these thresholds is measured.** They are reasoned starting points;
the first labelled clips should be used to set them, the way the fire
monitor's are flagged in `fire/monitor.py`.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from vision_service.classes import VEHICLE_CLASSES
from vision_service.clips.model import Finding
from vision_service.clips.severity import SecondStats
from vision_service.records import ImageTrack

MOVE_WINDOW_S = 2.0
MOVE_FRAC = 0.25
STALL_S = 20.0
MIN_PASSERS = 2
SAME_DIRECTION_COS = 0.7
LOST_AFTER_S = 3.0
JAM_MIN_VEHICLES = 10
JAM_MAX_MOVING_SHARE = 0.2
JAM_MIN_S = 60.0


@dataclass
class _TrackState:
    hist: deque = field(default_factory=deque)       # (t, x, y, h)
    moving: bool | None = None                       # None until MOVE_WINDOW_S of history
    heading: tuple[float, float] | None = None       # unit vector of its last movement
    moved_ever: bool = False
    stop_since: float | None = None
    passers: set = field(default_factory=set)
    box_norm: tuple[float, float, float, float] | None = None
    last_seen: float = 0.0
    flagged: Finding | None = None


class MotionAnalyser:
    def __init__(self) -> None:
        self._tracks: dict[int, _TrackState] = {}
        self._findings: list[Finding] = []
        self.seconds: list[SecondStats] = []
        self._second: int | None = None
        self._last_counts = (0, 0, 0)
        self._t = 0.0

    def observe(self, t: float, tracks: list[ImageTrack], frame_wh: tuple[int, int]) -> None:
        """One processed frame's tracks, in time order."""
        self._close_seconds(t)
        self._t = t
        w, h = frame_wh
        movers: list[tuple[int, tuple[float, float]]] = []
        vehicles = moving = stopped = 0
        for tr in tracks:
            if tr.vclass not in VEHICLE_CLASSES or tr.coasting:
                continue
            x1, y1, x2, y2 = (float(v) for v in tr.box)
            st = self._tracks.setdefault(tr.track_id, _TrackState())
            st.last_seen = t
            st.box_norm = (x1 / w, y1 / h, x2 / w, y2 / h) if w and h else None
            st.hist.append((t, (x1 + x2) / 2, y2, max(1.0, y2 - y1)))
            while st.hist and t - st.hist[0][0] > MOVE_WINDOW_S:
                st.hist.popleft()
            vehicles += 1
            self._update_motion(tr.track_id, st, t)
            if st.moving:
                moving += 1
                if st.heading is not None:
                    movers.append((tr.track_id, st.heading))
            elif st.moving is False:
                stopped += 1
        self._last_counts = (vehicles, moving, stopped)
        self._check_stalls(t, movers)
        self._drop_lost(t)

    def _update_motion(self, tid: int, st: _TrackState, t: float) -> None:
        t0, x0, y0, _ = st.hist[0]
        _, x, y, _ = st.hist[-1]
        if t - t0 < MOVE_WINDOW_S * 0.75:
            return                                   # not enough history to say yet
        heights = sorted(p[3] for p in st.hist)
        scale = heights[len(heights) // 2]
        dx, dy = x - x0, y - y0
        dist = math.hypot(dx, dy)
        if dist > MOVE_FRAC * scale:
            st.moving = True
            st.moved_ever = True
            st.heading = (dx / dist, dy / dist)
            if st.flagged is not None:
                st.flagged.end_s = t                 # it moved off: the stall is over
                st.flagged = None
            st.stop_since = None
            st.passers.clear()
        else:
            if st.moving is not False:
                st.stop_since = t
            st.moving = False

    def _check_stalls(self, t: float, movers: list[tuple[int, tuple[float, float]]]) -> None:
        for tid, st in self._tracks.items():
            if st.moving is not False or not st.moved_ever or st.heading is None:
                continue
            hx, hy = st.heading
            for mid, (mx, my) in movers:
                if mid != tid and mx * hx + my * hy >= SAME_DIRECTION_COS:
                    st.passers.add(mid)
            assert st.stop_since is not None
            stopped_for = t - st.stop_since
            if st.flagged is not None:
                st.flagged.end_s = t
                st.flagged.confidence = _stall_confidence(stopped_for, len(st.passers))
                st.flagged.evidence.update(stopped_s=round(stopped_for, 1),
                                           passed_by=len(st.passers))
            elif stopped_for >= STALL_S and len(st.passers) >= MIN_PASSERS:
                st.flagged = Finding(
                    anomaly_type="vehicle_breakdown", detector="stalled",
                    confidence=_stall_confidence(stopped_for, len(st.passers)),
                    start_s=st.stop_since, end_s=t, box_norm=st.box_norm,
                    evidence={"track_id": tid, "stopped_s": round(stopped_for, 1),
                              "passed_by": len(st.passers), "heuristic": True})
                self._findings.append(st.flagged)

    def _drop_lost(self, t: float) -> None:
        for tid in [tid for tid, st in self._tracks.items() if t - st.last_seen > LOST_AFTER_S]:
            st = self._tracks.pop(tid)
            if st.flagged is not None:
                st.flagged.end_s = st.last_seen

    def _close_seconds(self, t: float) -> None:
        sec = int(t)
        if self._second is None:
            self._second = sec
        while self._second < sec:
            v, m, s = self._last_counts
            self.seconds.append(SecondStats(float(self._second), v, m, s))
            self._second += 1

    def finish(self) -> list[Finding]:
        """Close the clip; returns the stalled-vehicle and congestion findings."""
        self._close_seconds(self._t + 1.0)
        for st in self._tracks.values():
            if st.flagged is not None:
                st.flagged.end_s = self._t
        return self._findings + self._congestion()

    def _congestion(self) -> list[Finding]:
        out: list[Finding] = []
        run: list[SecondStats] = []
        for s in [*self.seconds, None]:
            jammed = (s is not None and s.vehicles >= JAM_MIN_VEHICLES
                      and s.moving <= JAM_MAX_MOVING_SHARE * s.vehicles)
            if jammed:
                assert s is not None
                run.append(s)
                continue
            if run and run[-1].t - run[0].t + 1 >= JAM_MIN_S:
                length = run[-1].t - run[0].t + 1
                out.append(Finding(
                    anomaly_type="heavy_congestion", detector="congestion",
                    confidence=0.5 + 0.5 * min(1.0, (length - JAM_MIN_S) / JAM_MIN_S),
                    start_s=run[0].t, end_s=run[-1].t + 1,
                    evidence={"seconds": int(length),
                              "mean_vehicles": round(sum(r.vehicles for r in run) / len(run), 1),
                              "mean_moving": round(sum(r.moving for r in run) / len(run), 1),
                              "heuristic": True}))
            run = []
        return out


def _stall_confidence(stopped_for: float, passers: int) -> float:
    return min(1.0, 0.5 + 0.25 * min(1.0, (stopped_for - STALL_S) / STALL_S)
               + 0.25 * min(1.0, (passers - MIN_PASSERS) / 4))

"""Analyse one clip with every detector that is installed.

Each detector runs at its own rate, the one it was built or tested at:

- vehicles (detector + ByteTrack + `motion.MotionAnalyser`): 5 frames/s, the
  tracker's configured rate -- gives the stalled-vehicle and congestion
  findings, and the traffic measurements severity is judged from;
- accident model: 2 frames/s, its training and test rate (`accident.py`);
- fire/smoke scorer: once a second, as in the live video mode (`main.py`).

All findings are kept, ranked by severity, then by type (fire, accident,
stalled vehicle, congestion), then by confidence; the first is the clip's
main finding. A clip with no finding is a valid result -- "normal traffic"
-- and the result names which detectors ran, so "nothing found" is never
mistaken for "not looked for".
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from vision_service.clips.accident import AccidentAlarm, AlarmRule
from vision_service.clips.model import Finding
from vision_service.clips.motion import MotionAnalyser
from vision_service.clips.severity import LEVELS, assess
from vision_service.detect.base import Detector
from vision_service.fire.detector import FireScore
from vision_service.fire.monitor import FireCandidate, FireMonitor
from vision_service.track.bytetrack import ByteTrackConfig, ByteTracker

VEHICLE_FPS = 5.0
ACCIDENT_FPS = 2.0
FIRE_FPS = 1.0
READ_FPS = 10.0  # frames read from the video: every rate above falls on this grid
TYPE_PRIORITY = {"fire": 0, "accident": 1, "vehicle_breakdown": 2, "heavy_congestion": 3}


class FireScorerLike(Protocol):
    def score(self, frame: np.ndarray) -> FireScore: ...


class AccidentModelLike(Protocol):
    rule: AlarmRule

    def prob(self, frame: np.ndarray) -> float | None:
        """None while a stateful model has no new score due."""
        ...


@dataclass
class ClipDetectors:
    vehicles: Detector | None = None
    fire: FireScorerLike | None = None
    accident: AccidentModelLike | None = None

    def names(self) -> list[str]:
        return [n for n, d in (("vehicles", self.vehicles), ("fire", self.fire),
                               ("accident", self.accident)) if d is not None]


@dataclass
class ClipAnalysis:
    findings: list[Finding]
    detectors: list[str]
    duration_s: float
    timeline: dict = field(default_factory=dict)

    @property
    def main(self) -> Finding | None:
        return self.findings[0] if self.findings else None


def analyse_clip(
    frames: Iterable[tuple[float, np.ndarray]],
    detectors: ClipDetectors,
    *,
    duration_s: float | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> ClipAnalysis:
    """`frames` yields (seconds into the video, BGR frame) in time order."""
    if not detectors.names():
        raise ValueError("no detector is installed, so the clip cannot be analysed")
    tracker = ByteTracker(ByteTrackConfig(fps=VEHICLE_FPS)) if detectors.vehicles else None
    motion = MotionAnalyser() if detectors.vehicles else None
    fire_monitor = FireMonitor("clip") if detectors.fire else None
    alarm = AccidentAlarm(detectors.accident.rule) if detectors.accident else None
    accident_fps = getattr(detectors.accident, "sample_fps", ACCIDENT_FPS)
    reset = getattr(detectors.accident, "reset", None)
    if reset is not None:
        reset()   # a stateful model starts each clip empty  # noqa: E501
    fire_candidates: list[FireCandidate] = []
    accident_p: dict[int, float] = {}
    fire_p: dict[int, float] = {}
    next_vehicle = next_fire = next_accident = 0.0
    last_t = 0.0

    for t, frame in frames:
        last_t = t
        h, w = frame.shape[:2]
        if detectors.vehicles is not None and t >= next_vehicle:
            assert tracker is not None and motion is not None
            motion.observe(t, tracker.update(detectors.vehicles.detect(frame)), (w, h))
            next_vehicle = _next_slot(t, VEHICLE_FPS)
        if detectors.accident is not None and t >= next_accident:
            assert alarm is not None
            p = detectors.accident.prob(frame)
            if p is not None:
                alarm.observe(t, p)
                accident_p[int(t)] = max(p, accident_p.get(int(t), 0.0))
            next_accident = _next_slot(t, accident_fps)
        if detectors.fire is not None and t >= next_fire:
            assert fire_monitor is not None
            score = detectors.fire.score(frame)
            fire_monitor.observe(t, score)
            new, _ = fire_monitor.drain()
            fire_candidates.extend(new)
            fire_p[int(t)] = max(score.p_fire, score.p_smoke, fire_p.get(int(t), 0.0))
            next_fire = _next_slot(t, FIRE_FPS)
        if on_progress is not None and duration_s:
            on_progress(min(1.0, t / duration_s))

    findings: list[Finding] = []
    if motion is not None:
        findings.extend(motion.finish())
    findings.extend(_fire_findings(fire_candidates, last_t))
    if alarm is not None:
        findings.extend(_accident_findings(alarm, last_t))

    scene = motion.seconds if motion is not None else None
    for f in findings:
        sev = assess(f.anomaly_type, f.start_s, f.end_s, scene)
        f.severity = sev.level
        f.reasons = [_detector_reason(f), *sev.reasons]
    findings.sort(key=lambda f: (-LEVELS.index(f.severity), TYPE_PRIORITY.get(f.anomaly_type, 9),
                                 -f.confidence, f.start_s))
    return ClipAnalysis(
        findings=findings,
        detectors=detectors.names(),
        duration_s=duration_s if duration_s is not None else last_t,
        timeline=_timeline(last_t, scene, accident_p if alarm else None,
                           fire_p if fire_monitor else None),
    )


def _next_slot(t: float, fps: float) -> float:
    """The next point of a fixed 1/fps grid after `t`. A grid, not `t + step`:
    with frames that do not land exactly on the step, `t + step` drifts (frames
    at 5 fps sampled every 0.5 s that way come out every 0.6 s)."""
    step = 1.0 / fps
    return (math.floor(t / step + 1e-6) + 1) * step - 1e-6


def _fire_findings(candidates: list[FireCandidate], last_t: float) -> list[Finding]:
    out = []
    for c in candidates:
        box = c.evidence.get("box_norm")
        out.append(Finding(
            anomaly_type="fire", detector="fire", confidence=c.score, start_s=c.first_t,
            end_s=c.resolved_t if c.resolved_t is not None else last_t,
            box_norm=tuple(box) if box else None,
            evidence={"kind": c.kind, **{k: v for k, v in c.evidence.items() if k != "box_norm"}}))
    return out


def _accident_findings(alarm: AccidentAlarm, last_t: float) -> list[Finding]:
    rule = alarm.rule
    return [Finding(
        anomaly_type="accident", detector="accident", confidence=run["peak"],
        start_s=run["start_s"], end_s=run["end_s"],
        evidence={"alarm_s": round(run["alarm_s"], 2), "peak": round(run["peak"], 4),
                  "thr": rule.thr, "k": rule.k, "n": rule.n, "rule_validated": rule.validated})
        for run in alarm.runs]


def _detector_reason(f: Finding) -> str:
    e = f.evidence
    if f.detector == "accident":
        text = (f"accident model: {e['k']} of {e['n']} frames at or above {e['thr']:.2f} "
                f"(peak {e['peak']:.2f})")
        return text if e.get("rule_validated") else text + "; alarm rule not validated yet"
    if f.detector == "fire":
        return (f"fire/smoke scorer: {e.get('kind') or 'fire'} in {e.get('hits')} of the last "
                f"{e.get('window')} one-second checks (peak {f.confidence:.2f})")
    if f.detector == "stalled":
        return (f"a vehicle stopped for {e['stopped_s']:.0f} s while {e['passed_by']} vehicles "
                f"going its way drove past it")
    if f.detector == "congestion":
        return (f"{e['seconds']} s with about {e['mean_vehicles']:.0f} vehicles in view and "
                f"{e['mean_moving']:.1f} moving")
    return f.detector


def _timeline(last_t: float, scene, accident_p, fire_p) -> dict:
    n = int(last_t) + 1
    out: dict = {"t": list(range(n))}
    if scene is not None:
        by_t = {int(s.t): s for s in scene}
        out["vehicles"] = [by_t[i].vehicles if i in by_t else None for i in range(n)]
        out["moving"] = [by_t[i].moving if i in by_t else None for i in range(n)]
    if accident_p is not None:
        out["accident"] = [round(accident_p[i], 3) if i in accident_p else None for i in range(n)]
    if fire_p is not None:
        out["fire"] = [round(fire_p[i], 3) if i in fire_p else None for i in range(n)]
    return out

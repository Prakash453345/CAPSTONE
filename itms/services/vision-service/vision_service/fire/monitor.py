"""From one score per second to a fire candidate for an operator.

`FireMonitor` is one camera's persistence layer. The scorer
(`detector.FireScorer`) answers "does this frame alarm?"; a candidate needs
more than one frame, like every other rule here (`incidents/rules.py`):

- **raise** when at least `raise_hits` of the last `window` observations
  alarm. At the intended 1 Hz that is 3 alarming seconds out of the last 5;
- **resolve** once `clear_s` seconds have passed with no alarming frame;
- after a resolution the same camera stays quiet for `cooldown_s`.

**These settings are not measured.** Step 2 scored single images; there is
no labelled street-fire video, so nothing here has been tuned or tested on
fire that moves, flickers or grows. They are conservative guesses (they only
remove the frame-level false alarms that do not repeat), and the first real
footage should be used to set them. No flicker or growth rule is in: a rule
with no data behind it would only look like evidence.

A candidate is not an incident: ADR-006's operator gate stands between it
and anything that is dispatched.
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from dataclasses import dataclass, field

from vision_service.fire.detector import FireScore


@dataclass(frozen=True)
class FireMonitorConfig:
    window: int = 5
    raise_hits: int = 3
    clear_s: float = 30.0
    cooldown_s: float = 120.0
    max_gap_s: float = 10.0   # observations further apart than this do not count together


@dataclass
class FireCandidate:
    candidate_id: str
    camera_id: str
    kind: str                      # "fire" | "smoke" | "fire+smoke": what alarmed while it was open
    score: float                   # the highest alarming probability seen
    first_t: float                 # the first alarming frame of the run that raised it
    raised_t: float
    evidence: dict
    status: str = "ACTIVE"
    resolved_t: float | None = None
    kinds: set = field(default_factory=set, repr=False)


@dataclass
class FireMonitor:
    camera_id: str
    cfg: FireMonitorConfig = field(default_factory=FireMonitorConfig)

    def __post_init__(self) -> None:
        self._obs: deque[tuple[float, bool, FireScore]] = deque(maxlen=self.cfg.window)
        self._candidate: FireCandidate | None = None
        self._last_alarm_t: float = -math.inf
        self._cooldown_until: float = -math.inf
        self.new: list[FireCandidate] = []
        self.resolved: list[FireCandidate] = []

    @property
    def active(self) -> FireCandidate | None:
        return self._candidate

    def observe(self, t: float, score: FireScore) -> None:
        """One scored frame. New and resolved candidates are collected in
        `new` / `resolved`; the caller drains them after each observation."""
        if self._obs and t - self._obs[-1][0] > self.cfg.max_gap_s:
            self._obs.clear()          # a gap in the video: do not stitch the two sides together
        alarm = score.alarm
        self._obs.append((t, alarm, score))
        if alarm:
            self._last_alarm_t = t
        c = self._candidate
        if c is not None:
            if alarm:
                self._update(c, score)
            elif t - self._last_alarm_t >= self.cfg.clear_s:
                c.status, c.resolved_t = "RESOLVED", t
                self.resolved.append(c)
                self._candidate = None
                self._cooldown_until = t + self.cfg.cooldown_s
            return
        hits = [s for _, a, s in self._obs if a]
        if len(hits) >= self.cfg.raise_hits and t >= self._cooldown_until:
            first_t = next(tt for tt, a, _ in self._obs if a)
            c = FireCandidate(
                candidate_id=f"fire-{self.camera_id}-{uuid.uuid4().hex[:8]}",
                camera_id=self.camera_id, kind="", score=0.0, first_t=first_t,
                raised_t=t, evidence={"hits": len(hits), "window": len(self._obs)})
            for s in hits:
                self._update(c, s)
            self._candidate = c
            self.new.append(c)

    @staticmethod
    def _update(c: FireCandidate, s: FireScore) -> None:
        fire, smoke = s.fire_alarm, s.smoke_alarm
        if fire:
            c.kinds.add("fire")
        if smoke:
            c.kinds.add("smoke")
        c.kind = "+".join(k for k in ("fire", "smoke") if k in c.kinds)
        top = max(s.p_fire if fire else 0.0, s.p_smoke if smoke else 0.0)
        if top >= c.score:
            c.score = top
            w, h = s.frame_wh
            box = s.box_fire if (fire and (not smoke or s.p_fire >= s.p_smoke)) else s.box_smoke
            c.evidence.update({
                "p_fire": round(s.p_fire, 4), "p_smoke": round(s.p_smoke, 4),
                "thresholds": list(s.thresholds),
                "box_norm": None if box is None or not w or not h else [
                    round(box[0] / w, 4), round(box[1] / h, 4),
                    round(box[2] / w, 4), round(box[3] / h, 4)]})

    def drain(self) -> tuple[list[FireCandidate], list[FireCandidate]]:
        new, res = self.new, self.resolved
        self.new, self.resolved = [], []
        return new, res

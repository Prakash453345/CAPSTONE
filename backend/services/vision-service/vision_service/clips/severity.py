"""Severity of a clip finding: a short, explainable rule set, not a model.

There is no labelled severity data to train on, so severity is decided by
rules a reviewer can check against the video, and every step of the decision
is written into `reasons`:

1. **Start from the type.** Fire and accident start at high, a stalled
   vehicle at medium, congestion at low.
2. **Raise it from what the traffic does next**, measured by the vehicle
   tracker in the seconds after the finding starts:
   - *traffic past it stops* (vehicles in view, almost none moving) -> blocked
     for fire, accident and a stalled vehicle: the road is shut;
   - a stalled vehicle with a queue of 5+ stopped vehicles, or one that stays
     for 90 s or more -> high;
   - congestion with 20+ stopped vehicles, or lasting 120 s or more -> medium.
     Congestion is never rated above medium: it is a traffic state, not an
     incident.
3. **Confidence stays separate.** How sure the detector was is reported next
   to severity, never folded into it.

Without the vehicle detector there are no traffic measurements; the severity
is then the type's starting level and the reasons say so.

The numbers (5 vehicles, 90 s, 20 vehicles, 120 s, the 20 s window) are
starting points chosen by hand, not fitted to data -- there is none yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

LEVELS = ("low", "medium", "high", "blocked")

BASE_SEVERITY: dict[str, str] = {
    "fire": "high",
    "accident": "high",
    "vehicle_breakdown": "medium",
    "heavy_congestion": "low",
}

AFTER_WINDOW_S = 20.0          # how long after the start "what traffic does next" looks
STOPPED_FLOW_MIN_VEHICLES = 3.0
STOPPED_FLOW_MAX_MOVING = 0.5  # mean moving vehicles per second at or below this = stopped
STALL_QUEUE = 5
STALL_LONG_S = 90.0
CONGESTION_QUEUE = 20
CONGESTION_LONG_S = 120.0


@dataclass(frozen=True)
class SecondStats:
    """What the vehicle tracker saw during one second of video."""

    t: float
    vehicles: int
    moving: int
    stopped: int


@dataclass(frozen=True)
class Severity:
    level: str
    reasons: tuple[str, ...]


def _raise(level: str, to: str) -> str:
    return to if LEVELS.index(to) > LEVELS.index(level) else level


def assess(
    anomaly_type: str,
    start_s: float,
    end_s: float,
    scene: Sequence[SecondStats] | None,
) -> Severity:
    """Severity of one finding from its type and the traffic around it.
    `scene` is the tracker's per-second stats for the whole clip, or None
    when no vehicle detector ran."""
    base = BASE_SEVERITY.get(anomaly_type, "medium")
    level = base
    reasons = [f"{anomaly_type.replace('_', ' ')}: starts at {base}"]
    if not scene:
        reasons.append("no vehicle detector on this clip, so severity comes from the type alone")
        return Severity(level, tuple(reasons))

    after = [s for s in scene if start_s <= s.t < start_s + AFTER_WINDOW_S]
    duration = max(0.0, end_s - start_s)
    if after:
        mean_vehicles = sum(s.vehicles for s in after) / len(after)
        mean_moving = sum(s.moving for s in after) / len(after)
        queue = max(s.stopped for s in after)
        flow_stopped = (mean_vehicles >= STOPPED_FLOW_MIN_VEHICLES
                        and mean_moving <= STOPPED_FLOW_MAX_MOVING)
    else:
        mean_vehicles = mean_moving = 0.0
        queue = 0
        flow_stopped = False

    if anomaly_type in ("fire", "accident", "vehicle_breakdown") and flow_stopped:
        level = _raise(level, "blocked")
        reasons.append(
            f"traffic past it stopped: {mean_vehicles:.0f} vehicles in view, "
            f"{mean_moving:.1f} moving on average in the next {AFTER_WINDOW_S:.0f} s -> blocked")
    if anomaly_type == "vehicle_breakdown":
        if queue >= STALL_QUEUE:
            level = _raise(level, "high")
            reasons.append(f"{queue} vehicles stopped behind or around it -> high")
        if duration >= STALL_LONG_S:
            level = _raise(level, "high")
            reasons.append(f"stalled for {duration:.0f} s -> high")
    if anomaly_type == "heavy_congestion":
        if queue >= CONGESTION_QUEUE:
            level = _raise(level, "medium")
            reasons.append(f"{queue} vehicles stopped at once -> medium")
        if duration >= CONGESTION_LONG_S:
            level = _raise(level, "medium")
            reasons.append(f"lasted {duration:.0f} s -> medium")
    if level == base:
        if anomaly_type == "heavy_congestion":
            reasons.append(f"at most {queue} stopped at once, {duration:.0f} s long: stays {base}")
        else:
            reasons.append(f"traffic around it kept moving ({mean_moving:.1f} moving per second): "
                           f"stays {base}")
    return Severity(level, tuple(reasons))

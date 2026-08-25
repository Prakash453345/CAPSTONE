"""Queue-spillback tracking [build guide §8.1: "Queue spillback events --
Count of link-full episodes | Directly tests the θ_m term"].

Not wired to anything that *acts* on it yet -- the θ_m blocking term this
metric is meant to validate is M4's CA-MP job (§3.4), which doesn't exist
yet. This is purely observational for M3: a first real number for what
"normal" spillback looks like on the corridor's three tuned baselines,
before M4's blocking-aware optimizer exists to try to reduce it. Bug-fixed
end-to-end verification of M4's own gating behaviour will want exactly
this same counter run before/after, so it goes in now rather than later.

Scope: only the lanes that directly feed the corridor's 7 signal-
controlled junctions (`link_lanes.link_to_lane_map()`'s own lane set,
flattened across every junction) -- the lanes where a signal-caused queue
actually forms and could spill back into the intersection behind it. Not
every lane in the network; most mid-block lanes aren't queue-forming in
the same load-bearing sense.

"Full" is TraCI's own `getLastStepOccupancy` (percentage of the lane's
length physically covered by vehicles, already accounting for vehicle
length + minGap) at or above `occupancy_threshold` -- a lane at ~90%+
occupancy is bumper-to-bumper for practical purposes. An "episode" is a
*rising edge*: the transition from below-threshold to at-or-above-
threshold. A lane stuck full for 60 consecutive seconds counts as one
episode, matching the metric's own name ("episodes", not "seconds full")
-- counting every tick separately would conflate a single long jam with
sixty short ones.
"""

from __future__ import annotations

from collections.abc import Iterable

import traci

_DEFAULT_OCCUPANCY_THRESHOLD = 0.9


class SpillbackTracker:
    """One instance per scenario run (not per junction) -- the metric is a
    whole-corridor count, matching how the gate table reports it."""

    def __init__(
        self,
        lane_ids: Iterable[str],
        *,
        occupancy_threshold: float = _DEFAULT_OCCUPANCY_THRESHOLD,
    ):
        self._lane_ids = list(lane_ids)
        self._threshold = occupancy_threshold
        self._currently_full: set[str] = set()
        self.episode_count = 0

    def sample(self) -> None:
        """Poll every tracked lane once via live TraCI state. No sim-time
        parameter needed (unlike `ActuationDetector`): spillback has no
        gap-timeout memory to thread through time, only a level-crossing
        to detect on each lane independently."""
        for lane_id in self._lane_ids:
            occupancy = traci.lane.getLastStepOccupancy(lane_id) / 100.0
            is_full = occupancy >= self._threshold
            was_full = lane_id in self._currently_full
            if is_full and not was_full:
                self.episode_count += 1
                self._currently_full.add(lane_id)
            elif not is_full and was_full:
                self._currently_full.discard(lane_id)

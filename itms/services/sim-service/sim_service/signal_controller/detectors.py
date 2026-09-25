"""A stop-line presence detector, emulated over live TraCI lane queries --
what a real semi-actuated cabinet gets from an inductive loop at each
approach, which `JunctionContext.has_demand`/`wait_times_s` need populated
from *something* real before `semi_actuated.propose` can be driven against
the actual corridor rather than only synthetic Hypothesis configs.

Modeled on a standard loop-detector actuated controller, not invented from
scratch: a lane counts as "calling" the instant a vehicle occupies it, and
keeps calling for `gap_timeout_s` after the last vehicle was seen -- the
same "extension gap" logic that keeps a real actuated green alive between
individual vehicle arrivals rather than gapping out the instant the lane
is momentarily clear. `wait_times_s` reported alongside is time-since-the-
call-first-started, which is a reasonable proxy for "how long has this
movement been asking to be served" -- not a literal per-vehicle stopped-
delay measurement (this class has no notion of individual vehicles, only
lane occupancy), a real approximation stated rather than hidden.

That wait clock has one requirement easy to get wrong, and an earlier
version of this class got it wrong: it must reset when the movement is
actually served (given a green), not only when its lane happens to clear
of vehicles. A heavily-trafficked through movement can be occupied nearly
continuously even *while* it has a green -- more cars keep arriving as
others clear -- so a wait clock keyed purely to "lane occupied" never
resets on such a movement and grows without bound, eventually reporting a
false I5 starvation violation for a movement that is in fact being served
regularly. `sample`'s `served_movements` parameter exists for exactly
this: the caller (`control/runner.py`, which already knows which phase is
currently live) tells this detector which links just got served, and
their wait clocks reset regardless of what the lane occupancy sensor says.
`has_demand`'s own gap-timeout clock is unaffected by this -- occupancy is
still occupancy, whether or not the movement is currently green.

Deliberately stateful (unlike every strategy module, which stays a pure
function of an already-built `JunctionContext`) because a gap timeout is
inherently a memory of "when did I last see something" -- that memory has
to live somewhere between ticks, and it does not belong inside
`JunctionContext` itself (which is a snapshot, not a place to accumulate
detector history) or inside a strategy (which must stay pure per the
safety kernel's whole reason for existing -- see `interlocks.py`'s
docstring). It belongs at the same layer as `TraCICabinet`: real,
stateful, I/O-touching infrastructure the runner assembles a
`JunctionContext` from every tick.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import traci


class ActuationDetector:
    """One instance per signal-controlled junction. `link_lanes` is that
    junction's `link_lanes.link_to_lane_map()[tls_id]` -- `{"L{i}": lane_id}`."""

    def __init__(self, link_lanes: Mapping[str, str], *, gap_timeout_s: float = 3.0):
        self._link_lanes = link_lanes
        self._gap_timeout_s = gap_timeout_s
        self._last_seen_s: dict[str, float] = {}
        self._call_started_s: dict[str, float] = {}

    def sample(
        self, sim_time_s: float, served_movements: frozenset[str] = frozenset()
    ) -> tuple[dict[str, bool], dict[str, float]]:
        """Poll every link's lane once, at the current sim time.
        `served_movements` -- the link ids that were actually green up to
        this instant (`cfg.phases[ctx.current_phase_id].green_movements`,
        the caller's job to supply, see module docstring) -- resets those
        links' wait clocks regardless of lane occupancy. Returns
        `(has_demand, wait_times_s)`, both keyed by link id, ready to drop
        straight into a new `JunctionContext`."""
        has_demand: dict[str, bool] = {}
        wait_times_s: dict[str, float] = {}
        for link_id, lane_id in self._link_lanes.items():
            occupied = traci.lane.getLastStepVehicleNumber(lane_id) > 0
            if occupied:
                self._last_seen_s[link_id] = sim_time_s
                self._call_started_s.setdefault(link_id, sim_time_s)
            if link_id in served_movements:
                self._call_started_s[link_id] = sim_time_s

            last_seen = self._last_seen_s.get(link_id, -math.inf)
            calling = (sim_time_s - last_seen) <= self._gap_timeout_s
            has_demand[link_id] = calling
            if calling:
                wait_times_s[link_id] = sim_time_s - self._call_started_s.get(link_id, sim_time_s)
            else:
                wait_times_s[link_id] = 0.0
                self._call_started_s.pop(link_id, None)
        return has_demand, wait_times_s


class StopBarLoops:
    """Presence over the last `zone_m` of each approach lane -- a stop-bar
    loop, emulated over TraCI the same way `ActuationDetector` emulates a
    whole-lane call. It exists for M8's camera cross-check
    (`itms_domain.camera.BlindCameraCheck`), which needs a zone the camera
    can also see: `ActuationDetector`'s zone is the whole approach, up to
    600 m, most of it out of any camera's view."""

    def __init__(self, link_lanes: Mapping[str, str], *, zone_m: float = 20.0):
        self._link_lanes = link_lanes
        self._zone_m = zone_m
        self._length: dict[str, float] = {}

    def sample(self) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for link_id, lane_id in self._link_lanes.items():
            length = self._length.get(lane_id)
            if length is None:
                length = self._length[lane_id] = float(traci.lane.getLength(lane_id))
            out[link_id] = any(traci.vehicle.getLanePosition(v) >= length - self._zone_m
                               for v in traci.lane.getLastStepVehicleIDs(lane_id))
        return out

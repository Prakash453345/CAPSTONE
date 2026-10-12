"""Measures what actually happened, so `control/online_calibration.py`
has a residual to learn from.

The split follows this package's existing convention exactly: anything
that touches TraCI lives here beside `QueueStateSampler` and
`ActuationDetector`, and the thing that reasons about the numbers stays a
pure module under `control/`. That is what keeps the learner unit-testable
without a simulator.

**How a crossing is detected, and why not by counting.** SUMO has no
stop-line detector unless one is placed in the network, and adding
inductive loops to the corridor's `.net.xml` would change the artefact
every prior milestone measured against. Instead this tracks vehicle
*identity*: the set of vehicle ids on a movement's approach lane is
sampled each tick, and a vehicle present last tick and absent this tick
has left that lane. During green, leaving the approach lane means
crossing the stop line.

Two ways that inference can be wrong, both handled rather than assumed
away:

- **Teleports.** SUMO teleports a vehicle that has waited too long
  (`--time-to-teleport 300` in this project's runs, and the corridor's
  logs show it happening at heavy demand). A teleported vehicle vanishes
  from the lane without crossing, and counting it as discharge would
  inflate the measured capacity of exactly the movements that are
  performing worst. `traci.simulation.getStartingTeleportIDList()` names
  them on the step they teleport, and they are excluded.
- **Lane changes.** A vehicle can leave the approach lane sideways rather
  than forwards. Excluded by requiring it to have been within
  `_STOPLINE_ZONE_M` of the stop line on its last observed tick -- a
  vehicle that close is committed to the crossing, and a lane change from
  there is not a manoeuvre SUMO's model performs.

**Effective green, not green -- and the same window on both sides.** The
discharge rate that matters is measured over the interval a queue
actually discharges at capacity, which begins after the start-up wave
rather than at the green onset. So the first `startup_lost_s` of every
green is excluded from the denominator *and* the crossings during it are
excluded from the numerator.

The first version of this file excluded it from the denominator only,
which is a systematic overestimate of saturation flow by
`startup_lost / (green - startup)` -- measured against a synthetic
constant-rate queue at +11.8% for a 20s green and **+40% for an 8s
green**, worst exactly where greens are shortest. The docstring claimed
the `measure_saturation_flow.py` convention ("discards its first
crossings") while the code applied it to one side of the ratio only.
Fixed, and `tests/signal_controller/test_discharge_observer.py` pins the
measured rate against a known ground truth at several green durations so
the two sides cannot drift apart again.

**A known, deliberate omission:** vehicles that clear on yellow are not
counted. The runner does not call `tick()` during a transition (it
`continue`s past the junction while sequencing yellow and all-red), so
those crossings are invisible here. They are absent from the numerator
*and* the denominator, so the resulting *rate* stays unbiased -- roughly
20% of real discharge is simply not sampled. Standard practice would
fold part of the yellow into effective green; doing that would need the
observer driven through transitions, which is a runner change rather
than an observer one. Stated so the omission is a known bound on the
sample rather than an unnoticed bias.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import traci

# How close to the stop line a vehicle must have been on its last
# observed tick for its disappearance to count as a crossing rather than
# a lane change. Roughly two car lengths.
_STOPLINE_ZONE_M = 12.0

_DEFAULT_PCU = 1.0
_HALTING_SPEED_MPS = 0.1


@dataclass
class _GreenWindow:
    """One movement's in-progress green."""

    elapsed_s: float = 0.0
    discharged_pcu: float = 0.0
    prev_ids: dict[str, tuple[float, float]] = field(default_factory=dict)
    """vehicle id -> (distance to stop line, PCU), as of last tick.

    PCU is captured *here*, while the vehicle is still on the lane, rather
    than looked up when it disappears. Looking it up afterwards is the
    obvious implementation and it is wrong twice over: `traci.vehicle.
    getTypeID` on a departed vehicle raises, and the fallback that
    swallowed the exception returned a default of 1.0 PCU -- so every
    vehicle that crossed and then left the network entirely would have
    been measured as a car regardless of what it was. On a corridor whose
    demand is 35% motorcycles at 0.25 PCU, that silently inflates measured
    discharge, and it inflates it most for the movements with the shortest
    downstream links. Caching at observation time removes the lookup
    rather than guarding it."""


@dataclass
class _ArrivalCohort:
    """One tick's `approaching_pcu` prediction, awaiting its outcome."""

    predicted_pcu: float
    pending_ids: dict[str, tuple[float, float]]
    remaining_s: float


class DischargeObserver:
    """One per junction. Driven by the runner alongside the other
    samplers; hands completed observations to an `OnlineCalibration`."""

    def __init__(
        self,
        approach_lanes: Mapping[str, str],
        pcu_by_vtype: Mapping[str, float],
        *,
        startup_lost_s: float = 2.0,
        arrival_horizon_s: float = 8.0,
        lane_cache=None,
    ):
        self._cache = lane_cache
        self._approach_lanes = approach_lanes
        self._pcu = pcu_by_vtype
        self._startup_lost_s = startup_lost_s
        self._arrival_horizon_s = arrival_horizon_s
        self._lane_length: dict[str, float] = {}
        self._green: dict[str, _GreenWindow] = {}
        self._cohorts: dict[str, list[_ArrivalCohort]] = {}
        self._served: frozenset[str] = frozenset()

    def _length(self, lane_id: str) -> float:
        cached = self._lane_length.get(lane_id)
        if cached is None:
            cached = self._lane_length[lane_id] = traci.lane.getLength(lane_id)
        return cached

    def _lane_state(self, lane_id: str) -> dict[str, tuple[float, float]]:
        """`{vehicle id: (distance to stop line, PCU)}` for one lane, now.

        PCU is read here, while the vehicle is definitely present -- see
        `_GreenWindow.prev_ids` for why reading it later is a real
        measurement bug and not merely an exception to catch."""
        if self._cache is not None:
            return {
                veh_id: (distance, pcu)
                for veh_id, (distance, _speed, pcu) in self._cache.state(lane_id).items()
            }
        length = self._length(lane_id)
        out: dict[str, tuple[float, float]] = {}
        for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
            distance = max(0.0, length - traci.vehicle.getLanePosition(veh_id))
            pcu = self._pcu.get(traci.vehicle.getTypeID(veh_id), _DEFAULT_PCU)
            out[veh_id] = (distance, pcu)
        return out

    def tick(
        self,
        served_movements: frozenset[str],
        step_length: float,
        approaching_pcu: Mapping[str, float] | None = None,
    ) -> list[tuple[str, float, float, bool]]:
        """Advance one simulation step.

        Returns completed green observations as
        `(movement, discharged_pcu, effective_green_s, queue_remained)` --
        one entry per movement whose green ended this tick, ready to hand
        to `OnlineCalibration.observe_green`."""
        teleported = set(traci.simulation.getStartingTeleportIDList())
        completed: list[tuple[str, float, float, bool]] = []

        # Movements whose green ended this tick: close their windows first,
        # while `prev_ids` still describes the green that just finished.
        for movement in self._served - served_movements:
            window = self._green.pop(movement, None)
            if window is None:
                continue
            effective = max(0.0, window.elapsed_s - self._startup_lost_s)
            lane = self._approach_lanes.get(movement)
            queue_remained = False
            if lane is not None:
                queue_remained = traci.lane.getLastStepHaltingNumber(lane) > 0
            completed.append((movement, window.discharged_pcu, effective, queue_remained))

        for movement in served_movements:
            lane = self._approach_lanes.get(movement)
            if lane is None:
                continue
            window = self._green.get(movement)
            if window is None:
                # First tick of this green: establish a baseline to diff
                # against. No departure is detectable yet -- but the second
                # still elapsed, so `elapsed_s` must advance. Leaving it at
                # zero here was the other half of the ratio bug: it shrank
                # the denominator by one tick without shrinking the
                # numerator.
                window = self._green[movement] = _GreenWindow(prev_ids=self._lane_state(lane))
                window.elapsed_s = step_length
                continue
            current = self._lane_state(lane)
            # Departures seen now happened over the interval ending at
            # `elapsed_s`. Count them only once that interval lies past the
            # start-up wave, which is the same cut the denominator makes.
            if window.elapsed_s >= self._startup_lost_s:
                for veh_id, (distance, pcu) in window.prev_ids.items():
                    if veh_id in current or veh_id in teleported:
                        continue
                    if distance <= _STOPLINE_ZONE_M:
                        window.discharged_pcu += pcu
            window.prev_ids = current
            window.elapsed_s += step_length

        self._served = frozenset(served_movements)
        if approaching_pcu is not None:
            self._track_arrivals(approaching_pcu, step_length)
        return completed

    # ---- arrival cohorts ------------------------------------------------

    def _track_arrivals(self, approaching_pcu: Mapping[str, float], step_length: float) -> None:
        """Open one cohort per movement per tick and age the open ones.

        A cohort is the specific set of vehicle *ids* counted as
        approaching at that instant, not just the total -- so the check at
        expiry is "did these particular vehicles arrive", which a running
        total could not answer."""
        for movement, predicted in approaching_pcu.items():
            lane = self._approach_lanes.get(movement)
            if lane is None or predicted <= 0.0:
                continue
            if self._cache is not None:
                pending = {
                    veh_id: (distance, pcu)
                    for veh_id, (distance, speed, pcu) in self._cache.state(lane).items()
                    if speed >= _HALTING_SPEED_MPS
                }
            else:
                pending = {
                    veh_id: state
                    for veh_id, state in self._lane_state(lane).items()
                    if traci.vehicle.getSpeed(veh_id) >= _HALTING_SPEED_MPS
                }
            if pending:
                self._cohorts.setdefault(movement, []).append(
                    _ArrivalCohort(predicted, pending, self._arrival_horizon_s)
                )

        for cohorts in self._cohorts.values():
            for cohort in cohorts:
                cohort.remaining_s -= step_length

    def expired_cohorts(self) -> list[tuple[str, float, float]]:
        """Cohorts whose horizon has elapsed, as
        `(movement, predicted_pcu, arrived_pcu)`.

        "Arrived" means the vehicle either left the approach lane (it
        crossed) or is now within the stop-line zone -- both count as
        having reached the junction within the horizon, which is what
        `approaching_pcu` claimed. A vehicle still mid-lane and still
        moving did not arrive in time and is what makes the ratio less
        than one."""
        out: list[tuple[str, float, float]] = []
        for movement, cohorts in self._cohorts.items():
            lane = self._approach_lanes.get(movement)
            if lane is None:
                continue
            still_open: list[_ArrivalCohort] = []
            for cohort in cohorts:
                if cohort.remaining_s > 0.0:
                    still_open.append(cohort)
                    continue
                current = self._lane_state(lane)
                arrived = 0.0
                for veh_id, (_, pcu) in cohort.pending_ids.items():
                    still_here = current.get(veh_id)
                    if still_here is None or still_here[0] <= _STOPLINE_ZONE_M:
                        arrived += pcu
                out.append((movement, cohort.predicted_pcu, arrived))
            self._cohorts[movement] = still_open
        return out

"""One TraCI read per lane per tick, shared by every sampler.

**Why this exists.** Profiling a single medium-demand run
(`cProfile`, 2387 steps) found 2,319,510 TraCI round-trips -- **972 per
simulation step** -- and 234 of the run's 260 seconds spent inside
`traci.domain._getUniversal`. The controller's own arithmetic did not
appear until far down the profile. This is an I/O-bound program that
looks like a CPU-bound one.

Two specific wastes accounted for most of it:

- **`getTypeID` was called 444,510 times** for a value that cannot
  change. A vehicle's type is fixed for its whole life; asking SUMO for
  it once per vehicle per lane per tick is a round-trip to learn
  something already known.
- **The same lanes were read twice per tick.** `QueueStateSampler` and
  `DischargeObserver` each independently called
  `getLastStepVehicleIDs` + `getLanePosition` + `getSpeed` over
  overlapping lane sets, because each was written to be self-contained.
  Self-contained is the right instinct for correctness and the wrong one
  for a protocol where every attribute is a network hop.

`LaneCache` fixes both without changing what anything measures: one read
per lane per tick, memoized by tick, plus a permanent per-vehicle type
cache. Callers ask for the same things and get the same answers.

**Subscriptions were tried here and deliberately backed out.** The
obvious next step is a TraCI *context subscription* per lane -- SUMO
pushes every vehicle's position, speed and type after each step, and one
`getAllContextSubscriptionResults()` call replaces all per-lane polling.
Implemented, it measured **14.3 ms/step against this cache's 23.4**, a
further 1.43x.

It is wrong, and quietly so. `subscribeContext(lane, ..., dist=0.0)` is a
*geometric* query against the lane's shape, not the membership query
`getLastStepVehicleIDs` answers. Compared directly over 16,000
lane-ticks on this corridor:

    lane-ticks whose vehicle set differed : 2,527  (15.8%)
    vehicles the subscription MISSED      : 3,588
    vehicles the subscription added       : 0

A purely one-sided undercount -- a vehicle partly onto the lane, or
straddling its boundary, is simply absent. Queues would read low on
roughly one lane-observation in six, silently, in a controller whose
pressure function is a queue difference and whose learning layer is a
discharge measurement. 1.43x is not worth that in this system.

Retrievable if wanted: subscribe to the lane-level
`LAST_STEP_VEHICLE_ID_LIST` for authoritative membership and use the
context subscription only for the per-vehicle attributes, intersecting
the two. That is correct but needs the intersection to be a subset in
practice, which is an assumption to verify rather than assert. Left
undone, with the measurement recorded, rather than shipped on the
assumption that a faster number is a better one.
"""

from __future__ import annotations

from collections.abc import Mapping

import traci

_DEFAULT_PCU = 1.0


class LaneCache:
    """Per-tick memoized lane state. One instance per scenario run, shared
    across every junction's samplers.

    `advance(tick)` invalidates the per-tick memo. Callers must not hold a
    returned mapping across ticks -- it is the cache's own dict, handed
    out unowned to avoid a copy per read, and it is replaced rather than
    mutated when the tick advances.
    """

    def __init__(self, pcu_by_vtype: Mapping[str, float]):
        self._pcu_by_vtype = pcu_by_vtype
        self._tick = -1.0
        self._lanes: dict[str, dict[str, tuple[float, float, float]]] = {}
        self._lane_length: dict[str, float] = {}
        self._vtype_pcu: dict[str, float] = {}
        # Instrumentation: proves the cache is doing what it claims, and
        # makes a regression in hit rate visible rather than merely slow.
        self.reads = 0
        self.hits = 0

    def advance(self, tick: float) -> None:
        if tick != self._tick:
            self._tick = tick
            self._lanes.clear()

    def length(self, lane_id: str) -> float:
        cached = self._lane_length.get(lane_id)
        if cached is None:
            cached = self._lane_length[lane_id] = traci.lane.getLength(lane_id)
        return cached

    def _pcu_of(self, veh_id: str) -> float:
        """Vehicle type is immutable, so this is cached for the life of the
        run rather than per tick. Vehicle ids are not reused within a SUMO
        run, so the dict grows with total vehicles seen -- a few thousand
        entries over a full scenario, against the 444,510 round-trips it
        removes."""
        cached = self._vtype_pcu.get(veh_id)
        if cached is None:
            cached = self._vtype_pcu[veh_id] = self._pcu_by_vtype.get(
                traci.vehicle.getTypeID(veh_id), _DEFAULT_PCU
            )
        return cached

    def state(self, lane_id: str) -> dict[str, tuple[float, float, float]]:
        """`{vehicle id: (distance to stop line, speed, PCU)}` for one lane,
        this tick. Read from TraCI at most once per lane per tick however
        many samplers ask."""
        self.reads += 1
        cached = self._lanes.get(lane_id)
        if cached is not None:
            self.hits += 1
            return cached
        length = self.length(lane_id)
        out: dict[str, tuple[float, float, float]] = {}
        for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
            out[veh_id] = (
                max(0.0, length - traci.vehicle.getLanePosition(veh_id)),
                traci.vehicle.getSpeed(veh_id),
                self._pcu_of(veh_id),
            )
        self._lanes[lane_id] = out
        return out

    def stats(self) -> dict[str, float]:
        return {
            "reads": self.reads,
            "hits": self.hits,
            "hit_rate": (self.hits / self.reads) if self.reads else 0.0,
            "vehicles_typed": len(self._vtype_pcu),
        }

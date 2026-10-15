"""Live per-movement queue/occupancy sampling for M4's CA-MP strategy
[build guide §3.2.1, §3.4] -- what `JunctionContext.queue_pcu` and
`JunctionContext.receiving_occupancy` need populated from *something* real
before `camp.propose` can be driven against the actual corridor rather
than only synthetic Hypothesis configs, the same gap `ActuationDetector`
closed for `semi_actuated`'s `has_demand`/`wait_times_s`.

Two independent measurements, each keyed by link id (`L{i}`, matching
`link_lanes.link_to_lane_map()`'s labels):

**`queue_pcu[l]`** -- §3.2.1's observed queue term, `Σ_{v in V_l}
pcu(class(v)) · 1[speed(v) < v_stop]`: the PCU-weighted count of vehicles
currently *stopped* on movement `l`'s own approach lane. Only the
observed part -- this build has no arrival-augmentation (`camp.py`'s own
module docstring already scopes `q̂_l = q_l` to M5), so this sampler's
whole job is that one term. "Stopped" uses SUMO's own halting-speed
convention (0.1 m/s -- the same threshold `getLastStepHaltingNumber`
and `waitingTime` accumulation use internally), not an invented cutoff.
`pcu(class)` comes from each vehicle's own vType, read once per run from
the route file's `<param key="pcu">` values (`assign_vtypes.py`) via
`load_vtype_pcu` below -- the same "read it from the file that defines
the vType" pattern `metrics.py.load_vtype_occupancy` already established,
so the two never have to be kept in sync by hand. A vType with no `pcu`
param defaults to 1.0 (car-equivalent), matching that same precedent.

**`receiving_occupancy[l]`** -- `ρ_m`, the fraction of the *downstream*
lane `l` discharges into that's physically covered by vehicles right now
(`traci.lane.getLastStepOccupancy()`, which already returns a fraction in
[0, 1] -- see the unit note below), from
`link_lanes.link_to_receiving_lane_map()`. This is exactly
`SpillbackTracker`'s own occupancy query, pointed at each movement's own
receiving lane instead of a fixed spillback-lane list -- reused rather
than reinvented.

**Unit note (fixed 2026-09-18).** Both occupancy reads used to divide the
TraCI value by 100, on the assumption that it is a percentage. It is not:
`traci.lane.getLastStepOccupancy` returns the occupied *fraction* of the
lane. Measured on this corridor at heavy demand, the raw value peaks at
0.625 on a 599 m lane holding 81 vehicles (~0.62 of its length, so the raw
number is the fraction, not a percent). The extra division capped every
`receiving_occupancy` at ~0.0067, which left `acamp.gate` >= 0.99992 on every
tick of every run -- disabling A-CA-MP's spillback discount entirely
(ablating the gate reproduced the shipped results bit-for-bit) and
`corridor/engine.py`'s `rho_couple` test with it.

**A road SUMO splits into several edges (added 2026-09-29).** A turn bay,
a change in lane count or, in an OpenStreetMap import, any change of tag
ends one edge and starts another, and the signal's approach lane is then
only the last stretch -- 4 m on a generated grid with turn bays. Measured
on that lane alone, a queue of forty vehicles reads as one. `upstream` and
`downstream` (`itms_domain.lane_chains`) name the lanes that continue
an approach or receiving lane through nodes where nothing but the edge
changes, each with its share of the lane's traffic and its distance
from the stop line. With them the sampler measures the road rather than
the edge: halted vehicles on the chain count toward the queue (share-
weighted), moving ones toward `approaching_pcu` by their distance to the
stop line, and receiving occupancy is length-weighted over the chain --
what a single unsplit lane of the same length would have read. Without
them (the default) nothing changes.

Unlike `ActuationDetector` (a gap-timeout clock) or `SpillbackTracker` (a
rising-edge counter), neither measurement here needs memory across ticks
-- both are pure live snapshots. `sample()` still takes no arguments
beyond `self` and is still a method on a per-junction instance (not a
bare function), for the same reason `SpillbackTracker.sample()` isn't
one: this is I/O-touching infrastructure the runner assembles, living at
the same layer as every other detector, not inside a pure strategy.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import traci

# SUMO's own internal convention for "this vehicle counts as halted" --
# matches what `getLastStepHaltingNumber`/waiting-time accumulation use,
# not a cutoff invented for this sampler.
_HALTING_SPEED_MPS = 0.1

# `itms_domain.lane_chains`' entries: (lane id, share, offset in metres)
Chain = Sequence[tuple[str, float, float]]

# Fallback PCU for a vType with no `pcu` param -- car-equivalent, the same
# default `load_vtype_occupancy` uses for a missing `occupancy` param.
_DEFAULT_PCU = 1.0

# Head-of-line blocking: the front vehicle counts as blocked when the tail of
# a vehicle stopped in the junction ahead of it is closer than this.
_BLOCK_GAP_M = 3.0

# How far ahead the arrival test looks, in seconds. Sized to one clearance
# interval plus a short green: a vehicle further out than this cannot be
# served by the decision currently being made, so counting it would raise
# a phase's claim on green for traffic that will still be inbound when
# that green ends. Tier-1 (tunable, and in fact tuned -- `tuning.py`
# treats it as a learnable parameter), not a Tier-0 safety constant.
_ARRIVAL_HORIZON_S = 8.0


@dataclass(frozen=True)
class QueueSample:
    """One tick's complete per-movement state estimate, keyed by link id
    throughout. A record rather than a tuple because the four fields are
    all `dict[str, float]` and positional unpacking of four same-typed
    dicts is a mis-destructuring waiting to happen. Field names match
    `JunctionContext`'s own exactly, so the runner's construction of a
    context from one of these is a rename-free copy."""

    queue_pcu: dict[str, float] = field(default_factory=dict)
    receiving_occupancy: dict[str, float] = field(default_factory=dict)
    receiving_queue_pcu: dict[str, float] = field(default_factory=dict)
    approaching_pcu: dict[str, float] = field(default_factory=dict)
    blocked_by: dict[str, str] = field(default_factory=dict)
    yield_waiting_pcu: dict[str, float] = field(default_factory=dict)


def load_vtype_pcu(route_path: str | Path) -> dict[str, float]:
    """Read `{vType id: pcu}` from a route file's own `<vType>`
    definitions (see `assign_vtypes.py`). Mirrors
    `metrics.py.load_vtype_occupancy` field-for-field except for which
    `<param>` key it reads -- occupancy (people/vehicle) and PCU (roadway-
    space/vehicle) are different physical quantities that happen to be
    tabulated from the same per-class source."""
    root = ET.parse(route_path).getroot()
    pcu: dict[str, float] = {}
    for vtype in root.findall("vType"):
        vtype_id = vtype.get("id")
        if vtype_id is None:
            continue
        param = vtype.find("param[@key='pcu']")
        pcu[vtype_id] = (
            float(param.get("value", str(_DEFAULT_PCU))) if param is not None else _DEFAULT_PCU
        )
    return pcu


class QueueStateSampler:
    """One instance per signal-controlled junction. `approach_lanes` is
    that junction's `link_lanes.link_to_lane_map()[tls_id]`;
    `receiving_lanes` is the same junction's
    `link_lanes.link_to_receiving_lane_map()[tls_id]` -- both
    `{"L{i}": lane_id}`, same convention `ActuationDetector` uses.
    `pcu_by_vtype` is `load_vtype_pcu(route_path)`'s output."""

    def __init__(
        self,
        approach_lanes: Mapping[str, str],
        receiving_lanes: Mapping[str, str],
        pcu_by_vtype: Mapping[str, float],
        *,
        halting_speed_mps: float = _HALTING_SPEED_MPS,
        arrival_horizon_s: float = _ARRIVAL_HORIZON_S,
        lane_cache=None,
        upstream: Mapping[str, Chain] | None = None,
        downstream: Mapping[str, Chain] | None = None,
        internal_links: Mapping[str, str] | None = None,
        vias: Mapping[str, list[tuple[str, float]]] | None = None,
        yield_lanes: Mapping[str, tuple[str, ...]] | None = None,
    ):
        self._approach_lanes = approach_lanes
        self._yield_lanes = yield_lanes or {}
        self._vias = vias or {}
        """`itms_domain.lane_chains.vias_from_sumo_net`: the internal lanes
        inside an approach's chain. Vehicles halted on them count toward the
        queue (the first vehicle of a queue can stand there)."""
        self._upstream = upstream or {}
        self._downstream = downstream or {}
        # {junction-internal lane: "L{i}"} (`strategies.hol.internal_links`);
        # when given, `sample_extended` also reports head-of-line blocking
        self._internal_links = internal_links
        self._receiving_lanes = receiving_lanes
        self._pcu_by_vtype = pcu_by_vtype
        self._halting_speed_mps = halting_speed_mps
        self._arrival_horizon_s = arrival_horizon_s
        # Optional so every existing caller and test keeps working
        # unchanged; when present, lane reads are shared with every other
        # sampler on the same tick instead of repeated. See
        # `lane_cache.LaneCache` for the profile that motivated it.
        self._cache = lane_cache
        # Lane geometry is fixed for the whole run -- queried once on first
        # use rather than once per tick per lane. `traci.lane.getLength` is
        # a network property, not live state, so caching it cannot go stale
        # the way a queue reading would.
        self._lane_length_m: dict[str, float] = {}
        self._box: dict[str, list[tuple[str, float, str]]] | None = None

    def _length_of(self, lane_id: str) -> float:
        cached = self._lane_length_m.get(lane_id)
        if cached is None:
            cached = traci.lane.getLength(lane_id)
            self._lane_length_m[lane_id] = cached
        return cached

    def _halting_pcu(self, lane_id: str) -> float:
        if self._cache is not None:
            return sum(
                pcu
                for _, speed, pcu in self._cache.state(lane_id).values()
                if speed < self._halting_speed_mps
            )
        total = 0.0
        for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
            if traci.vehicle.getSpeed(veh_id) < self._halting_speed_mps:
                vtype_id = traci.vehicle.getTypeID(veh_id)
                total += self._pcu_by_vtype.get(vtype_id, _DEFAULT_PCU)
        return total

    def _queue(self, lane_id: str, chains: Mapping[str, Chain]) -> float:
        """Halted PCU on `lane_id` and on the lanes that continue it
        (share-weighted)."""
        total = self._halting_pcu(lane_id)
        chain = chains.get(lane_id)
        if chain:
            total += sum(share * self._halting_pcu(x) for x, share, _ in chain)
        if chains is self._upstream:
            total += sum(share * self._halting_pcu(x) for x, share in self._vias.get(lane_id, ()))
        return total

    def _approaching(self, lane_id: str) -> float:
        total = self._approaching_pcu(lane_id)
        for x, share, offset_m in self._upstream.get(lane_id, ()):
            total += share * self._approaching_pcu(x, offset_m)
        return total

    def _occupancy(self, lane_id: str) -> float:
        """Receiving occupancy; over a chain, length-weighted -- what one lane
        the chain's length would read."""
        occ = traci.lane.getLastStepOccupancy(lane_id)
        chain = self._downstream.get(lane_id)
        if not chain:
            return occ
        length = self._length_of(lane_id)
        covered, total = occ * length, length
        for x, share, _ in chain:
            lx = share * self._length_of(x)
            covered += lx * traci.lane.getLastStepOccupancy(x)
            total += lx
        return covered / total if total > 0 else occ

    def _approaching_pcu(self, lane_id: str, offset_m: float = 0.0) -> float:
        """PCU-weighted count of vehicles still *moving* on `lane_id` whose
        time-to-stopline is inside `arrival_horizon_s`.

        Deliberately a time-to-arrival test, not Advanced-MP's own fixed
        "effective range" `L = v_max · t_duration` [Zhang et al., ICML
        2022 §4.2] which counts every running vehicle inside a fixed
        *distance*. Both answer "who can actually get here before the
        decision I'm making now expires", but a fixed distance answers it
        correctly only when every vehicle inside it travels at `v_max`.
        This corridor's demand is explicitly heterogeneous
        (`assign_vtypes.py`'s 35/40/20/5 motorcycle/car/auto/bus mix, each
        with its own `maxSpeed`), and its approaches are frequently
        partly-queued, so a fixed radius would count a bus crawling at
        2 m/s behind a queue as equivalent to a motorcycle at 14 m/s in
        clear air -- the slow one cannot arrive in time and should not
        raise this phase's claim on green. Dividing by each vehicle's own
        live speed prices that difference directly, using data already in
        the same TraCI call the queue loop makes.

        Vehicles below the halting threshold are excluded outright rather
        than given a large time-to-arrival: they are, by this module's own
        definition, already counted in `queue_pcu`, and counting them in
        both would double-weight a stopped vehicle in any downstream
        consumer that adds the two (which is exactly what an arrival-
        augmented `q̂_l = q_l + ...` does). The halting threshold is thus
        the single partition between the two measurements, not two
        independently-chosen cutoffs that could overlap or leave a gap."""
        total = 0.0
        if self._cache is not None:
            for distance_m, speed, pcu in self._cache.state(lane_id).values():
                if speed < self._halting_speed_mps:
                    continue  # already counted as queue -- see docstring
                if (distance_m + offset_m) / speed <= self._arrival_horizon_s:
                    total += pcu
            return total
        length_m = self._length_of(lane_id)
        for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
            speed = traci.vehicle.getSpeed(veh_id)
            if speed < self._halting_speed_mps:
                continue  # already counted as queue -- see docstring
            distance_m = max(0.0, length_m - traci.vehicle.getLanePosition(veh_id))
            if (distance_m + offset_m) / speed <= self._arrival_horizon_s:
                vtype_id = traci.vehicle.getTypeID(veh_id)
                total += self._pcu_by_vtype.get(vtype_id, _DEFAULT_PCU)
        return total

    def _box_lanes(self) -> dict[str, list[tuple[str, float, str]]]:
        """`{approach lane: [(internal lane, metres from the stop line to its
        start, its link)]}`: for every link leaving the lane, its lane
        through the box and -- where the link has a waiting position inside
        the box -- the lane that continues it. Network geometry, read once."""
        if self._box is None:
            links = self._internal_links or {}
            box: dict[str, list[tuple[str, float, str]]] = {}
            for lane_id in set(self._approach_lanes.values()):
                found: dict[str, tuple[float, str]] = {}
                for link in traci.lane.getLinks(lane_id):
                    via, offset_m = link[4], 0.0
                    while via and via in links and via not in found:
                        found[via] = (offset_m, links[via])
                        offset_m += self._length_of(via)
                        onward = traci.lane.getLinks(via)
                        via = onward[0][4] if onward else ""
                box[lane_id] = [(il, off, lk) for il, (off, lk) in found.items()]
            self._box = box
        return self._box

    def _blocked_by(self) -> dict[str, str]:
        """`{movement: blocking vehicle's movement}` -- see
        `JunctionContext.blocked_by`. A lane is blocked when its front
        vehicle is stopped and a vehicle that left this lane is stopped
        inside the junction with its tail within `_BLOCK_GAP_M` of that
        front vehicle: a turner waiting in the box for a gap. What a camera
        over the junction sees, not what a stop-bar loop does.

        The first version asked SUMO for the front vehicle's leader
        (`traci.vehicle.getLeader`). That is the vehicle ahead *on the front
        vehicle's own path*, so a through vehicle held up by a turner whose
        tail had cleared the stop line -- on the turn's own internal lane,
        0.2 m to the side -- had no leader and its lane was not reported.
        Motorcycles and auto-rickshaws are shorter than the 4 m to the
        waiting position, so most of the traffic blocked that way. It showed
        when the cameras' reading was scored against this one: 233 of 536
        "false" camera detections in 900 s were such lanes."""
        if not self._internal_links:
            return {}
        out: dict[str, str] = {}
        by_lane: dict[str, list[str]] = {}
        for link_id, lane_id in self._approach_lanes.items():
            by_lane.setdefault(lane_id, []).append(link_id)
        box = self._box_lanes()
        for lane_id, movements in by_lane.items():
            front, best = None, None
            if self._cache is not None:
                for veh_id, (distance_m, speed, _) in self._cache.state(lane_id).items():
                    if best is None or distance_m < best:
                        front, best, front_speed = veh_id, distance_m, speed
            else:
                length_m = self._length_of(lane_id)
                for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
                    distance_m = length_m - traci.vehicle.getLanePosition(veh_id)
                    if best is None or distance_m < best:
                        front, best = veh_id, distance_m
                        front_speed = traci.vehicle.getSpeed(veh_id)
            if front is None or front_speed >= self._halting_speed_mps:
                continue
            nearest: tuple[float, str] | None = None   # (tail, metres past the stop line; link)
            for internal_lane, offset_m, link in box.get(lane_id, ()):
                for veh_id in traci.lane.getLastStepVehicleIDs(internal_lane):
                    if traci.vehicle.getSpeed(veh_id) >= self._halting_speed_mps:
                        continue
                    tail_m = (offset_m + traci.vehicle.getLanePosition(veh_id)
                              - traci.vehicle.getLength(veh_id))
                    if nearest is None or tail_m < nearest[0]:
                        nearest = (tail_m, link)
            if nearest is None or best + nearest[0] > _BLOCK_GAP_M:
                continue
            for m in movements:
                out[m] = nearest[1]
        return out

    def sample(self) -> tuple[dict[str, float], dict[str, float]]:
        """Poll every tracked lane once via live TraCI state. Returns
        `(queue_pcu, receiving_occupancy)`, both keyed by link id, ready
        to drop straight into a new `JunctionContext`. A link present in
        `approach_lanes` but absent from `receiving_lanes` (shouldn't
        happen given both come from the same set of `<connection>`
        elements, but not assumed) is simply left out of
        `receiving_occupancy` -- `camp.py`'s own pressure terms already
        treat a missing entry as ρ=0, the correct reading for "no
        downstream data" here too.

        Kept at its original two-value return shape, unchanged, so every
        existing caller (`runner.py`'s M4 path, `test_queue_state.py`)
        keeps working exactly as before -- `sample_extended` below is the
        superset, not a replacement."""
        queue_pcu = {
            link_id: self._queue(lane_id, self._upstream)
            for link_id, lane_id in self._approach_lanes.items()
        }
        receiving_occupancy = {
            link_id: self._occupancy(lane_id)
            for link_id, lane_id in self._receiving_lanes.items()
        }
        return queue_pcu, receiving_occupancy

    def sample_extended(self) -> QueueSample:
        """Everything `sample()` returns, plus the two measurements M5's
        A-CA-MP needs that M4 had no source for: the downstream lane's own
        stopped queue (`receiving_queue_pcu`) and the inbound-platoon count
        (`approaching_pcu`). Returned as a named record rather than a
        4-tuple because a 4-tuple of same-typed dicts is exactly the shape
        that gets silently mis-destructured at a call site.

        Separate method rather than widening `sample()`'s return: this is
        strictly more TraCI work per tick (one extra pass over every
        approach lane for the arrival test, one extra pass over every
        receiving lane for its queue), and M4's `camp.propose` reads
        neither field, so making its 60-run gate pay that cost to produce
        numbers it then ignores would slow the comparison arm without
        changing it. The runner picks the method by what the strategy
        under test actually consumes."""
        queue_pcu: dict[str, float] = {}
        approaching_pcu: dict[str, float] = {}
        for link_id, lane_id in self._approach_lanes.items():
            queue_pcu[link_id] = self._queue(lane_id, self._upstream)
            approaching_pcu[link_id] = self._approaching(lane_id)

        receiving_occupancy: dict[str, float] = {}
        receiving_queue_pcu: dict[str, float] = {}
        for link_id, lane_id in self._receiving_lanes.items():
            receiving_occupancy[link_id] = self._occupancy(lane_id)
            receiving_queue_pcu[link_id] = self._queue(lane_id, self._downstream)

        return QueueSample(
            queue_pcu=queue_pcu,
            receiving_occupancy=receiving_occupancy,
            receiving_queue_pcu=receiving_queue_pcu,
            approaching_pcu=approaching_pcu,
            blocked_by=self._blocked_by(),
            yield_waiting_pcu={
                link_id: sum(self._halting_pcu(x) for x in lanes)
                for link_id, lanes in self._yield_lanes.items()
            },
        )

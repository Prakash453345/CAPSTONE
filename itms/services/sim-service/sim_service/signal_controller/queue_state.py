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
(`traci.lane.getLastStepOccupancy() / 100`), from
`link_lanes.link_to_receiving_lane_map()`. This is exactly
`SpillbackTracker`'s own occupancy query, pointed at each movement's own
receiving lane instead of a fixed spillback-lane list -- reused rather
than reinvented.

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
from collections.abc import Mapping
from pathlib import Path

import traci

# SUMO's own internal convention for "this vehicle counts as halted" --
# matches what `getLastStepHaltingNumber`/waiting-time accumulation use,
# not a cutoff invented for this sampler.
_HALTING_SPEED_MPS = 0.1

# Fallback PCU for a vType with no `pcu` param -- car-equivalent, the same
# default `load_vtype_occupancy` uses for a missing `occupancy` param.
_DEFAULT_PCU = 1.0


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
    ):
        self._approach_lanes = approach_lanes
        self._receiving_lanes = receiving_lanes
        self._pcu_by_vtype = pcu_by_vtype
        self._halting_speed_mps = halting_speed_mps

    def sample(self) -> tuple[dict[str, float], dict[str, float]]:
        """Poll every tracked lane once via live TraCI state. Returns
        `(queue_pcu, receiving_occupancy)`, both keyed by link id, ready
        to drop straight into a new `JunctionContext`. A link present in
        `approach_lanes` but absent from `receiving_lanes` (shouldn't
        happen given both come from the same set of `<connection>`
        elements, but not assumed) is simply left out of
        `receiving_occupancy` -- `camp.py`'s own pressure terms already
        treat a missing entry as ρ=0, the correct reading for "no
        downstream data" here too."""
        queue_pcu: dict[str, float] = {}
        for link_id, lane_id in self._approach_lanes.items():
            total = 0.0
            for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
                if traci.vehicle.getSpeed(veh_id) < self._halting_speed_mps:
                    vtype_id = traci.vehicle.getTypeID(veh_id)
                    total += self._pcu_by_vtype.get(vtype_id, _DEFAULT_PCU)
            queue_pcu[link_id] = total

        receiving_occupancy: dict[str, float] = {}
        for link_id, lane_id in self._receiving_lanes.items():
            receiving_occupancy[link_id] = traci.lane.getLastStepOccupancy(lane_id) / 100.0

        return queue_pcu, receiving_occupancy

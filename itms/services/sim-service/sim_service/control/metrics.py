"""The M3 metrics collector [build guide §8.1/§8.2] -- turns one completed
SUMO run's `--tripinfo-output` file, plus the corridor demand's own vType
occupancy assumptions (`scenarios/networks/vijayawada/assign_vtypes.py`),
into the per-run scorecard the M3 gate needs: person-delay,
person-throughput, a wait-time *distribution* (not just a mean -- §8.2 is
explicit that the mean alone hides exactly the fairness question this
project cares about), and stops per vehicle.

Three deliberate choices, each because a more "obvious" alternative was
checked and rejected:

- **Person-delay uses SUMO's own `timeLoss` tripinfo attribute**, not a
  hand-derived (route length / edge speed limit) free-flow time computed a
  second time from `net.xml`. `timeLoss` is SUMO's own per-vehicle
  computation of "time lost versus that vehicle's own ideal/free-flow
  speed" -- it already accounts for each vehicle's individual
  `speedFactor` (randomised per vehicle, not just per vType) and every
  edge's real speed limit along its actual route. Re-deriving the same
  number less precisely from geometry would be strictly worse, not more
  rigorous.
- **Occupancy is read from `<vType><param key="occupancy">`** in the same
  route file the run's tripinfo vehicles reference (`vType=` attribute on
  each `<tripinfo>`), not a constant table duplicated here -- see
  `assign_vtypes.py`'s docstring for why, and for the (explicitly
  documented-as-assumed, not measured) mix and occupancy figures
  themselves.
- **Wait-time distribution uses tripinfo's `waitingTime`** (total time a
  vehicle spent below 0.1 m/s over its whole trip) as the per-approach-
  wait proxy the gate's "max-wait" metric asks for. The gate's own wording
  ("max per-approach wait ... report the distribution") is written for a
  live per-movement wait clock; the actuated strategies already maintain
  one internally (`ActuationDetector.wait_times_s`), but Webster and
  fixed-time are demand-blind and never construct one, so a metric built
  from that internal clock would not be comparable across all three
  baselines the gate needs one table for. `waitingTime` is the one wait
  signal every strategy produces identically (it comes from SUMO's own
  vehicle simulation, not from the controller under test), which is what
  makes a *paired* comparison across controllers meaningful -- at the
  cost of being a trip-level aggregate (summed over every signal a
  vehicle passed) rather than a true single-junction approach wait.
  Documented here rather than silently assumed.

**Warm-up, not cool-down:** trips departing in the first `warmup_s`
(default 600s, matching §8.2's "discard the first ~600 s (network
filling)") are excluded from person-delay, wait-time, and stops --
a controller that hasn't reached steady state yet shouldn't count against
or for it. Person-throughput is *not* warm-up-filtered: "persons
completing trips per hour" is naturally a whole-scenario figure (a
50-minute run that includes a 10-minute ramp-up is still a real 50-minute
run), and filtering it would make throughput numbers depend on a choice
(where the window ends) that delay/wait/stops don't need to make. A
cool-down exclusion ("don't count vehicles still in the network at the
end") needs no code here: `--tripinfo-output` only ever records vehicles
that actually arrived, so an in-progress vehicle at the run's end is
already absent from the file by construction.
"""

from __future__ import annotations

import statistics
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TripRecord:
    vehicle_id: str
    vtype: str
    depart_s: float
    duration_s: float
    time_loss_s: float
    waiting_time_s: float
    waiting_count: int


@dataclass(frozen=True)
class WaitTimeDistribution:
    mean_s: float
    p50_s: float
    p95_s: float
    p99_s: float
    max_s: float


@dataclass(frozen=True)
class RunMetrics:
    n_trips_total: int
    n_trips_scored: int
    person_delay_s: float
    person_throughput_per_hour: float
    wait_time_s: WaitTimeDistribution
    stops_per_vehicle: float


def parse_tripinfo(tripinfo_path: str | Path) -> list[TripRecord]:
    """Read a `--tripinfo-output` XML file into `TripRecord`s. Pure I/O --
    every value here is copied straight off SUMO's own attributes, no
    derived math (that's `score_trips`'s job, kept separately testable
    against hand-built records rather than a real SUMO output file)."""
    root = ET.parse(tripinfo_path).getroot()
    records = []
    for trip in root.findall("tripinfo"):
        records.append(
            TripRecord(
                vehicle_id=trip.get("id", ""),
                vtype=trip.get("vType", ""),
                depart_s=float(trip.get("depart", "0")),
                duration_s=float(trip.get("duration", "0")),
                time_loss_s=float(trip.get("timeLoss", "0")),
                waiting_time_s=float(trip.get("waitingTime", "0")),
                waiting_count=int(trip.get("waitingCount", "0")),
            )
        )
    return records


def load_vtype_occupancy(route_path: str | Path) -> dict[str, float]:
    """Read `{vType id: occupancy}` from a route file's own `<vType>`
    definitions (see `assign_vtypes.py`). A vType with no `occupancy`
    param is assumed to carry 1 person -- the same default a plain,
    un-mixed `veh_passenger` fleet implicitly has."""
    root = ET.parse(route_path).getroot()
    occupancy: dict[str, float] = {}
    for vtype in root.findall("vType"):
        vtype_id = vtype.get("id")
        if vtype_id is None:
            continue
        param = vtype.find("param[@key='occupancy']")
        occupancy[vtype_id] = float(param.get("value", "1.0")) if param is not None else 1.0
    return occupancy


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile over an already-sorted sequence -- simple
    and dependency-free (no numpy in this service), and adequate for a
    reporting table rather than a statistical test (§8.2's Wilcoxon
    signed-rank test, when it's built, works from the raw per-seed means,
    not from these percentiles)."""
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(fraction * len(sorted_values)))
    return sorted_values[index]


def score_trips(
    trips: Sequence[TripRecord],
    occupancy_by_vtype: dict[str, float],
    *,
    warmup_s: float = 600.0,
    scenario_duration_s: float = 1800.0,
) -> RunMetrics:
    """Pure aggregation over already-parsed trips -- see module docstring
    for why `timeLoss`/`waitingTime`/warm-up-only-filtering were each
    chosen over the more obvious alternative."""
    scored = [t for t in trips if t.depart_s >= warmup_s]

    person_delay_s = sum(
        occupancy_by_vtype.get(t.vtype, 1.0) * t.time_loss_s for t in scored
    )
    total_persons_completed = sum(occupancy_by_vtype.get(t.vtype, 1.0) for t in trips)
    scenario_duration_hours = scenario_duration_s / 3600.0
    person_throughput_per_hour = (
        total_persons_completed / scenario_duration_hours if scenario_duration_hours > 0 else 0.0
    )

    waits = sorted(t.waiting_time_s for t in scored)
    wait_dist = WaitTimeDistribution(
        mean_s=statistics.fmean(waits) if waits else 0.0,
        p50_s=_percentile(waits, 0.50),
        p95_s=_percentile(waits, 0.95),
        p99_s=_percentile(waits, 0.99),
        max_s=waits[-1] if waits else 0.0,
    )

    stops_per_vehicle = (
        statistics.fmean(t.waiting_count for t in scored) if scored else 0.0
    )

    return RunMetrics(
        n_trips_total=len(trips),
        n_trips_scored=len(scored),
        person_delay_s=person_delay_s,
        person_throughput_per_hour=person_throughput_per_hour,
        wait_time_s=wait_dist,
        stops_per_vehicle=stops_per_vehicle,
    )


def compute_run_metrics(
    tripinfo_path: str | Path,
    route_path: str | Path,
    *,
    warmup_s: float = 600.0,
    scenario_duration_s: float = 1800.0,
) -> RunMetrics:
    """Convenience wrapper: parse both files, then score. Kept thin on
    purpose -- `parse_tripinfo`/`load_vtype_occupancy` (I/O) and
    `score_trips` (pure math) are each unit-tested independently."""
    trips = parse_tripinfo(tripinfo_path)
    occupancy = load_vtype_occupancy(route_path)
    return score_trips(
        trips, occupancy, warmup_s=warmup_s, scenario_duration_s=scenario_duration_s
    )

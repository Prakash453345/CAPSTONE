"""Which crews are near a point, found the way Uber finds nearby drivers.

A call for service has a location and a kind (ambulance, police, fire truck).
The question is "which available crews of that kind are closest", and asking
it by scanning every crew and measuring each one does not scale: the cost
grows with the whole fleet, not with how many crews are actually nearby.

**The method.** The map is divided into hexagonal cells (Uber's H3 grid). Each
crew sits in exactly one cell, so the index is a dict from cell to the crews in
it. To answer a query, take the cell the call is in, look at it and the rings
of cells around it, and stop at the first ring that has produced enough
candidates. Work is bounded by how many cells were visited, not by fleet size.
Hexagons rather than squares because every neighbour of a hexagon is the same
distance from its centre, so a ring is a fair approximation of a circle and
there are no "corner" cells that are further away than the edge ones.

**Why a ring is not the answer.** A hex ring is still straight-line geometry.
Vijayawada's corridor is cut by the Krishna river: a crew 400 m away across it
can be 6 km by road. So the index only *shortlists*; the caller re-ranks the
shortlist by live road travel time (`rank_by_road_time`). That is the same
shape `FacilityIndex.nearest_by_air` and `dispatcher.choose` already use for
hospitals, and for the same reason.

**Stopping rule.** Finding `k` candidates in ring *r* is not enough to be sure
they are the `k` closest: a crew in ring *r+1* can be nearer than one at the far
corner of ring *r*. So after the first ring that yields `k`, one more ring is
searched (`SAFETY_RINGS`). The result is then sorted by true distance and cut
to `k`. Still a heuristic, and stated as one, not a proof.

**What this does not do.** It knows where a crew is and whether it is
available; it does not know whether the crew is about to go off shift, is
refuelling, or has a driver. That is a register's job (see `Crew.available`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import h3

DEFAULT_RESOLUTION = 8
"""H3 resolution. 8 has an edge of about 460 m and a cell area of about
0.74 km^2: a city block cluster. A call in a dense area finds a handful of
crews in its own cell plus the first ring, while the 16-junction corridor
here fits in a few dozen cells. Resolution 9 (~175 m) is the usual choice for
ride-hailing pick-ups; emergency crews are far sparser than taxis, so a
coarser cell avoids searching many empty rings."""

SAFETY_RINGS = 1
"""Extra rings searched after `k` candidates are found; see the module docstring."""

MAX_RINGS = 12
"""Hard stop on the search radius. 12 rings at resolution 8 is roughly 10 km, a
whole city. A call with nobody within that range is a real condition for the
caller to handle (`nearest` returns fewer than `k`, possibly none)."""


@dataclass
class Crew:
    """One responding unit as the dispatcher sees it."""

    crew_id: str
    kind: str
    """`EmergencyKind.name`: "AMBULANCE", "POLICE" or "FIRE_TRUCK"."""
    lat: float
    lon: float
    available: bool = True
    """False while on a call, off shift, or otherwise not to be sent."""
    edge: str | None = None
    """The road edge the crew is on (or based at), when known; routing needs it."""
    label: str = ""


@dataclass(frozen=True)
class Candidate:
    """A crew found near a point, with how far away it is."""

    crew: Crew
    distance_m: float
    """Straight-line distance, the shortlist order."""
    cell: str
    """The H3 cell the crew was in, for audit and for drawing the search."""
    road_time_s: float | None = None
    """Live travel time, once `rank_by_road_time` has priced it."""


RoadTimeFn = Callable[[Crew], float | None]
"""`crew -> seconds to reach the call by road`, or None when unreachable."""


class CrewIndex:
    """Every crew, bucketed by H3 cell, queryable by kind and location."""

    def __init__(self, crews: Iterable[Crew] = (), *, resolution: int = DEFAULT_RESOLUTION) -> None:
        self._res = resolution
        self._crews: dict[str, Crew] = {}
        self._cell_of: dict[str, str] = {}
        self._cells: dict[str, set[str]] = {}
        for crew in crews:
            self.add(crew)

    # ---- membership ---------------------------------------------------

    def __len__(self) -> int:
        return len(self._crews)

    def __contains__(self, crew_id: object) -> bool:
        return crew_id in self._crews

    @property
    def resolution(self) -> int:
        return self._res

    def get(self, crew_id: str) -> Crew | None:
        return self._crews.get(crew_id)

    def all(self) -> list[Crew]:
        return list(self._crews.values())

    def cell_for(self, lat: float, lon: float) -> str:
        return h3.latlng_to_cell(lat, lon, self._res)

    def add(self, crew: Crew) -> None:
        """Register a crew, or replace one with the same id."""
        if crew.crew_id in self._crews:
            self.remove(crew.crew_id)
        cell = self.cell_for(crew.lat, crew.lon)
        self._crews[crew.crew_id] = crew
        self._cell_of[crew.crew_id] = cell
        self._cells.setdefault(cell, set()).add(crew.crew_id)

    def remove(self, crew_id: str) -> None:
        crew = self._crews.pop(crew_id, None)
        if crew is None:
            return
        cell = self._cell_of.pop(crew_id)
        members = self._cells.get(cell)
        if members is not None:
            members.discard(crew_id)
            if not members:
                del self._cells[cell]

    def move(self, crew_id: str, lat: float, lon: float, *, edge: str | None = None) -> None:
        """A position update. Only touches the index when the crew changed cell,
        which is what makes a 1 Hz GPS stream cheap."""
        crew = self._crews.get(crew_id)
        if crew is None:
            raise KeyError(crew_id)
        crew.lat, crew.lon = lat, lon
        if edge is not None:
            crew.edge = edge
        cell = self.cell_for(lat, lon)
        old = self._cell_of[crew_id]
        if cell != old:
            self._cells[old].discard(crew_id)
            if not self._cells[old]:
                del self._cells[old]
            self._cells.setdefault(cell, set()).add(crew_id)
            self._cell_of[crew_id] = cell

    def set_available(self, crew_id: str, available: bool) -> None:
        crew = self._crews.get(crew_id)
        if crew is None:
            raise KeyError(crew_id)
        crew.available = available

    # ---- the query ----------------------------------------------------

    def nearest(
        self,
        lat: float,
        lon: float,
        kind: str,
        k: int = 5,
        *,
        max_rings: int = MAX_RINGS,
    ) -> list[Candidate]:
        """Up to `k` available crews of `kind`, nearest first by straight line.

        Fewer than `k` (or none) means nobody of that kind is free within
        `max_rings`; the caller decides what that means."""
        if k <= 0:
            return []
        origin = self.cell_for(lat, lon)
        found: dict[str, Candidate] = {}
        enough_at: int | None = None
        for ring in range(max_rings + 1):
            for cell in _ring(origin, ring):
                for crew_id in self._cells.get(cell, ()):
                    crew = self._crews[crew_id]
                    if crew.available and crew.kind == kind:
                        found[crew_id] = Candidate(
                            crew, _haversine_m(lat, lon, crew.lat, crew.lon), cell
                        )
            if enough_at is None and len(found) >= k:
                enough_at = ring
            if enough_at is not None and ring >= enough_at + SAFETY_RINGS:
                break
        return sorted(found.values(), key=lambda c: (c.distance_m, c.crew.crew_id))[:k]


def rank_by_road_time(
    candidates: Iterable[Candidate], road_time: RoadTimeFn
) -> list[Candidate]:
    """Re-rank a shortlist by live road travel time, fastest first.

    A crew with no route (None) is dropped. If *no* candidate can be priced,
    the straight-line order is kept rather than returning nothing, because a
    crew that is near by air is a better answer than no crew; the caller can
    see that from `road_time_s` being None."""
    shortlist = list(candidates)
    priced: list[Candidate] = []
    for cand in shortlist:
        seconds = road_time(cand.crew)
        if seconds is not None:
            priced.append(
                Candidate(cand.crew, cand.distance_m, cand.cell, road_time_s=seconds)
            )
    if not priced:
        return shortlist
    return sorted(priced, key=lambda c: (c.road_time_s, c.distance_m, c.crew.crew_id))


def _ring(origin: str, ring: int) -> list[str]:
    """The cells exactly `ring` steps from `origin` (ring 0 is the origin)."""
    if ring == 0:
        return [origin]
    return list(h3.grid_ring(origin, ring))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))

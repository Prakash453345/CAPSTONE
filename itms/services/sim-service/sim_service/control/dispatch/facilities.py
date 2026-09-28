"""The facilities an emergency vehicle can be sent to.

Loaded from `scenarios/networks/vijayawada/facilities.json`, which
`extract_facilities.py` produces from the OSM extract. That file's own
docstring is the authority on what in it is observed and what is
inferred, and the short version belongs here too because every consumer
of this module needs it:

**The facilities and their locations are real. The capability tags are a
model.** Most are keyword-matched from the facility's name -- "Maxivision
Eye Hospital" gets `ophthalmic` because of the word "Eye" -- and a name
says nothing about whether the theatre is staffed tonight or a bed is
free. Treating this as a clinical directory would be wrong. Treating it
as a plausible specialisation of a real facility set, so that
"nearest facility that can treat this" becomes a routing constraint worth
optimising against, is what it is for.

A deployment replaces the JSON with the health authority's register. The
schema is deliberately plain so that swap is a data change and not a code
change.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

GENERAL = "general"
"""The capability an undifferentiated emergency needs. Distinguished from
"no capability recorded": an unlabelled *hospital* is given `general` by
the extractor, an unlabelled *clinic* is given nothing and is therefore
never chosen. See `extract_facilities._capabilities` for why that
asymmetry is the safe direction to err in."""


@dataclass(frozen=True)
class Facility:
    """One hospital or clinic, snapped to the edge an ambulance would
    approach it on."""

    id: str
    name: str
    kind: str
    edge: str
    edge_offset_m: float
    lat: float
    lon: float
    capabilities: frozenset[str]

    def can_treat(self, capability: str) -> bool:
        return capability in self.capabilities


class FacilityIndex:
    """Every known facility, queryable by capability.

    Small enough to hold in memory and scan -- 106 on this corridor --
    so there is no spatial index here. A city-scale register would want
    one; saying so is cheaper than building one that is never exercised."""

    def __init__(self, facilities: Iterable[Facility]) -> None:
        self._facilities = list(facilities)
        self._by_capability: dict[str, list[Facility]] = {}
        for facility in self._facilities:
            for capability in facility.capabilities:
                self._by_capability.setdefault(capability, []).append(facility)

    @classmethod
    def from_json(cls, path: str | Path) -> FacilityIndex:
        raw = json.loads(Path(path).read_text())
        return cls(
            Facility(
                id=entry["id"],
                name=entry["name"],
                kind=entry["kind"],
                edge=entry["edge"],
                edge_offset_m=float(entry["edge_offset_m"]),
                lat=float(entry["lat"]),
                lon=float(entry["lon"]),
                capabilities=frozenset(entry["capabilities"]),
            )
            for entry in raw["facilities"]
        )

    def __len__(self) -> int:
        return len(self._facilities)

    @property
    def all(self) -> list[Facility]:
        return list(self._facilities)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._by_capability)

    def with_capability(self, capability: str) -> list[Facility]:
        """Facilities that can treat `capability`.

        Returns them unordered -- ordering is the dispatcher's job and
        depends on live travel time, which this class deliberately knows
        nothing about."""
        return list(self._by_capability.get(capability, ()))

    def nearest_by_air(
        self, lat: float, lon: float, capability: str, k: int
    ) -> list[Facility]:
        """The `k` capable facilities closest in a straight line.

        A prefilter, not an answer. Routing to every capable facility is
        the correct computation and it is `k` network searches too many
        when `k` is 55; straight-line distance narrows the field cheaply
        because it is a lower bound on road distance, so a facility that
        is far by air cannot be near by road.

        **Where that reasoning breaks, and it breaks here.** The bound is
        one-directional: near by air does *not* imply near by road. A
        facility across a barrier -- and Vijayawada's corridor is cut by
        the Krishna river -- can sit 400 m away and 6 km by road, while
        the genuinely quickest facility sits further out and gets cut
        from the shortlist. `k` is therefore set generously rather than
        tightly, and the dispatcher records how many candidates it
        actually routed so a shortlist that is too small shows up in the
        logs instead of hiding as a slightly worse choice."""
        capable = self.with_capability(capability)
        return sorted(capable, key=lambda f: _haversine_m(lat, lon, f.lat, f.lon))[:k]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle metres. Used only for the shortlist, where the
    difference between this and a projected-plane distance is far below
    the error the shortlist itself introduces."""
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))

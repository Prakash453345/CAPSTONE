"""Dispatch: facility selection and re-routing.

Every test here uses an injected route function rather than a simulator,
which is the point of `RouteFn` being a parameter -- travel times are the
only thing the decision depends on, and stating them directly is both
faster and clearer than arranging traffic that produces them.

The facility-data tests at the end run against the real extract, because
what they check is a property of *that* data: whether the capability
model is coherent enough to route against.
"""

from __future__ import annotations

import itertools
import json
import re

import pytest
from itms_domain.paths import DATA_DIR
from sim_service.control.dispatch import (
    Facility,
    FacilityIndex,
    IncidentRequest,
    capability_coverage,
    choose,
    should_redispatch,
)
from sim_service.control.dispatch.facilities import _haversine_m

_ROOT = DATA_DIR
_FACILITIES = _ROOT / "scenarios" / "networks" / "vijayawada" / "facilities.json"

_MERGE_RADIUS_M = 250.0
"""Mirrors `extract_facilities.MERGE_RADIUS_M`. Restated rather than
imported because that module imports `sumolib` at module scope and this
test needs nothing from SUMO -- the cost of the duplication is that the
two can drift, and the consequence of drift is a test that passes while
the extractor merges on a different radius, which is why the number is
named here rather than inlined."""


def _identity(name: str) -> str:
    """Mirrors `extract_facilities._identity`; see above for why."""
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\b(hospital|hospitals|clinic|centre|center|nursing home)\b", " ", text)
    return " ".join(text.split())


def _facility(fid: str, edge: str, caps: set[str], lat: float = 16.5, lon: float = 80.6):
    return Facility(
        id=fid, name=fid, kind="hospital", edge=edge, edge_offset_m=10.0,
        lat=lat, lon=lon, capabilities=frozenset(caps),
    )


def _index(*facilities) -> FacilityIndex:
    return FacilityIndex(facilities)


def _routes(table: dict[str, tuple[tuple[str, ...], float]]):
    """A `RouteFn` from a `{destination edge: (route, travel time)}` table.
    A destination absent from the table is unreachable."""
    return lambda _from, to: table.get(to)


def _request(capability: str = "general") -> IncidentRequest:
    return IncidentRequest("INC-1", "origin", 16.5, 80.6, capability)


# -- selection ---------------------------------------------------------


def test_chooses_the_capable_facility_with_the_shortest_travel_time():
    index = _index(
        _facility("near-but-wrong", "e1", {"dental"}),
        _facility("far-and-right", "e2", {"general"}),
        _facility("nearest-and-right", "e3", {"general"}),
    )
    route = _routes({"e1": (("a",), 10.0), "e2": (("a", "b"), 300.0), "e3": (("a", "c"), 120.0)})
    decision = choose(_request(), index, route)
    assert decision is not None
    assert decision.facility.id == "nearest-and-right"
    assert decision.travel_time_s == 120.0
    assert decision.considered == 2, "the dental facility is not a candidate at all"


def test_travel_time_beats_distance():
    """The reason dispatch is computed live rather than from a table.
    A facility further away down a clear road beats a nearer one behind
    a jam, and only a router that sees current conditions can tell them
    apart."""
    index = _index(
        _facility("close", "e1", {"general"}, lat=16.5001, lon=80.6001),
        _facility("distant", "e2", {"general"}, lat=16.52, lon=80.62),
    )
    jammed = _routes({"e1": (("a",), 400.0), "e2": (("a", "b"), 90.0)})
    decision = choose(_request(), index, jammed)
    assert decision is not None and decision.facility.id == "distant"


def test_an_unreachable_facility_is_counted_not_crashed_on():
    index = _index(
        _facility("unreachable", "e1", {"general"}),
        _facility("reachable", "e2", {"general"}),
    )
    decision = choose(_request(), index, _routes({"e2": (("a",), 50.0)}))
    assert decision is not None
    assert decision.facility.id == "reachable"
    assert decision.unreachable == 1


def test_no_capable_facility_returns_none_rather_than_falling_back():
    """Falling back to `general` when the required capability is absent
    is a policy decision, and a consequential one -- "we could not reach
    an ophthalmic facility so we sent them to a general one" must be
    owned by a caller, not made silently here."""
    index = _index(_facility("general-only", "e1", {"general"}))
    assert choose(_request("cardiac"), index, _routes({"e1": (("a",), 50.0)})) is None


def test_every_capable_facility_unreachable_returns_none():
    index = _index(_facility("stranded", "e1", {"general"}))
    assert choose(_request(), index, _routes({})) is None


def test_ties_break_deterministically():
    """Same reason the corridor engine's arbitration key is total: a
    tie-break that falls through to dictionary ordering can differ
    between two runs of identical input."""
    route = _routes({"e1": (("a",), 100.0), "e2": (("a",), 100.0)})
    for order in ((("b-fac", "e1"), ("a-fac", "e2")), (("a-fac", "e2"), ("b-fac", "e1"))):
        index = _index(*(_facility(fid, edge, {"general"}) for fid, edge in order))
        decision = choose(_request(), index, route)
        assert decision is not None and decision.facility.id == "a-fac"


def test_runners_up_expose_the_margin():
    """A choice won by two seconds is a different thing from one won by
    four minutes, and only the second is worth defending."""
    index = _index(
        _facility("winner", "e1", {"general"}),
        _facility("second", "e2", {"general"}),
        _facility("third", "e3", {"general"}),
    )
    route = _routes({"e1": (("a",), 60.0), "e2": (("a",), 62.0), "e3": (("a",), 400.0)})
    decision = choose(_request(), index, route)
    assert decision is not None
    assert [name for name, _ in decision.runners_up] == ["second", "third"]
    assert decision.runners_up[0][1] == 62.0


# -- re-dispatch -------------------------------------------------------


def test_redispatch_requires_a_real_improvement_not_merely_a_better_one():
    """A vehicle already committed has a crew expecting it. Flapping
    between two facilities whose travel times cross and re-cross costs
    more than the seconds it chases."""
    index = _index(
        _facility("current", "e1", {"general"}),
        _facility("rival", "e2", {"general"}),
    )
    committed = choose(_request(), index, _routes({"e1": (("a",), 100.0), "e2": (("a",), 500.0)}))
    assert committed is not None and committed.facility.id == "current"

    marginal = _routes({"e1": (("a",), 100.0), "e2": (("a",), 80.0)})
    assert should_redispatch(committed, _request(), index, marginal, improvement_s=30.0) is None

    decisive = _routes({"e1": (("a",), 400.0), "e2": (("a",), 80.0)})
    switched = should_redispatch(committed, _request(), index, decisive, improvement_s=30.0)
    assert switched is not None and switched.facility.id == "rival"


def test_redispatch_measures_against_a_fresh_estimate_not_the_original():
    """The estimate made at dispatch is stale by construction. Measuring
    improvement against it would re-route on nothing more than the
    original having been optimistic."""
    index = _index(
        _facility("current", "e1", {"general"}),
        _facility("rival", "e2", {"general"}),
    )
    committed = choose(_request(), index, _routes({"e1": (("a",), 300.0), "e2": (("a",), 999.0)}))
    assert committed is not None and committed.travel_time_s == 300.0

    # The road to `current` has cleared: it is now 70 s, better than the
    # rival's 90 s. Against the stale 300 s the rival would look like a
    # 210 s win.
    cleared = _routes({"e1": (("a",), 70.0), "e2": (("a",), 90.0)})
    assert should_redispatch(committed, _request(), index, cleared) is None


def test_redispatch_does_not_propose_the_facility_already_chosen():
    index = _index(_facility("only", "e1", {"general"}))
    route = _routes({"e1": (("a",), 100.0)})
    committed = choose(_request(), index, route)
    assert committed is not None
    assert should_redispatch(committed, _request(), index, route) is None


# -- the real facility extract ----------------------------------------


@pytest.fixture(scope="module")
def real_index() -> FacilityIndex:
    if not _FACILITIES.exists():  # pragma: no cover - artefact absent
        pytest.skip("facilities.json not extracted")
    return FacilityIndex.from_json(_FACILITIES)


def test_the_corridor_has_a_usable_facility_set(real_index):
    assert len(real_index) > 50
    assert len(real_index.with_capability("general")) > 20, (
        "too few general facilities for an undifferentiated emergency to have a choice"
    )


def test_no_facility_appears_twice(real_index):
    """OSM carries one building as both a node and a way, and the two
    copies disagree -- in this extract one pair was tagged `hospital`
    with `general` and `clinic` with `obstetric`, so a fertility clinic
    became a general-emergency destination. Merging by rounded
    coordinates missed it: the copies sit 90-95 m apart and a 100 m grid
    cell separates points that close about as often as it groups them.

    What makes a duplicate is therefore *one facility under two records*,
    which is a claim about identity and position together -- not about
    position alone. Two facilities sharing a coordinate are ordinary and
    this extract has two such pairs, both real: American Oncology
    Institute and Metro Superspeciality Hospitals sit 11 m apart on one
    campus, as do Ferti CARE and Tenet Diagnostics. An assertion that
    positions are distinct would call those a bug and would be answered
    by making the data wrong."""
    ids = [f.id for f in real_index.all]
    assert len(ids) == len(set(ids))

    same_name_and_place = [
        (a.name, b.name)
        for a, b in itertools.combinations(real_index.all, 2)
        if _identity(a.name) == _identity(b.name)
        and _haversine_m(a.lat, a.lon, b.lat, b.lon) <= _MERGE_RADIUS_M
    ]
    assert not same_name_and_place, f"unmerged duplicates: {same_name_and_place}"


def test_no_facility_is_both_general_and_a_laboratory(real_index):
    """The negative-keyword rule, checked against the data it was written
    for. `amenity=hospital` is applied loosely in OSM -- to diagnostics
    centres and fertility clinics among others -- and the first version's
    "an unlabelled hospital is general" fallback offered those as
    destinations for an undifferentiated emergency."""
    banned = ("diagnostic", "laborator", "scan", "imaging", "pharmac", "fertility")
    for facility in real_index.with_capability("general"):
        lowered = facility.name.lower()
        assert not any(word in lowered for word in banned), (
            f"{facility.name!r} should not be a general-emergency destination"
        )


def test_capability_vocabulary_has_no_synonym_pairs(real_index):
    """Two spellings of one capability is a lookup that fails silently.
    The extract produced `ophthalmic` from names and `ophthalmology` from
    an OSM tag until they were folded together."""
    synonym_pairs = [
        ("ophthalmic", "ophthalmology"), ("orthopaedic", "orthopaedics"),
        ("paediatric", "paediatrics"), ("paediatric", "children"),
        ("cardiac", "cardiology"), ("neuro", "neurology"),
        ("obstetric", "obstetrics"), ("obstetric", "fertility"),
    ]
    present = real_index.capabilities
    for canonical, synonym in synonym_pairs:
        assert not (canonical in present and synonym in present), (
            f"{canonical!r} and {synonym!r} both present -- one capability, two names"
        )


def test_coverage_is_reported_commonest_first(real_index):
    coverage = capability_coverage(real_index)
    assert coverage[0][0] == "general"
    assert [count for _, count in coverage] == sorted(
        (count for _, count in coverage), reverse=True
    )


def test_facility_json_round_trips(real_index, tmp_path):
    out = tmp_path / "facilities.json"
    out.write_text(
        json.dumps(
            {
                "facilities": [
                    {
                        "id": f.id, "name": f.name, "kind": f.kind, "edge": f.edge,
                        "edge_offset_m": f.edge_offset_m, "lat": f.lat, "lon": f.lon,
                        "capabilities": sorted(f.capabilities),
                    }
                    for f in real_index.all
                ]
            }
        )
    )
    assert len(FacilityIndex.from_json(out)) == len(real_index)

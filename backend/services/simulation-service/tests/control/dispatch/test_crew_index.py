"""`CrewIndex`: the hex-cell shortlist agrees with a brute-force scan, only
returns available crews of the asked kind, and re-ranks by road time."""

from __future__ import annotations

import random

from sim_service.control.dispatch.crew_index import (
    Crew,
    CrewIndex,
    _haversine_m,
    rank_by_road_time,
)

# Vijayawada corridor, roughly
LAT, LON = 16.5062, 80.6480


def _crew(cid: str, kind: str, dlat: float = 0.0, dlon: float = 0.0, **kw) -> Crew:
    return Crew(cid, kind, LAT + dlat, LON + dlon, **kw)


def test_nearest_orders_by_distance_and_filters_kind():
    idx = CrewIndex(
        [
            _crew("amb-far", "AMBULANCE", 0.02),
            _crew("amb-near", "AMBULANCE", 0.002),
            _crew("pol-near", "POLICE", 0.0005),
        ]
    )
    got = idx.nearest(LAT, LON, "AMBULANCE", k=5)
    assert [c.crew.crew_id for c in got] == ["amb-near", "amb-far"]
    assert [c.crew.crew_id for c in idx.nearest(LAT, LON, "POLICE")] == ["pol-near"]
    assert idx.nearest(LAT, LON, "FIRE_TRUCK") == []


def test_unavailable_crews_are_never_returned():
    idx = CrewIndex([_crew("a", "AMBULANCE", 0.001), _crew("b", "AMBULANCE", 0.005)])
    idx.set_available("a", False)
    assert [c.crew.crew_id for c in idx.nearest(LAT, LON, "AMBULANCE")] == ["b"]
    idx.set_available("a", True)
    assert [c.crew.crew_id for c in idx.nearest(LAT, LON, "AMBULANCE")] == ["a", "b"]


def test_move_updates_cell_and_results():
    idx = CrewIndex([_crew("a", "POLICE", 0.05)])
    before = idx.nearest(LAT, LON, "POLICE")[0]
    idx.move("a", LAT + 0.0001, LON)
    after = idx.nearest(LAT, LON, "POLICE")[0]
    assert after.distance_m < before.distance_m
    assert after.cell == idx.cell_for(LAT + 0.0001, LON)


def test_remove_and_replace():
    idx = CrewIndex([_crew("a", "POLICE")])
    idx.remove("a")
    assert len(idx) == 0 and idx.nearest(LAT, LON, "POLICE") == []
    idx.add(_crew("a", "POLICE"))
    idx.add(_crew("a", "POLICE", 0.01))  # same id replaces
    assert len(idx) == 1


def test_nobody_in_range_is_empty_not_an_error():
    idx = CrewIndex([_crew("far", "AMBULANCE", 1.0)])  # ~110 km away
    assert idx.nearest(LAT, LON, "AMBULANCE", k=3) == []


def test_matches_brute_force_on_a_random_fleet():
    rng = random.Random(7)
    crews = [
        _crew(f"c{i}", rng.choice(["AMBULANCE", "POLICE"]),
              rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05))
        for i in range(400)
    ]
    idx = CrewIndex(crews)
    misses = 0
    for _ in range(60):
        lat, lon = LAT + rng.uniform(-0.04, 0.04), LON + rng.uniform(-0.04, 0.04)
        want = sorted(
            (c for c in crews if c.kind == "AMBULANCE"),
            key=lambda c: _haversine_m(lat, lon, c.lat, c.lon),
        )[:3]
        got = idx.nearest(lat, lon, "AMBULANCE", k=3)
        misses += [c.crew.crew_id for c in got] != [c.crew_id for c in want]
        assert len(got) == 3
    # a heuristic shortlist (see module docstring), but with the safety ring it
    # should essentially always agree on a fleet this dense
    assert misses <= 1


def test_search_touches_far_fewer_crews_than_the_fleet(monkeypatch):
    rng = random.Random(3)
    crews = [
        _crew(f"c{i}", "AMBULANCE", rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1))
        for i in range(2000)
    ]
    idx = CrewIndex(crews)
    seen = 0
    real = idx._crews.__getitem__

    class Counting(dict):
        def __getitem__(self, key):
            nonlocal seen
            seen += 1
            return real(key)

    idx._crews = Counting(idx._crews)
    idx.nearest(LAT, LON, "AMBULANCE", k=3)
    assert seen < len(crews) / 4


def test_rank_by_road_time_reorders_and_drops_unreachable():
    idx = CrewIndex(
        [
            _crew("across-river", "AMBULANCE", 0.001),
            _crew("same-bank", "AMBULANCE", 0.004),
            _crew("cut-off", "AMBULANCE", 0.002),
        ]
    )
    shortlist = idx.nearest(LAT, LON, "AMBULANCE", k=3)
    assert shortlist[0].crew.crew_id == "across-river"
    times = {"across-river": 600.0, "same-bank": 90.0, "cut-off": None}
    ranked = rank_by_road_time(shortlist, lambda c: times[c.crew_id])
    assert [c.crew.crew_id for c in ranked] == ["same-bank", "across-river"]
    assert ranked[0].road_time_s == 90.0


def test_rank_by_road_time_keeps_air_order_when_nothing_can_be_priced():
    idx = CrewIndex([_crew("a", "POLICE", 0.001), _crew("b", "POLICE", 0.003)])
    shortlist = idx.nearest(LAT, LON, "POLICE", k=2)
    ranked = rank_by_road_time(shortlist, lambda c: None)
    assert [c.crew.crew_id for c in ranked] == ["a", "b"]
    assert all(c.road_time_s is None for c in ranked)

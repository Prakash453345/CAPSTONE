"""Emergency routing on the real district network (`vijayawada_district`).

The district keeps the whole arterial grid, so routes genuinely compete. These
tests check, on that real graph and under randomised live conditions:

* the recommended route is optimal (against an independent Bellman-Ford),
* every returned route is a real, connected, loopless drive from the source
  road to the destination road, ranked by cost, within the alternative rules,
* the network actually offers choices (most requests get alternatives),
* blockages: a blocked road is avoided when there is any way round it; when
  there is none, every route crossing one says so; a blocked source or
  destination is refused with a reason.
"""

from __future__ import annotations

import math
import random
from collections import deque

import pytest
from itms_domain import EmergencyRoutingConfig
from itms_domain.paths import DATA_DIR
from sim_service.routing import EdgeConditions, NoRouteError, RoadGraph, RoutePlanner
from sim_service.routing.search import _overlap

NET = DATA_DIR / "scenarios" / "networks" / "vijayawada" / "vijayawada_district.net.xml"

pytestmark = pytest.mark.skipif(not NET.exists(), reason="district network not built")


@pytest.fixture(scope="module")
def graph() -> RoadGraph:
    return RoadGraph.from_network(NET)


def random_conditions(graph: RoadGraph, rng: random.Random) -> dict[str, EdgeConditions]:
    cond: dict[str, EdgeConditions] = {}
    for e in rng.sample(sorted(graph.edges), k=len(graph.edges) // 4):
        severity = rng.choice([None, None, None, "low", "medium", "high"])
        cond[e] = EdgeConditions(
            congestion=rng.random(),
            congestion_variance=rng.random() * 0.2,
            anomaly_severity=severity,
            anomaly_impact=rng.random() if severity else 0.0,
            entry_signal_phase=rng.choice([None, "green", "yellow", "red"]),
        )
    return cond


def bellman_ford(graph: RoadGraph, source: str, weight) -> dict[str, float]:
    """Queue-based Bellman-Ford (SPFA): an independent label-correcting check
    on Dijkstra's label-setting answer."""
    dist = {e: math.inf for e in graph.edges}
    dist[source] = 0.0
    queue = deque([source])
    queued = {source}
    while queue:
        a = queue.popleft()
        queued.discard(a)
        for ge in graph.neighbours(a):
            w = weight(a, ge)
            if math.isfinite(w) and dist[a] + w < dist[ge.to_edge] - 1e-12:
                dist[ge.to_edge] = dist[a] + w
                if ge.to_edge not in queued:
                    queued.add(ge.to_edge)
                    queue.append(ge.to_edge)
    return dist


def assert_valid_route(graph: RoadGraph, edges: tuple[str, ...], source: str, dest: str) -> None:
    assert edges[0] == source and edges[-1] == dest
    assert len(set(edges)) == len(edges), "a road is driven twice"
    for a, b in zip(edges, edges[1:], strict=False):
        assert any(ge.to_edge == b for ge in graph.neighbours(a)), f"no connection {a} -> {b}"


def test_every_road_reaches_every_other(graph: RoadGraph) -> None:
    src = sorted(graph.edges)[0]
    planner = RoutePlanner(graph)
    reach = bellman_ford(graph, src, planner._weight(graph, {}))
    assert all(math.isfinite(d) for d in reach.values())


@pytest.mark.parametrize("seed", range(40))
def test_recommended_route_is_optimal_and_every_route_is_valid(graph: RoadGraph, seed: int) -> None:
    rng = random.Random(seed)
    cond = random_conditions(graph, rng)
    source, dest = rng.sample(sorted(graph.edges), 2)
    planner = RoutePlanner(graph)
    routes = planner.plan(source, dest, cond)

    weight = planner._weight(graph, cond)
    truth = bellman_ford(graph, source, weight)[dest]
    assert routes[0].cost.total_score == pytest.approx(truth, abs=2e-3)  # total_score is rounded

    cfg = planner.config
    for r in routes:
        assert_valid_route(graph, r.edges, source, dest)
        assert r.cost.total_score <= routes[0].cost.total_score * cfg.alternative_max_stretch + 1e-3
    scores = [r.cost.total_score for r in routes]
    assert scores == sorted(scores)
    assert [r.rank for r in routes] == list(range(len(routes)))
    length = lambda e: graph.edges[e].length_m  # noqa: E731
    for i, r in enumerate(routes):
        for q in routes[:i]:
            assert _overlap(r.edges, q.edges, length) <= cfg.alternative_max_overlap + 1e-9
    assert len({r.edges for r in routes}) == len(routes)


def test_the_district_offers_real_choices(graph: RoadGraph) -> None:
    rng = random.Random(11)
    planner = RoutePlanner(graph)
    with_alternatives = sum(
        len(planner.plan(*rng.sample(sorted(graph.edges), 2))) > 1 for _ in range(100)
    )
    assert with_alternatives >= 80, f"only {with_alternatives}/100 requests had an alternative"


def test_a_blocked_road_is_avoided_when_there_is_a_way_round(graph: RoadGraph) -> None:
    rng = random.Random(3)
    planner = RoutePlanner(graph)
    checked = 0
    for _ in range(60):
        source, dest = rng.sample(sorted(graph.edges), 2)
        best = planner.plan(source, dest)[0]
        inner = best.edges[1:-1]
        if not inner:
            continue
        block = inner[len(inner) // 2]
        cond = {block: EdgeConditions(anomaly_severity="blocked", anomaly_impact=1.0)}
        detour = planner.plan(source, dest, cond)[0]
        without = graph.without_edges({block})
        truth = bellman_ford(without, source, planner._weight(without, cond))[dest]
        if not math.isfinite(truth):
            # the blocked road is the only way in: the one route is offered,
            # and it says plainly that it crosses the blockage
            assert detour.forced_through == (block,)
            assert detour.reliable is False
            continue
        assert block not in detour.edges
        assert detour.forced_through == ()
        # and it is the best route on the graph without that road
        assert detour.cost.total_score == pytest.approx(truth, abs=2e-3)
        checked += 1
    assert checked >= 40


def test_when_every_way_in_is_blocked_each_route_says_so(graph: RoadGraph) -> None:
    rng = random.Random(5)
    planner = RoutePlanner(graph, EmergencyRoutingConfig(alternative_max_stretch=50.0))
    for _ in range(30):
        source, dest = rng.sample(sorted(graph.edges), 2)
        feeders = [a for a, ges in graph.adjacency.items() if any(ge.to_edge == dest for ge in ges)]
        if source in feeders:
            continue
        cond = {f: EdgeConditions(anomaly_severity="blocked", anomaly_impact=1.0) for f in feeders}
        routes = planner.plan(source, dest, cond)
        for r in routes:
            crossed = set(feeders) & set(r.edges)
            assert crossed, "a route reached the destination without crossing a blocked feeder"
            assert set(r.forced_through) == crossed
            assert r.reliable is False
        return
    pytest.fail("no suitable source/destination pair found")


def test_blocked_source_or_destination_is_refused(graph: RoadGraph) -> None:
    source, dest = sorted(graph.edges)[:2]
    planner = RoutePlanner(graph)
    blocked = EdgeConditions(anomaly_severity="blocked", anomaly_impact=1.0)
    with pytest.raises(NoRouteError, match="current road is blocked"):
        planner.plan(source, dest, {source: blocked})
    with pytest.raises(NoRouteError, match="destination road is blocked"):
        planner.plan(source, dest, {dest: blocked})


def test_unknown_roads_and_invalid_config_are_refused(graph: RoadGraph) -> None:
    source = sorted(graph.edges)[0]
    with pytest.raises(NoRouteError, match="unknown source"):
        RoutePlanner(graph).plan("nope", source)
    with pytest.raises(NoRouteError, match="unknown destination"):
        RoutePlanner(graph).plan(source, "nope")
    with pytest.raises(NoRouteError, match="config is invalid"):
        RoutePlanner(graph, EmergencyRoutingConfig(alternative_max_stretch=0.5)).plan(
            source, sorted(graph.edges)[1]
        )


def test_planning_is_deterministic(graph: RoadGraph) -> None:
    rng = random.Random(9)
    cond = random_conditions(graph, rng)
    source, dest = rng.sample(sorted(graph.edges), 2)
    first = [r.edges for r in RoutePlanner(graph).plan(source, dest, cond)]
    for _ in range(3):
        assert [r.edges for r in RoutePlanner(graph).plan(source, dest, cond)] == first

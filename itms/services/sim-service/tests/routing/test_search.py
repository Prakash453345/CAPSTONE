"""`GraphSearchEngine` -- the search mechanism."""

from __future__ import annotations

import math

from _synthetic import edge, linear_graph
from sim_service.routing.graph import GraphEdge, RoadGraph
from sim_service.routing.search import GraphSearchEngine


def _uniform_weight(_from: str, _ge: GraphEdge) -> float:
    return 1.0


def test_finds_the_direct_chain_over_the_long_bypass():
    g = linear_graph(5)
    eng = GraphSearchEngine(g)
    # weight = the to-edge's free-flow time, so the short chain wins
    res = eng.shortest_path(
        "E0", "E4", lambda _f, ge: g.edges[ge.to_edge].free_flow_time_s
    )
    assert res.edges == ("E0", "E1", "E2", "E3", "E4")
    assert res.found


def test_source_equals_target_is_a_zero_length_path():
    g = linear_graph(3)
    res = GraphSearchEngine(g).shortest_path("E1", "E1", _uniform_weight)
    assert res.edges == ("E1",)
    assert res.total_weight == 0.0


def test_unreachable_target_returns_an_empty_result():
    # island edge with no inbound links
    g = RoadGraph(
        edges={"E0": edge("E0"), "X": edge("X")},
        adjacency={"E0": ()},
        signalised_junctions=frozenset(),
    )
    res = GraphSearchEngine(g).shortest_path("E0", "X", _uniform_weight)
    assert not res.found
    assert math.isinf(res.total_weight)


def test_unknown_endpoints_return_empty():
    g = linear_graph(3)
    eng = GraphSearchEngine(g)
    assert not eng.shortest_path("nope", "E2", _uniform_weight).found
    assert not eng.shortest_path("E0", "nope", _uniform_weight).found


def test_infinite_edge_weight_is_skipped():
    g = linear_graph(4)
    eng = GraphSearchEngine(g)

    def weight(_f: str, ge: GraphEdge) -> float:
        return math.inf if ge.to_edge == "E2" else g.edges[ge.to_edge].free_flow_time_s

    res = eng.shortest_path("E0", "E3", weight)
    # E0->E1->E2->E3 is blocked at E2, so it must take the bypass E0->B->E3
    assert "E2" not in res.edges
    assert res.edges == ("E0", "B", "E3")


def test_k_shortest_returns_diverse_routes_best_first():
    g = linear_graph(6)
    eng = GraphSearchEngine(g)
    routes = eng.k_shortest(
        "E0", "E5", lambda _f, ge: g.edges[ge.to_edge].free_flow_time_s, k=2
    )  # unfiltered: plain Yen
    assert len(routes) == 2
    assert routes[0].total_weight <= routes[1].total_weight
    assert routes[0].edges != routes[1].edges
    # the second route is pushed onto the bypass
    assert "B" in routes[1].edges

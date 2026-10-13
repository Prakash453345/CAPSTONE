"""Exactness of `GraphSearchEngine` against brute force.

On small random directed graphs every loopless path can be enumerated, so the
search's answers can be checked against ground truth rather than examples:

* `shortest_path` returns a minimum-cost path,
* `k_shortest` unfiltered (plain Yen) returns the k cheapest loopless paths,
* `k_shortest` filtered returns exactly the paths a greedy pass over all
  loopless paths in cost order would accept under the same stretch/overlap
  rule -- i.e. the filter never skips a cheaper qualifying route.

Weights are continuous random draws, so ties (where several answers would be
equally right) have probability zero and paths can be compared exactly.
"""

from __future__ import annotations

import math
import random

import pytest

from _synthetic import edge
from sim_service.routing.graph import GraphEdge, RoadGraph
from sim_service.routing.search import GraphSearchEngine, _overlap


def random_graph(rng: random.Random, n: int, p: float) -> tuple[RoadGraph, dict[tuple[str, str], float]]:
    """`n` road edges with random arcs (density `p`), random lengths and arc weights."""
    ids = [f"R{i}" for i in range(n)]
    edges = {e: edge(e, length=rng.uniform(40, 400)) for e in ids}
    adjacency: dict[str, list[GraphEdge]] = {}
    weights: dict[tuple[str, str], float] = {}
    for a in ids:
        for b in ids:
            if a != b and rng.random() < p:
                adjacency.setdefault(a, []).append(
                    GraphEdge(to_edge=b, junction_id=f"j_{b}", signalised=False, tl_id=None)
                )
                weights[(a, b)] = rng.uniform(0.5, 10.0)
    graph = RoadGraph(edges=edges, adjacency={k: tuple(v) for k, v in adjacency.items()}, signalised_junctions=frozenset())
    return graph, weights


def all_simple_paths(graph: RoadGraph, s: str, t: str) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    stack: list[tuple[str, tuple[str, ...]]] = [(s, (s,))]
    while stack:
        cur, path = stack.pop()
        if cur == t:
            out.append(path)
            continue
        for ge in graph.neighbours(cur):
            if ge.to_edge not in path:
                stack.append((ge.to_edge, path + (ge.to_edge,)))
    return out


def cost(path: tuple[str, ...], w: dict[tuple[str, str], float]) -> float:
    return sum(w[(a, b)] for a, b in zip(path, path[1:], strict=False))


SEEDS = range(300)


@pytest.mark.parametrize("seed", SEEDS)
def test_shortest_path_is_optimal(seed: int) -> None:
    rng = random.Random(seed)
    graph, w = random_graph(rng, n=rng.randint(4, 9), p=rng.uniform(0.15, 0.45))
    s, t = rng.sample(sorted(graph.edges), 2)
    truth = sorted(cost(p, w) for p in all_simple_paths(graph, s, t))
    res = GraphSearchEngine(graph).shortest_path(s, t, lambda a, ge: w[(a, ge.to_edge)])
    if not truth:
        assert not res.found and math.isinf(res.total_weight)
        return
    assert res.found
    assert res.edges[0] == s and res.edges[-1] == t
    assert math.isclose(res.total_weight, truth[0], rel_tol=1e-9)
    assert math.isclose(cost(res.edges, w), truth[0], rel_tol=1e-9)


@pytest.mark.parametrize("seed", SEEDS)
def test_plain_yen_returns_the_k_cheapest_loopless_paths(seed: int) -> None:
    rng = random.Random(1000 + seed)
    graph, w = random_graph(rng, n=rng.randint(4, 8), p=rng.uniform(0.2, 0.5))
    s, t = rng.sample(sorted(graph.edges), 2)
    k = rng.randint(1, 6)
    truth = sorted(all_simple_paths(graph, s, t), key=lambda p: cost(p, w))[:k]
    got = GraphSearchEngine(graph).k_shortest(s, t, lambda a, ge: w[(a, ge.to_edge)], k=k)
    assert [r.edges for r in got] == truth
    for r in got:
        assert len(set(r.edges)) == len(r.edges)  # loopless
        assert math.isclose(r.total_weight, cost(r.edges, w), rel_tol=1e-9)


@pytest.mark.parametrize("seed", SEEDS)
def test_filtered_alternatives_are_the_cheapest_qualifying_routes(seed: int) -> None:
    rng = random.Random(5000 + seed)
    graph, w = random_graph(rng, n=rng.randint(5, 9), p=rng.uniform(0.2, 0.5))
    s, t = rng.sample(sorted(graph.edges), 2)
    k = rng.randint(2, 4)
    stretch = rng.choice([1.2, 1.6, 2.5, math.inf])
    max_overlap = rng.choice([0.0, 0.3, 0.7, 1.0])
    length = lambda e: graph.edges[e].length_m  # noqa: E731

    ordered = sorted(all_simple_paths(graph, s, t), key=lambda p: cost(p, w))
    expected: list[tuple[str, ...]] = []
    if ordered:
        best = cost(ordered[0], w)
        expected.append(ordered[0])
        for p in ordered[1:]:
            if len(expected) == k or cost(p, w) > best * stretch:
                break
            if all(_overlap(p, q, length) <= max_overlap for q in expected):
                expected.append(p)

    got = GraphSearchEngine(graph).k_shortest(
        s, t, lambda a, ge: w[(a, ge.to_edge)], k=k, max_stretch=stretch, max_overlap=max_overlap
    )
    assert [r.edges for r in got] == expected


# ---- edge cases ------------------------------------------------------


def _chain() -> RoadGraph:
    """A -> B -> C, A -> C directly (costlier), and a C -> A back arc (a loop)."""
    edges = {e: edge(e) for e in "ABC"}
    arcs = {"A": ("B", "C"), "B": ("C",), "C": ("A",)}
    adjacency = {
        a: tuple(GraphEdge(to_edge=b, junction_id=f"j{b}", signalised=False, tl_id=None) for b in bs)
        for a, bs in arcs.items()
    }
    return RoadGraph(edges=edges, adjacency=adjacency, signalised_junctions=frozenset())


W = {("A", "B"): 1.0, ("B", "C"): 1.0, ("A", "C"): 5.0, ("C", "A"): 1.0}


def _w(a: str, ge: GraphEdge) -> float:
    return W[(a, ge.to_edge)]


def test_loops_are_never_returned() -> None:
    routes = GraphSearchEngine(_chain()).k_shortest("A", "C", _w, k=10)
    assert [r.edges for r in routes] == [("A", "B", "C"), ("A", "C")]


def test_k_one_and_same_endpoints() -> None:
    eng = GraphSearchEngine(_chain())
    assert [r.edges for r in eng.k_shortest("A", "C", _w, k=1)] == [("A", "B", "C")]
    assert [r.edges for r in eng.k_shortest("B", "B", _w, k=3)] == [("B",)]


def test_banned_edges_and_arcs() -> None:
    eng = GraphSearchEngine(_chain())
    assert eng.shortest_path("A", "C", _w, banned_edges={"B"}).edges == ("A", "C")
    assert eng.shortest_path("A", "C", _w, banned_arcs={("A", "B"), ("A", "C")}).found is False
    assert eng.shortest_path("A", "C", _w, banned_edges={"A"}).found is False
    assert eng.shortest_path("A", "C", _w, banned_edges={"C"}).found is False


def test_negative_weights_are_rejected() -> None:
    with pytest.raises(ValueError):
        GraphSearchEngine(_chain()).shortest_path("A", "C", lambda _a, _ge: -1.0)


def test_non_finite_weights_make_an_arc_unusable() -> None:
    eng = GraphSearchEngine(_chain())
    nan_on_b = lambda a, ge: math.nan if ge.to_edge == "B" else _w(a, ge)  # noqa: E731
    assert eng.shortest_path("A", "C", nan_on_b).edges == ("A", "C")
    assert [r.edges for r in eng.k_shortest("A", "C", nan_on_b, k=3)] == [("A", "C")]


def test_results_are_deterministic() -> None:
    rng = random.Random(42)
    graph, w = random_graph(rng, n=12, p=0.3)
    s, t = sorted(graph.edges)[0], sorted(graph.edges)[-1]
    fn = lambda a, ge: round(w[(a, ge.to_edge)])  # integer weights: many ties  # noqa: E731
    eng = GraphSearchEngine(graph)
    first = [r.edges for r in eng.k_shortest(s, t, fn, k=5)]
    for _ in range(5):
        assert [r.edges for r in GraphSearchEngine(graph).k_shortest(s, t, fn, k=5)] == first


def test_overlap_measure() -> None:
    length = {"S": 50.0, "X": 100.0, "Y": 300.0, "Z": 100.0, "T": 50.0}.__getitem__
    # endpoints never count; X is 100 of the 400 m between them
    assert _overlap(("S", "X", "Y", "T"), ("S", "X", "Z", "T"), length) == pytest.approx(0.25)
    assert _overlap(("S", "X", "Y", "T"), ("S", "X", "Y", "T"), length) == 1.0
    assert _overlap(("S", "T"), ("S", "X", "T"), length) == 1.0  # nothing of its own

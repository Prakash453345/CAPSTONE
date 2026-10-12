"""`GraphSearchEngine` -- the search *mechanism*: exact least-cost paths over a
`RoadGraph`, with edge weights supplied by a callback so the cost model stays
separate.

* `shortest_path` is Dijkstra (an admissible A* heuristic is accepted but
  optional). Weights must be non-negative, which `RouteCostModel` guarantees;
  non-finite weights mark an arc as unusable. Ties are broken
  deterministically, so the same request on the same conditions always
  returns the same route.

* `k_shortest` is Yen's algorithm: the exact k best *loopless* routes in cost
  order. On a district grid, "an alternative" must mean a genuinely different
  way to get there, so the stream of exact routes is filtered: an alternative
  is offered only if it costs at most `max_stretch` x the best route and shares
  at most `max_overlap` of its length with every route already offered. The
  filter never changes which route is best, and the routes it skips still seed
  Yen's search, so no cheaper qualifying route is ever missed.

Paths are sequences of road edges (the graph's nodes); "loopless" means no
road is driven twice.
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Callable, Collection
from dataclasses import dataclass

from sim_service.routing.graph import GraphEdge, RoadGraph

# weight(from_edge, graph_edge) -> cost to traverse into graph_edge.to_edge
WeightFn = Callable[[str, GraphEdge], float]
# heuristic(edge_id) -> admissible lower bound on remaining cost to the target
HeuristicFn = Callable[[str], float]
# length_of(edge_id) -> metres, for the overlap test
LengthFn = Callable[[str], float]

# Safety valve on Yen's candidate generation: how many exact routes may be
# drawn while looking for `k` qualifying ones. Far above what a city district
# needs (each draw is one Dijkstra per spur node), and it bounds the worst case
# when every near-optimal route is a near-duplicate of the first.
_MAX_YEN_DRAWS = 64


@dataclass(frozen=True)
class SearchResult:
    edges: tuple[str, ...]  # source .. destination, inclusive
    total_weight: float

    @property
    def found(self) -> bool:
        return len(self.edges) > 0


_NOT_FOUND = SearchResult((), math.inf)


class GraphSearchEngine:
    def __init__(self, graph: RoadGraph):
        self.graph = graph

    # ---- single best path ----------------------------------------

    def shortest_path(
        self,
        source: str,
        target: str,
        weight: WeightFn,
        *,
        heuristic: HeuristicFn | None = None,
        edge_penalty: dict[str, float] | None = None,
        banned_edges: Collection[str] = (),
        banned_arcs: Collection[tuple[str, str]] = (),
        max_cost: float = math.inf,
    ) -> SearchResult:
        """Least-weight path from `source` edge to `target` edge, or an empty
        `SearchResult` if none exists.

        `edge_penalty` multiplies the weight of entering an edge.
        `banned_edges` may not be entered; `banned_arcs` (from, to) may not be
        taken. Both are what Yen's spur searches use; a banned source or target
        means there is no path. `max_cost` drops any partial path whose cost
        plus `heuristic` already exceeds it (exact when the heuristic is
        admissible: such a path can only finish above the bound)."""
        g = self.graph
        if source not in g.edges or target not in g.edges:
            return _NOT_FOUND
        banned = set(banned_edges)
        if source in banned or target in banned:
            return _NOT_FOUND
        if source == target:
            return SearchResult((source,), 0.0)

        pen = edge_penalty or {}
        no_arcs = set(banned_arcs)
        h = heuristic or (lambda _e: 0.0)
        best: dict[str, float] = {source: 0.0}
        prev: dict[str, str] = {}
        done: set[str] = set()
        # (priority, tie-break, edge): the counter keeps equal-cost entries in
        # insertion order, so results never depend on string comparison of ids
        tie = itertools.count()
        pq: list[tuple[float, int, str]] = [(h(source), next(tie), source)]

        while pq:
            _, _, cur = heapq.heappop(pq)
            if cur in done:
                continue  # stale entry for an edge already settled
            done.add(cur)
            if cur == target:
                break
            cur_g = best[cur]
            for ge in g.neighbours(cur):
                nxt = ge.to_edge
                if nxt in done or nxt in banned or (cur, nxt) in no_arcs:
                    continue
                step = weight(cur, ge)
                if not math.isfinite(step):
                    continue
                if step < 0:
                    raise ValueError(f"negative weight {step} entering {nxt!r}: Dijkstra requires >= 0")
                step *= pen.get(nxt, 1.0)
                cand = cur_g + step
                hn = h(nxt)
                if cand + hn > max_cost + 1e-9:
                    continue  # cannot finish within the bound (or cannot finish at all)
                if cand < best.get(nxt, math.inf):
                    best[nxt] = cand
                    prev[nxt] = cur
                    heapq.heappush(pq, (cand + hn, next(tie), nxt))

        if target not in done:
            return _NOT_FOUND
        path = [target]
        while path[-1] != source:
            path.append(prev[path[-1]])
        path.reverse()
        return SearchResult(tuple(path), best[target])

    # ---- alternatives --------------------------------------------

    def _distances_to(self, target: str, weight: WeightFn) -> dict[str, float]:
        """Least cost from every edge to `target` (backward Dijkstra over the
        reversed arcs). Edges that cannot reach the target are absent."""
        reverse: dict[str, list[tuple[str, float]]] = {}
        for a, ges in self.graph.adjacency.items():
            for ge in ges:
                w = weight(a, ge)
                if math.isfinite(w):
                    reverse.setdefault(ge.to_edge, []).append((a, w))
        dist = {target: 0.0}
        tie = itertools.count()
        pq: list[tuple[float, int, str]] = [(0.0, next(tie), target)]
        done: set[str] = set()
        while pq:
            d, _, cur = heapq.heappop(pq)
            if cur in done:
                continue
            done.add(cur)
            for prev_edge, w in reverse.get(cur, ()):
                nd = d + w
                if nd < dist.get(prev_edge, math.inf):
                    dist[prev_edge] = nd
                    heapq.heappush(pq, (nd, next(tie), prev_edge))
        return dist

    def path_weight(self, edges: tuple[str, ...], weight: WeightFn) -> float:
        """Total weight of an explicit path (the source edge itself is free,
        matching `shortest_path`); inf if any step is not a usable arc."""
        total = 0.0
        for a, b in zip(edges, edges[1:], strict=False):
            ge = next((x for x in self.graph.neighbours(a) if x.to_edge == b), None)
            if ge is None:
                return math.inf
            w = weight(a, ge)
            if not math.isfinite(w):
                return math.inf
            total += w
        return total

    def k_shortest(
        self,
        source: str,
        target: str,
        weight: WeightFn,
        *,
        k: int = 3,
        heuristic: HeuristicFn | None = None,
        max_stretch: float = math.inf,
        max_overlap: float = 1.0,
        length_of: LengthFn | None = None,
    ) -> list[SearchResult]:
        """Up to `k` routes, best first: the optimal route, then the cheapest
        loopless routes that each cost at most `max_stretch` x the optimum and
        share at most `max_overlap` of their length with every route already
        returned (source and destination roads, which every route shares, do
        not count). `max_stretch=inf, max_overlap=1` gives plain Yen."""
        k = max(1, k)
        # Yen re-searches the same arcs many times; an arc's weight is fixed
        # for the duration of one call, so compute each one once
        weight = _memoised(weight)
        # Exact cost-to-target on the unrestricted graph, from one backward
        # search. Banning roads/turns only ever raises that cost, so it is an
        # admissible and consistent A* heuristic for every spur search, and the
        # spurs head straight for the target instead of flooding the network.
        to_target = self._distances_to(target, weight)
        if heuristic is None:
            heuristic = lambda e: to_target.get(e, math.inf)  # noqa: E731
        first = self.shortest_path(source, target, weight, heuristic=heuristic)
        if not first.found:
            return []
        accepted = [first]
        if k == 1 or len(first.edges) <= 1:
            return accepted

        length = length_of or (lambda e: self.graph.edges[e].length_m)
        limit = first.total_weight * max_stretch if math.isfinite(max_stretch) else math.inf
        drawn: list[SearchResult] = [first]  # every exact route, in cost order
        seen: set[tuple[str, ...]] = {first.edges}
        tie = itertools.count()
        candidates: list[tuple[float, int, tuple[str, ...]]] = []

        while len(accepted) < k and len(drawn) < _MAX_YEN_DRAWS:
            last = drawn[-1].edges
            # spur from every edge of the last drawn route except the target
            for i in range(len(last) - 1):
                spur = last[i]
                root = last[: i + 1]
                # arcs the earlier routes took out of this same root
                no_arcs = {
                    (spur, p.edges[i + 1])
                    for p in drawn
                    if len(p.edges) > i + 1 and p.edges[: i + 1] == root
                }
                root_cost = self.path_weight(root, weight)
                spur_res = self.shortest_path(
                    spur,
                    target,
                    weight,
                    heuristic=heuristic,
                    banned_edges=root[:-1],  # loopless: never re-enter the root
                    banned_arcs=no_arcs,
                    # a route over the stretch limit is never offered
                    max_cost=limit - root_cost,
                )
                if not spur_res.found:
                    continue
                path = root[:-1] + spur_res.edges
                if path in seen:
                    continue
                cost = self.path_weight(path, weight)
                if not math.isfinite(cost):
                    continue
                seen.add(path)
                heapq.heappush(candidates, (cost, next(tie), path))

            if not candidates:
                break  # no other loopless route exists
            cost, _, path = heapq.heappop(candidates)
            if cost > limit + 1e-9:
                break  # every remaining route is costlier still
            route = SearchResult(path, cost)
            drawn.append(route)
            if all(_overlap(route.edges, a.edges, length) <= max_overlap + 1e-9 for a in accepted):
                accepted.append(route)

        return accepted


def _memoised(weight: WeightFn) -> WeightFn:
    cache: dict[tuple[str, str], float] = {}

    def cached(from_edge: str, ge: GraphEdge) -> float:
        key = (from_edge, ge.to_edge)
        w = cache.get(key)
        if w is None:
            w = cache[key] = weight(from_edge, ge)
        return w

    return cached


def _overlap(a: tuple[str, ...], b: tuple[str, ...], length: LengthFn) -> float:
    """Share of route `a`'s length (excluding the source and destination
    roads every route between the same endpoints shares) that also lies on
    route `b`."""
    inner = a[1:-1]
    total = sum(length(e) for e in inner)
    if total <= 0:
        # no road of its own between the endpoints: identical in substance
        return 1.0 if set(inner) <= set(b) else 0.0
    shared = set(b)
    return sum(length(e) for e in inner if e in shared) / total

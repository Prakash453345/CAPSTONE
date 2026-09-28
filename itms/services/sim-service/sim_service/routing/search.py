"""`GraphSearchEngine` -- the search *mechanism*. A standard weighted
shortest-path (Dijkstra; an admissible A* heuristic is accepted but optional)
over a `RoadGraph`, with edge weights supplied by a callback so the cost model
stays separate.

`k_shortest` returns a few near-best routes by re-running the search with the
previous route's edges penalised -- enough for a "recommended + alternative"
UI without the full machinery of Yen's algorithm (the corridor has 33 edges).
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable
from dataclasses import dataclass

from sim_service.routing.graph import GraphEdge, RoadGraph

# weight(from_edge, graph_edge) -> cost to traverse into graph_edge.to_edge
WeightFn = Callable[[str, GraphEdge], float]
# heuristic(edge_id) -> admissible lower bound on remaining cost to the target
HeuristicFn = Callable[[str], float]


@dataclass(frozen=True)
class SearchResult:
    edges: tuple[str, ...]  # source .. destination, inclusive
    total_weight: float

    @property
    def found(self) -> bool:
        return len(self.edges) > 0


class GraphSearchEngine:
    def __init__(self, graph: RoadGraph):
        self.graph = graph

    def shortest_path(
        self,
        source: str,
        target: str,
        weight: WeightFn,
        *,
        heuristic: HeuristicFn | None = None,
        edge_penalty: dict[str, float] | None = None,
    ) -> SearchResult:
        """Least-weight path from `source` edge to `target` edge. Returns an
        empty `SearchResult` if the target is unreachable. `edge_penalty`
        multiplies the weight of entering a given edge (used by
        `k_shortest` to push subsequent routes off the first one)."""
        g = self.graph
        if source not in g.edges or target not in g.edges:
            return SearchResult((), math.inf)
        if source == target:
            return SearchResult((source,), 0.0)

        pen = edge_penalty or {}
        h = heuristic or (lambda _e: 0.0)
        best: dict[str, float] = {source: 0.0}
        prev: dict[str, str] = {}
        pq: list[tuple[float, str]] = [(h(source), source)]

        while pq:
            _, cur = heapq.heappop(pq)
            if cur == target:
                break
            cur_g = best[cur]
            for ge in g.neighbours(cur):
                nxt = ge.to_edge
                step = weight(cur, ge) * pen.get(nxt, 1.0)
                if not math.isfinite(step):
                    continue
                cand = cur_g + step
                if cand < best.get(nxt, math.inf) - 1e-12:
                    best[nxt] = cand
                    prev[nxt] = cur
                    heapq.heappush(pq, (cand + h(nxt), nxt))

        if target not in best:
            return SearchResult((), math.inf)

        path = [target]
        while path[-1] != source:
            path.append(prev[path[-1]])
        path.reverse()
        return SearchResult(tuple(path), best[target])

    def k_shortest(
        self,
        source: str,
        target: str,
        weight: WeightFn,
        *,
        k: int = 3,
        diversity_penalty: float = 3.0,
        heuristic: HeuristicFn | None = None,
    ) -> list[SearchResult]:
        """Up to `k` distinct routes, best first. Each subsequent search
        penalises every edge already used by an accepted route by
        `diversity_penalty`x, so alternatives genuinely diverge rather than
        differ by one hop."""
        results: list[SearchResult] = []
        seen: set[tuple[str, ...]] = set()
        penalty: dict[str, float] = {}

        for _ in range(max(1, k)):
            res = self.shortest_path(
                source, target, weight, heuristic=heuristic, edge_penalty=penalty
            )
            if not res.found or res.edges in seen:
                break
            results.append(res)
            seen.add(res.edges)
            for e in res.edges[1:]:  # not the source edge itself
                penalty[e] = penalty.get(e, 1.0) + diversity_penalty
        return results

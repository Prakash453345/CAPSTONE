"""`RoutePlanner` -- graph + cost model + search, producing explainable
`RouteResult`s.

`plan()` returns the recommended route first, then up to
`config.max_alternatives` genuinely-different alternatives, each carrying the
full `RouteCostBreakdown` and the lists the "why this route" panel needs
(signalised intersections, congested segments, anomalous segments avoided).

`plan()` searches twice at most. The primary pass excludes every BLOCKED edge
outright -- the graph literally doesn't have them -- exactly like before.
Only when that pass finds *no* path at all does a second pass run, on the
full graph, allowing BLOCKED edges back in at a large-but-finite cost
(`RouteCostModel` / `config.blocked_fallback_anomaly_norm`). This is a
deliberate product decision, not a relaxation of safety: a real emergency
vehicle can usually still get through a "blocked" road when it is the only
way in or out, and a hard "no route" here would strand an otherwise-valid
dispatch over one bad segment instead of giving the operator a route to
review. Routes from that second pass always come back `reliable=False` with
`forced_through` naming the edges crossed anyway, so the operator sees the
hazard plainly rather than a mission failure.

Failure is a typed `NoRouteError` with a human-readable reason -- never a raw
exception or an empty list without explanation. It is now reserved for routes
that are unreachable outright (unknown edges, a genuinely isolated
destination, or the vehicle's *own* current/destination edge itself blocked)
-- not merely "the only path crosses an active incident".
"""

from __future__ import annotations

from collections.abc import Mapping

from itms_domain import EmergencyRoutingConfig, RouteCostBreakdown, RouteResult

from sim_service.routing.cost import EdgeConditions, RouteCostModel
from sim_service.routing.graph import GraphEdge, RoadGraph
from sim_service.routing.search import GraphSearchEngine

_CONGESTED_AT = 0.55  # congestion index above which a segment is "congested"


class NoRouteError(Exception):
    """No safe route could be produced. `.reason` is operator-facing text."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RoutePlanner:
    def __init__(
        self,
        graph: RoadGraph,
        config: EmergencyRoutingConfig | None = None,
    ):
        self.graph = graph
        self.config = config or EmergencyRoutingConfig()
        self.cost_model = RouteCostModel(self.config)

    def plan(
        self,
        source_edge: str,
        dest_edge: str,
        conditions: Mapping[str, EdgeConditions] | None = None,
    ) -> list[RouteResult]:
        cond = dict(conditions or {})
        self._preflight(source_edge, dest_edge, cond)

        blocked = {e for e, c in cond.items() if c.is_blocked}
        avoiding = self.graph.without_edges(blocked)
        if source_edge not in avoiding.edges:
            raise NoRouteError("the emergency vehicle's current road is blocked")
        if dest_edge not in avoiding.edges:
            raise NoRouteError("the destination road is blocked")

        graph = avoiding
        candidates = self._search(graph, source_edge, dest_edge, cond)
        fallback = False

        if not candidates and blocked:
            # The primary pass found nothing avoiding the blockage at all --
            # it's the only way through. Retry on the full graph: BLOCKED
            # edges are no longer excluded, just heavily penalised
            # (RouteCostModel folds `is_blocked` into a large finite
            # anomaly_norm precisely for this pass), so the search still
            # prefers any real alternative and only lands here when there
            # truly is none.
            graph = self.graph
            candidates = self._search(graph, source_edge, dest_edge, cond)
            fallback = True

        if not candidates:
            raise NoRouteError(
                "no route is currently available — the destination is isolated by "
                "active road blockages or congestion"
            )

        # the free-flow shortest path (ignores conditions, and blockages --
        # it's purely "what would the ideal path be") -- used to report which
        # anomalous edges the chosen route "avoided"
        ff = GraphSearchEngine(self.graph).shortest_path(
            source_edge, dest_edge, lambda _f, ge: self.graph.edges[ge.to_edge].free_flow_time_s
        )
        ff_edges = set(ff.edges)
        anomalous = {e for e, c in cond.items() if c.has_active_anomaly}

        results: list[RouteResult] = []
        for rank, cand in enumerate(candidates):
            # each route reports the blocked roads *it* crosses: in the
            # fallback pass an alternative may cross a different one than the
            # recommended route does, and must be flagged just the same
            crossed = blocked & set(cand.edges) if fallback else set()
            results.append(
                self._build_result(
                    cand.edges, cond, graph, ff_edges, anomalous, rank,
                    forced_through=frozenset(crossed),
                )
            )
        return results

    def _search(
        self,
        graph: RoadGraph,
        source_edge: str,
        dest_edge: str,
        cond: Mapping[str, EdgeConditions],
    ):
        """The recommended route plus up to `max_alternatives` genuinely
        different alternatives (see `GraphSearchEngine.k_shortest`)."""
        return GraphSearchEngine(graph).k_shortest(
            source_edge,
            dest_edge,
            self._weight(graph, cond),
            k=1 + max(0, self.config.max_alternatives),
            max_stretch=self.config.alternative_max_stretch,
            max_overlap=self.config.alternative_max_overlap,
        )

    def _weight(self, graph: RoadGraph, cond: Mapping[str, EdgeConditions]):
        def weight(from_edge: str, ge: GraphEdge) -> float:
            ec = cond.get(ge.to_edge)
            if ge.signalised:
                ec = _with_signal(ec)
            return self.cost_model.edge_cost(graph.edges[ge.to_edge], ec).weighted_total

        return weight

    def evaluate(
        self,
        edges: tuple[str, ...],
        conditions: Mapping[str, EdgeConditions] | None = None,
    ) -> RouteResult:
        """Cost an already-valid edge path under `conditions` and return its
        `RouteResult`. Continuous monitoring uses this to score the route a
        vehicle is currently on and compare it against a fresh `plan()` -- the
        route it returns is *not* run through the search, so `rank` is 0 and
        `anomalous_segments_avoided` is empty by construction.

        Raises `NoRouteError` if `edges` is empty, references an unknown road,
        or is not actually connected in the graph.
        """
        cond = dict(conditions or {})
        if not edges:
            raise NoRouteError("cannot evaluate an empty route")
        for e in edges:
            if not self.graph.has_edge(e):
                raise NoRouteError(f"route references unknown road {e!r}")
        for a, b in zip(edges, edges[1:], strict=False):
            if _find_graph_edge(self.graph, a, b) is None:
                raise NoRouteError(f"route is no longer connected between {a!r} and {b!r}")
        anomalous = {e for e, c in cond.items() if c.has_active_anomaly}
        blocked = {e for e, c in cond.items() if c.is_blocked}
        return self._build_result(
            tuple(edges), cond, self.graph, set(), anomalous, rank=0,
            forced_through=blocked & set(edges),
        )

    # ---- internals ----------------------------------------------

    def _preflight(
        self, source_edge: str, dest_edge: str, cond: Mapping[str, EdgeConditions]
    ) -> None:
        if not self.graph.has_edge(source_edge):
            raise NoRouteError(f"unknown source road {source_edge!r}")
        if not self.graph.has_edge(dest_edge):
            raise NoRouteError(f"unknown destination road {dest_edge!r}")
            
        if not self.graph.neighbours(source_edge):
            raise NoRouteError(
                f"cannot route from {source_edge!r} — it is a network terminus "
                "with no onward road connections"
            )
            
        has_incoming = any(
            dest_edge in [ge.to_edge for ge in ges]
            for ges in self.graph.adjacency.values()
        )
        if not has_incoming:
            raise NoRouteError(
                f"cannot route to {dest_edge!r} — it is a network boundary entry "
                "edge with no incoming roads"
            )

        problems = self.config.validate()
        if problems:
            raise NoRouteError(f"routing config is invalid: {problems[0]}")

    def _build_result(
        self,
        edges: tuple[str, ...],
        cond: Mapping[str, EdgeConditions],
        graph: RoadGraph,
        ff_edges: set[str],
        anomalous: set[str],
        rank: int,
        forced_through: frozenset[str] | set[str] = frozenset(),
    ) -> RouteResult:
        total_distance = 0.0
        travel_time_s = 0.0
        congestion_cost = 0.0
        anomaly_cost = 0.0
        signal_delay_s = 0.0
        disruption_cost = 0.0
        reliability_cost = 0.0
        weighted_total = 0.0
        signalised: list[str] = []
        congested: list[str] = []

        # per-edge cost for edges after the source (each is "entered" via a junction)
        prev_edge = edges[0]
        total_distance += graph.edges[edges[0]].length_m
        travel_time_s += graph.edges[edges[0]].free_flow_time_s
        for eid in edges[1:]:
            info = graph.edges[eid]
            ge = _find_graph_edge(graph, prev_edge, eid)
            ec = cond.get(eid)
            if ge is not None and ge.signalised:
                ec = _with_signal(ec)
                if ge.junction_id not in signalised:
                    signalised.append(ge.junction_id)
            parts = self.cost_model.edge_cost(info, ec)
            total_distance += info.length_m
            travel_time_s += parts.travel_time_s
            congestion_cost += parts.congestion_cost
            anomaly_cost += parts.anomaly_cost
            signal_delay_s += parts.signal_delay_s
            disruption_cost += parts.disruption_cost
            reliability_cost += parts.reliability_cost
            weighted_total += parts.weighted_total
            if (ec.congestion if ec else 0.0) >= _CONGESTED_AT:
                congested.append(eid)
            prev_edge = eid

        breakdown = RouteCostBreakdown(
            travel_time_s=round(travel_time_s, 1),
            congestion_cost=round(congestion_cost, 3),
            anomaly_cost=round(anomaly_cost, 3),
            signal_delay_s=round(signal_delay_s, 1),
            disruption_cost=round(disruption_cost, 3),
            reliability_cost=round(reliability_cost, 3),
            total_score=round(weighted_total, 3),
        )
        avoided = tuple(sorted(anomalous & ff_edges - set(edges)))
        n_intersections = max(0, len(edges) - 1)
        # A route forced through a BLOCKED edge is never "reliable", full
        # stop -- regardless of what the weighted reliability math says (a
        # short route with just one such edge could otherwise slip under
        # `reliability_reject_threshold`). This is the signal the UI keys its
        # "only route available, proceed with caution" warning off of.
        reliable = (
            not forced_through
            and reliability_cost <= self.config.reliability_reject_threshold
        )

        return RouteResult(
            edges=tuple(edges),
            total_distance_m=round(total_distance, 1),
            total_travel_time_s=round(travel_time_s, 1),
            eta_s=round(travel_time_s + signal_delay_s, 1),
            n_intersections=n_intersections,
            signalised_intersections=tuple(signalised),
            congested_segments=tuple(congested),
            anomalous_segments_avoided=avoided,
            forced_through=tuple(sorted(forced_through)),
            cost=breakdown,
            reliable=reliable,
            weights_used=self.config.as_dict(),
            rank=rank,
        )


def _find_graph_edge(graph: RoadGraph, frm: str, to: str) -> GraphEdge | None:
    for ge in graph.neighbours(frm):
        if ge.to_edge == to:
            return ge
    return None


def _with_signal(ec: EdgeConditions | None) -> EdgeConditions:
    if ec is None:
        return EdgeConditions(entry_is_signalised=True)
    if ec.entry_is_signalised:
        return ec
    return EdgeConditions(
        congestion=ec.congestion,
        mean_speed_frac=ec.mean_speed_frac,
        congestion_variance=ec.congestion_variance,
        anomaly_severity=ec.anomaly_severity,
        anomaly_impact=ec.anomaly_impact,
        entry_is_signalised=True,
        entry_signal_phase=ec.entry_signal_phase,
    )

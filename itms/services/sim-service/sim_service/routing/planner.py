"""`RoutePlanner` -- graph + cost model + search, producing explainable
`RouteResult`s.

`plan()` returns the recommended route first, then up to
`config.max_alternatives` genuinely-different alternatives, each carrying the
full `RouteCostBreakdown` and the lists the "why this route" panel needs
(signalised intersections, congested segments, anomalous segments avoided).

Failure is a typed `NoRouteError` with a human-readable reason -- never a raw
exception or an empty list without explanation.
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
        graph = self.graph.without_edges(blocked)
        if source_edge not in graph.edges:
            raise NoRouteError("the emergency vehicle's current road is blocked")
        if dest_edge not in graph.edges:
            raise NoRouteError("the destination road is blocked")

        engine = GraphSearchEngine(graph)

        def weight(from_edge: str, ge: GraphEdge) -> float:
            ec = cond.get(ge.to_edge)
            if ge.signalised:
                ec = _with_signal(ec)
            return self.cost_model.edge_cost(graph.edges[ge.to_edge], ec).weighted_total

        candidates = engine.k_shortest(
            source_edge, dest_edge, weight, k=1 + max(0, self.config.max_alternatives)
        )
        if not candidates:
            raise NoRouteError(
                "no route is currently available — the destination is isolated by "
                "active road blockages or congestion"
            )

        # the free-flow shortest path (ignores conditions) -- used to report
        # which anomalous edges the chosen route "avoided"
        ff = engine.shortest_path(
            source_edge, dest_edge, lambda _f, ge: graph.edges[ge.to_edge].free_flow_time_s
        )
        ff_edges = set(ff.edges)
        anomalous = {e for e, c in cond.items() if c.has_active_anomaly}

        results: list[RouteResult] = []
        for rank, cand in enumerate(candidates):
            results.append(
                self._build_result(cand.edges, cond, graph, ff_edges, anomalous, rank)
            )
        return results

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
        return self._build_result(tuple(edges), cond, self.graph, set(), anomalous, rank=0)

    # ---- internals ----------------------------------------------

    def _preflight(
        self, source_edge: str, dest_edge: str, cond: Mapping[str, EdgeConditions]
    ) -> None:
        if not self.graph.has_edge(source_edge):
            raise NoRouteError(f"unknown source road {source_edge!r}")
        if not self.graph.has_edge(dest_edge):
            raise NoRouteError(f"unknown destination road {dest_edge!r}")
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
        reliable = reliability_cost <= self.config.reliability_reject_threshold

        return RouteResult(
            edges=tuple(edges),
            total_distance_m=round(total_distance, 1),
            total_travel_time_s=round(travel_time_s, 1),
            eta_s=round(travel_time_s + signal_delay_s, 1),
            n_intersections=n_intersections,
            signalised_intersections=tuple(signalised),
            congested_segments=tuple(congested),
            anomalous_segments_avoided=avoided,
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

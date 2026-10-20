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
from dataclasses import replace

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
        cost_model=None,
        *,
        static_prior: bool = False,
    ):
        """`cost_model` defaults to the weighted `RouteCostModel`; pass an
        `EtaCostModel` to cost routes in seconds (its A* heuristic is then
        used too)."""
        self.graph = graph
        self.config = config or EmergencyRoutingConfig()
        self.cost_model = cost_model or RouteCostModel(self.config)
        # static_prior: the route that is best with no live traffic data
        # (lanes, turns, signals, anomalies only) is kept unless the live best
        # route beats it by the reroute margin. Live data about roads minutes
        # ahead is a weak forecast; small predicted gains from it are noise.
        self.static_prior = static_prior

    def plan(
        self,
        source_edge: str,
        dest_edge: str,
        conditions: Mapping[str, EdgeConditions] | None = None,
        *,
        allowed_edges: set[str] | None = None,
    ) -> list[RouteResult]:
        """`allowed_edges` limits the search to a band of edges (hex band);
        if no route exists inside it, the full graph is searched."""
        cond = dict(conditions or {})
        source_edge, dest_edge = self.usable_ends(source_edge, dest_edge)
        self._preflight(source_edge, dest_edge, cond)
        res = None
        if allowed_edges is not None:
            band = set(allowed_edges) | {source_edge, dest_edge}
            try:
                res = self._plan_on(self.graph.subgraph(band), source_edge, dest_edge, cond)
            except NoRouteError:
                res = None
        if not res:
            res = self._plan_on(self.graph, source_edge, dest_edge, cond)
        if self.static_prior and hasattr(self.cost_model, "config"):
            res = self._apply_static_prior(res, source_edge, dest_edge, cond)
        return res

    def _apply_static_prior(self, res, source_edge, dest_edge, cond):
        from sim_service.routing.eta_cost import should_reroute

        static_cond = {
            e: EdgeConditions(anomaly_severity=c.anomaly_severity, anomaly_impact=c.anomaly_impact)
            for e, c in cond.items()
            if c.has_active_anomaly
        }
        try:
            prior_edges = self._plan_on(self.graph, source_edge, dest_edge, static_cond)[0].edges
            prior = self.evaluate(prior_edges, cond)
        except NoRouteError:
            return res
        if prior.edges == res[0].edges or prior.forced_through:
            return res
        if should_reroute(prior.score, res[0].score, self.cost_model.config):
            return res
        return [replace(prior, anomalous_segments_avoided=res[0].anomalous_segments_avoided)] + [
            r for r in res if r.edges != prior.edges
        ]

    def _search(self, graph: RoadGraph, source_edge, dest_edge, cond, k):
        h = None
        if hasattr(self.cost_model, "heuristic"):
            h = self.cost_model.heuristic(graph, dest_edge)
        return GraphSearchEngine(graph).k_shortest(
            source_edge, dest_edge, self._weight(graph, cond), k=k, heuristic=h
        )

    def _plan_on(
        self,
        full: RoadGraph,
        source_edge: str,
        dest_edge: str,
        cond: dict,
    ) -> list[RouteResult]:

        # The two ends of a trip are never avoided, blocked or not: a vehicle
        # on a closed road still has to drive off it, and a closed road is
        # exactly where police, ambulance and fire are sent. Refusing them
        # meant no responder could ever reach a BLOCKED incident, and an
        # ambulance at one could not leave for the hospital.
        blocked = {e for e, c in cond.items() if c.is_blocked} - {source_edge, dest_edge}
        avoiding = full.without_edges(blocked)

        k = 1 + max(0, self.config.max_alternatives)
        graph = avoiding
        candidates = self._search(graph, source_edge, dest_edge, cond, k)
        forced_through: frozenset[str] = frozenset()

        if not candidates and blocked:
            # The primary pass found nothing avoiding the blockage at all --
            # it's the only way through. Retry on the full graph: BLOCKED
            # edges are no longer excluded, just heavily penalised
            # (RouteCostModel folds `is_blocked` into a large finite
            # anomaly_norm precisely for this pass), so the search still
            # prefers any real alternative and only lands here when there
            # truly is none.
            graph = full
            candidates = self._search(graph, source_edge, dest_edge, cond, k)
            if candidates:
                forced_through = blocked & set(candidates[0].edges)

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
            results.append(
                self._build_result(
                    cand.edges, cond, graph, ff_edges, anomalous, rank,
                    forced_through=forced_through & set(cand.edges),
                )
            )
        return results

    def _weight(self, graph: RoadGraph, cond: Mapping[str, EdgeConditions]):
        def weight(from_edge: str, ge: GraphEdge) -> float:
            ec = cond.get(ge.to_edge)
            if ge.signalised:
                ec = _with_signal(ec)
            return self.cost_model.edge_cost(
                graph.edges[ge.to_edge], ec, ge, graph.edges.get(from_edge), cond.get(from_edge)
            ).weighted_total

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

    def usable_ends(self, source_edge: str, dest_edge: str) -> tuple[str, str]:
        """The roads a trip between these two can actually start and end on.

        A road that leads nowhere (it leaves the map) cannot start a trip, and
        one nothing leads into (it enters the map) cannot end one. A unit
        parked on the first, or an incident on the second, used to be simply
        unreachable. Both are usually one carriageway of a two-way road in OSM
        data, so the trip uses the other carriageway of the same road (SUMO
        names it with the sign flipped: "123#4" / "-123#4"); failing that, a
        start moves back along the road to where it can turn off, and an end
        moves on to the road just after.

        Last, a destination the start cannot reach at all -- a stretch of road
        the map extract cut off from everything else -- becomes the nearest
        road that can be reached, when `edge_points` (road midpoints) is set:
        responders stop on the closest connected road rather than not go.
        """
        g = self.graph
        if g.has_edge(source_edge) and not g.neighbours(source_edge):
            alt = _reverse_edge(source_edge)
            if g.has_edge(alt) and g.neighbours(alt):
                source_edge = alt
            else:
                source_edge = self._way_out(source_edge) or source_edge
        entered = self._entered_edges()
        if g.has_edge(dest_edge) and dest_edge not in entered:
            alt = _reverse_edge(dest_edge)
            if g.has_edge(alt) and alt in entered:
                dest_edge = alt
            else:
                after = sorted(
                    ge.to_edge for ge in g.neighbours(dest_edge) if ge.to_edge in entered
                )
                if after:
                    dest_edge = after[0]
        points = getattr(self, "edge_points", None)
        if points and g.has_edge(source_edge) and dest_edge in points:
            reach = self._reachable(source_edge)
            if dest_edge not in reach:
                px, py = points[dest_edge]
                near = [e for e in reach if e in points and e != source_edge]
                if near:
                    dest_edge = min(
                        near, key=lambda e: (points[e][0] - px) ** 2 + (points[e][1] - py) ** 2
                    )
        return source_edge, dest_edge

    def _way_out(self, dead_end: str) -> str | None:
        """The nearest road behind a dead end from which another road leads
        off, walking back along the roads that feed it."""
        preds: dict[str, list[str]] = {}
        for e, ges in self.graph.adjacency.items():
            for ge in ges:
                preds.setdefault(ge.to_edge, []).append(e)
        seen, frontier = {dead_end}, [dead_end]
        for _ in range(12):
            nxt: list[str] = []
            for e in frontier:
                for p in sorted(preds.get(e, ())):
                    if p in seen:
                        continue
                    seen.add(p)
                    if any(ge.to_edge not in seen for ge in self.graph.neighbours(p)):
                        return p
                    nxt.append(p)
            frontier = nxt
            if not frontier:
                break
        return None

    def _reachable(self, source_edge: str) -> set[str]:
        """Every road a trip starting on `source_edge` can get to."""
        seen, stack = {source_edge}, [source_edge]
        while stack:
            for ge in self.graph.neighbours(stack.pop()):
                if ge.to_edge not in seen:
                    seen.add(ge.to_edge)
                    stack.append(ge.to_edge)
        return seen

    def _entered_edges(self) -> set[str]:
        """Every road some other road leads into (cached: the graph is fixed)."""
        if getattr(self, "_entered_for", None) is not self.graph:
            self._entered_cache = {
                ge.to_edge for ges in self.graph.adjacency.values() for ge in ges
            }
            self._entered_for = self.graph
        return self._entered_cache

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
            
        if dest_edge not in self._entered_edges():
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
            parts = self.cost_model.edge_cost(
                info, ec, ge, graph.edges.get(prev_edge), cond.get(prev_edge)
            )
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
    return replace(ec, entry_is_signalised=True)


def _reverse_edge(edge_id: str) -> str:
    """SUMO's id for the other carriageway of an OSM two-way road."""
    return edge_id[1:] if edge_id.startswith("-") else f"-{edge_id}"

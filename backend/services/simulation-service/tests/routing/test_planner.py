"""`RoutePlanner` -- graph + cost + search producing explainable RouteResults,
and its error handling."""

from __future__ import annotations

import math

import pytest
from _synthetic import edge, linear_graph
from itms_domain import EmergencyRoutingConfig
from sim_service.routing.cost import EdgeConditions
from sim_service.routing.graph import GraphEdge, RoadGraph
from sim_service.routing.planner import NoRouteError, RoutePlanner


def _diamond(b_len: float = 180.0) -> RoadGraph:
    """S -> {A, B} -> T. A is short but can carry an anomaly; B is longer."""
    edges = {
        "S": edge("S", 100.0, to="jS"),
        "A": edge("A", 100.0, to="jA"),
        "B": edge("B", b_len, to="jB"),
        "T": edge("T", 100.0, to="jT"),
    }
    adjacency = {
        "S": (
            GraphEdge("A", "jA", False, None),
            GraphEdge("B", "jB", False, None),
        ),
        "A": (GraphEdge("T", "jT", True, "TL1"),),
        "B": (GraphEdge("T", "jT", False, None),),
    }
    return RoadGraph(
        edges=edges,
        adjacency=adjacency,
        signalised_junctions=frozenset({"jT"}),
    )


# ---- happy paths -----------------------------------------------------


def test_plan_returns_the_recommended_route_first_with_a_full_breakdown():
    planner = RoutePlanner(linear_graph(4))
    routes = planner.plan("E0", "E3")
    r = routes[0]
    assert r.edges == ("E0", "E1", "E2", "E3")
    assert r.rank == 0
    assert r.eta_s > 0 and r.total_distance_m > 0
    assert r.n_intersections == 3
    assert r.cost.total_score > 0
    # every component present in the summary the UI shows
    s = r.summary()
    assert set(s["cost"]) >= {
        "travel_time_s", "congestion_cost", "anomaly_cost", "signal_delay_s",
        "disruption_cost", "reliability_cost", "total_score",
    }
    assert s["weights_used"]["anomaly_weight"] == EmergencyRoutingConfig().anomaly_weight


def test_a_high_severity_anomaly_pushes_the_route_off_the_short_branch():
    planner = RoutePlanner(_diamond())
    clean = planner.plan("S", "T")[0]
    assert clean.edges == ("S", "A", "T")  # short branch when nothing is wrong

    cond = {"A": EdgeConditions(anomaly_severity="high", anomaly_impact=0.85)}
    diverted = planner.plan("S", "T", cond)[0]
    assert diverted.edges == ("S", "B", "T")  # now the longer branch wins
    assert "A" in diverted.anomalous_segments_avoided


def test_blocked_edge_is_removed_and_the_route_goes_around_it():
    planner = RoutePlanner(_diamond())
    cond = {"A": EdgeConditions(anomaly_severity="blocked")}
    r = planner.plan("S", "T", cond)[0]
    assert "A" not in r.edges
    assert r.edges == ("S", "B", "T")
    assert not r.forced_through  # a real alternative existed -- never forced
    assert r.reliable


def _single_path_graph() -> RoadGraph:
    """S -> M -> T, one road, no bypass -- the "only one route" case."""
    edges = {
        "S": edge("S", 100.0, to="jM"),
        "M": edge("M", 100.0, to="jT"),
        "T": edge("T", 100.0, to="jEnd"),
    }
    adjacency = {
        "S": (GraphEdge("M", "jT", False, None),),
        "M": (GraphEdge("T", "jEnd", False, None),),
    }
    return RoadGraph(edges=edges, adjacency=adjacency, signalised_junctions=frozenset())  # type: ignore[arg-type]


def test_blocked_edge_on_the_only_route_is_crossed_anyway_as_a_last_resort():
    """No alternative exists around the blockage -- plan() must still return
    a route (the operator's only option), not fail the whole mission."""
    planner = RoutePlanner(_single_path_graph())
    cond = {"M": EdgeConditions(anomaly_severity="blocked")}
    r = planner.plan("S", "T", cond)[0]
    assert r.edges == ("S", "M", "T")           # the only physical path
    assert r.forced_through == ("M",)           # named, so the UI can warn
    assert not r.reliable                       # never "reliable" when forced
    assert math.isfinite(r.eta_s) and r.eta_s > 0
    assert math.isfinite(r.cost.total_score)    # displayable, not +inf


def test_forced_through_route_still_prefers_a_real_alternative_when_one_exists():
    """Sanity check that the fallback pass doesn't make BLOCKED edges "free" --
    given a real choice, the search still avoids one."""
    planner = RoutePlanner(_diamond())
    cond = {"A": EdgeConditions(anomaly_severity="blocked")}
    r = planner.plan("S", "T", cond)[0]
    assert r.edges == ("S", "B", "T")
    assert not r.forced_through


def test_signalised_intersections_and_congested_segments_are_reported():
    # B is very long here, so the route stays on S-A-T despite congestion on A
    planner = RoutePlanner(_diamond(b_len=900.0))
    cond = {"A": EdgeConditions(congestion=0.8)}
    r = planner.plan("S", "T", cond)[0]
    assert r.edges == ("S", "A", "T")
    assert r.signalised_intersections == ("jT",)
    assert "A" in r.congested_segments
    assert r.cost.signal_delay_s > 0


def test_alternatives_are_returned_and_ranked():
    # the bypass costs ~1.66x the direct chain: allow that much stretch here
    planner = RoutePlanner(
        linear_graph(6), EmergencyRoutingConfig(max_alternatives=1, alternative_max_stretch=2.0)
    )
    routes = planner.plan("E0", "E5")
    assert len(routes) == 2
    assert routes[0].cost.total_score <= routes[1].cost.total_score
    assert routes[0].rank == 0 and routes[1].rank == 1
    assert routes[0].edges != routes[1].edges


def test_weights_change_which_route_is_recommended():
    g = _diamond()
    cond = {"A": EdgeConditions(anomaly_severity="medium", anomaly_impact=0.4)}
    # anomaly-averse config avoids A; anomaly-blind config keeps the short A
    averse = RoutePlanner(g, EmergencyRoutingConfig(anomaly_weight=5.0)).plan("S", "T", cond)[0]
    blind = RoutePlanner(g, EmergencyRoutingConfig(anomaly_weight=0.0)).plan("S", "T", cond)[0]
    assert averse.edges == ("S", "B", "T")
    assert blind.edges == ("S", "A", "T")


# ---- error handling -------------------------------------------------


def test_unknown_source_or_destination_raises_with_a_reason():
    planner = RoutePlanner(linear_graph(3))
    with pytest.raises(NoRouteError) as ei:
        planner.plan("ghost", "E2")
    assert "ghost" in ei.value.reason
    with pytest.raises(NoRouteError):
        planner.plan("E0", "ghost")


def test_isolated_destination_raises_no_route():
    g = RoadGraph(
        edges={"E0": edge("E0"), "ISL": edge("ISL")},
        adjacency={"E0": ()},
        signalised_junctions=frozenset(),
    )
    with pytest.raises(NoRouteError) as ei:
        RoutePlanner(g).plan("E0", "ISL")
    assert "isolated" in ei.value.reason or "terminus" in ei.value.reason


def test_blocked_ends_of_a_trip_are_still_driven():
    """Responders are sent *to* blocked roads, and leave them again (an
    ambulance at a blocked accident going on to hospital)."""
    planner = RoutePlanner(_diamond())
    blocked = EdgeConditions(anomaly_severity="blocked")
    assert planner.plan("S", "T", {"S": blocked})[0].edges[0] == "S"
    assert planner.plan("S", "T", {"T": blocked})[0].edges[-1] == "T"


def test_a_trip_starting_on_a_dead_end_or_ending_on_an_entry_road_uses_the_other_carriageway():
    """'-S' (S's other carriageway) leads nowhere; '-T' is entered by nothing.
    A unit parked on '-S' starts on 'S'; an incident on '-T' is reached via 'T'."""
    g = _diamond()
    edges = {**g.edges, "-S": edge("-S", 100.0, to="jS0"), "-T": edge("-T", 100.0, to="jT0")}
    adjacency = {**g.adjacency, "-T": (GraphEdge("-S", "jS0", False, None),)}
    planner = RoutePlanner(RoadGraph(edges=edges, adjacency=adjacency,
                                     signalised_junctions=g.signalised_junctions))
    assert planner.usable_ends("-S", "-T") == ("S", "T")
    route = planner.plan("-S", "-T")[0]
    assert route.edges[0] == "S" and route.edges[-1] == "T"

def test_invalid_config_is_rejected_before_searching():
    bad = EmergencyRoutingConfig(travel_time_weight=-1.0)
    with pytest.raises(NoRouteError) as ei:
        RoutePlanner(linear_graph(3), bad).plan("E0", "E2")
    assert "config" in ei.value.reason


# ---- evaluate() : cost a known path (Phase 7 monitoring) -----------


def test_evaluate_scores_a_known_path_under_current_conditions():
    planner = RoutePlanner(linear_graph(4))
    clean = planner.evaluate(("E0", "E1", "E2", "E3"))
    assert clean.edges == ("E0", "E1", "E2", "E3")
    assert clean.rank == 0
    congested = planner.evaluate(
        ("E0", "E1", "E2", "E3"),
        {"E2": EdgeConditions(congestion=0.9, mean_speed_frac=0.15)},
    )
    assert congested.score > clean.score  # same path costs more when the road ahead clogs


def test_evaluate_rejects_a_disconnected_or_unknown_path():
    planner = RoutePlanner(linear_graph(4))
    with pytest.raises(NoRouteError):
        planner.evaluate(("E0", "E3"))          # not adjacent
    with pytest.raises(NoRouteError):
        planner.evaluate(("E0", "ghost"))       # unknown edge
    with pytest.raises(NoRouteError):
        planner.evaluate(())                    # empty


def test_evaluate_then_plan_is_the_monitoring_comparison():
    """A blockage on the current path makes evaluate() score it far above a
    fresh plan() from the same origin -- the signal Phase 7 reroutes on."""
    planner = RoutePlanner(_diamond())
    cond = {"A": EdgeConditions(congestion=0.95, mean_speed_frac=0.1)}
    on_route = planner.evaluate(("S", "A", "T"), cond)
    best = planner.plan("S", "T", cond)[0]
    assert best.edges == ("S", "B", "T")
    assert on_route.score > best.score


def test_a_unit_parked_on_a_one_way_dead_end_starts_where_it_can_turn_off():
    """'D' leads only into the dead end 'X' (no other carriageway): a trip
    from 'X' starts back on 'S', the nearest road with another way out."""
    g = _diamond()
    edges = {**g.edges, "D": edge("D", 50.0, to="jD"), "X": edge("X", 50.0, to="jX")}
    adjacency = {**g.adjacency, "S": (*g.adjacency["S"], GraphEdge("D", "jD", False, None)),
                 "D": (GraphEdge("X", "jX", False, None),)}
    planner = RoutePlanner(RoadGraph(edges=edges, adjacency=adjacency,
                                     signalised_junctions=g.signalised_junctions))
    assert planner.usable_ends("X", "T")[0] == "S"
    assert planner.plan("X", "T")[0].edges[0] == "S"


def test_a_cut_off_road_is_served_from_the_nearest_reachable_one():
    g = _diamond()
    edges = {**g.edges, "I": edge("I", 50.0, to="jI"), "-I": edge("-I", 50.0, to="jI0")}
    adjacency = {**g.adjacency, "I": (GraphEdge("-I", "jI0", False, None),),
                 "-I": (GraphEdge("I", "jI", False, None),)}
    planner = RoutePlanner(RoadGraph(edges=edges, adjacency=adjacency,
                                     signalised_junctions=g.signalised_junctions))
    planner.edge_points = {"S": (0, 0), "A": (100, 50), "B": (100, -50), "T": (200, 0),
                           "I": (110, 60), "-I": (110, 60)}
    assert planner.usable_ends("S", "I") == ("S", "A")
    assert planner.plan("S", "I")[0].edges[-1] == "A"


def test_an_alternative_much_costlier_than_the_best_is_not_offered():
    # same graph, default stretch 1.6: the 1.66x bypass is not a real choice
    routes = RoutePlanner(linear_graph(6), EmergencyRoutingConfig(max_alternatives=1)).plan("E0", "E5")
    assert [r.edges for r in routes] == [("E0", "E1", "E2", "E3", "E4", "E5")]

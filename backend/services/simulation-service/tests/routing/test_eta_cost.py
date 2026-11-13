"""EtaCostModel, should_reroute and HexIndex."""

import pytest
from sim_service.routing import EdgeConditions, RoadGraph, RoutePlanner
from sim_service.routing.eta_cost import (
    EtaCostConfig,
    EtaCostModel,
    should_reroute,
    traffic_speed_frac,
)
from sim_service.routing.graph import EdgeInfo, GraphEdge
from sim_service.routing.hexgrid import HexIndex, cell_of, disk


def _edge(eid, x0, x1, y=0.0, lanes=1, length=None, speed=10.0):
    return EdgeInfo(eid, length or abs(x1 - x0), lanes, speed, f"j{eid}a", f"j{eid}b",
                    (x0, y), (x1, y))


def _two_route_graph():
    # S -> A -> T (short, single lane) and S -> B -> T (longer, signalised, 3 lanes)
    edges = {
        "S": _edge("S", 0, 100),
        "A": _edge("A", 100, 600),
        "B": _edge("B", 100, 600, length=650, lanes=3),
        "T": _edge("T", 600, 700),
    }
    adj = {
        "S": (GraphEdge("A", "j1", False, None), GraphEdge("B", "j1", True, "TL1")),
        "A": (GraphEdge("T", "j2", False, None),),
        "B": (GraphEdge("T", "j2", False, None),),
    }
    return RoadGraph(edges=edges, adjacency=adj, signalised_junctions=frozenset({"j1"}),
                     lefthand=True)


def test_cost_is_seconds_and_free_flow_matches_length_over_speed():
    m = EtaCostModel(EtaCostConfig(ev_speed_factor=1.0))
    p = m.edge_cost(_edge("x", 0, 100), EdgeConditions(mean_speed_frac=1.0))
    assert abs(p.weighted_total - 10.0) < 1e-9


def test_jam_slows_single_lane_more_than_multilane():
    m = EtaCostModel()
    jam = EdgeConditions(mean_speed_frac=0.1)
    one = m.edge_cost(_edge("a", 0, 500, lanes=1), jam).weighted_total
    three = m.edge_cost(_edge("b", 0, 500, lanes=3), jam).weighted_total
    assert three < one


def test_preempted_signal_costs_only_crossing_when_queue_clears_in_lead():
    m = EtaCostModel()
    ge = GraphEdge("e", "j", True, "TL")
    small_q = m.junction_s(ge, _edge("f", 0, 100, lanes=2), EdgeConditions(halting=4),
                           EdgeConditions())
    assert small_q == m.config.crossing_s
    big_q = m.junction_s(ge, _edge("f", 0, 100, lanes=1), EdgeConditions(halting=30),
                         EdgeConditions())
    assert big_q > m.config.crossing_s


def test_cross_turn_depends_on_driving_side():
    lh, rh = EtaCostModel(lefthand=True), EtaCostModel(lefthand=False)
    assert lh.turn_s("r") > lh.turn_s("l")
    assert rh.turn_s("l") > rh.turn_s("r")


def test_router_takes_longer_multilane_road_when_short_one_is_jammed():
    g = _two_route_graph()
    planner = RoutePlanner(g, cost_model=EtaCostModel(lefthand=True))
    free = planner.plan("S", "T", {})[0]
    assert free.edges == ("S", "A", "T")
    jam = {"A": EdgeConditions(mean_speed_frac=0.05, halting=40)}
    assert planner.plan("S", "T", jam)[0].edges == ("S", "B", "T")


def test_should_reroute_needs_margin_plus_switch_cost():
    c = EtaCostConfig()
    assert not should_reroute(200.0, 185.0, c)   # 15 s saving < 15 + 5
    assert should_reroute(200.0, 170.0, c)       # 30 s saving > 17 + 5


def test_hex_cells_and_band():
    assert cell_of(0, 0, 100) == (0, 0)
    assert len(disk((0, 0), 1)) == 7
    g = _two_route_graph()
    h = HexIndex(g, size_m=100)
    band = h.band("S", "T", rings=1)
    assert band is not None and {"S", "T"} <= band
    planner = RoutePlanner(g, cost_model=EtaCostModel())
    assert planner.plan("S", "T", {}, allowed_edges=band)[0].edges[0] == "S"


def _frac(**kw):
    base = dict(mean_speed_mps=13.9, vehicles=0, halting=0, length_m=400.0, lanes=1,
                speed_limit_mps=13.9)
    base.update(kw)
    return traffic_speed_frac(**base)


def test_one_slow_car_does_not_slow_a_whole_road():
    """One car pulling away on a 396 m road read as speed 0.02 of the limit
    and made the road cost 139 s instead of 24 s."""
    assert _frac(mean_speed_mps=0.3, vehicles=1, length_m=396.0) > 0.95


def test_standing_vehicles_are_the_queue_not_the_speed():
    # two cars at a red light: charged as queue (halting), not as a slow road
    assert _frac(mean_speed_mps=0.0, vehicles=2, halting=2) == 1.0
    # 15 standing, 10 moving at 5.2 m/s: the speed is the movers', not the mean
    f = _frac(mean_speed_mps=2.08, vehicles=25, halting=15, length_m=216.0)
    assert 0.4 < f < 0.7


def test_dense_slow_traffic_still_slows_the_road():
    # 30 cars spread along 400 m at 4 m/s: the whole road moves at that speed
    assert _frac(mean_speed_mps=4.0, vehicles=30) == pytest.approx(4.0 / 13.9)
    assert _frac(vehicles=0) == 1.0 and _frac(mean_speed_mps=-1.0, vehicles=3) == 1.0


"""`RoadGraph.from_network` against the real Vijayawada corridor .net.xml
(XML parse only, no SUMO)."""

from __future__ import annotations

from itms_domain.paths import DATA_DIR
from sim_service.routing.graph import RoadGraph

_NET = (
    DATA_DIR
    / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
)


def _graph() -> RoadGraph:
    return RoadGraph.from_network(_NET)


def test_nodes_are_the_33_real_edges_with_static_attrs():
    g = _graph()
    assert len(g.edges) == 33
    for info in g.edges.values():
        assert info.length_m > 0
        assert info.num_lanes >= 1
        assert info.speed_limit_mps > 0
        assert info.free_flow_time_s > 0
        assert not info.edge_id.startswith(":")


def test_seven_signalised_junctions():
    assert len(_graph().signalised_junctions) == 7


def test_adjacency_is_directed_and_non_trivial():
    g = _graph()
    total_links = sum(len(v) for v in g.adjacency.values())
    assert total_links >= 33  # at least one onward move per through edge, roughly
    # every adjacency target is a real node
    for src, ges in g.adjacency.items():
        assert src in g.edges
        for ge in ges:
            assert ge.to_edge in g.edges
            assert ge.junction_id == g.edges[ge.to_edge].from_junction


def test_at_least_one_graph_edge_is_signalised_and_carries_its_tl():
    g = _graph()
    sig = [ge for ges in g.adjacency.values() for ge in ges if ge.signalised]
    assert sig, "no signalised movements found"
    assert all(ge.tl_id for ge in sig)
    assert all(g.is_signalised_junction(ge.junction_id) for ge in sig)


def test_without_edges_drops_nodes_and_incident_links():
    g = _graph()
    victim = next(iter(g.edges))
    g2 = g.without_edges([victim])
    assert victim not in g2.edges
    assert victim not in g2.adjacency
    for ges in g2.adjacency.values():
        assert all(ge.to_edge != victim for ge in ges)
    # unrelated edges survive
    assert len(g2.edges) == len(g.edges) - 1


def test_without_edges_is_a_noop_for_unknown_ids():
    g = _graph()
    assert g.without_edges(["nope"]) is g

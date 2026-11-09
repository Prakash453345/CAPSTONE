"""Depots and hospitals recorded on the corridor network must land on roads the
district graph has, or every dispatch from them fails "unknown source road"."""

import json

from itms_domain.paths import VIJAYAWADA_NET_DIR

from sim_service.routing import RoadGraph
from sim_service.routing.snap import EdgeSnapper

NET = VIJAYAWADA_NET_DIR / "vijayawada_district.net.xml"


def test_every_depot_and_facility_resolves_to_a_district_road() -> None:
    graph = RoadGraph.from_network(NET)
    snapper = EdgeSnapper(NET, graph)
    depots = json.loads((VIJAYAWADA_NET_DIR / "responder_depots.json").read_text())["depots"]
    facilities = json.loads((VIJAYAWADA_NET_DIR / "facilities.json").read_text())["facilities"]
    for place in [*depots, *facilities]:
        edge = snapper.snap(place["edge"], place["lat"], place["lon"])
        assert graph.has_edge(edge), place["name"]
        assert graph.neighbours(edge), f"{place['name']} snapped to a dead end"


def test_a_known_road_is_left_alone() -> None:
    graph = RoadGraph.from_network(NET)
    edge = next(e for e in sorted(graph.edges) if graph.neighbours(e))
    assert EdgeSnapper(NET, graph).snap(edge, 0.0, 0.0) == edge

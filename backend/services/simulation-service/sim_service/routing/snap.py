"""Put a place (a hospital, a police station) on a road the routing graph has.

`facilities.json` and `responder_depots.json` were snapped to the corridor
network. The district network re-splits and renames roads, so a depot's `edge`
can be a road the district graph has never heard of: a unit parked there fails
every dispatch with "unknown source road". Whatever network is loaded, a place
whose recorded road is missing is re-snapped here to the nearest road that
exists, can be entered and can be left."""

from __future__ import annotations

from pathlib import Path

from sim_service.routing.graph import RoadGraph

_RADII_M = (60.0, 150.0, 400.0, 1000.0, 2500.0)


class EdgeSnapper:
    def __init__(self, net_path: str | Path, graph: RoadGraph) -> None:
        import sumolib

        self._net = sumolib.net.readNet(str(net_path))
        self._graph = graph
        self._entered = {ge.to_edge for ges in graph.adjacency.values() for ge in ges}

    def _usable(self, edge_id: str) -> bool:
        return (
            self._graph.has_edge(edge_id)
            and bool(self._graph.neighbours(edge_id))
            and edge_id in self._entered
        )

    def snap(self, edge_id: str, lat: float, lon: float) -> str:
        """`edge_id` if the graph has it, else the nearest usable road to
        (lat, lon); the original id if nothing is within a kilometre."""
        if self._graph.has_edge(edge_id):
            return edge_id
        x, y = self._net.convertLonLat2XY(lon, lat)
        for radius in _RADII_M:
            near = [
                (dist, e.getID())
                for e, dist in self._net.getNeighboringEdges(x, y, radius)
                if self._usable(e.getID())
            ]
            if near:
                return min(near)[1]
        return edge_id

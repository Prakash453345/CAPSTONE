"""A hand-built RoadGraph for the search / planner tests -- a small directed
grid so routes have real choices without needing the .net.xml."""

from __future__ import annotations

from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph


def edge(
    eid: str, length: float = 100.0, speed: float = 10.0, frm: str = "", to: str = ""
) -> EdgeInfo:
    return EdgeInfo(
        edge_id=eid,
        length_m=length,
        num_lanes=1,
        speed_limit_mps=speed,
        from_junction=frm or f"{eid}_a",
        to_junction=to or f"{eid}_b",
        start_xy=(0.0, 0.0),
        end_xy=(length, 0.0),
    )


def linear_graph(n: int, *, length: float = 100.0) -> RoadGraph:
    """E0 -> E1 -> ... -> E{n-1}, plus a parallel bypass E0 -> B -> E{n-1}
    that is longer, so there is a real cost decision."""
    edges = {f"E{i}": edge(f"E{i}", length, to=f"j{i}") for i in range(n)}
    edges["B"] = edge("B", length * (n - 1) * 1.4, to="jB")  # long bypass
    adjacency: dict[str, list[GraphEdge]] = {}
    for i in range(n - 1):
        adjacency.setdefault(f"E{i}", []).append(
            GraphEdge(to_edge=f"E{i+1}", junction_id=f"j{i+1}", signalised=False, tl_id=None)
        )
    adjacency.setdefault("E0", []).append(
        GraphEdge(to_edge="B", junction_id="jB", signalised=False, tl_id=None)
    )
    adjacency.setdefault("B", []).append(
        GraphEdge(to_edge=f"E{n-1}", junction_id=f"j{n-1}", signalised=True, tl_id="TL9")
    )
    return RoadGraph(
        edges=edges,
        adjacency={k: tuple(v) for k, v in adjacency.items()},
        signalised_junctions=frozenset({f"j{n-1}"}),
    )

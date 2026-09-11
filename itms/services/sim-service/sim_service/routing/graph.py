"""The routable road graph, built once from a SUMO `.net.xml`.

Nodes are real edges (internal `:`-prefixed edges are excluded); a directed
graph edge `A -> B` exists when the network has a `<connection from="A"
to="B">`. Each graph edge remembers the junction crossed to enter `B` and
whether that movement is signal-controlled (the connection carries a `tl`
attribute) -- that's what the cost model's signal-delay term keys on.

Static only: length, lane count, speed limit, geometry endpoints. Live state
(congestion, queues, signal phase, anomalies) is supplied separately as
`EdgeConditions`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EdgeInfo:
    edge_id: str
    length_m: float
    num_lanes: int
    speed_limit_mps: float
    from_junction: str
    to_junction: str
    # network-local coords of the edge's endpoints (SUMO x,y metres), for an
    # optional A* heuristic and for reporting
    start_xy: tuple[float, float]
    end_xy: tuple[float, float]

    @property
    def free_flow_time_s(self) -> float:
        return self.length_m / max(0.1, self.speed_limit_mps)


@dataclass(frozen=True)
class GraphEdge:
    """One directed A -> B link. `junction_id` is B's entry junction (== the
    junction physically crossed); `signalised` is True iff at least one SUMO
    connection A->B carries a `tl`."""

    to_edge: str
    junction_id: str
    signalised: bool
    tl_id: str | None


@dataclass(frozen=True)
class RoadGraph:
    edges: dict[str, EdgeInfo]
    adjacency: dict[str, tuple[GraphEdge, ...]]
    signalised_junctions: frozenset[str]
    # {tl_id: {(from_edge, to_edge): {"L3", "L4"}}} -- the SUMO signal link
    # indices a given turn uses at a signalised junction. Populated from the
    # network's `<connection tl= linkIndex=>` elements; consumed by the green
    # corridor to size a preemption around the movements an EV actually needs.
    link_movements: Mapping[str, Mapping[tuple[str, str], frozenset[str]]] = field(
        default_factory=dict
    )

    # ---- queries -----------------------------------------------------

    def has_edge(self, edge_id: str) -> bool:
        return edge_id in self.edges

    def neighbours(self, edge_id: str) -> tuple[GraphEdge, ...]:
        return self.adjacency.get(edge_id, ())

    def is_signalised_junction(self, junction_id: str) -> bool:
        return junction_id in self.signalised_junctions

    def movements_for(self, tl_id: str, from_edge: str, to_edge: str) -> frozenset[str]:
        """The signal link labels (`L{i}`, matching `Tier0Config` movement ids)
        this turn crosses at `tl_id`. Empty if the network has no controlled
        connection for the pair -- the caller treats that as "nothing to
        preempt here"."""
        return self.link_movements.get(tl_id, {}).get((from_edge, to_edge), frozenset())

    def without_edges(self, blocked: Iterable[str]) -> RoadGraph:
        """A copy with `blocked` edges removed from both the node set and every
        adjacency list -- used to drop BLOCKED-severity anomalies before the
        search rather than carrying an infinite cost through it."""
        drop = {e for e in blocked if e in self.edges}
        if not drop:
            return self
        edges = {k: v for k, v in self.edges.items() if k not in drop}
        adjacency = {
            src: tuple(ge for ge in ges if ge.to_edge not in drop)
            for src, ges in self.adjacency.items()
            if src not in drop
        }
        return RoadGraph(
            edges=edges,
            adjacency=adjacency,
            signalised_junctions=self.signalised_junctions,
            link_movements=self.link_movements,
        )

    # ---- construction --------------------------------------------

    @classmethod
    def from_network(cls, net_path: str | Path) -> RoadGraph:
        root = ET.parse(net_path).getroot()

        # junction coords + which are traffic lights
        jx: dict[str, tuple[float, float]] = {}
        signalised: set[str] = set()
        for j in root.findall("junction"):
            jid = j.get("id")
            if jid is None:
                continue
            try:
                jx[jid] = (float(j.get("x", "0")), float(j.get("y", "0")))
            except ValueError:
                jx[jid] = (0.0, 0.0)
            if j.get("type") == "traffic_light":
                signalised.add(jid)

        edges: dict[str, EdgeInfo] = {}
        for e in root.findall("edge"):
            if e.get("function") == "internal" or (e.get("id") or "").startswith(":"):
                continue
            eid = e.get("id")
            frm = e.get("from")
            to = e.get("to")
            lanes = e.findall("lane")
            if not eid or frm is None or to is None or not lanes:
                continue
            length = _f(lanes[0].get("length"), 0.0)
            speed = _f(lanes[0].get("speed"), 13.9)
            edges[eid] = EdgeInfo(
                edge_id=eid,
                length_m=length,
                num_lanes=len(lanes),
                speed_limit_mps=speed,
                from_junction=frm,
                to_junction=to,
                start_xy=jx.get(frm, (0.0, 0.0)),
                end_xy=jx.get(to, (0.0, 0.0)),
            )

        # connections -> adjacency, collapsing parallel connections between the
        # same edge pair (a through+right out of one edge is one graph edge)
        raw: dict[tuple[str, str], tuple[str, bool, str | None]] = {}
        for c in root.findall("connection"):
            a, b = c.get("from"), c.get("to")
            if not a or not b or a not in edges or b not in edges:
                continue
            tl = c.get("tl")
            junction = edges[b].from_junction
            key = (a, b)
            prev = raw.get(key)
            # signalised wins if any connection between the pair carries a tl
            sig = bool(tl) or (prev[1] if prev else False)
            raw[key] = (junction, sig, tl or (prev[2] if prev else None))

        adjacency: dict[str, list[GraphEdge]] = {}
        for (a, b), (junction, sig, tl) in raw.items():
            adjacency.setdefault(a, []).append(
                GraphEdge(to_edge=b, junction_id=junction, signalised=sig, tl_id=tl)
            )

        # {tl_id: {(from_edge, to_edge): {"L{linkIndex}", ...}}} -- every
        # controlled connection, grouped by the edge pair it serves (an edge
        # pair with two through lanes contributes two link indices to the same
        # movement set).
        link_movements: dict[str, dict[tuple[str, str], set[str]]] = {}
        for c in root.findall("connection"):
            tl = c.get("tl")
            link_index = c.get("linkIndex")
            a, b = c.get("from"), c.get("to")
            if not tl or link_index is None or not a or not b:
                continue
            link_movements.setdefault(tl, {}).setdefault((a, b), set()).add(f"L{link_index}")

        return cls(
            edges=edges,
            adjacency={k: tuple(v) for k, v in adjacency.items()},
            signalised_junctions=frozenset(signalised),
            link_movements={
                tl: {pair: frozenset(links) for pair, links in pairs.items()}
                for tl, pairs in link_movements.items()
            },
        )


def _f(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default

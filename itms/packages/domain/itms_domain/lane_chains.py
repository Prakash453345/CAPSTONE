"""A signalised approach that SUMO splits into several edges, measured as one
road.

SUMO ends an edge wherever anything about the road changes: a turn bay
starting, a lane added or dropped, and in an OpenStreetMap import any change
of tag. The traffic light's approach lane is then only the last stretch
before the stop line. On a generated 4x4 grid with turn bays
(`scenarios/generated/grid4_rh_turns`) every approach lane was 4 m long: the
controller saw queues of about one vehicle per lane however long the real
queue was, and at heavy demand did 2.2x Webster's delay.

`lane_chains` finds, for every signalised approach lane, the lanes that
continue it upstream through nodes that are not junctions (no signal and no
more than two neighbouring nodes: the road merely continues), and for every
receiving lane those that continue it downstream. Consumers add what is on
the chain to what is on the lane, so a measurement no longer depends on
where the network happens to be cut into edges.

Pure standard library, so the signal-control path can use it without numpy.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

_SIGNAL_TYPES = frozenset({"traffic_light", "traffic_light_unregulated",
                           "traffic_light_right_on_red"})

# (lane id, share, offset_m): see `lane_chains`
Chain = list[tuple[str, float, float]]


@dataclass(frozen=True)
class Link:
    """One `<connection>` between two normal lanes."""
    from_lane: str
    to_lane: str
    tls_id: str | None = None
    link_index: int | None = None
    direction: str = ""


def lane_chains(
    lanes: Mapping[str, tuple[str, float]],
    edge_nodes: Mapping[str, tuple[str, str]],
    junction_types: Mapping[str, str],
    links: Iterable[Link],
    *,
    max_m: float = 1000.0,
) -> tuple[dict[str, Chain], dict[str, Chain]]:
    """`(upstream, downstream)`.

    `lanes` is `{lane id: (edge id, length)}`, `edge_nodes` `{edge id: (from
    node, to node)}`, `junction_types` `{node: SUMO junction type}`.

    `upstream[a]` lists, for a signalised approach lane `a`, the lanes that
    continue it upstream; `downstream[r]`, for a receiving lane `r`, those
    that continue it downstream. Only lanes with a chain appear. Each entry
    is `(lane id, share, offset_m)`:

    - `share`: the part of that lane's traffic that belongs to this one. A
      lane that feeds two lanes of the next edge (a turn bay opening) gives
      each half; shares multiply along the chain.
    - `offset_m`: upstream, the distance from that lane's end to the stop
      line; downstream, from the receiving lane's start to that lane's
      start.

    A chain never includes the same road's other direction (a U-turn at a
    dead end, or any turn back onto the edge's twin) and stops at a real
    junction or after `max_m`."""
    neighbours: dict[str, set[str]] = {}
    for a, b in edge_nodes.values():
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)

    def pass_through(node: str) -> bool:
        t = junction_types.get(node)
        return t is not None and t not in _SIGNAL_TYPES and len(neighbours.get(node, ())) <= 2

    preds: dict[str, list[str]] = {}
    succs: dict[str, list[str]] = {}
    approach: list[str] = []
    receiving: list[str] = []
    for c in links:
        if c.tls_id and c.link_index is not None:
            approach.append(c.from_lane)
            receiving.append(c.to_lane)
        if c.direction in ("t", "T"):
            continue  # a U-turn leads onto the same road's other direction
        preds.setdefault(c.to_lane, []).append(c.from_lane)
        succs.setdefault(c.from_lane, []).append(c.to_lane)

    def walk(lane_id: str, forward: bool) -> Chain:
        out: Chain = []
        frontier = [(lane_id, 1.0, 0.0)]
        seen = {lane_id}
        while frontier:
            cur, share, off = frontier.pop()
            edge, length = lanes[cur]
            a, b = edge_nodes.get(edge, ("", ""))
            node, far = (b, a) if forward else (a, b)
            if not pass_through(node):
                continue
            nxt_off = off + length
            if nxt_off > max_m:
                continue
            for x in (succs if forward else preds).get(cur, []):
                if x not in lanes or x in seen:
                    continue
                xa, xb = edge_nodes.get(lanes[x][0], ("", ""))
                near, other = (xa, xb) if forward else (xb, xa)
                # x must join cur at `node`, and not be the same road's other
                # direction (which leads back to cur's far end)
                if near != node or other == far:
                    continue
                # x's traffic is split over the lanes of cur's edge it feeds
                # (upstream) or is fed by (downstream)
                fan = [f for f in (preds if forward else succs).get(x, [])
                       if f in lanes and lanes[f][0] == edge]
                s = share / max(1, len(fan))
                seen.add(x)
                out.append((x, s, nxt_off))
                frontier.append((x, s, nxt_off))
        return out

    up = {ln: walk(ln, False) for ln in dict.fromkeys(approach) if ln in lanes}
    down = {ln: walk(ln, True) for ln in dict.fromkeys(receiving) if ln in lanes}
    return ({k: v for k, v in up.items() if v}, {k: v for k, v in down.items() if v})


def from_sumo_net(net_path: str | Path, *, max_m: float = 1000.0) -> tuple[
        dict[str, Chain], dict[str, Chain]]:
    """`lane_chains` for a SUMO `.net.xml`."""
    root = ET.parse(net_path).getroot()
    lanes: dict[str, tuple[str, float]] = {}
    edge_nodes: dict[str, tuple[str, str]] = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        eid = e.get("id", "")
        edge_nodes[eid] = (e.get("from", ""), e.get("to", ""))
        for ln in e.findall("lane"):
            lanes[ln.get("id", "")] = (eid, float(ln.get("length", "0")))
    junction_types = {j.get("id", ""): j.get("type", "") for j in root.findall("junction")
                      if j.get("type") != "internal"}
    links = []
    for c in root.findall("connection"):
        fe, te, fl, tl = c.get("from"), c.get("to"), c.get("fromLane"), c.get("toLane")
        if fe is None or te is None or fl is None or tl is None:
            continue
        if fe.startswith(":") or te.startswith(":"):
            continue
        li = c.get("linkIndex")
        links.append(Link(f"{fe}_{fl}", f"{te}_{tl}", c.get("tl"),
                          int(li) if li is not None else None, c.get("dir", "")))
    return lane_chains(lanes, edge_nodes, junction_types, links, max_m=max_m)

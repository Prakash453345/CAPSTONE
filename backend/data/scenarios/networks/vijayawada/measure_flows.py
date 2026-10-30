"""Measure per-movement demand flow for every signal-controlled junction in
the Vijayawada corridor, from the network's own `.net.xml` and the demand
scenario's `.rou.xml` -- the "measured flows" `webster.compute_timing`
needs, as opposed to a guessed cycle length [build guide §7 M3: "compute
optimal cycle from measured flows, do not guess"].

Two pieces of real data, neither approximated:

- **Link -> edge mapping**: `.net.xml`'s own `<connection tl="..."
  linkIndex="..." from="...">` elements are the authoritative link-to-edge
  correspondence -- the same linkIndex numbering `extract_tier0_config.py`
  reads tlLogic phase strings against (`"L{linkIndex}"`), so a flow
  measured on the connection's `from` edge is measured for exactly the
  movement a `Phase.green_movements` entry names.
- **Traversal counts**: `.rou.xml`'s `<vehicle><route edges="...">` is this
  scenario's actual assigned demand -- counting how many vehicle routes
  cross each edge over the scenario's departure window gives a real,
  non-guessed flow rate for that edge. This network's demand (`build.sh`'s
  `randomTrips.py` + `duarouter`) is synthetic in the sense that no city
  ever measured it, but it is exactly the flow this scenario actually
  presents to the signal -- which is the flow Webster's formula needs
  measured against.

One approximation, stated rather than hidden: a route "uses" an edge once
per occurrence in its edge list, regardless of how many lanes on that edge
actually feed the junction's several `linkIndex` connections (a through
lane and a turn lane sharing one edge both count that edge's full
traversal count as their movement's flow). This is conservative in the
direction that matters -- it can only *overstate* a given movement's
demand, never understate it -- and is not correctable without per-lane
route assignment data this network's demand generation never produced.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_NET = _HERE / "vijayawada_corridor.net.xml"
_DEFAULT_ROUTES = _HERE.parent.parent / "demand" / "vijayawada" / "vijayawada_corridor.rou.xml"


def _link_to_edge_map(net_path: str | Path) -> dict[str, dict[str, str]]:
    """`{tls_id: {"L{linkIndex}": from_edge_id}}`, straight from
    `<connection>` elements -- one entry per signal-controlled movement."""
    tree = ET.parse(net_path)
    root = tree.getroot()
    mapping: dict[str, dict[str, str]] = {}
    for conn in root.findall("connection"):
        tls_id = conn.get("tl")
        link_index = conn.get("linkIndex")
        from_edge = conn.get("from")
        if not tls_id or link_index is None or not from_edge:
            continue  # an uncontrolled connection (no tl attribute) -- not our concern here
        mapping.setdefault(tls_id, {})[f"L{link_index}"] = from_edge
    return mapping


def _edge_traversal_counts(route_path: str | Path) -> tuple[Counter[str], float]:
    """Counts how many vehicle routes cross each edge, and the scenario's
    departure window in hours (max `depart` - min `depart`, falling back to
    1 vehicle-period if there's only one departure -- avoids a division by
    zero on a degenerate scenario rather than papering over what it means)."""
    tree = ET.parse(route_path)
    root = tree.getroot()
    counts: Counter[str] = Counter()
    departs: list[float] = []
    for vehicle in root.findall("vehicle"):
        depart_attr = vehicle.get("depart")
        if depart_attr is not None:
            departs.append(float(depart_attr))
        route = vehicle.find("route")
        if route is None:
            continue
        edges = (route.get("edges") or "").split()
        counts.update(edges)
    for flow in root.findall("flow"):
        # This network's demand is `<vehicle>`-only (see module docstring),
        # but a `<flow>` element is legitimate SUMO demand syntax elsewhere
        # -- handled for completeness, not because this scenario uses it.
        route = flow.find("route")
        if route is not None:
            edges = (route.get("edges") or "").split()
            counts.update(edges)
    window_hours = ((max(departs) - min(departs)) / 3600.0) if len(departs) >= 2 else (1.0 / 3600.0)
    return counts, max(window_hours, 1.0 / 3600.0)


def compute_link_flows(
    net_path: str | Path = _DEFAULT_NET, route_path: str | Path = _DEFAULT_ROUTES
) -> dict[str, dict[str, float]]:
    """`{tls_id: {"L{i}": veh_per_hour}}` for every signal-controlled link
    in the network that this scenario's demand actually uses (a link whose
    edge nothing ever traverses is simply absent -- `webster.compute_timing`
    already treats a missing link as zero flow)."""
    link_to_edge = _link_to_edge_map(net_path)
    edge_counts, window_hours = _edge_traversal_counts(route_path)

    flows: dict[str, dict[str, float]] = {}
    for tls_id, links in link_to_edge.items():
        for link_id, edge_id in links.items():
            count = edge_counts.get(edge_id, 0)
            if count == 0:
                continue
            flows.setdefault(tls_id, {})[link_id] = count / window_hours
    return flows


def main() -> None:
    net_path = sys.argv[1] if len(sys.argv) > 1 else str(_DEFAULT_NET)
    route_path = sys.argv[2] if len(sys.argv) > 2 else str(_DEFAULT_ROUTES)
    flows = compute_link_flows(net_path, route_path)
    print(f"measured flows for {len(flows)} junctions from {route_path}")
    for tls_id in sorted(flows):
        links = flows[tls_id]
        summary = ", ".join(f"{link}={veh_h:.0f}veh/h" for link, veh_h in sorted(links.items()))
        print(f"  {tls_id}: {summary}")


if __name__ == "__main__":
    main()

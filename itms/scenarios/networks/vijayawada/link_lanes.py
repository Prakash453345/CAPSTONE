"""Map each signal-controlled link to the exact SUMO lane that feeds it, for
every junction in the Vijayawada corridor -- what semi-actuated control
needs that Webster's tuning didn't. `measure_flows.py` aggregates demand at
edge granularity (fine for a flow *ratio* averaged over the whole scenario);
live actuation needs to ask "is there a vehicle sitting in the exact lane
this movement serves, right now," which means the lane, not just the edge
-- an edge with two through lanes and a turn lane can feed three different
`linkIndex` values that must not be conflated.

`<connection from="..." fromLane="i" tl="..." linkIndex="j">` in the
network's own `.net.xml` names both the edge and the specific lane on it;
SUMO's own lane-id convention is `f"{edge_id}_{lane_index}"`, which is all
`traci.lane.getLastStepVehicleNumber` needs to query that lane directly.

Importable: `link_to_lane_map(net_path) -> dict[str, dict[str, str]]`,
`{tls_id: {"L{linkIndex}": lane_id}}`, keyed identically to
`extract_tier0_config.py`'s `Phase.green_movements` labels.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_NET = _HERE / "vijayawada_corridor.net.xml"


def link_to_lane_map(net_path: str | Path = _DEFAULT_NET) -> dict[str, dict[str, str]]:
    tree = ET.parse(net_path)
    root = tree.getroot()
    mapping: dict[str, dict[str, str]] = {}
    for conn in root.findall("connection"):
        tls_id = conn.get("tl")
        link_index = conn.get("linkIndex")
        from_edge = conn.get("from")
        from_lane = conn.get("fromLane")
        if not tls_id or link_index is None or not from_edge or from_lane is None:
            continue  # an uncontrolled connection -- not our concern here
        lane_id = f"{from_edge}_{from_lane}"
        mapping.setdefault(tls_id, {})[f"L{link_index}"] = lane_id
    return mapping

"""Lanes that give way to a signal's exit road.

A signal's green sends a stream down its exit road. If that road ends, soon, at
a priority junction where a side road must give way to it, the side road's
vehicles need gaps in the stream. A signal that rests in green (`rest_in_green`)
makes none: on the Vijayawada district the exit lane `850997565_0` of one signal
yields to the road the neighbouring signal feeds, and starved while that signal
rested (baselines/2026-10-13_rest_offpeak_v2, "Could it stay on all day?").

`yield_lanes_from_net` maps, per signal, each link ("L{i}") to the lanes that
give way to the link's exit road at the exit road's far end, if that end is
within `max_exit_m`. `QueueStateSampler` measures the halted PCU on them.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

DEFAULT_MAX_EXIT_M = 200.0
"""Longest exit road still counted as "just past the exit". Past this, a platoon
disperses and the give-way finds its own gaps."""


def yield_lanes_from_net(
    net_path: str | Path, max_exit_m: float = DEFAULT_MAX_EXIT_M,
) -> dict[str, dict[str, tuple[str, ...]]]:
    root = ET.parse(net_path).getroot()
    length: dict[str, float] = {}
    for edge in root.findall("edge"):
        if edge.get("function") == "internal":
            continue
        lanes = edge.findall("lane")
        if lanes:
            length[edge.get("id")] = max(float(x.get("length", "0")) for x in lanes)
    # at each edge's far junction: which connections keep right of way ('M'), which give way ('m')
    major: dict[str, set[str]] = defaultdict(set)   # edge -> {"M" seen}
    yielding: dict[str, list[str]] = defaultdict(list)  # to-junction key -> lanes that yield
    conns = root.findall("connection")
    edge_to: dict[str, str] = {e.get("id"): e.get("to") for e in root.findall("edge")
                               if e.get("function") != "internal"}
    for c in conns:
        if c.get("tl") is not None:
            continue
        frm = c.get("from")
        if frm not in edge_to:
            continue
        if c.get("state") == "M":
            major[frm].add(c.get("to"))
        elif c.get("state") == "m":
            lane = f"{frm}_{c.get('fromLane')}"
            if lane not in yielding[edge_to[frm]]:
                yielding[edge_to[frm]].append(lane)
    out: dict[str, dict[str, tuple[str, ...]]] = {}
    for c in conns:
        tls, idx, to = c.get("tl"), c.get("linkIndex"), c.get("to")
        if tls is None or idx is None or to not in major or length.get(to, 1e9) > max_exit_m:
            continue
        lanes = tuple(x for x in yielding.get(edge_to[to], ()) if not x.startswith(f"{to}_"))
        if lanes:
            out.setdefault(tls, {})[f"L{idx}"] = lanes
    return out

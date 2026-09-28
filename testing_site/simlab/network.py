"""The corridor, read out of the repo once and cached.

Everything the browser needs to draw the map and offer sane pickers:
geometry from the exported GeoJSON, topology and lengths from the SUMO
`.net.xml`, and the hospital list from `facilities.json`. All three are read
only -- this module never writes into `itms/`.

Edge lengths and the from/to junction of each edge come from the net file
rather than being re-derived from the GeoJSON: the net file is what SUMO and
every controller in the repo actually reason about, so anything this tool
reports about an edge matches what the simulation thinks about it.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Any

from simlab import paths


def _latlon_of(coords: list[list[float]]) -> tuple[float, float]:
    """Midpoint of a LineString, for placing a label or a marker."""
    if not coords:
        return (0.0, 0.0)
    mid = coords[len(coords) // 2]
    return (mid[1], mid[0])


@lru_cache(maxsize=1)
def _geojson() -> dict:
    if not paths.GEOJSON_PATH.exists():
        return {"type": "FeatureCollection", "features": []}
    with paths.GEOJSON_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _netxml() -> ET.Element | None:
    if not paths.NET_PATH.exists():
        return None
    return ET.parse(paths.NET_PATH).getroot()


@lru_cache(maxsize=1)
def corridor() -> dict[str, Any]:
    """One payload: edges, junctions, traffic lights, adjacency, bounds."""
    gj = _geojson()
    root = _netxml()

    geom: dict[str, list[list[float]]] = {}
    junction_pt: dict[str, list[float]] = {}
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        if props.get("kind") == "edge":
            geom[props["edge_id"]] = feat["geometry"]["coordinates"]
        elif props.get("kind") == "junction":
            junction_pt[props["junction_id"]] = feat["geometry"]["coordinates"]

    edges: dict[str, dict] = {}
    junctions: dict[str, dict] = {}
    tls: dict[str, dict] = {}
    adjacency: dict[str, list[str]] = {}
    signalised_entry: dict[str, set[str]] = {}

    if root is not None:
        for j in root.findall("junction"):
            jid = j.get("id") or ""
            if j.get("type") == "internal" or not jid:
                continue
            pt = junction_pt.get(jid)
            junctions[jid] = {
                "id": jid,
                "type": j.get("type"),
                "lat": pt[1] if pt else None,
                "lon": pt[0] if pt else None,
                "is_traffic_light": j.get("type") in ("traffic_light", "traffic_light_right_on_red"),
            }

        for tl in root.findall("tlLogic"):
            tid = tl.get("id") or ""
            phases = tl.findall("phase")
            tls[tid] = {
                "id": tid,
                "n_phases": len(phases),
                "n_links": len(phases[0].get("state", "")) if phases else 0,
                "program": tl.get("programID"),
                "lat": junctions.get(tid, {}).get("lat"),
                "lon": junctions.get(tid, {}).get("lon"),
            }

        for e in root.findall("edge"):
            eid = e.get("id") or ""
            if e.get("function") == "internal" or not eid:
                continue
            lanes = e.findall("lane")
            lengths = [float(ln.get("length", "0") or 0) for ln in lanes]
            speeds = [float(ln.get("speed", "0") or 0) for ln in lanes]
            coords = geom.get(eid, [])
            lat, lon = _latlon_of(coords)
            edges[eid] = {
                "id": eid,
                "name": e.get("name") or None,
                "from": e.get("from"),
                "to": e.get("to"),
                "road_type": e.get("type"),
                "num_lanes": len(lanes),
                "length_m": round(max(lengths) if lengths else 0.0, 1),
                "speed_limit_mps": round(max(speeds) if speeds else 0.0, 2),
                "lane_ids": [ln.get("id") for ln in lanes],
                "coords": coords,
                "lat": lat,
                "lon": lon,
            }

        for c in root.findall("connection"):
            frm, to = c.get("from"), c.get("to")
            if not frm or not to or frm.startswith(":") or to.startswith(":"):
                continue
            adjacency.setdefault(frm, [])
            if to not in adjacency[frm]:
                adjacency[frm].append(to)
            tl_id = c.get("tl")
            if tl_id:
                signalised_entry.setdefault(to, set()).add(tl_id)

    # An edge leaving a dead end is where demand can actually be injected;
    # an edge entering one is where a trip can actually finish. randomTrips'
    # own --fringe-factor works off the same idea.
    for eid, ed in edges.items():
        frm = junctions.get(ed.get("from") or "", {})
        to = junctions.get(ed.get("to") or "", {})
        ed["is_entry"] = frm.get("type") in ("dead_end", "priority", None) and not adjacency_in(
            adjacency, eid
        )
        ed["is_exit"] = not adjacency.get(eid)
        ed["fringe_source"] = frm.get("type") == "dead_end"
        ed["fringe_sink"] = to.get("type") == "dead_end"
        ed["signalised_entry_tls"] = sorted(signalised_entry.get(eid, ()))
        ed["free_flow_time_s"] = (
            round(ed["length_m"] / ed["speed_limit_mps"], 1) if ed["speed_limit_mps"] else None
        )

    lats = [e["lat"] for e in edges.values() if e["lat"]]
    lons = [e["lon"] for e in edges.values() if e["lon"]]
    bounds = (
        [[min(lats), min(lons)], [max(lats), max(lons)]]
        if lats and lons
        else [[16.4977, 80.6178], [16.5144, 80.6541]]
    )

    return {
        "edges": edges,
        "edge_order": sorted(edges),
        "junctions": junctions,
        "traffic_lights": tls,
        "adjacency": adjacency,
        "bounds": bounds,
        "center": [
            sum(lats) / len(lats) if lats else 16.506,
            sum(lons) / len(lons) if lons else 80.636,
        ],
        "n_edges": len(edges),
        "n_junctions": len(junctions),
        "n_traffic_lights": len(tls),
    }


def adjacency_in(adjacency: dict[str, list[str]], edge_id: str) -> bool:
    for targets in adjacency.values():
        if edge_id in targets:
            return True
    return False


@lru_cache(maxsize=1)
def facilities() -> list[dict]:
    if not paths.FACILITIES_PATH.exists():
        return []
    with paths.FACILITIES_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    items = data.get("facilities", data) if isinstance(data, dict) else data
    out = []
    for f in items:
        out.append(
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "kind": f.get("kind"),
                "lat": f.get("lat"),
                "lon": f.get("lon"),
                "edge": f.get("edge"),
                "capabilities": f.get("capabilities") or [],
            }
        )
    out.sort(key=lambda f: (f["kind"] != "hospital", (f["name"] or "").lower()))
    return out


@lru_cache(maxsize=1)
def suggest_pair() -> dict:
    """The most interesting origin/destination pair on this network: the one
    whose free-flow shortest path crosses the most signalised junctions,
    tie-broken by length. Used as the default in the scenario builder and by
    the guided demos, so both keep working if the corridor is ever rebuilt
    with different edge ids.
    """
    net = corridor()
    edges = net["edges"]
    sources = [e for e, d in edges.items() if d.get("fringe_source")] or list(edges)
    sinks = [e for e, d in edges.items() if d.get("fringe_sink")] or list(edges)

    best = None
    for s in sources:
        for t in sinks:
            if s == t:
                continue
            path = shortest_path(s, t)
            if not path.get("ok") or len(path["edges"]) < 3:
                continue
            score = (path["n_signals"], path["length_m"])
            if best is None or score > best[0]:
                best = (score, s, t, path)

    if best is None:
        keys = net["edge_order"]
        fallback = keys[0] if keys else ""
        return {
            "origin": fallback,
            "destination": keys[-1] if keys else "",
            "route": [],
            "mid_edge": fallback,
            "ahead_edge": fallback,
            "n_signals": 0,
            "length_m": 0,
        }

    _, origin, destination, path = best
    route = path["edges"]
    return {
        "origin": origin,
        "destination": destination,
        "route": route,
        "mid_edge": route[max(1, len(route) // 2)] if len(route) > 2 else route[-1],
        "ahead_edge": route[max(1, int(len(route) * 0.7))] if len(route) > 2 else route[-1],
        "n_signals": path["n_signals"],
        "length_m": path["length_m"],
        "free_flow_s": path["free_flow_s"],
    }


@lru_cache(maxsize=4096)
def shortest_path(source: str, target: str) -> dict:
    """Free-flow shortest path over the corridor, computed here in the
    server so the site can validate an origin/destination pair (and show the
    path) before a run is started.

    Deliberately the same graph shape the repo's own router walks -- edge
    nodes, `connection` arcs, free-flow time as the weight -- but reimplemented
    on the parsed net file rather than importing `sim_service.routing`, so
    scenario validation works even when the repo's virtualenv does not exist
    yet. The live emergency router in the simulation is the repo's own; this
    is only for pre-flight.
    """
    net = corridor()
    edges, adjacency = net["edges"], net["adjacency"]
    if source not in edges:
        return {"ok": False, "reason": f"unknown origin edge {source!r}"}
    if target not in edges:
        return {"ok": False, "reason": f"unknown destination edge {target!r}"}
    if source == target:
        return {
            "ok": True,
            "edges": [source],
            "length_m": edges[source]["length_m"],
            "free_flow_s": edges[source]["free_flow_time_s"] or 0.0,
            "n_signals": 0,
        }

    import heapq

    def w(eid: str) -> float:
        e = edges[eid]
        return e["free_flow_time_s"] or (e["length_m"] / 8.0 if e["length_m"] else 1.0)

    best = {source: 0.0}
    prev: dict[str, str] = {}
    pq = [(0.0, source)]
    while pq:
        cost, cur = heapq.heappop(pq)
        if cur == target:
            break
        if cost > best.get(cur, math.inf) + 1e-12:
            continue
        for nxt in adjacency.get(cur, []):
            if nxt not in edges:
                continue
            cand = cost + w(nxt)
            if cand < best.get(nxt, math.inf) - 1e-12:
                best[nxt] = cand
                prev[nxt] = cur
                heapq.heappush(pq, (cand, nxt))

    if target not in best:
        return {
            "ok": False,
            "reason": "no connected path between those two roads on this network",
        }

    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    path.reverse()
    return {
        "ok": True,
        "edges": path,
        "length_m": round(sum(edges[e]["length_m"] for e in path), 1),
        "free_flow_s": round(sum(w(e) for e in path[1:]), 1),
        "n_signals": sum(1 for e in path if edges[e]["signalised_entry_tls"]),
        "signals": sorted({t for e in path for t in edges[e]["signalised_entry_tls"]}),
    }

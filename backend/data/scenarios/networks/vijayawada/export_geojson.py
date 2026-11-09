"""Export the Vijayawada corridor SUMO network to GeoJSON, for the dashboard's
live map (M1 gate: "watch simulated traffic move on a real map of your
city"). Not part of the netconvert pipeline in build.sh -- this reads the
finished .net.xml, so re-run it whenever the network changes.

Writes vijayawada_corridor.geojson, plain GeoJSON, for anyone/anything that
wants it. (It also used to write network_data.js for the static web demo,
which was removed with docs/archive/ in November 2026.)

Usage: python export_geojson.py [path/to/vijayawada_corridor.net.xml]
       python export_geojson.py NET OUT.geojson

The second form writes only OUT.geojson, compact (shapes simplified to 1 m,
coordinates to 5 decimals), for other networks such as the district grid the
console bundles or another city (the web app's `VITE_CITY`); the corridor's
file above is left alone. A junction whose own coordinates are off its roads
(netconvert left four joined Amaravati junctions at y = 0) is placed at the
mean of its roads' ends there instead.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import sumolib

_HERE = Path(__file__).resolve().parent
_DEFAULT_NET = _HERE / "vijayawada_corridor.net.xml"
_GEOJSON_OUT = _HERE / "vijayawada_corridor.geojson"


def _junction_xy(node, tolerance_m: float = 200.0) -> tuple[float, float]:
    """The node's coordinates, or the mean of its roads' ends at it when the
    node lies more than `tolerance_m` from all of them."""
    x, y = node.getCoord()
    ends = [e.getShape()[-1] for e in node.getIncoming() if not e.isSpecial()]
    ends += [e.getShape()[0] for e in node.getOutgoing() if not e.isSpecial()]
    if ends and min(((ex - x) ** 2 + (ey - y) ** 2) ** 0.5 for ex, ey in ends) > tolerance_m:
        return (sum(ex for ex, _ in ends) / len(ends), sum(ey for _, ey in ends) / len(ends))
    return x, y


def build_feature_collection(net_path: str) -> dict:
    net = sumolib.net.readNet(net_path)
    features = []

    for edge in net.getEdges():
        if edge.isSpecial():  # internal junction-connector edges -- not real road
            continue
        coords = [net.convertXY2LonLat(x, y) for x, y in edge.getShape()]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "kind": "edge",
                    "edge_id": edge.getID(),
                    "name": edge.getName() or None,
                    "num_lanes": edge.getLaneNumber(),
                    "speed_limit_mps": edge.getSpeed(),
                    "road_type": edge.getType() or None,
                },
            }
        )

    for node in net.getNodes():
        x, y = _junction_xy(node)
        lon, lat = net.convertXY2LonLat(x, y)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "kind": "junction",
                    "junction_id": node.getID(),
                    "junction_type": node.getType(),
                    "is_traffic_light": node.getType() == "traffic_light",
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


# Compact export: the console bundles this file, so every byte is downloaded
# by every map page. Douglas-Peucker at 1 m keeps each road's shape within a
# metre of SUMO's (invisible at street zoom, and lengths change by well under
# 1%), and 5 decimals of a degree is about 1 m.
_SIMPLIFY_M = 1.0
_DECIMALS = 5


def _simplify(pts: list, tol_m: float) -> list:
    if len(pts) < 3:
        return pts
    kx = 111_320 * math.cos(math.radians(pts[0][1]))  # metres per degree here
    ky = 110_540

    def off(p, a, b) -> float:
        ax, ay = (p[0] - a[0]) * kx, (p[1] - a[1]) * ky
        bx, by = (b[0] - a[0]) * kx, (b[1] - a[1]) * ky
        seg = bx * bx + by * by
        t = 0.0 if seg == 0 else max(0.0, min(1.0, (ax * bx + ay * by) / seg))
        return math.hypot(ax - t * bx, ay - t * by)

    i, worst = max(((i, off(pts[i], pts[0], pts[-1])) for i in range(1, len(pts) - 1)), key=lambda x: x[1])
    if worst <= tol_m:
        return [pts[0], pts[-1]]
    return _simplify(pts[: i + 1], tol_m)[:-1] + _simplify(pts[i:], tol_m)


def _compact(fc: dict) -> str:
    def rnd(c, decimals=_DECIMALS):
        return [round(c[0], decimals), round(c[1], decimals)]

    for f in fc["features"]:
        g = f["geometry"]
        if g["type"] == "Point":
            g["coordinates"] = rnd(g["coordinates"])
            continue
        line = _simplify(g["coordinates"], _SIMPLIFY_M)
        short = [rnd(c) for c in line]
        if any(a == b for a, b in zip(short, short[1:])):
            # a sub-metre stub (netconvert leaves some between joined
            # junctions) would collapse to a point: keep its full precision
            short = [rnd(c, 7) for c in line]
        g["coordinates"] = short
        f["properties"].pop("junction_type", None)  # unused by the console
    return json.dumps(fc, separators=(",", ":"))


def main() -> None:
    net_path = sys.argv[1] if len(sys.argv) > 1 else str(_DEFAULT_NET)
    fc = build_feature_collection(net_path)
    if len(sys.argv) > 2:  # another network: just its GeoJSON, compact
        out = Path(sys.argv[2])
        out.write_text(_compact(fc) + "\n")
        print(f"wrote {out} ({len(fc['features'])} features)")
        return

    _GEOJSON_OUT.write_text(json.dumps(fc, indent=2))
    print(f"wrote {_GEOJSON_OUT} ({len(fc['features'])} features)")


if __name__ == "__main__":
    main()

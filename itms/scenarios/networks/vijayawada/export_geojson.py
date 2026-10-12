"""Export the Vijayawada corridor SUMO network to GeoJSON, for the dashboard's
live map (M1 gate: "watch simulated traffic move on a real map of your
city"). Not part of the netconvert pipeline in build.sh -- this reads the
finished .net.xml, so re-run it whenever the network changes.

Writes two files with the same content:
  - vijayawada_corridor.geojson   plain GeoJSON, for anyone/anything that wants it
  - ../../../web/network_data.js  the same FeatureCollection wrapped as
    `window.ITMS_NETWORK = {...}`, so index.html can load it with a plain
    <script src> tag. That matters because the dashboard is opened directly
    as a file:// URL (see web/README or scripts/dev.sh) -- fetch() of a
    sibling file over file:// is blocked by Chrome's CORS handling, but a
    <script src="local.js"> is not, so shipping the data as JS instead of
    JSON is the actual fix, not a stylistic choice.

Usage: python export_geojson.py [path/to/vijayawada_corridor.net.xml]
       python export_geojson.py NET OUT.geojson

The second form writes only OUT.geojson, compact (shapes simplified to 1 m,
coordinates to 5 decimals), for other networks such as the district grid the console
bundles; the corridor's two files above are left alone.
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
_JS_OUT = _HERE.parents[2] / "web" / "network_data.js"


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
                },
            }
        )

    for node in net.getNodes():
        x, y = node.getCoord()
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
    if len(sys.argv) > 2:
        out = Path(sys.argv[2])
        out.write_text(_compact(fc) + "\n")
        print(f"wrote {out} ({len(fc['features'])} features)")
        return

    _GEOJSON_OUT.write_text(json.dumps(fc, indent=2))
    print(f"wrote {_GEOJSON_OUT} ({len(fc['features'])} features)")

    js = "// Generated by scenarios/networks/vijayawada/export_geojson.py -- do not hand-edit.\n"
    js += f"window.ITMS_NETWORK = {json.dumps(fc)};\n"
    _JS_OUT.write_text(js)
    print(f"wrote {_JS_OUT}")


if __name__ == "__main__":
    main()

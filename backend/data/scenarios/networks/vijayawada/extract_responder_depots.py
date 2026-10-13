"""Pull the corridor's police stations out of the OSM extract and snap each
one to a network edge -- the depot registry `IncidentResponseOrchestrator`
draws police vehicles from, the same way `facilities.json` is where it draws
ambulances from (hospitals).

Sits beside `extract_facilities.py` and follows its convention exactly: a
scenario-preparation script that turns the raw OSM artefact into something
the control code can consume, run once and committed as data rather than
re-parsed at simulation time.

**What's real and what isn't.** The station exists, its coordinates are
OSM's, its name is OSM's, and the edge it snaps to is computed from the
actual network geometry -- a police car routed to that edge arrives at that
station. Nothing here is inferred the way `facilities.py`'s capability tags
are; `amenity=police` needs no further interpretation.

**Fire trucks are conspicuously absent.** The corridor's OSM extract
(`vijayawada_corridor_bbox.osm.xml`) has zero `amenity=fire_station` nodes in
this bounding box -- not a bug in this script, an absence in the source data.
`kind` is still a field on every entry (not hardcoded to "police") so a
future re-run over a wider extract, or a hand-added entry, picks up a
`fire_station` depot with no code change anywhere that reads this file.

Usage:
    python scenarios/networks/vijayawada/extract_responder_depots.py
writes `responder_depots.json` next to the network.
"""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("SUMO_HOME", "/usr/share/sumo")
import sumolib  # noqa: E402

_HERE = Path(__file__).resolve().parent
NET_PATH = _HERE / "vijayawada_corridor.net.xml"
OSM_PATH = _HERE / "vijayawada_corridor_bbox.osm.xml"
OUT_PATH = _HERE / "responder_depots.json"

SNAP_RADIUS_M = 400.0
"""Same generous radius `extract_facilities.py` uses, and for the same
reason: OSM places a station node anywhere inside its grounds, and the
vehicle bay is on the road."""

# OSM amenity value -> EmergencyKind value (itms_domain.emergency.EmergencyKind).
# Only `police` has real data in this corridor today; see the module
# docstring for why `fire_station` isn't wired to a fabricated entry instead.
_AMENITY_TO_KIND: dict[str, str] = {
    "police": "police",
    "fire_station": "fire_truck",
}


def _node_coords(root: ET.Element) -> dict[str, tuple[float, float]]:
    return {
        n.get("id"): (float(n.get("lat")), float(n.get("lon")))
        for n in root.findall("node")
    }


def extract(net_path: Path = NET_PATH, osm_path: Path = OSM_PATH) -> list[dict]:
    net = sumolib.net.readNet(str(net_path))
    root = ET.parse(osm_path).getroot()
    coords = _node_coords(root)

    depots: list[dict] = []
    for element in list(root.findall("node")) + list(root.findall("way")):
        tags = {t.get("k"): t.get("v") for t in element.findall("tag")}
        amenity = tags.get("amenity")
        kind = _AMENITY_TO_KIND.get(amenity)
        if kind is None:
            continue

        if element.tag == "node":
            latlon = coords.get(element.get("id"))
        else:
            latlon = next(
                (coords[nd.get("ref")] for nd in element.findall("nd")
                 if nd.get("ref") in coords),
                None,
            )
        if latlon is None:
            continue
        lat, lon = latlon

        x, y = net.convertLonLat2XY(lon, lat)
        candidates = net.getNeighboringEdges(x, y, r=SNAP_RADIUS_M)
        drivable = [
            (edge, dist) for edge, dist in candidates
            if edge.allows("emergency") and not edge.isSpecial()
        ]
        if not drivable:
            continue
        edge, distance = min(drivable, key=lambda pair: pair[1])
        name = tags.get("name", "").strip() or "(unnamed)"

        depots.append({
            "id": f"{amenity}:{element.get('id')}",
            "name": name,
            "kind": kind,
            "lat": lat,
            "lon": lon,
            "edge": edge.getID(),
            "edge_offset_m": round(edge.getLength() / 2.0, 1),
            "snap_distance_m": round(distance, 1),
        })

    return sorted(depots, key=lambda d: (d["kind"], d["name"]))


def main() -> None:
    depots = extract()
    OUT_PATH.write_text(json.dumps({"depots": depots}, indent=2))

    from collections import Counter

    counts = Counter(d["kind"] for d in depots)
    print(f"{len(depots)} depots -> {OUT_PATH.name}")
    for kind, count in counts.most_common():
        print(f"    {kind:12s} {count:3d}")
    missing = [k for k in _AMENITY_TO_KIND.values() if k not in counts]
    if missing:
        print(f"  no depots found for: {', '.join(missing)} -- "
              "response for that kind will no-op until real data exists")


if __name__ == "__main__":
    sys.exit(main())

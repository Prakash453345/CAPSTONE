"""Filter a raw OSM bbox extract down to the district's drivable arterial grid.

Where `filter_corridor.py` keeps one arterial (MG Road) and the streets that
touch it -- deliberately a single route -- this keeps every road in the box
that a city's traffic and its emergency vehicles actually use: trunk,
primary, secondary and tertiary roads, their link ramps and unclassified
connectors. That is what turns the corridor into a network with competing
routes (MG Road vs. Gopal Reddy Road vs. Eluru Road, and the cross streets
between them), which is what the emergency router has to choose among.

Residential lanes, service roads, footways and paths are dropped: hundreds of
short lanes add simulation cost and routes no dispatcher would send an
ambulance down, without adding real alternatives between the arterials.

Usage:
    python filter_district.py raw_osm.xml filtered_district.osm.xml
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET

KEEP_HIGHWAY = {
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
}


def filter_district(src: str, dst: str) -> tuple[int, int]:
    tree = ET.parse(src)
    root = tree.getroot()

    kept_ways = []
    used_nodes: set[str] = set()
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if tags.get("highway") not in KEEP_HIGHWAY:
            continue
        if tags.get("access") in {"no", "private"} or tags.get("area") == "yes":
            continue
        kept_ways.append(way)
        used_nodes.update(nd.get("ref") for nd in way.findall("nd"))

    out = ET.Element("osm", root.attrib)
    for child in root:
        if child.tag in {"note", "meta", "bounds"}:
            out.append(child)
    for node in root.findall("node"):
        if node.get("id") in used_nodes:
            out.append(node)
    for way in kept_ways:
        out.append(way)

    ET.ElementTree(out).write(dst, encoding="UTF-8", xml_declaration=True)
    return len(kept_ways), len(used_nodes)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    args = ap.parse_args()
    ways, nodes = filter_district(args.src, args.dst)
    print(f"kept {ways} ways, {nodes} nodes -> {args.dst}")


if __name__ == "__main__":
    main()

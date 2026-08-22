#!/usr/bin/env python3
"""Filter a raw OSM extract down to one named arterial plus the streets that
actually cross it, discarding everything else in the bounding box.

Why this exists: a straight bbox export of an Indian city core contains the
full street grid -- hundreds of junctions -- because netconvert (correctly)
imports every road inside the box. The build guide wants 9-16 junctions on
one arterial [build guide M1], not "however many happen to be inside a
rectangle." Filtering by road *name* rather than by geography is what gets
us the real corridor instead of an arbitrary crop.

Usage:
    python3 filter_corridor.py raw_osm.xml filtered_corridor.osm.xml \
        --arterial "MG Road"

Outputs an OSM XML containing only nodes/ways for the named arterial, any
other named way that shares a node with it (the real cross streets), and any
way touching the arterial's own endpoints (so it connects into whatever it
joins at either end, e.g. Benz Circle's flyover).
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET

ARTERIAL_TYPES = {
    "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
}


def load_ways(root: ET.Element) -> list[tuple[ET.Element, str | None, list[str]]]:
    ways = []
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if tags.get("highway") not in ARTERIAL_TYPES:
            continue
        name = tags.get("name") or tags.get("name:en")
        nodes = [ref for nd in way.findall("nd") if (ref := nd.get("ref")) is not None]
        ways.append((way, name, nodes))
    return ways


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_osm")
    parser.add_argument("output_osm")
    parser.add_argument(
        "--arterial", required=True, help="OSM 'name' tag of the main road, e.g. 'MG Road'"
    )
    args = parser.parse_args()

    tree = ET.parse(args.input_osm)
    root = tree.getroot()
    ways = load_ways(root)

    arterial_nodes: set[str] = set()
    arterial_terminals: set[str] = set()
    for _way, name, nodes in ways:
        if name == args.arterial and nodes:
            arterial_nodes.update(nodes)
            arterial_terminals.add(nodes[0])
            arterial_terminals.add(nodes[-1])

    if not arterial_nodes:
        raise SystemExit(f"no way named {args.arterial!r} found with an arterial highway type")

    crossing_names: set[str] = set()
    for _way, name, nodes in ways:
        if name and name != args.arterial and arterial_nodes & set(nodes):
            crossing_names.add(name)

    keep_names = {args.arterial} | crossing_names

    kept_ways = []
    for way, name, nodes in ways:
        if name in keep_names or arterial_terminals & set(nodes):
            kept_ways.append(way)

    kept_node_ids = {nd.get("ref") for way in kept_ways for nd in way.findall("nd")}

    new_root = ET.Element("osm", root.attrib)
    for node in root.findall("node"):
        if node.get("id") in kept_node_ids:
            new_root.append(node)
    for way in kept_ways:
        new_root.append(way)

    ET.ElementTree(new_root).write(args.output_osm, xml_declaration=True, encoding="UTF-8")

    print(f"arterial: {args.arterial!r} ({len(arterial_nodes)} nodes)")
    print(f"crossing streets kept: {sorted(crossing_names)}")
    print(f"kept {len(kept_ways)} of {len(ways)} arterial-type ways, {len(kept_node_ids)} nodes")


if __name__ == "__main__":
    main()

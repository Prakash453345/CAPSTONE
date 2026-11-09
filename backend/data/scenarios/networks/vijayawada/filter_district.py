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

`--extend more.osm.xml --box W,S,E,N --margin D` grows the district outward along
the busy routes. From the second file only trunk, primary and secondary roads (and their
links) are added, each clipped to the box grown by D degrees (0.01 is about 1 km),
so a national highway that runs for 20 km joins the district for D beyond its edge.
The first file's roads are kept exactly as they were; a road both files have (same
OSM id) is taken from the first.

Usage:
    python filter_district.py raw_osm.xml filtered_district.osm.xml [--extend more.osm.xml --box W,S,E,N --margin D]
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
BUSY = {"trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"}


def _usable(tags: dict) -> bool:
    return tags.get("access") not in {"no", "private"} and tags.get("area") != "yes"


def _clip(way: ET.Element, at: dict, box: tuple[float, float, float, float]) -> list[list[ET.Element]]:
    """The runs of consecutive nodes of `way` that lie inside `box`."""
    runs: list[list[ET.Element]] = []
    run: list[ET.Element] = []
    for nd in way.findall("nd"):
        p = at.get(nd.get("ref"))
        if p is not None and box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]:
            run.append(nd)
            continue
        if len(run) >= 2:
            runs.append(run)
        run = []
    if len(run) >= 2:
        runs.append(run)
    return runs


def filter_district(
    src: str,
    dst: str,
    extend: str | None = None,
    box: tuple[float, float, float, float] | None = None,
    margin: float = 0.0,
) -> tuple[int, int]:
    root = ET.parse(src).getroot()
    nodes_by_id = {n.get("id"): n for n in root.findall("node")}

    kept_ways = []
    seen_ids: set[str] = set()
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if tags.get("highway") not in KEEP_HIGHWAY or not _usable(tags):
            continue
        kept_ways.append(way)
        seen_ids.add(way.get("id"))

    if extend and box:
        more = ET.parse(extend).getroot()
        at = {n.get("id"): (float(n.get("lon")), float(n.get("lat"))) for n in more.findall("node")}
        grown = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
        for n in more.findall("node"):
            nodes_by_id.setdefault(n.get("id"), n)
        for way in more.findall("way"):
            tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
            if tags.get("highway") not in BUSY or not _usable(tags) or way.get("id") in seen_ids:
                continue
            for k, run in enumerate(_clip(way, at, grown)):
                piece = ET.Element("way", {**way.attrib, "id": way.get("id") if k == 0 else f"{way.get('id')}{k}"})
                piece.extend(run)
                piece.extend(c for c in way if c.tag != "nd")
                kept_ways.append(piece)

    if extend and box:
        # which roads are the extension, for select_district's pruning
        with open(dst + ".extension", "w") as f:
            f.write("\n".join(w.get("id") for w in kept_ways if w.get("id") not in seen_ids) + "\n")

    used_nodes = {nd.get("ref") for way in kept_ways for nd in way.findall("nd")}
    out = ET.Element("osm", root.attrib)
    for child in root:
        if child.tag in {"note", "meta", "bounds"}:
            out.append(child)
    for nid in used_nodes:
        if nid in nodes_by_id:
            out.append(nodes_by_id[nid])
    for way in kept_ways:
        out.append(way)
    ET.ElementTree(out).write(dst, encoding="UTF-8", xml_declaration=True)
    return len(kept_ways), len(used_nodes)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--extend", help="a larger OSM extract to take the busy routes from")
    ap.add_argument("--box", help="W,S,E,N of the district the routes connect to")
    ap.add_argument("--margin", type=float, default=0.0, help="degrees beyond the box to follow them")
    args = ap.parse_args()
    box = tuple(float(v) for v in args.box.split(",")) if args.box else None
    ways, nodes = filter_district(args.src, args.dst, args.extend, box, args.margin)  # type: ignore[arg-type]
    print(f"kept {ways} ways, {nodes} nodes -> {args.dst}")


if __name__ == "__main__":
    main()

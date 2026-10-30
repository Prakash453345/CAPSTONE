"""Turn an OpenStreetMap extract of a city that is still being built into the
road network it is planned to have.

OpenStreetMap tags a road under construction `highway=construction` with the
class it will have in `construction=*`; netconvert drops such ways. This
script promotes them, sets the lane count the plan gives them, and keeps only
the classes named (the arterial network; village streets and farm tracks are
left out).

    python scenarios/osm_planned_roads.py IN.osm.xml OUT.osm.xml \
        --planned-lanes 2 --lanes "Seed Access Road=3"

Amaravati: the ten priority E and N roads are sub-arterials with a 50 m right
of way and a four-lane carriageway, six of them with two more lanes for buses
(World Bank, Environmental Assessment for 10 Priority Roads, 2018), so planned
roads get two lanes each way.
"""
import argparse
import xml.etree.ElementTree as ET

KEEP = ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
        "secondary", "secondary_link", "tertiary", "tertiary_link")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--planned-class", default="secondary",
                    help="class of a construction way whose own class is missing or minor")
    ap.add_argument("--planned-lanes", type=int, default=2, help="lanes each way on planned roads")
    ap.add_argument("--lanes", action="append", default=[], metavar="NAME=N",
                    help="lanes each way on the road of this name (repeatable)")
    args = ap.parse_args()
    by_name = {k: int(v) for k, v in (x.split("=") for x in args.lanes)}

    tree = ET.parse(args.src)
    root = tree.getroot()
    used, kept, promoted = set(), 0, 0
    for way in list(root.findall("way")):
        tags = {t.get("k"): t for t in way.findall("tag")}
        cls = tags["highway"].get("v") if "highway" in tags else None
        each_way = None
        if cls == "construction":
            planned = tags["construction"].get("v") if "construction" in tags else None
            if planned not in KEEP:
                planned = None if planned in ("residential", "service") else args.planned_class
            if planned is not None:
                tags["highway"].set("v", planned)
                cls, each_way, promoted = planned, args.planned_lanes, promoted + 1
        if cls not in KEEP:
            root.remove(way)
            continue
        name = (tags["name"].get("v") if "name" in tags else None) or \
               (tags["ref"].get("v") if "ref" in tags else None)
        each_way = by_name.get(name, each_way)
        if each_way is not None:
            one_way = "oneway" in tags and tags["oneway"].get("v") in ("yes", "1", "true")
            total = str(each_way if one_way else 2 * each_way)
            if "lanes" in tags:
                tags["lanes"].set("v", total)
            else:
                ET.SubElement(way, "tag", {"k": "lanes", "v": total})
        kept += 1
        used.update(nd.get("ref") for nd in way.findall("nd"))
    for node in list(root.findall("node")):
        if node.get("id") not in used:
            root.remove(node)
    for rel in list(root.findall("relation")):
        root.remove(rel)
    tree.write(args.out, encoding="UTF-8", xml_declaration=True)
    print(f"kept {kept} ways ({promoted} were under construction), {len(used)} nodes -> {args.out}")


if __name__ == "__main__":
    main()

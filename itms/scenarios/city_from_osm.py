"""A scenario for any city, straight from OpenStreetMap.

    python scenarios/city_from_osm.py --bbox W,S,E,N --name hyderabad_ameerpet --lefthand
    python scenarios/city_from_osm.py --osm my_area.osm.xml --name my_area --lefthand
    ITMS_SCENARIO=scenarios/generated/hyderabad_ameerpet python scripts/m8_closed_loop_gate.py ...

Steps:

1. **Download** (`--bbox`): SUMO's `osmGet.py` fetches the area from the
   Overpass API. This needs ordinary internet access; it does not work from
   the build sandbox, where the file is given with `--osm` instead.
2. **Convert** with netconvert, the options the corridor's
   `networks/vijayawada/build.sh` uses (OSM nodes within 25 m joined into
   one junction, lights on one junction cluster joined, OSM signal tags
   read), roads that cars can use only, cropped to the box. Speed limits are
   capped at 50 km/h (`--max-speed`), as the corridor's are
   (`networks/vijayawada/cap_speeds.py`: OSM's typemap gives city trunk
   roads inter-urban limits, and the yellow and the delay metric read them).
3. **Signals.** OpenStreetMap marks few signals in Indian cities: the
   Vijayawada extract converts to one light in about 1,500 junctions, and
   netconvert's own guess (`--tls.guess`, by the sum of incoming speeds)
   adds three, because the speeds are low. So a junction also gets a
   light where at least `--signal-approaches` (3) of the roads entering it
   are `--signal-class` (tertiary) or above: two real roads crossing, or a
   T of them. Residential streets meeting stay give-way junctions. The
   corridor's seven lights were chosen by hand the same way ("the
   highest-degree real crossroads on the arterial").
4. **Scenario**: `build_scenario.py --net` (demand at three levels set by
   load, the vehicle mix, cameras).

`scenario.json` records the source (bbox or file), the netconvert command and
the signal rule, so the network can be rebuilt.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

sys.path.insert(0, str(_HERE / "networks" / "vijayawada"))

from build_scenario import sumo_home  # noqa: E402
from cap_speeds import URBAN_ARTERIAL_MPS, cap_speeds  # noqa: E402

# OSM highway classes, most important first
CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential"]

NETCONVERT_OPTIONS = [
    "--geometry.remove", "--geometry.remove.min-length", "5",
    "--junctions.join", "--junctions.join-dist", "25",
    "--tls.guess-signals", "--tls.discard-simple", "--tls.join",
    "--roundabouts.guess", "--ramps.guess",
    "--keep-edges.by-vclass", "passenger", "--remove-edges.isolated",
]


def _class_rank(edge_type: str | None) -> int:
    """Position of an edge's OSM class in CLASSES (`highway.primary_link`
    counts as primary); unknown classes rank below all of them."""
    if not edge_type or not edge_type.startswith("highway."):
        return len(CLASSES)
    base = edge_type.removeprefix("highway.").removesuffix("_link")
    return CLASSES.index(base) if base in CLASSES else len(CLASSES)


def junctions_to_signal(net: Path, *, min_class: str = "tertiary",
                        approaches: int = 3) -> list[str]:
    """Junctions, not yet signalised, where at least `approaches` entering
    roads are `min_class` or above and at least three roads meet."""
    root = ET.parse(net).getroot()
    limit = CLASSES.index(min_class)
    entering: dict[str, list[int]] = defaultdict(list)
    neighbours: dict[str, set[str]] = defaultdict(set)
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        a, b = e.get("from", ""), e.get("to", "")
        entering[b].append(_class_rank(e.get("type")))
        neighbours[a].add(b)
        neighbours[b].add(a)
    types = {j.get("id"): j.get("type") for j in root.findall("junction")}
    return sorted(
        n for n, ranks in entering.items()
        if len(neighbours[n]) >= 3
        and sum(r <= limit for r in ranks) >= approaches
        and types.get(n) not in ("traffic_light", "traffic_light_right_on_red",
                                 "traffic_light_unregulated", "dead_end", "rail_crossing")
    )


def zero_length_joins(net: Path, below_m: float = 1.0) -> list[list[str]]:
    """Groups of OSM nodes that came out as separate junctions with an edge of
    (almost) no length between them: a crossing of divided roads that
    netconvert joined only in part. Each group is to be joined explicitly."""
    root = ET.parse(net).getroot()
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for edge in root.findall("edge"):
        if edge.get("function") == "internal":
            continue
        if float(edge.find("lane").get("length")) < below_m:
            parent[find(edge.get("from"))] = find(edge.get("to"))
    groups: dict[str, set[str]] = {}
    for junction in parent:
        members = junction.removeprefix("cluster_").split("_") if junction.startswith(
            "cluster_") else [junction]
        groups.setdefault(find(junction), set()).update(members)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--bbox", help="W,S,E,N in degrees (downloads from OpenStreetMap)")
    src.add_argument("--osm", help="an OSM XML file you already have")
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", help="default scenarios/generated/<name>")
    ap.add_argument("--crop", help="W,S,E,N to keep (default: --bbox; none for --osm)")
    ap.add_argument("--lefthand", action="store_true", help="left-hand traffic (India)")
    ap.add_argument("--mix", default=None, help="india (default with --lefthand) or cars")
    ap.add_argument("--signal-class", default="tertiary", choices=CLASSES)
    ap.add_argument("--signal-approaches", type=int, default=3)
    ap.add_argument("--join-parallel", action="store_true",
                    help="also join junctions whose roads come in as two parallel carriageways "
                         "(netconvert refuses these by default; without it a crossing of two "
                         "divided roads stays several junctions with 0.2 m edges between them)")
    ap.add_argument("--join-dist", type=float, default=25.0,
                    help="join OSM nodes of one junction within this many metres. Wide roads "
                         "drawn as two carriageways need more: nodes 30-60 m apart otherwise "
                         "stay two junctions with a 0.2 m, one-lane edge between them")
    ap.add_argument("--max-speed", type=float, default=URBAN_ARTERIAL_MPS,
                    help="m/s cap on every lane (default 13.89 = 50 km/h; 0 keeps OSM's)")
    ap.add_argument("--no-cameras", action="store_true")
    ap.add_argument("--levels", help="passed to build_scenario.py")
    ap.add_argument("--periods", help="passed to build_scenario.py (an exact rebuild)")
    args = ap.parse_args()

    home = sumo_home()
    env = {**os.environ, "SUMO_HOME": str(home), "PROJ_LIB": str(home / "data" / "proj")}
    out = Path(args.out or _HERE / "generated" / args.name)
    work = out / "osm"
    work.mkdir(parents=True, exist_ok=True)

    if args.bbox:
        subprocess.run([sys.executable, str(home / "tools" / "osmGet.py"), "--bbox", args.bbox,
                        "-p", args.name, "-d", str(work)], check=True, env=env)
        osm = work / f"{args.name}_bbox.osm.xml"
    else:
        osm = Path(args.osm).resolve()
    crop = args.crop or args.bbox

    raw = work / f"{args.name}_osm.net.xml"
    convert = [str(home / "bin" / "netconvert"), "--osm-files", str(osm), "-o", str(raw),
               "--type-files", str(home / "data" / "typemap" / "osmNetconvert.typ.xml"),
               *[f"{args.join_dist:g}" if prev == "--junctions.join-dist" else opt
                 for prev, opt in zip([None, *NETCONVERT_OPTIONS], NETCONVERT_OPTIONS,
                                      strict=False)]]
    if args.join_parallel:
        convert += ["--junctions.join.parallel-threshold", "0"]
    if crop:
        convert += ["--keep-edges.in-geo-boundary", crop]
    if args.lefthand:
        convert.append("--lefthand")
    subprocess.run(convert, check=True, env=env, capture_output=True)
    if args.join_parallel:
        # what the automatic join still left as junctions with nothing between them
        joins_file = work / f"{args.name}_joins.nod.xml"
        for _ in range(3):
            groups = zero_length_joins(raw)
            if not groups:
                break
            known = ET.parse(joins_file).getroot() if joins_file.exists() else ET.Element("nodes")
            for group in groups:
                ET.SubElement(known, "join", {"nodes": " ".join(group)})
            ET.ElementTree(known).write(joins_file, encoding="UTF-8", xml_declaration=True)
            subprocess.run([*convert, "--node-files", str(joins_file)], check=True, env=env,
                           capture_output=True)

    extra = junctions_to_signal(raw, min_class=args.signal_class,
                                approaches=args.signal_approaches)
    net = work / f"{args.name}.net.xml"
    resignal = [str(home / "bin" / "netconvert"), "-s", str(raw), "-o", str(net),
                "--tls.join", "--tls.discard-simple"]
    if extra:
        resignal += ["--tls.set", ",".join(extra)]
    subprocess.run(resignal, check=True, env=env, capture_output=True)
    capped = cap_speeds(net, args.max_speed) if args.max_speed > 0 else 0

    mix = args.mix or ("india" if args.lefthand else "cars")
    build = [sys.executable, str(_HERE / "build_scenario.py"), "--net", str(net),
             "--name", args.name, "--out", str(out), "--mix", mix]
    if args.no_cameras:
        build.append("--no-cameras")
    if args.levels:
        build += ["--levels", args.levels]
    if args.periods:
        build += ["--periods", args.periods]
    subprocess.run(build, check=True, env=env)

    manifest_path = out / "scenario.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["osm"] = {
        "bbox": args.bbox, "file": None if args.bbox else str(osm), "crop": crop,
        "netconvert": " ".join(Path(c).name if c.startswith("/") else c for c in convert[1:]),
        "signal_rule": f"OSM signal tags, plus junctions where >= {args.signal_approaches} "
                       f"entering roads are {args.signal_class} or above",
        "signals_added": len(extra),
        "max_speed_mps": args.max_speed or None, "lanes_capped": capped,
    }
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"{args.name}: {manifest['signalised_junctions']} signalised junctions "
          f"({len(extra)} by the class rule) -> {out}")


if __name__ == "__main__":
    main()

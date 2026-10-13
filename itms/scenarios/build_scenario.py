"""Build a scenario for ANY road network: the network, demand at three
levels, and a camera plan -- everything the gates and the live services need.

The project was built on one corridor (`networks/vijayawada/`, demand in
`demand/vijayawada/`), and its demand levels there are fixed trip rates
(`randomTrips -p 5.0 / 2.5 / 1.25`). A fixed rate means something different on
every other network: what is "heavy" for a two-lane corridor is nothing for a
six-lane grid. So here a level is defined by **how loaded the busiest
junction is**: its flow ratio `Y`, the sum over its phases of the critical
movement's flow over saturation flow -- what `webster.compute_timing` (the
fixed-time baseline's own calculation) reports as `degree_of_saturation`.
It is `Y`, not `X = Y * C / (C - L)`: lost time is not counted, so `Y = 1`
is already past capacity. The Vijayawada corridor's own levels measure as
light 0.245, medium 0.471, heavy 0.996, so the defaults (0.25 / 0.5 / 1.0)
put any network at the load the corridor was studied at. The saturation
flow is Webster's nominal one, which overstates what a single lane shared
with turning traffic carries. The trip period that reaches each target is found by iteration
(flow is close to proportional to 1/period).

Input is either an existing SUMO network (`--net`, e.g. an OpenStreetMap
export converted with netconvert) or one generated here (`--generate`):

    grid:NXxNY,block_m,lanes[,attach_m]     a Manhattan grid
    spider:arms,circles,radius_m,lanes      radial rings
    rand:iterations,min_dist_m,lanes[,seed] an irregular random street net

with `--lefthand` for left-hand traffic (India) and `--turn-lanes 1` for a
dedicated turning lane. Every junction of degree 3+ is signalised.

Demand is SUMO's `randomTrips.py` (fringe-weighted trips, routed by
duarouter), departures over 30 minutes like the corridor's, then the vehicle
mix: `--mix india` is the corridor's two-wheeler-heavy mix (its vTypes,
occupancy and PCU, `demand/vijayawada/assign_vtypes.py`), `--mix cars` an
all-car fleet.

    python scenarios/build_scenario.py --generate grid:3x3,300,2 --lefthand \\
        --out scenarios/generated/grid3_lh
    python scenarios/build_scenario.py --net city.net.xml --out scenarios/generated/city2

The result is a directory with `scenario.json` (read by the harnesses when
`ITMS_SCENARIO` points at it), the network, one route file and sumocfg per
level, and `cameras.json`.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
sys.path.insert(0, str(_ROOT / "scenarios" / "demand" / "vijayawada"))
import assign_vtypes as india  # noqa: E402
from extract_tier0_config import load_configs  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402

LEVELS = {"light": 0.25, "medium": 0.5, "heavy": 1.0}
DEMAND_END_S = 1800
MIXES = {
    # the corridor's mix, unchanged (its vTypes, occupancy and PCU)
    "india": {"mix": india._MIX, "occupancy": india._OCCUPANCY, "pcu": india._PCU,  # noqa: SLF001
              "vclass": india._VCLASS, "shape": india._GUI_SHAPE,  # noqa: SLF001
              "color": india._COLOR},  # noqa: SLF001
    "cars": {"mix": {"veh_car": 1.0}, "occupancy": {"veh_car": 1.5}, "pcu": {"veh_car": 1.0},
             "vclass": {"veh_car": "passenger"}, "shape": {"veh_car": "passenger/sedan"},
             "color": {"veh_car": "127,209,255"}},
}


def sumo_home() -> Path:
    home = os.environ.get("SUMO_HOME")
    if home:
        return Path(home)
    import sumo  # noqa: PLC0415

    return Path(sumo.__file__).parent


def _bin(name: str) -> str:
    return str(sumo_home() / "bin" / name)


def generate_net(spec: str, out: Path, *, lefthand: bool, turn_lanes: int, speed: float,
                 tls_layout: str = "opposites") -> list:
    kind, _, params = spec.partition(":")
    p = [v.strip() for v in params.split(",")] if params else []
    cmd = [_bin("netgenerate"), "-o", str(out), "--default-junction-type", "traffic_light",
           "--default.speed", str(speed), "--no-turnarounds", "true",
           "--tls.layout", tls_layout]
    if kind == "grid":
        nx, ny = (int(v) for v in p[0].lower().split("x"))
        cmd += ["--grid", "--grid.x-number", str(nx), "--grid.y-number", str(ny),
                "--grid.length", p[1], "--default.lanenumber", p[2],
                "--grid.attach-length", p[3] if len(p) > 3 else p[1]]
    elif kind == "spider":
        cmd += ["--spider", "--spider.arm-number", p[0], "--spider.circle-number", p[1],
                "--spider.space-radius", p[2], "--default.lanenumber", p[3]]
    elif kind == "rand":
        cmd += ["--rand", "--rand.iterations", p[0], "--rand.min-distance", p[1],
                "--rand.max-distance", str(3 * float(p[1])), "--default.lanenumber", p[2],
                "--seed", p[3] if len(p) > 3 else "1", "--rand.min-angle", "45",
                "--rand.neighbor-dist1", "0", "--rand.neighbor-dist2", "0"]
    else:
        raise SystemExit(f"unknown generator {kind!r} (grid, spider, rand)")
    if lefthand:
        cmd.append("--lefthand")
    if turn_lanes:
        cmd += ["--turn-lanes", str(turn_lanes)]
    subprocess.run(cmd, check=True, capture_output=True)
    _unsignal_minor(out)
    return cmd


def _unsignal_minor(net: Path) -> None:
    """`--default-junction-type traffic_light` also signals dead ends and
    two-way bends; only junctions where three or more roads meet keep their
    signal (netconvert rebuilds the programs)."""
    root = ET.parse(net).getroot()
    edges_at: dict[str, set] = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        for end in (e.get("from"), e.get("to")):
            other = e.get("to") if end == e.get("from") else e.get("from")
            edges_at.setdefault(end, set()).add(other)
    minor = [j.get("id") for j in root.findall("junction")
             if j.get("type") == "traffic_light" and len(edges_at.get(j.get("id"), ())) < 3]
    if minor:
        tmp = net.with_name(net.stem + ".tmp.net.xml")
        subprocess.run([_bin("netconvert"), "-s", str(net), "-o", str(tmp),
                        "--tls.unset", ",".join(minor)], check=True, capture_output=True)
        tmp.replace(net)


def assign_mix(rou: Path, mix_name: str, seed: int = 7) -> None:
    m = MIXES[mix_name]
    text = rou.read_text(encoding="UTF-8")
    split = text.index("<routes")
    root = ET.fromstring(text[split:])
    for old in root.findall("vType"):
        root.remove(old)
    for type_id in reversed(list(m["mix"])):
        el = ET.Element("vType", {"id": type_id, "vClass": m["vclass"][type_id],
                                  "guiShape": m["shape"][type_id], "color": m["color"][type_id]})
        ET.SubElement(el, "param", {"key": "occupancy", "value": str(m["occupancy"][type_id])})
        ET.SubElement(el, "param", {"key": "pcu", "value": str(m["pcu"][type_id])})
        root.insert(0, el)
    rng = random.Random(seed)
    ids, weights = list(m["mix"]), list(m["mix"].values())
    for v in root.findall("vehicle"):
        v.set("type", rng.choices(ids, weights=weights, k=1)[0])
    ET.indent(root, space="    ")
    rou.write_text(text[:split] + ET.tostring(root, encoding="unicode") + "\n", encoding="UTF-8")


def trips(net: Path, rou: Path, period: float, seed: int) -> None:
    tmp_trips = rou.with_suffix(".trips.xml")
    subprocess.run([sys.executable, str(sumo_home() / "tools" / "randomTrips.py"), "-n", str(net),
                    "-o", str(tmp_trips), "--route-file", str(rou), "-b", "0",
                    "-e", str(DEMAND_END_S), "-p", f"{period:.4f}", "--fringe-factor", "5",
                    "--validate", "--seed", str(seed), "--vehicle-class", "passenger",
                    "--prefix", "veh"], check=True, capture_output=True)
    tmp_trips.unlink(missing_ok=True)
    for extra in rou.parent.glob(rou.stem + ".alt.xml"):
        extra.unlink()


def max_ds(net: Path, rou: Path, configs) -> tuple[float, str]:
    from sim_service.control.strategies import webster  # noqa: PLC0415

    flows = compute_link_flows(net, rou)
    best = (0.0, "")
    for tls, cfg in configs.items():
        ds = webster.compute_timing(cfg, flows.get(tls, {})).degree_of_saturation
        best = max(best, (ds, tls))
    return best


def demand_for(net: Path, rou: Path, target: float, configs, mix: str, seed: int) -> dict:
    period, history = 4.0, []
    for _ in range(8):
        trips(net, rou, period, seed)
        assign_mix(rou, mix)
        ds, tls = max_ds(net, rou, configs)
        history.append((round(period, 4), round(ds, 4)))
        if abs(ds - target) <= 0.02 * max(target, 0.1):
            break
        period = period * ds / target if ds > 0 else period / 2
    return {"target_ds": target, "achieved_ds": round(ds, 4), "busiest_tls": tls,
            "period_s": round(period, 4), "iterations": history}


SUMOCFG = """<?xml version="1.0" encoding="UTF-8"?>
<!-- generated by scenarios/build_scenario.py -->
<configuration>
    <input>
        <net-file value="{net}"/>
        <route-files value="{rou}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="{end}"/>
        <step-length value="1"/>
    </time>
    <processing>
        <time-to-teleport value="300"/>
    </processing>
</configuration>
"""


def map_center(net: Path) -> str | None:
    """`"lat,lon"` of the network's middle, for the web map
    (`VITE_MAP_CENTER`); None for a network without a map projection
    (netgenerate's), whose coordinates are not on the globe."""
    for _, el in ET.iterparse(net, events=("start",)):
        if el.tag == "location":
            proj = el.get("projParameter", "!")
            if proj in ("", "!"):
                return None
            # the middle of what was kept (convBoundary), not of what OSM
            # delivered (origBoundary: a cropped import keeps the whole ways')
            x0, y0, x1, y1 = (float(v) for v in el.get("convBoundary", "0,0,0,0").split(","))
            ox, oy = (float(v) for v in el.get("netOffset", "0,0").split(","))
            try:
                from pyproj import Proj  # noqa: PLC0415

                lon, lat = Proj(proj)((x0 + x1) / 2 - ox, (y0 + y1) / 2 - oy, inverse=True)
            except Exception:  # noqa: BLE001 -- no pyproj: the delivered area's middle
                w, so, e, n = (float(v) for v in el.get("origBoundary", "0,0,0,0").split(","))
                lat, lon = (so + n) / 2, (w + e) / 2
            return f"{lat:.6f},{lon:.6f}"
    return None


def plan_cameras(net: Path, out: Path) -> dict:
    from itms_geo import RoadNetwork  # noqa: PLC0415
    from vision_service.cameras import CameraRig, save_registry  # noqa: PLC0415
    from vision_service.placement import plan_network_cameras  # noqa: PLC0415

    network = RoadNetwork.from_sumo_net(net)
    results = plan_network_cameras(network, mount_height_m=10.0, hfov_deg=50.0, fps=5.0)
    rig = CameraRig.build(network, [r.spec for r in results])
    save_registry(out, [r.spec for r in results], network=net.name,
                  meta={"planner": "vision_service.placement.plan_network_cameras",
                        "mount_height_m": 10.0, "hfov_deg": 50.0},
                  max_resolution_m_per_px=rig.max_resolution_m_per_px)
    return {"cameras": len(results)}


def plan_box_cameras(net: Path, cameras: Path, out: Path) -> dict:
    """`cameras` (the approach cameras) plus one junction-overview camera per
    signalised junction, written to `out`: the rig for a controller that
    needs to see a vehicle waiting inside the junction
    (`sim_service/control/strategies/hol.py`). A separate file, so the
    scenario's ordinary camera runs keep the rig they were measured with."""
    from itms_geo import RoadNetwork  # noqa: PLC0415
    from vision_service.cameras import load_registry, save_registry  # noqa: PLC0415
    from vision_service.placement import plan_box_cameras as plan  # noqa: PLC0415

    network = RoadNetwork.from_sumo_net(net)
    specs, raw = load_registry(cameras)
    results = plan(network, mount_height_m=10.0, hfov_deg=90.0, fps=5.0)
    save_registry(out, [*specs, *(r.spec for r in results)], network=net.name,
                  meta={**raw.get("meta", {}),
                        "box_planner": "vision_service.placement.plan_box_cameras",
                        "box_hfov_deg": 90.0},
                  max_resolution_m_per_px=raw.get("max_resolution_m_per_px", 0.6))
    paths = sum(len(r.covered_from_stopline_m) for r in results)
    seen = sum(sum(r.covered_from_stopline_m.values()) for r in results)
    total = sum(p.length for r in results
                for p in network.box_paths[r.spec.tls_id].values())
    return {"box_cameras": len(results), "box_paths": paths,
            "box_path_metres_covered": round(seen / total, 3) if total else 0.0}


def main() -> None:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--add-box-cameras", action="store_true",
                     help="add junction-overview cameras (cameras_box.json) to the scenario "
                          "already in --out, and nothing else")
    src.add_argument("--net", help="an existing SUMO .net.xml")
    src.add_argument("--generate", help="grid:NXxNY,block_m,lanes | spider:arms,circles,radius,"
                                        "lanes | rand:iterations,min_dist_m,lanes[,seed]")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name")
    ap.add_argument("--lefthand", action="store_true")
    ap.add_argument("--turn-lanes", type=int, default=0)
    ap.add_argument("--tls-layout", choices=("opposites", "incoming"), default="opposites",
                    help="generated nets: opposite approaches share a phase (2-phase with "
                         "permissive turns), or one phase per approach")
    ap.add_argument("--speed", type=float, default=13.89, help="m/s, generated nets only")
    ap.add_argument("--mix", choices=sorted(MIXES), default="india")
    ap.add_argument("--levels", default=",".join(f"{k}:{v}" for k, v in LEVELS.items()))
    ap.add_argument("--periods", help="level:seconds,... -- use these trip periods instead of "
                                      "searching (to rebuild a scenario exactly from its "
                                      "scenario.json)")
    ap.add_argument("--seed", type=int, default=42, help="randomTrips seed (the corridor's)")
    ap.add_argument("--no-cameras", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    if args.add_box_cameras:
        manifest = json.loads((out / "scenario.json").read_text())
        manifest.update(plan_box_cameras(out / manifest["net"], out / manifest["cameras_file"],
                                         out / "cameras_box.json"))
        manifest["box_cameras_file"] = "cameras_box.json"
        (out / "scenario.json").write_text(json.dumps(manifest, indent=1))
        print({k: v for k, v in manifest.items() if k.startswith("box_")})
        return
    out.mkdir(parents=True, exist_ok=True)
    name = args.name or out.name
    net = out / f"{name}.net.xml"
    manifest: dict = {"name": name, "net": net.name, "mix": args.mix, "levels": {},
                      "demand": "randomTrips --fringe-factor 5, 0-1800 s, routed by duarouter"}
    if args.generate:
        cmd = generate_net(args.generate, net, lefthand=args.lefthand,
                           turn_lanes=args.turn_lanes, speed=args.speed,
                           tls_layout=args.tls_layout)
        manifest["generated"] = {"spec": args.generate, "lefthand": args.lefthand,
                                 "turn_lanes": args.turn_lanes, "speed_mps": args.speed,
                                 "tls_layout": args.tls_layout,
                                 "netgenerate": " ".join(["netgenerate", *[
                                     net.name if c == str(net) else c for c in cmd[1:]]])}
    else:
        if str(args.net).endswith(".gz"):
            with gzip.open(args.net, "rb") as src, net.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            shutil.copyfile(args.net, net)
        manifest["source_net"] = str(args.net)
    configs = load_configs(net)
    if not configs:
        raise SystemExit(f"{net} has no signalised junction")
    manifest["signalised_junctions"] = len(configs)
    manifest["map_center"] = map_center(net)
    manifest["phases_per_junction"] = sorted(len(c.ring_order) for c in configs.values())
    periods = dict(kv.split(":") for kv in args.periods.split(",")) if args.periods else {}
    for level, target in (kv.split(":") for kv in args.levels.split(",")):
        rou = out / f"{name}_{level}.rou.xml"
        if level in periods:
            period = float(periods[level])
            trips(net, rou, period, args.seed)
            assign_mix(rou, args.mix)
            ds, tls = max_ds(net, rou, configs)
            info = {"target_ds": float(target), "achieved_ds": round(ds, 4), "busiest_tls": tls,
                    "period_s": round(period, 4), "iterations": [(round(period, 4), round(ds, 4))]}
        else:
            info = demand_for(net, rou, float(target), configs, args.mix, args.seed)
        cfg = out / f"{name}_{level}.sumocfg"
        cfg.write_text(SUMOCFG.format(net=net.name, rou=rou.name, end=DEMAND_END_S))
        manifest["levels"][level] = {"sumocfg": cfg.name, "route": rou.name, **info}
        print(f"{level}: target X {target}, got {info['achieved_ds']} at period "
              f"{info['period_s']} s ({info['busiest_tls']})", flush=True)
    if not args.no_cameras:
        manifest.update(plan_cameras(net, out / "cameras.json"))
        manifest["cameras_file"] = "cameras.json"
    (out / "scenario.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {out / 'scenario.json'}: {len(configs)} signalised junctions")


if __name__ == "__main__":
    main()

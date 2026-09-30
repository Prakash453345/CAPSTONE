"""Plan the Vijayawada corridor's junction cameras and write the registry.

One camera per signalised approach (`vision_service/placement.py` explains
the layout and the search). Writes
`scenarios/networks/vijayawada/cameras.json`, which every M8 experiment and
the live vision service load -- so the camera layout is a reviewed, committed
file rather than something recomputed differently on every machine.

    python scripts/m8_plan_cameras.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from itms_geo import RoadNetwork
from vision_service.cameras import CameraRig, save_registry
from vision_service.placement import describe, plan_network_cameras

_ROOT = Path(__file__).resolve().parent.parent
_NET_DIR = _ROOT / "scenarios" / "networks" / "vijayawada"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", default=str(_NET_DIR / "vijayawada_corridor.net.xml"))
    ap.add_argument("--out", default=str(_NET_DIR / "cameras.json"))
    ap.add_argument("--height", type=float, default=10.0)
    ap.add_argument("--hfov", type=float, default=50.0)
    ap.add_argument("--fps", type=float, default=5.0)
    args = ap.parse_args()

    net = RoadNetwork.from_sumo_net(args.net)
    results = plan_network_cameras(net, mount_height_m=args.height, hfov_deg=args.hfov,
                                   fps=args.fps)
    print(describe(results))
    rig = CameraRig.build(net, [r.spec for r in results])
    approach, receiving = net.link_lane_maps()
    a_lanes = {lane for links in approach.values() for lane in links.values()}
    r_lanes = {lane for links in receiving.values() for lane in links.values()}
    covered_a = [rig.coverage_by_lane[lane].covered_from_end_m for lane in a_lanes
                 if lane in rig.coverage_by_lane]
    covered_r = [rig.coverage_by_lane[lane].covered_from_start_m for lane in r_lanes
                 if lane in rig.coverage_by_lane]
    meta = {
        "planner": "vision_service.placement.plan_network_cameras",
        "mount_height_m": args.height,
        "hfov_deg": args.hfov,
        "approach_lanes": len(a_lanes),
        "approach_lanes_seen_from_stop_line": sum(1 for v in covered_a if v > 0),
        "approach_mean_covered_from_stop_line_m": round(sum(covered_a) / max(1, len(covered_a)),
                                                        1),
        "receiving_lanes": len(r_lanes),
        "receiving_lanes_seen_from_start": sum(1 for v in covered_r if v > 0),
    }
    net_path = Path(args.net).resolve()
    rel_net = net_path.relative_to(_ROOT) if net_path.is_relative_to(_ROOT) else args.net
    save_registry(args.out, [r.spec for r in results], network=str(rel_net), meta=meta,
                  max_resolution_m_per_px=rig.max_resolution_m_per_px)
    print(json.dumps(meta, indent=1))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

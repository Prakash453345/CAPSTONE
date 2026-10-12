"""Calibrate a real camera from point correspondences and add it to a
registry.

Pick at least four points you can find both in a frame and on the map --
lane-marking corners, kerb corners, the ends of a stop line -- spread over
the part of the road the camera is meant to measure. Write them down:

    {
      "camera_id": "cam_benz_circle_north",
      "tls_id": "cluster_1880441740_4393296791",
      "image_size": [1920, 1080],
      "nadir_lonlat": [80.6481, 16.4990],
      "source": "rtsp://${CAM_USER}:${CAM_PASS}@10.0.0.12/stream1",
      "points": [
        {"image": [412, 988],  "lonlat": [80.64812, 16.49871]},
        {"image": [1502, 961], "lonlat": [80.64830, 16.49868]},
        ...
      ]
    }

(`"xy": [x, y]` in SUMO network metres instead of `"lonlat"` works too.
The `source` may name environment variables, as above, so the registry
never holds a camera password.)

Six or more points, please. A homography has eight unknowns, so **four points
fit exactly and their error is zero whatever you clicked** -- the RMS check
means something only when there are points to spare, and RANSAC can only
throw out a mis-click if enough good points outvote it. A calibration with
fewer than `--min-inliers` (default 6) agreeing points is refused.

    python -m vision_service.calibrate points.json --registry cameras.json

fits the ground homography with RANSAC, reports the reprojection error in
pixels **and** what that error means on the road in metres (a 3-pixel error
at 100 m is a metre or more), refuses a calibration whose RMS error is worse
than `--max-rms-px`, and writes the camera into the registry as a
`HomographyCamera`. It also prints which lanes the camera covers, from the
stop line back -- the number that decides whether it can measure a queue.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from itms_geo import (
    HomographyCamera,
    RoadNetwork,
    camera_coverage,
    estimate_homography_ransac,
    reprojection_error,
)
from itms_geo.road import lanes_near

from vision_service.cameras import CameraSpec, load_registry, save_registry


def calibrate(points: dict, network: RoadNetwork, *, ransac_px: float = 4.0) -> tuple[
    HomographyCamera, dict
]:
    img = np.array([p["image"] for p in points["points"]], dtype=np.float64)
    if "lonlat" in points["points"][0]:
        ground = network.lonlat_to_xy(np.array([p["lonlat"] for p in points["points"]]))
    else:
        ground = np.array([p["xy"] for p in points["points"]], dtype=np.float64)
    h, inliers = estimate_homography_ransac(ground, img, threshold=ransac_px)
    rep = reprojection_error(h, ground[inliers], img[inliers])
    if "nadir_lonlat" in points:
        nadir = network.lonlat_to_xy(np.array([points["nadir_lonlat"]]))[0]
    else:
        nadir = np.asarray(points["nadir_xy"], dtype=np.float64)
    w, hh = points["image_size"]
    cam = HomographyCamera.from_matrix(h, int(w), int(hh), nadir, points["camera_id"])
    # the same error on the road: image -> ground for each clicked point
    back = cam.image_to_ground(img[inliers])
    ground_err = np.hypot(*(back - ground[inliers]).T)
    report = {
        "points": len(img),
        "inliers": int(inliers.sum()),
        "outliers": [int(i) for i in np.nonzero(~inliers)[0]],
        "rms_px": rep.rms,
        "max_px": rep.max,
        "ground_rms_m": float(np.sqrt(np.mean(ground_err**2))),
        "ground_max_m": float(ground_err.max()),
    }
    return cam, report


def main() -> None:
    ap = argparse.ArgumentParser(description="Calibrate a camera from point correspondences.")
    ap.add_argument("points")
    ap.add_argument("--registry", required=True)
    ap.add_argument("--net", default=None, help="SUMO net (default: the registry's network)")
    ap.add_argument("--max-rms-px", type=float, default=3.0)
    ap.add_argument("--min-inliers", type=int, default=6,
                    help="agreeing points required; 4 always fit exactly, so they prove nothing")
    ap.add_argument("--fps", type=float, default=5.0)
    args = ap.parse_args()

    pts = json.loads(Path(args.points).read_text())
    reg_path = Path(args.registry)
    specs, raw = (load_registry(reg_path) if reg_path.exists() else ([], {}))
    net_path = args.net or raw.get("network")
    if not net_path:
        raise SystemExit("no --net and the registry names no network")
    net_file = Path(net_path)
    if not net_file.is_absolute() and not net_file.exists():
        # a registry names its network relative to the repository root
        for base in reg_path.resolve().parents:
            if (base / net_path).exists():
                net_file = base / net_path
                break
        else:
            raise SystemExit(f"network {net_path} not found from {reg_path} or the cwd")
    network = RoadNetwork.from_sumo_net(net_file)
    cam, report = calibrate(pts, network)
    print(json.dumps(report, indent=1))
    if report["inliers"] < args.min_inliers:
        raise SystemExit(f"rejected: only {report['inliers']} points agree (need "
                         f"{args.min_inliers}) -- with so few, the error above proves nothing; "
                         "add points spread over the lanes the camera should measure")
    if report["rms_px"] > args.max_rms_px:
        raise SystemExit(f"rejected: RMS {report['rms_px']:.2f} px > {args.max_rms_px} px -- "
                         "check the outliers listed above and re-pick those points")
    cov = camera_coverage(cam, lanes_near(network, cam.position_xy, 250.0),
                          max_resolution_m_per_px=raw.get("max_resolution_m_per_px", 0.6))
    for lid, c in sorted(cov.items()):
        print(f"  {lid:24s} covered {c.covered_m:6.1f} m   from stop line "
              f"{c.covered_from_end_m:6.1f} m   from lane start {c.covered_from_start_m:6.1f} m")
    spec = CameraSpec(pts["camera_id"], cam, tls_id=pts.get("tls_id"),
                      approach_edge=pts.get("approach_edge"), fps=args.fps,
                      source=pts.get("source", "simcam"),
                      notes=f"calibrated from {report['inliers']} points, "
                            f"RMS {report['rms_px']:.2f} px / {report['ground_rms_m']:.2f} m")
    specs = [s for s in specs if s.camera_id != spec.camera_id] + [spec]
    save_registry(reg_path, specs, network=str(net_path),
                  max_resolution_m_per_px=raw.get("max_resolution_m_per_px", 0.6),
                  meta=raw.get("meta", {}))
    print(f"wrote {spec.camera_id} to {reg_path}")


if __name__ == "__main__":
    main()

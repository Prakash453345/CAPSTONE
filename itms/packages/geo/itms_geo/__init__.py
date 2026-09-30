"""Camera and road geometry for the ITMS vision pipeline (M8).

- `homography` -- normalised-DLT estimation, RANSAC, reprojection error
- `camera` -- `PinholeCamera` (from a pose) and `HomographyCamera` (from a
  calibration), both behind the `GroundCamera` interface
- `road` -- lanes, links and nearest-lane queries read from a SUMO net
- `coverage` -- which metres of which lane a camera can actually measure
"""

from itms_geo.camera import (
    GroundCamera,
    HomographyCamera,
    PinholeCamera,
    camera_from_dict,
    homography_camera_from_pinhole,
)
from itms_geo.coverage import LaneCoverage, camera_coverage, lane_coverage, merge_coverage
from itms_geo.homography import (
    apply_homography,
    estimate_homography,
    estimate_homography_ransac,
    reprojection_error,
)
from itms_geo.road import Lane, LaneLocator, RoadNetwork, heading_diff, heading_of

__all__ = [
    "GroundCamera",
    "HomographyCamera",
    "Lane",
    "LaneCoverage",
    "LaneLocator",
    "PinholeCamera",
    "RoadNetwork",
    "apply_homography",
    "camera_coverage",
    "camera_from_dict",
    "estimate_homography",
    "estimate_homography_ransac",
    "heading_diff",
    "heading_of",
    "homography_camera_from_pinhole",
    "lane_coverage",
    "merge_coverage",
    "reprojection_error",
]

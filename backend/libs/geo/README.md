# itms-geo

Camera and road geometry for the M8 vision pipeline. numpy only (`pyproj`
optional, for lon/lat).

| module | what |
|---|---|
| `homography` | normalised DLT, seeded RANSAC, reprojection error |
| `camera` | `PinholeCamera` (a pose: position, height, compass heading, pitch, roll, hfov) and `HomographyCamera` (a calibration), both behind `GroundCamera`: `ground_to_image`, `image_to_ground`, `ground_resolution` (m/px, closed-form Jacobian) |
| `road` | `RoadNetwork.from_sumo_net` -- lanes, edges, junctions, connections, the controller's `L{i}` link numbering (`link_lane_maps`, identical to `link_lanes.py`), phase link states, lon/lat; `LaneLocator` for nearest-lane queries with heading agreement |
| `coverage` | which metres of which lane a camera measures at a usable resolution (default <= 0.6 m/px), counted from the stop line |
| `lanecal` | calibration from the lane markings in one frame -- see below |

## Calibrating a real camera

Two routes, both ending in a `HomographyCamera`:

1. **Surveyed points** -- `python -m vision_service.calibrate points.json
   --registry cameras.json`: four or more image/lon-lat pairs, RANSAC, and a
   report of the error in pixels *and* in metres on the road.
2. **Lane markings** -- `itms_geo.lanecal.calibrate_from_lane_marks`: click
   two or more lane lines (with their lateral offsets), four dash starts
   along one of them, and the stop line. The lines fix the lateral scale,
   the dashes the stretch along the road, the stop line the shear; the dash
   period comes from the marking standard or a tape. No survey needed.

   It can also recover the dash period from the camera itself (square
   pixels, centred principal point). That is exact on clean marks and
   **ill-conditioned for a camera looking down the road** -- 32 % median
   scale error at 1 px of click noise when the camera is yawed 5 degrees
   off the road axis, 5 % at 35 degrees -- so use it as a cross-check only.
   The numbers and the reason are in the module docstring.

## Tests

`pytest packages/geo` -- 50 tests, including pinhole/homography round trips,
the Vijayawada link numbering against `extract_tier0_config`, and lane-mark
calibration recovering a known camera.

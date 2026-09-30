"""Where to put the cameras: one per signalised approach, at the stop line,
looking outward along the arm.

From that spot a camera sees the approach lanes queue-head first -- where
`queue_pcu` and `approaching_pcu` live -- and the departure lanes of the
same arm near-end first, which is where spillback into the junction starts.

For each approach edge the planner:

1. finds the stop line (mean of the approach lanes' downstream ends) and the
   travel direction there;
2. stands the pole `setback` metres past the stop line (into the junction),
   because a camera pitched to see 100 m up the road cannot see the ground
   directly under itself -- the near edge of its frame lands 10-20 m out;
3. aims at a point ~45 m up the approach centreline, so curved approaches
   are followed rather than looked past;
4. searches setback x pitch for the pose that maximises the metres of
   approach lane covered **contiguously from the stop line** at the rig's
   resolution limit (capped at 150 m per lane, beyond which extra reach buys
   the controller nothing it can use).

This is a starting layout for simulation and for a site survey, not a
substitute for one; a surveyed installation replaces each pose with a
point-correspondence calibration and nothing downstream changes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from itms_geo.camera import PinholeCamera
from itms_geo.coverage import DEFAULT_MAX_RESOLUTION_M_PER_PX, lane_coverage
from itms_geo.road import RoadNetwork, heading_of

from vision_service.cameras import CameraSpec

_OBJECTIVE_CAP_M = 150.0
_AIM_UPSTREAM_M = 45.0


@dataclass(frozen=True)
class PlacementResult:
    spec: CameraSpec
    setback_m: float
    covered_from_stopline_m: dict[str, float]  # approach lane -> metres

    @property
    def mean_covered_m(self) -> float:
        v = list(self.covered_from_stopline_m.values())
        return float(np.mean(v)) if v else 0.0


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(v[0], v[1]))
    return v / n if n > 1e-9 else np.array([0.0, 1.0])


def plan_approach_camera(
    network: RoadNetwork,
    tls_id: str,
    edge_id: str,
    *,
    mount_height_m: float = 10.0,
    hfov_deg: float = 50.0,
    width_px: int = 1920,
    height_px: int = 1080,
    fps: float = 5.0,
    setbacks_m: Sequence[float] = (8.0, 12.0, 16.0, 20.0, 25.0),
    pitches_deg: Iterable[float] = tuple(np.arange(6.0, 36.0, 1.0)),
    max_resolution_m_per_px: float = DEFAULT_MAX_RESOLUTION_M_PER_PX,
) -> PlacementResult:
    lanes = [network.lanes[lid] for lid in network.edges[edge_id]]
    ends = np.vstack([ln.point_at(ln.length)[0] for ln in lanes])
    stop = ends.mean(axis=0)
    dirs = np.vstack([ln.point_at(ln.length)[0] - ln.point_at(max(0.0, ln.length - 5.0))[0]
                      for ln in lanes])
    travel = _unit(dirs.mean(axis=0))
    mid = lanes[len(lanes) // 2]
    aim = mid.point_at(max(0.0, mid.length - _AIM_UPSTREAM_M))[0]
    pitches = list(pitches_deg)

    best: tuple[float, float, PinholeCamera, dict[str, float]] | None = None
    for setback in setbacks_m:
        pos = stop + setback * travel
        heading = float(heading_of((aim - pos)[None])[0])
        for pitch in pitches:
            cam = PinholeCamera(
                x=float(pos[0]),
                y=float(pos[1]),
                height_m=mount_height_m,
                heading_deg=round(heading, 2),
                pitch_deg=float(pitch),
                width_px=width_px,
                height_px=height_px,
                hfov_deg=hfov_deg,
                camera_id=f"cam_{tls_id}_{edge_id}",
            )
            got = {
                ln.lane_id: lane_coverage(
                    cam, ln, max_resolution_m_per_px=max_resolution_m_per_px
                ).covered_from_end_m
                for ln in lanes
            }
            score = sum(min(v, _OBJECTIVE_CAP_M) for v in got.values())
            # strictly better only: ties keep the smaller setback / lower pitch
            if best is None or score > best[0] + 1e-6:
                best = (score, setback, cam, got)
    assert best is not None
    _, setback, cam, got = best
    spec = CameraSpec(
        camera_id=cam.camera_id,
        camera=cam,
        tls_id=tls_id,
        approach_edge=edge_id,
        fps=fps,
        source="simcam",
        notes=(
            f"planned: stop-line mount, setback {setback:.0f} m, height {mount_height_m:.0f} m, "
            f"pitch {cam.pitch_deg:.0f} deg, hfov {hfov_deg:.0f} deg"
        ),
    )
    return PlacementResult(spec, setback, got)


def plan_network_cameras(
    network: RoadNetwork, tls_ids: Iterable[str] | None = None, **kwargs
) -> list[PlacementResult]:
    out = []
    for tls in tls_ids if tls_ids is not None else network.tls_ids():
        for edge in network.approach_edges(tls):
            out.append(plan_approach_camera(network, tls, edge, **kwargs))
    return out


def describe(results: Sequence[PlacementResult]) -> str:
    lines = []
    for r in results:
        cov = ", ".join(f"{k}:{v:.0f}m" for k, v in r.covered_from_stopline_m.items())
        cam = r.spec.camera
        lines.append(
            f"{r.spec.camera_id:70s} setback={r.setback_m:4.0f} "
            f"pitch={getattr(cam, 'pitch_deg', math.nan):4.0f}  {cov}"
        )
    return "\n".join(lines)

"""Camera registry and the rig built from it.

A registry is a JSON file listing cameras: an id, which junction and
approach it watches, its geometry (a `PinholeCamera` pose or a
`HomographyCamera` calibration), a frame rate and a source URI. It is the
one piece of per-site configuration the vision service needs; everything
else is derived.

`CameraRig` is the registry joined to the road network: for every camera,
which lanes it sees and how well (`itms_geo.coverage`), and a lane locator
restricted to those lanes; for every lane, the union of all cameras'
coverage. Building it is the only expensive geometric step, and it happens
once at start-up.

**Two roles.** An `"approach"` camera (the default) looks out along one arm
and feeds the queue estimate. A `"box"` camera overlooks the junction itself
(`placement.plan_box_camera`): from where an approach camera stands, the
junction interior is under its frame, so a vehicle waiting inside the box
is out of its view. A box camera's tracks are used only to tell whether a
lane is blocked at its head (`state/estimator.py`); it is left out of every
lane's coverage, so adding one changes no queue estimate and no confidence.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from itms_geo.camera import GroundCamera, camera_from_dict
from itms_geo.coverage import (
    DEFAULT_MAX_RESOLUTION_M_PER_PX,
    LaneCoverage,
    camera_coverage,
    merge_coverage,
)
from itms_geo.road import LaneLocator, RoadNetwork, lanes_near

# Lanes further than this from a camera's pole are not even considered for
# its coverage -- no fixed junction camera resolves a vehicle at 250 m.
_CANDIDATE_RADIUS_M = 250.0


@dataclass(frozen=True)
class CameraSpec:
    camera_id: str
    camera: GroundCamera
    tls_id: str | None = None
    approach_edge: str | None = None
    fps: float = 5.0
    source: str = "simcam"
    notes: str = ""
    role: str = "approach"  # or "box": see the module docstring

    def to_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "tls_id": self.tls_id,
            "approach_edge": self.approach_edge,
            "role": self.role,
            "fps": self.fps,
            "source": self.source,
            "notes": self.notes,
            "geometry": self.camera.to_dict(),  # type: ignore[attr-defined]
        }

    @classmethod
    def from_dict(cls, d: dict) -> CameraSpec:
        return cls(
            camera_id=d["camera_id"],
            camera=camera_from_dict(d["geometry"]),
            tls_id=d.get("tls_id"),
            approach_edge=d.get("approach_edge"),
            fps=float(d.get("fps", 5.0)),
            source=d.get("source", "simcam"),
            notes=d.get("notes", ""),
            role=d.get("role", "approach"),
        )


def save_registry(
    path: str | Path,
    specs: Sequence[CameraSpec],
    *,
    network: str = "",
    max_resolution_m_per_px: float = DEFAULT_MAX_RESOLUTION_M_PER_PX,
    meta: dict | None = None,
) -> None:
    payload = {
        "network": network,
        "max_resolution_m_per_px": max_resolution_m_per_px,
        "meta": meta or {},
        "cameras": [s.to_dict() for s in specs],
    }
    Path(path).write_text(json.dumps(payload, indent=1))


def load_registry(path: str | Path) -> tuple[list[CameraSpec], dict]:
    raw = json.loads(Path(path).read_text())
    return [CameraSpec.from_dict(c) for c in raw["cameras"]], raw


@dataclass
class CameraRig:
    network: RoadNetwork
    specs: dict[str, CameraSpec]
    max_resolution_m_per_px: float = DEFAULT_MAX_RESOLUTION_M_PER_PX
    coverage_by_camera: dict[str, dict[str, LaneCoverage]] = field(default_factory=dict)
    locators: dict[str, LaneLocator] = field(default_factory=dict)
    coverage_by_lane: dict[str, LaneCoverage] = field(default_factory=dict)
    cameras_by_lane: dict[str, list[str]] = field(default_factory=dict)
    # what each overview ("box") camera sees of the lanes around its junction:
    # kept apart from `coverage_by_camera`, which feeds the queue estimate
    box_coverage: dict[str, dict[str, LaneCoverage]] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        network: RoadNetwork,
        specs: Iterable[CameraSpec],
        *,
        max_resolution_m_per_px: float = DEFAULT_MAX_RESOLUTION_M_PER_PX,
    ) -> CameraRig:
        rig = cls(network, {s.camera_id: s for s in specs}, max_resolution_m_per_px)
        per_lane: dict[str, list[LaneCoverage]] = {}
        for cid, spec in rig.specs.items():
            cand = lanes_near(network, spec.camera.position_xy, _CANDIDATE_RADIUS_M)
            cov = camera_coverage(
                spec.camera, cand, max_resolution_m_per_px=max_resolution_m_per_px
            )
            if spec.role == "box":
                rig.box_coverage[cid] = cov
            else:
                rig.coverage_by_camera[cid] = cov
            # The locator gets every candidate lane that is *visible at all*,
            # not only the covered ones: a vehicle at 150 m on a lane seen
            # at 0.9 m/px should still be placed on the right lane (and then
            # discounted), rather than on the nearest well-resolved lane.
            visible = camera_coverage(spec.camera, cand, max_resolution_m_per_px=float("inf"))
            rig.locators[cid] = LaneLocator([network.lanes[lid] for lid in visible])
            if spec.role == "box":
                continue  # not part of any lane's coverage (module docstring)
            for lid, c in cov.items():
                per_lane.setdefault(lid, []).append(c)
                rig.cameras_by_lane.setdefault(lid, []).append(cid)
        rig.coverage_by_lane = {lid: merge_coverage(parts) for lid, parts in per_lane.items()}
        return rig

    def coverage(self, lane_id: str) -> LaneCoverage | None:
        return self.coverage_by_lane.get(lane_id)

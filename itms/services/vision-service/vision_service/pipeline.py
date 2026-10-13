"""The whole vision system, wired: one `CameraPipeline` per camera (the part
that would run on an edge device at the junction), and a `VisionSystem` that
fuses them into link state, incident scores and camera health (the central
part).

Two ways in:

- `CameraPipeline.ingest_detections(t, detections)` -- a real detector's
  output for one frame (YOLO, ONNX, or anything that produces `Detection`s);
- `VisionSystem.step_world(prev, snap)` -- the digital twin: films the world
  through every camera at the configured frame rate (interpolating between
  simulation steps), adds detector errors, and runs every camera's pipeline.

Either way, `VisionSystem.tick(t)` closes one controller tick: assign lanes,
update health, estimate link state, evaluate incident rules.

**A gap in the video resets tracking.** When frames stop for longer than
the tracker's buffer (a stream that dropped, a camera that was off) and then
resume, every vehicle is a new vehicle. The first version carried tracks
across the gap: ByteTrack counts its buffer in *frames*, so a lost box from
before a half-hour outage was still "recent" on the first frame after it,
and a car queued in the same spot inherited a stop that began half an hour
earlier -- a stalled-vehicle alarm on recovery, and a stop time the queue
estimator had no business using.

**Camera faults** can be injected for experiments -- `offline` (no frames),
`blind` (frames keep arriving but the detector finds nothing: a model that
does not work on this view, a lens smeared with something the pixel checks
pass), and `bump` (the camera is physically knocked by a few degrees; it
keeps filming but its stored calibration no longer matches, which is
exactly what the drift monitor has to catch).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
from itms_geo.camera import PinholeCamera, homography_camera_from_pinhole

from vision_service.cameras import CameraRig, CameraSpec
from vision_service.classes import ClassTable
from vision_service.ground import GroundConfig, GroundTracker
from vision_service.health import CameraHealth, CameraStatus
from vision_service.incidents.rules import IncidentEngine, RuleConfig, SignalStateProvider
from vision_service.records import Detection, GroundTrack, ImageTrack
from vision_service.simcam import PerceptionErrorModel, WorldSnapshot, film, interpolate
from vision_service.simcam.errors import ErrorPreset
from vision_service.state.estimator import EstimatorConfig, LinkEstimate, LinkStateEstimator
from vision_service.track import ByteTrackConfig, ByteTracker


@dataclass(frozen=True)
class CameraFault:
    kind: str            # "offline" | "blind" | "bump"
    t_start: float
    t_end: float = float("inf")
    d_heading_deg: float = 0.0
    d_pitch_deg: float = 0.0
    d_roll_deg: float = 0.0

    def active(self, t: float) -> bool:
        return self.t_start <= t < self.t_end


class CameraPipeline:
    def __init__(
        self,
        spec: CameraSpec,
        rig: CameraRig,
        *,
        classes: ClassTable,
        tracker_config: ByteTrackConfig | None = None,
        ground_config: GroundConfig | None = None,
        error_model: PerceptionErrorModel | None = None,
    ):
        self.spec = spec
        cam = spec.camera
        # The ground stage only ever uses the ground-plane mapping -- exactly
        # what a real point-correspondence calibration provides.
        self.calibrated = homography_camera_from_pinhole(cam) if isinstance(cam, PinholeCamera) \
            else cam
        self.tracker = ByteTracker(tracker_config or ByteTrackConfig(fps=spec.fps))
        self.ground = GroundTracker(spec.camera_id, self.calibrated, rig.locators.get(
            spec.camera_id), classes, ground_config)
        self.errors = error_model
        self.health = CameraHealth(spec.camera_id)
        self.last_ground: list[GroundTrack] = []
        self.last_detections: list[Detection] = []
        self.last_tracks: list[ImageTrack] = []
        self.faults: list[CameraFault] = []
        self._last_frame_t: float | None = None
        self.resets = 0
        # evaluation hook: observer(camera_id, t, filmed, detections, tracks)
        self.observer: Callable | None = None

    def _fault(self, t: float, kind: str) -> CameraFault | None:
        for f in self.faults:
            if f.kind == kind and f.active(t):
                return f
        return None

    def ingest_detections(self, t: float, detections: list[Detection],
                          frame: np.ndarray | None = None) -> list[GroundTrack]:
        self.health.saw_frame(t, frame)
        last, self._last_frame_t = self._last_frame_t, t
        if last is not None and t - last > self.tracker.cfg.track_buffer_s:
            self.tracker.reset()
            self.ground.reset()
            self.resets += 1
        self.last_detections = detections
        tracks = self.tracker.update(detections)
        self.last_tracks = tracks
        self.last_ground = self.ground.update(t, tracks)
        return self.last_ground

    def ingest_world(self, t: float, snap: WorldSnapshot) -> list[GroundTrack]:
        if self.errors is None:
            raise RuntimeError("SimCam needs an error model")
        if self._fault(t, "offline") is not None:
            return self.last_ground  # no frame arrives; health will notice
        cam = self.spec.camera
        if not isinstance(cam, PinholeCamera):
            raise TypeError("SimCam needs a PinholeCamera pose to film with")
        bump = self._fault(t, "bump")
        if bump is not None:
            cam = cam.perturbed(d_heading_deg=bump.d_heading_deg, d_pitch_deg=bump.d_pitch_deg,
                                d_roll_deg=bump.d_roll_deg)
        filmed = film(cam, snap)
        dets = self.errors.detect(cam, filmed)
        if self._fault(t, "blind") is not None:
            dets = []  # the frame arrives; nothing in it is recognised
        out = self.ingest_detections(t, dets)
        if self.observer is not None:
            self.observer(self.spec.camera_id, t, filmed, dets, self.last_tracks)
        return out

    def close_tick(self) -> list[GroundTrack]:
        self.ground.assign_lanes(self.last_ground)
        return self.last_ground


@dataclass
class TickResult:
    t: float
    links: dict[tuple[str, str], LinkEstimate]
    vision_scores: dict[tuple[str, str], float]
    camera_status: dict[str, tuple[CameraStatus, float, list[str]]]
    tracks: list[GroundTrack] = field(default_factory=list)


class VisionSystem:
    def __init__(
        self,
        rig: CameraRig,
        approach_links: Mapping[str, Mapping[str, str]],
        receiving_links: Mapping[str, Mapping[str, str]],
        *,
        classes: ClassTable | None = None,
        preset: str | ErrorPreset | None = None,
        seed: int = 0,
        fps: float = 5.0,
        estimator_config: EstimatorConfig | None = None,
        rule_config: RuleConfig | None = None,
        signal_state: SignalStateProvider | None = None,
        tracker_config: ByteTrackConfig | None = None,
        ground_config: GroundConfig | None = None,
        lane_chains: tuple[Mapping, Mapping] | None = None,
    ):
        self.rig = rig
        self.classes = classes or ClassTable.default()
        self.fps = fps
        self.pipelines: dict[str, CameraPipeline] = {}
        for cid, spec in rig.specs.items():
            em = None
            if preset is not None:
                em = PerceptionErrorModel(preset, seed=seed, camera_id=cid)
                # an overview camera gets its roadside clutter too: its false
                # detections are what the blocked-lane test has to live with
                cov = rig.coverage_by_camera.get(cid) or rig.box_coverage.get(cid, {})
                em.place_hotspots([rig.network.lanes[lid] for lid in cov], cov)
            tcfg = tracker_config or ByteTrackConfig(fps=fps)
            self.pipelines[cid] = CameraPipeline(
                spec, rig, classes=self.classes, tracker_config=tcfg,
                ground_config=ground_config, error_model=em,
            )
        self.estimator = LinkStateEstimator(rig, approach_links, receiving_links,
                                            estimator_config, lane_chains=lane_chains)
        self.incidents = IncidentEngine(rig, approach_links, receiving_links, rule_config,
                                        signal_state)
        self.last: TickResult | None = None

    def inject_fault(self, camera_id: str, fault: CameraFault) -> None:
        self.pipelines[camera_id].faults.append(fault)

    def step_world(self, prev: WorldSnapshot | None, snap: WorldSnapshot) -> None:
        """Film one simulation step's worth of frames through every camera."""
        if prev is None or snap.t <= prev.t:
            frames = [snap]
        else:
            n = max(1, int(round((snap.t - prev.t) * self.fps)))
            frames = [interpolate(prev, snap, prev.t + (k / n) * (snap.t - prev.t))
                      for k in range(1, n + 1)]
        for w in frames:
            for p in self.pipelines.values():
                p.ingest_world(w.t, w)

    def tick(self, t: float, *, keep_tracks: bool = False) -> TickResult:
        tracks: list[GroundTrack] = []
        box_tracks: list[GroundTrack] = []  # junction-overview cameras (cameras.py)
        status: dict[str, tuple[CameraStatus, float, list[str]]] = {}
        net = self.rig.network
        for cid, p in self.pipelines.items():
            gts = p.close_tick()
            p.health.forced_offline = p._fault(t, "offline") is not None

            def lane_heading(g: GroundTrack) -> float | None:
                if g.lane_id is None:
                    return None
                lane = net.lanes[g.lane_id]
                return float(lane.heading_at(g.s)[0])

            p.health.drift.observe(t, gts, p.calibrated.position_xy, lane_heading)
            p.health.activity.observe(t, gts)
            status[cid] = p.health.assess(t)
            if status[cid][0] is not CameraStatus.FAILED:
                (box_tracks if p.spec.role == "box" else tracks).extend(gts)
        health = {cid: s[1] for cid, s in status.items()}
        links = self.estimator.update(t, tracks, health, box_tracks=box_tracks)
        scores = self.incidents.update(t, tracks, self.estimator)
        self.last = TickResult(t, links, scores, status, tracks if keep_tracks else [])
        return self.last

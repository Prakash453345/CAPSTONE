"""The running vision service: sources in, events out.

Two modes, one core:

- **`simcam`** (the default under `make dev`): consumes sim-service's
  `traffic.vehicle-positions` stream -- the same one the dashboard draws --
  films it through every camera in the registry, and runs the full
  perception pipeline on the result. The whole M8 chain runs live with no
  camera hardware, and what it publishes can be compared with the truth
  sitting on the neighbouring topic.
- **`video`**: every camera in the registry whose `source` is a file path or
  an `rtsp://` URL is read by its own thread, run through a real detector
  (YOLO11 / ONNX), and fed to the same pipeline.

Either way, once per second `VisionService.tick` closes the tick and
publishes `LinkStateEstimated` per junction, `CameraStatus` on change,
and vision anomalies as `AnomalyUpdated(source=VISION)`. `SignalChanged`
events keep the incident rules phase-aware.

The core (`VisionService`) takes a `publish(topic, event_type, payload,
key)` callable instead of a bus, so it is tested without Redis.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
from itms_common.events import occurred_at_s
from itms_geo.road import RoadNetwork

from vision_service.cameras import CameraRig
from vision_service.classes import ClassTable, vclass_from_sumo
from vision_service.events import (
    ANOMALY_TOPIC,
    CAMERA_STATUS_TOPIC,
    LINK_STATE_TOPIC,
    anomaly_payload,
    camera_status_payload,
    fire_payload,
    link_state_payload,
)
from vision_service.fire.detector import FireScore
from vision_service.fire.monitor import FireMonitor, FireMonitorConfig
from vision_service.health import CameraStatus
from vision_service.incidents import (
    DEFAULT_OPERATING_POINT,
    OPERATING_POINTS,
    PhaseSignalState,
    RuleConfig,
)
from vision_service.pipeline import TickResult, VisionSystem
from vision_service.privacy import EvidenceBuffer, EvidenceStore
from vision_service.records import Detection
from vision_service.review import ReviewSink
from vision_service.simcam.world import WorldSnapshot, snapshot_from_records

log = logging.getLogger("vision.service")

Publish = Callable[[str, str, dict, str | None], None]

_STATUS_REPEAT_S = 30.0
_VEHICLE_STALE_S = 3.0
# A consumer group created at the start of a stream replays its whole
# history; positions older than this are yesterday's traffic, not now's.
_MESSAGE_MAX_AGE_S = 5.0


@dataclass
class _PositionBook:
    """Latest position per vehicle from the `VehiclePositionUpdated` stream;
    vehicles not heard from for a few seconds have left the network."""

    network: RoadNetwork
    classes: ClassTable
    records: dict[str, dict] = field(default_factory=dict)
    seen: dict[str, float] = field(default_factory=dict)

    def update(self, t: float, payload: Mapping) -> None:
        xy = self.network.lonlat_to_xy(np.array([[payload["lon"], payload["lat"]]]))[0]
        vid = payload["vehicle_id"]
        self.records[vid] = {
            "id": vid,
            "vclass": vclass_from_sumo(payload.get("vehicle_type", "")),
            "x": float(xy[0]),
            "y": float(xy[1]),
            "heading": float(payload.get("heading_deg", 0.0)),
            "speed": float(payload.get("speed_mps", 0.0)),
            "lane_id": payload.get("edge_id", ""),
        }
        self.seen[vid] = t

    def snapshot(self, t: float) -> WorldSnapshot:
        for vid in [v for v, s in self.seen.items() if t - s > _VEHICLE_STALE_S]:
            self.records.pop(vid, None)
            self.seen.pop(vid, None)
        return snapshot_from_records(t, list(self.records.values()), self.classes)


class VisionService:
    def __init__(
        self,
        rig: CameraRig,
        approach: Mapping[str, Mapping[str, str]],
        receiving: Mapping[str, Mapping[str, str]],
        publish: Publish,
        *,
        preset: str | None = None,
        fps: float = 5.0,
        seed: int = 0,
        model: str = "vision-m8",
        evidence: EvidenceStore | None = None,
        rules: str | RuleConfig = DEFAULT_OPERATING_POINT,
        lane_chains: tuple[Mapping, Mapping] | None = None,
        fire: FireMonitorConfig | None = None,
        review_sink: ReviewSink | None = None,
    ):
        self.review_sink = review_sink
        self.rig = rig
        self.publish = publish
        self.model = model
        self.signal = PhaseSignalState(
            {tls: rig.network.phase_link_states(tls) for tls in approach})
        rule_config = OPERATING_POINTS[rules] if isinstance(rules, str) else rules
        self.system = VisionSystem(rig, approach, receiving, preset=preset, seed=seed, fps=fps,
                                   signal_state=self.signal, rule_config=rule_config,
                                   lane_chains=lane_chains)
        self.book = _PositionBook(rig.network, ClassTable.default())
        self._prev_snap: WorldSnapshot | None = None
        self._last_status: dict[str, tuple[str, float]] = {}
        self.evidence = evidence
        self.buffers: dict[str, EvidenceBuffer] = {cid: EvidenceBuffer() for cid in rig.specs}
        self.published: dict[str, int] = {}
        self._lonlat: dict[str, tuple[float, float] | None] = {}
        self._anomaly_start_ms: dict[str, int] = {}
        # fire/smoke: off unless a config is given (it needs its own models)
        self.fire: dict[str, FireMonitor] = (
            {cid: FireMonitor(cid, fire) for cid in rig.specs} if fire is not None else {})

    # ---- inputs ---------------------------------------------------------------------

    def on_signal_changed(self, t: float, payload: Mapping) -> None:
        self.signal.on_phase(t, payload["intersection_id"], payload["phase_id"])

    def on_vehicle_position(self, t: float, payload: Mapping) -> None:
        self.book.update(t, payload)

    def on_envelope(self, t: float, env: Mapping, *, wall_now: float | None = None) -> None:
        """One decoded bus message (simcam mode). Vehicle positions older than
        `_MESSAGE_MAX_AGE_S` are a replayed backlog and are skipped; signal
        changes are replayed in order, so the last one is the current phase.
        `occurred_at` is a datetime after decoding (Avro timestamp-millis):
        the first version divided it by 1000 and the service died on its
        first message -- found by the live end-to-end run."""
        kind = env.get("event_type")
        if kind == "VehiclePositionUpdated":
            at = occurred_at_s(dict(env))
            now = time.time() if wall_now is None else wall_now
            if at is None or now - at <= _MESSAGE_MAX_AGE_S:
                self.on_vehicle_position(t, env["payload"])
        elif kind == "SignalChanged":
            self.on_signal_changed(t, env["payload"])

    def on_frame(self, camera_id: str, t: float, frame: np.ndarray,
                 detections: list[Detection]) -> None:
        """A real camera frame and its detector output."""
        pipe = self.system.pipelines[camera_id]
        pipe.ingest_detections(t, detections, frame)
        if self.evidence is not None or self.review_sink is not None:
            self.buffers[camera_id].push(t, frame, detections + tracked_boxes(pipe.last_tracks))

    def on_fire_score(self, camera_id: str, t: float, score: FireScore) -> None:
        """One camera's fire/smoke score for one frame (about once a second);
        persistence and publishing happen in `FireMonitor` and `tick`."""
        mon = self.fire.get(camera_id)
        if mon is not None:
            mon.observe(t, score)

    def step_simcam(self, t: float) -> None:
        snap = self.book.snapshot(t)
        self.system.step_world(self._prev_snap, snap)
        self._prev_snap = snap

    def tick(self, t: float, *, sim_time_s: float | None = None) -> TickResult:
        res = self.system.tick(t)
        for tls in sorted({tls for tls, _ in res.links}):
            self._emit(LINK_STATE_TOPIC, "LinkStateEstimated",
                       link_state_payload(tls, res.links, res.vision_scores,
                                          sim_time_s=sim_time_s, model=self.model), tls)
        for cid, status in res.camera_status.items():
            last = self._last_status.get(cid)
            changed = last is None or last[0] != status[0]
            stale = last is not None and status[0] is not CameraStatus.OK and \
                t - last[1] >= _STATUS_REPEAT_S
            if changed or stale:
                spec = self.rig.specs[cid]
                self._emit(CAMERA_STATUS_TOPIC, "CameraStatus", camera_status_payload(
                    cid, status, self.system.pipelines[cid].health,
                    intersection_id=spec.tls_id, lonlat=self._camera_lonlat(cid),
                    heading_deg=getattr(spec.camera, "heading_deg", None)), cid)
                self._last_status[cid] = (status[0], t)
        eng = self.system.incidents
        now_ms = time.time() * 1000.0
        for cand in [*eng.new_candidates, *eng.resolved]:
            n_lanes = len(self.rig.network.edges.get(cand.edge_id, ())) or 1
            # when the incident *began* (its first sustained sighting), in wall
            # time -- the same on the ACTIVE and the RESOLVED update. The first
            # version stamped each update with the moment it was sent, so a
            # resolution moved the incident's start to its end.
            start_ms = self._anomaly_start_ms.setdefault(
                cand.anomaly_id, int(now_ms - 1000.0 * max(0.0, t - cand.first_t)))
            self._emit(ANOMALY_TOPIC, "AnomalyUpdated",
                       anomaly_payload(cand, n_lanes_on_edge=n_lanes, start_time_ms=start_ms,
                                       sim_tick=None if sim_time_s is None else int(sim_time_s)),
                       cand.edge_id)
            if cand in eng.new_candidates:
                self._save_evidence(cand)
            else:
                self._anomaly_start_ms.pop(cand.anomaly_id, None)
        self._emit_fire(t)
        return res

    def _emit_fire(self, t: float) -> None:
        now_ms = time.time() * 1000.0
        for cid, mon in self.fire.items():
            new, resolved = mon.drain()
            for cand in [*new, *resolved]:
                start_ms = self._anomaly_start_ms.setdefault(
                    cand.candidate_id, int(now_ms - 1000.0 * max(0.0, t - cand.first_t)))
                edge = self.rig.specs[cid].approach_edge or ""
                self._emit(ANOMALY_TOPIC, "AnomalyUpdated",
                           fire_payload(cand, edge_id=edge, start_time_ms=start_ms), edge or cid)
                if cand.status == "RESOLVED":
                    self._anomaly_start_ms.pop(cand.candidate_id, None)
                else:
                    buf = self.buffers.get(cid)
                    if buf is not None and len(buf):
                        clip = buf.redacted_clip()
                        if self.evidence is not None:
                            uri = self.evidence.save(cand.candidate_id, cid, clip,
                                                     {"rule": "fire_smoke", "kind": cand.kind})
                            log.info("evidence for %s from %s -> %s", cand.candidate_id, cid, uri)
                        if self.review_sink is not None:
                            self.review_sink(cid, edge, cand.kind or "fire", clip)

    def _emit(self, topic: str, event_type: str, payload: dict, key: str | None) -> None:
        self.publish(topic, event_type, payload, key)
        self.published[event_type] = self.published.get(event_type, 0) + 1

    def _camera_lonlat(self, cid: str) -> tuple[float, float] | None:
        if cid not in self._lonlat:
            try:
                xy = self.rig.specs[cid].camera.position_xy
                ll = self.rig.network.xy_to_lonlat(np.asarray(xy)[None])[0]
                self._lonlat[cid] = (float(ll[0]), float(ll[1]))
            except Exception:  # noqa: BLE001 -- pyproj missing or no projection: omit
                self._lonlat[cid] = None
        return self._lonlat[cid]

    def _save_evidence(self, cand) -> None:
        cams = self.rig.cameras_by_lane.get(cand.lane_id, [])
        for cid in cams:
            buf = self.buffers.get(cid)
            if buf is None or not len(buf):
                continue
            clip = buf.redacted_clip()
            if self.evidence is not None:
                uri = self.evidence.save(cand.anomaly_id, cid, clip,
                                         {"rule": cand.rule, "lane": cand.lane_id})
                log.info("evidence for %s from %s -> %s", cand.anomaly_id, cid, uri)
            if self.review_sink is not None:
                self.review_sink(cid, cand.edge_id, cand.rule, clip)


def tracked_boxes(tracks) -> list[Detection]:
    """Redact what is tracked, not only what is detected this frame: a person
    the detector missed for a frame (or saw only below its confidence
    threshold) is still where the tracker says it is."""
    return [Detection(tuple(float(v) for v in t.box), 1.0, t.vclass)  # type: ignore[arg-type]
            for t in tracks]


def run_simcam_forever(service: VisionService, redis_url: str, *, preset_note: str = "") -> None:
    """Consume sim-service's streams, tick once a second, publish to Redis."""
    from itms_common.bus import RedisStreamsSyncConsumer  # noqa: PLC0415
    from itms_common.events import decode_envelope  # noqa: PLC0415

    consumer = RedisStreamsSyncConsumer(
        ["traffic.vehicle-positions", "signal.changed"], group="vision-service",
        consumer="vision-1", url=redis_url)
    t0 = time.monotonic()
    next_tick = 1.0
    log.info("vision-service simcam mode %s: %d cameras", preset_note, len(service.rig.specs))
    while True:
        now = time.monotonic() - t0
        for msg in consumer.drain(max_messages=5000):
            try:
                service.on_envelope(now, decode_envelope(msg.raw))
            except Exception:  # noqa: BLE001 -- a bad message must not stop the service
                log.exception("unusable message on %s", msg.topic)
            consumer.ack(msg.topic, msg.message_id)
        if now >= next_tick:
            service.step_simcam(now)
            service.tick(now)
            next_tick = math.floor(now) + 1.0
        time.sleep(0.05)

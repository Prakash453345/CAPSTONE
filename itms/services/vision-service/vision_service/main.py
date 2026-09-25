"""vision-service entrypoint.

Env vars:

  VISION_MODE        "simcam" (default) | "video"
                     simcam: film sim-service's live vehicle stream through
                             every camera in the registry (digital twin)
                     video:  read each camera's `source` (file or rtsp://)
                             and run a real detector
  VISION_REGISTRY    camera registry JSON (default: the Vijayawada
                     cameras.json written by scripts/m8_plan_cameras.py)
  VISION_NET         SUMO net the registry's lanes come from (default: the
                     Vijayawada corridor)
  VISION_PRESET      simcam detector-error preset (default finetuned_day;
                     ideal | finetuned_day | coco_pretrained | night_rain)
  VISION_FPS         processing rate per camera (default 5)
  VISION_RULES       incident-rule operating point: "quiet" (default; held-out
                     19 % of in-view incidents at ~1.7 false alarms/h for the
                     corridor), "assist" (19 % at ~10/h -- no better on
                     held-out seeds) or "hand_set" (37 % at ~37/h) --
                     see vision_service.incidents.rules.OPERATING_POINTS
  VISION_DETECTOR    video mode: a .pt (Ultralytics) or .onnx model
                     (default yolo11n.pt)
  VISION_EVIDENCE    directory for redacted evidence clips (video mode;
                     unset = keep no evidence at all)
  MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY
                     send evidence to MinIO instead of the local directory
  REDIS_URL
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s vision-service %(message)s")
log = logging.getLogger("vision.main")

_REPO = Path(__file__).resolve().parents[3]
_NET_DIR = _REPO / "scenarios" / "networks" / "vijayawada"


def _publisher(redis_url: str):
    from itms_common.bus import RedisStreamsSyncBus  # noqa: PLC0415
    from itms_common.events import encode_envelope  # noqa: PLC0415

    bus = RedisStreamsSyncBus(redis_url)

    def publish(topic: str, event_type: str, payload: dict, key: str | None) -> None:
        bus.publish(topic, encode_envelope(event_type, "vision-service", payload,
                                           partition_key=key))

    return publish


def build_service(mode: str):
    from itms_geo import RoadNetwork  # noqa: PLC0415

    from vision_service.cameras import CameraRig, load_registry  # noqa: PLC0415
    from vision_service.incidents import DEFAULT_OPERATING_POINT  # noqa: PLC0415
    from vision_service.privacy import EvidenceStore  # noqa: PLC0415
    from vision_service.service import VisionService  # noqa: PLC0415

    registry = Path(os.environ.get("VISION_REGISTRY", _NET_DIR / "cameras.json"))
    net_path = Path(os.environ.get("VISION_NET", _NET_DIR / "vijayawada_corridor.net.xml"))
    specs, raw = load_registry(registry)
    if mode == "video":
        specs = [s for s in specs if s.source != "simcam"]
        if not specs:
            raise SystemExit(f"no camera in {registry} has a video source (file path or rtsp://)")
    net = RoadNetwork.from_sumo_net(net_path)
    rig = CameraRig.build(net, specs, max_resolution_m_per_px=raw.get("max_resolution_m_per_px",
                                                                         0.6))
    approach, receiving = net.link_lane_maps()
    evidence = None
    if os.environ.get("VISION_EVIDENCE") or os.environ.get("MINIO_ENDPOINT"):
        evidence = EvidenceStore(
            root=Path(os.environ.get("VISION_EVIDENCE", "var/evidence")),
            minio_endpoint=os.environ.get("MINIO_ENDPOINT"),
            minio_access_key=os.environ.get("MINIO_ACCESS_KEY"),
            minio_secret_key=os.environ.get("MINIO_SECRET_KEY"),
        )
    preset = os.environ.get("VISION_PRESET", "finetuned_day") if mode == "simcam" else None
    fps = float(os.environ.get("VISION_FPS", "5"))
    publish = _publisher(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    model = f"vision-m8/simcam:{preset}" if mode == "simcam" else \
        f"vision-m8/{os.environ.get('VISION_DETECTOR', 'yolo11n.pt')}"
    return VisionService(rig, approach, receiving, publish, preset=preset, fps=fps, model=model,
                         evidence=evidence,
                         rules=os.environ.get("VISION_RULES", DEFAULT_OPERATING_POINT)), specs


class LatestFrames:
    """The newest frame of each camera, and nothing older. A detector that
    falls behind skips frames instead of working through a backlog (a
    controller wants the road as it is now); cameras are served oldest-first
    so a busy one cannot starve the others. Frames carry the time they were
    *captured*, which is what tracking needs -- not the time the detector
    got round to them."""

    def __init__(self) -> None:
        self._slots: dict[str, tuple[float, object]] = {}
        self._cv = threading.Condition()
        self.dropped = 0

    def put(self, camera_id: str, t: float, frame) -> None:
        with self._cv:
            self.dropped += camera_id in self._slots
            self._slots[camera_id] = (t, frame)
            self._cv.notify()

    def take(self, timeout: float) -> tuple[str, float, object] | None:
        with self._cv:
            if not self._slots:
                self._cv.wait(timeout)
            if not self._slots:
                return None
            cid = min(self._slots, key=lambda c: self._slots[c][0])
            t, frame = self._slots.pop(cid)
            return cid, t, frame


def _run_video(service, specs) -> None:
    from vision_service.detect.base import Detector  # noqa: PLC0415
    from vision_service.sources import VideoSource  # noqa: PLC0415

    weights = os.environ.get("VISION_DETECTOR", "yolo11n.pt")
    detector: Detector
    if weights.endswith(".onnx"):
        from vision_service.detect.yolo import OnnxDetector  # noqa: PLC0415

        detector = OnnxDetector(weights)
    else:
        from vision_service.detect.yolo import UltralyticsDetector  # noqa: PLC0415

        detector = UltralyticsDetector(weights)
    latest = LatestFrames()
    t0 = time.monotonic()

    def reader(spec) -> None:
        # files play at their own speed, so they look like the camera they came from
        src = VideoSource(spec.source, fps=spec.fps, realtime=True)
        for _t, frame in src.frames():
            latest.put(spec.camera_id, time.monotonic() - t0, frame)
        log.warning("camera %s: source ended", spec.camera_id)

    for spec in specs:
        threading.Thread(target=reader, args=(spec,), daemon=True).start()
    next_tick = 1.0
    next_log = 60.0
    log.info("video mode: %d cameras, detector %s", len(specs), detector.name)
    while True:
        got = latest.take(timeout=0.2)
        if got is not None:
            cid, t, frame = got
            service.on_frame(cid, t, frame, detector.detect(frame))
        now = time.monotonic() - t0
        if now >= next_tick:
            service.tick(now)
            next_tick = now + 1.0
        if now >= next_log:
            log.info("video mode: %d frames skipped so far (detector behind)", latest.dropped)
            next_log = now + 60.0


def main() -> None:
    mode = os.environ.get("VISION_MODE", "simcam")
    service, specs = build_service(mode)
    try:
        if mode == "video":
            _run_video(service, specs)
        else:
            from vision_service.service import run_simcam_forever  # noqa: PLC0415

            run_simcam_forever(service, os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                               preset_note=os.environ.get("VISION_PRESET", "finetuned_day"))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

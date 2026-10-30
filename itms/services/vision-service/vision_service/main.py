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
  VISION_PRESET      simcam detector-error preset (default itms6_640: the
                     error model fitted to the adopted fine-tuned detector at
                     640 px, baselines/2026-09-27_m8_finetune_v2/; others:
                     ideal | finetuned_day | coco_pretrained | night_rain |
                     uvh26_640 | uvh26_1280 | stock_640 | itms6_960)
  VISION_FPS         processing rate per camera (default 5)
  VISION_RULES       incident-rule operating point: "quiet" (default; held-out
                     19 % of in-view incidents at ~1.7 false alarms/h for the
                     corridor), "assist" (19 % at ~10/h -- no better on
                     held-out seeds) or "hand_set" (37 % at ~37/h) --
                     see vision_service.incidents.rules.OPERATING_POINTS
  VISION_DETECTOR    video mode: a .pt (Ultralytics) or .onnx model (default
                     data/models/itms_six_aug_640.onnx, fine-tune v3 (v2 plus
                     degradation augmentation): `make vision-model` puts it
                     there; itms_six_fp32_640.onnx is v2; yolo11n.pt is stock)
  VISION_FIRE_DETECTOR / VISION_FIRE_CLASSIFIER
                     video mode, both or neither: the v4 fire/smoke detector
                     (.pt) and the Step 2 crop classifier (.onnx, made by
                     scripts/m8_fire_export_cls.py). Each camera is scored
                     about once a second; a run of alarming frames becomes an
                     AnomalyUpdated candidate (type "fire") for an operator.
                     Unset = the models in data/models (itms_fire_640.pt and
                     itms_fire_cls_112.onnx) when both are there, else no fire
                     detection. VISION_FIRE=0 turns it off.
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
# the adopted detector (baselines/2026-09-27_m8_finetune_v2/) and the simcam
# error model fitted to it; data/ is not in git, `make vision-model` fills it
DEFAULT_PRESET = "itms6_640"
DEFAULT_DETECTOR = _REPO / "data" / "models" / "itms_six_aug_640.onnx"
# the v4 fire/smoke detector and the Step 2 crop classifier (baselines/2026-10-03_m8_fire_v5_step2/)
DEFAULT_FIRE_DETECTOR = _REPO / "data" / "models" / "itms_fire_640.pt"
DEFAULT_FIRE_CLASSIFIER = _REPO / "data" / "models" / "itms_fire_cls_112.onnx"


def detector_path() -> str:
    """VISION_DETECTOR, else the adopted fine-tune -- which must be there: a
    silent fallback to a weaker model would look like it works."""
    weights = os.environ.get("VISION_DETECTOR")
    if weights:
        return weights
    if not DEFAULT_DETECTOR.exists():
        raise SystemExit(
            f"no detector at {DEFAULT_DETECTOR}. Run `make vision-model` (it copies the adopted "
            "fine-tune from data/uvh26/finetune_v3/, where the fine-tune notebook's results "
            "go), or set VISION_DETECTOR to a .onnx/.pt model (yolo11n.pt is the stock COCO one).")
    return str(DEFAULT_DETECTOR)


def fire_paths() -> tuple[str, str] | None:
    """(detector, classifier): the two env vars when set, else the models in
    data/models when both are there, else None (also None for VISION_FIRE=0).
    Setting only one of the two env vars is a mistake, not a default."""
    if os.environ.get("VISION_FIRE") == "0":
        return None
    det, cls = os.environ.get("VISION_FIRE_DETECTOR"), os.environ.get("VISION_FIRE_CLASSIFIER")
    if not det and not cls:
        if DEFAULT_FIRE_DETECTOR.exists() and DEFAULT_FIRE_CLASSIFIER.exists():
            return str(DEFAULT_FIRE_DETECTOR), str(DEFAULT_FIRE_CLASSIFIER)
        return None
    if not (det and cls):
        raise SystemExit("set both VISION_FIRE_DETECTOR and VISION_FIRE_CLASSIFIER, or neither")
    for path in (det, cls):
        if not Path(path).exists():
            raise SystemExit(f"fire model not found: {path}")
    return det, cls


def _publisher(redis_url: str):
    from itms_common.bus import RedisStreamsSyncBus  # noqa: PLC0415
    from itms_common.events import encode_envelope  # noqa: PLC0415

    bus = RedisStreamsSyncBus(redis_url)

    def publish(topic: str, event_type: str, payload: dict, key: str | None) -> None:
        bus.publish(topic, encode_envelope(event_type, "vision-service", payload,
                                           partition_key=key))

    return publish


def build_service(mode: str):
    from itms_domain.scenario import current  # noqa: PLC0415
    from itms_geo import RoadNetwork  # noqa: PLC0415

    from vision_service.cameras import CameraRig, load_registry  # noqa: PLC0415
    from vision_service.incidents import DEFAULT_OPERATING_POINT  # noqa: PLC0415
    from vision_service.privacy import EvidenceStore  # noqa: PLC0415
    from vision_service.service import VisionService  # noqa: PLC0415

    scenario = current()   # ITMS_SCENARIO, else the Vijayawada corridor
    registry = Path(os.environ.get("VISION_REGISTRY", scenario.cameras))
    net_path = Path(os.environ.get("VISION_NET", scenario.net))
    specs, raw = load_registry(registry)
    if mode == "video":
        specs = [s for s in specs if s.source != "simcam"]
        if not specs:
            raise SystemExit(f"no camera in {registry} has a video source (file path or rtsp://)")
    net = RoadNetwork.from_sumo_net(net_path)
    rig = CameraRig.build(net, specs, max_resolution_m_per_px=raw.get("max_resolution_m_per_px",
                                                                         0.6))
    approach, receiving = net.link_lane_maps()
    from itms_domain.lane_chains import from_sumo_net as chains_from_net  # noqa: PLC0415

    chains = chains_from_net(net_path)
    evidence = None
    if os.environ.get("VISION_EVIDENCE") or os.environ.get("MINIO_ENDPOINT"):
        evidence = EvidenceStore(
            root=Path(os.environ.get("VISION_EVIDENCE", "var/evidence")),
            minio_endpoint=os.environ.get("MINIO_ENDPOINT"),
            minio_access_key=os.environ.get("MINIO_ACCESS_KEY"),
            minio_secret_key=os.environ.get("MINIO_SECRET_KEY"),
        )
    preset = os.environ.get("VISION_PRESET", DEFAULT_PRESET) if mode == "simcam" else None
    fps = float(os.environ.get("VISION_FPS", "5"))
    publish = _publisher(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    fire = None
    if mode == "video" and fire_paths() is not None:
        from vision_service.fire import FireMonitorConfig  # noqa: PLC0415

        fire = FireMonitorConfig()
    model = f"vision-m8/simcam:{preset}" if mode == "simcam" else \
        f"vision-m8/{Path(detector_path()).name}"
    review_url = os.environ.get("VISION_REVIEW_URL", "")
    review_sink = None
    if review_url:
        from vision_service.review import make_review_sink  # noqa: PLC0415

        key = os.environ.get("API_KEY", "")
        if not key:
            raise SystemExit("VISION_REVIEW_URL is set but API_KEY is not: set the same API_KEY "
                             "api-service runs with, so camera flags can reach the review inbox")
        review_sink = make_review_sink(review_url, key)
        log.info("camera flags go to the review inbox at %s", review_url)
    return VisionService(rig, approach, receiving, publish, preset=preset, fps=fps, model=model,
                         evidence=evidence, review_sink=review_sink,
                         rules=os.environ.get("VISION_RULES", DEFAULT_OPERATING_POINT),
                         lane_chains=chains if (chains[0] or chains[1]) else None,
                         fire=fire), specs


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

    weights = detector_path()
    detector: Detector
    if weights.endswith(".onnx"):
        from vision_service.detect.yolo import OnnxDetector  # noqa: PLC0415

        detector = OnnxDetector(weights)
    else:
        from vision_service.detect.yolo import UltralyticsDetector  # noqa: PLC0415

        detector = UltralyticsDetector(weights)
    fire_scorer = None
    fire_cfg = fire_paths()
    if fire_cfg is not None:
        try:
            from vision_service.fire.detector import FireScorer  # noqa: PLC0415

            fire_scorer = FireScorer(*fire_cfg)
        except ImportError as e:
            raise SystemExit(f"fire detection is on but its packages are missing ({e}): "
                             "pip install -e 'services/vision-service[fire]', or set VISION_FIRE=0") from e  # noqa: E501
        log.info("fire detection on: %s", fire_scorer.name)
    last_fire: dict[str, float] = {}
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
            if fire_scorer is not None and t - last_fire.get(cid, -1e9) >= 1.0:
                last_fire[cid] = t       # about once a second per camera, not at the frame rate
                service.on_fire_score(cid, t, fire_scorer.score(frame))
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
                               preset_note=os.environ.get("VISION_PRESET", DEFAULT_PRESET))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

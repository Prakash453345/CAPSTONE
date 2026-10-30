"""The clip worker: `vision.clip-submitted` in, `vision.clip-analysed` out.

One clip at a time, in the order they were uploaded. For each clip:

1. publish ANALYSING with progress while `analyse.analyse_clip` runs (the
   video is read as fast as the detectors allow, not in real time);
2. save a JPEG of the main finding's moment, with people and number plates
   pixelated (`privacy.redact`, as for live evidence clips) and the flagged
   region outlined;
3. write `result.json` into the clip's directory (so a restart does not
   analyse it again) and publish DONE -- or FAILED with the error.

Which detectors run is decided once at start-up from the models on disk
(`build_detectors`); each one that is missing is logged and left out, and
every result names the ones that ran.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from vision_service.clips.analyse import READ_FPS, ClipAnalysis, ClipDetectors, analyse_clip

log = logging.getLogger("vision.clips.worker")

SUBMITTED_TOPIC = "vision.clip-submitted"
ANALYSED_TOPIC = "vision.clip-analysed"
CONSUMER_GROUP = "vision-clips"
RESULT_FILE = "result.json"
SNAPSHOT_FILE = "snapshot.jpg"
PROGRESS_EVERY_S = 1.0

_REPO = Path(__file__).resolve().parents[4]
DEFAULT_ACCIDENT_MODEL = _REPO / "data" / "models" / "itms_accident_224.onnx"
# The model the app keeps (`PROCEDURE_VIDEO_V9_ALL_DATA_LOCKED.md`): VideoMAE V4.
DEFAULT_ACCIDENT_VIDEO_MODEL = _REPO / "data" / "models" / "itms_accident_v4.pt"


# ---------------------------------------------------------------- detectors
def build_detectors() -> ClipDetectors:
    """Every detector whose model and packages are present. Env overrides:
    VISION_DETECTOR (vehicles), VISION_FIRE_DETECTOR + VISION_FIRE_CLASSIFIER
    (fire; VISION_FIRE=0 turns it off), VISION_ACCIDENT_MODEL (accident)."""
    from vision_service.main import DEFAULT_DETECTOR, fire_paths  # noqa: PLC0415

    dets = ClipDetectors()
    vehicles = os.environ.get("VISION_DETECTOR") or str(DEFAULT_DETECTOR)
    # an explicit VISION_DETECTOR may be a stock name Ultralytics downloads itself (yolo11n.pt)
    if Path(vehicles).exists() or os.environ.get("VISION_DETECTOR"):
        try:
            if vehicles.endswith(".onnx"):
                from vision_service.detect.yolo import OnnxDetector  # noqa: PLC0415

                dets.vehicles = OnnxDetector(vehicles)
            else:
                from vision_service.detect.yolo import UltralyticsDetector  # noqa: PLC0415

                dets.vehicles = UltralyticsDetector(vehicles)
            log.info("vehicles: %s", vehicles)
        except ImportError as e:
            log.warning("vehicles: off -- %s is there but its package is missing (%s)", vehicles, e)
    else:
        log.warning("vehicles: off -- no model at %s (no stalled-vehicle or congestion "
                    "findings, and severity comes from the type alone)", vehicles)

    fire = fire_paths()
    if fire is not None:
        try:
            from vision_service.fire.detector import FireScorer  # noqa: PLC0415

            dets.fire = FireScorer(*fire)
            log.info("fire: %s", dets.fire.name)
        except ImportError as e:
            log.warning("fire: off -- models present but packages missing (%s); "
                        "pip install -e 'services/vision-service[fire]'", e)
    else:
        log.warning("fire: off -- no fire models in data/models (or VISION_FIRE=0)")

    explicit = os.environ.get("VISION_ACCIDENT_MODEL")
    accident = Path(explicit) if explicit else (
        DEFAULT_ACCIDENT_MODEL if DEFAULT_ACCIDENT_MODEL.exists() else DEFAULT_ACCIDENT_VIDEO_MODEL)
    if accident.exists():
        try:
            if accident.suffix == ".pt":
                from vision_service.clips.accident_videomae import VideoMaeAccident  # noqa: PLC0415

                dets.accident = VideoMaeAccident(accident)
            else:
                from vision_service.clips.accident import AccidentModel  # noqa: PLC0415

                dets.accident = AccidentModel(accident)
            log.info("accident: %s (thr %.2f, %d of %d%s)", accident, dets.accident.rule.thr,
                     dets.accident.rule.k, dets.accident.rule.n,
                     "" if dets.accident.rule.validated else ", NOT validated")
        except ImportError as e:
            log.warning("accident: off -- %s is there but a package is missing (%s) -- onnxruntime, or torch and transformers for .pt", accident, e)  # noqa: E501
    else:
        log.warning("accident: off -- no model at %s (train it with "
                    "notebooks/m8_accident_step1_train.ipynb)", accident)
    return dets


# ---------------------------------------------------------------- video io
def video_info(path: str) -> tuple[float, float]:
    """(native fps, duration in seconds)."""
    import cv2  # noqa: PLC0415

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise OSError(f"cannot open video {Path(path).name}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
    n = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    cap.release()
    return fps, n / fps if n > 0 else 0.0


def read_frames(path: str, fps: float = READ_FPS) -> Iterator[tuple[float, np.ndarray]]:
    """Frames at about `fps`, timed by their position in the video. Frames in
    between are skipped with `grab()`, which does not decode them."""
    import cv2  # noqa: PLC0415

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise OSError(f"cannot open video {Path(path).name}")
    native = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
    index, next_t = 0, 0.0
    try:
        while cap.grab():
            t = index / native
            index += 1
            if t + 1e-6 < next_t:
                continue
            ok, frame = cap.retrieve()
            if ok:
                yield t, frame
                next_t = t + 1.0 / fps
    finally:
        cap.release()


def save_snapshot(path: str, at_s: float, box_norm, out: Path, vehicles=None) -> Path | None:
    """The frame at `at_s`, people and plates pixelated, the flagged region
    outlined. None if the frame cannot be read."""
    import cv2  # noqa: PLC0415

    from vision_service.privacy import redact  # noqa: PLC0415

    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, at_s) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    if vehicles is not None:
        frame = redact(frame, vehicles.detect(frame))
    if box_norm:
        h, w = frame.shape[:2]  # type: ignore[union-attr]
        x1, y1, x2, y2 = box_norm
        cv2.rectangle(frame, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)),
                      (0, 0, 255), max(2, w // 300))
    cv2.imwrite(str(out), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out


# ---------------------------------------------------------------- events
def analysed_payload(
    clip_id: str,
    status: str,
    *,
    progress: float = 0.0,
    analysis: ClipAnalysis | None = None,
    snapshot: Path | None = None,
    error: str = "",
    now_ms: int | None = None,
) -> dict:
    main = analysis.main if analysis is not None else None
    return {
        "clip_id": clip_id,
        "status": status,
        "progress": float(progress),
        "anomaly_type": main.anomaly_type if main else None,
        "severity": main.severity if main else None,
        "confidence": float(main.confidence) if main else None,
        "flagged_at_s": float(main.start_s) if main else None,
        "reasons": list(main.reasons) if main else [],
        "findings_json": json.dumps([f.to_json() for f in analysis.findings]) if analysis else "[]",
        "timeline_json": json.dumps(analysis.timeline) if analysis else "{}",
        "detectors": list(analysis.detectors) if analysis else [],
        "snapshot_path": str(snapshot) if snapshot else None,
        "duration_s": float(analysis.duration_s) if analysis else None,
        "error": error,
        "analysed_at": now_ms if now_ms is not None else int(time.time() * 1000),
    }


class ClipWorker:
    def __init__(self, detectors: ClipDetectors, publish) -> None:
        """`publish(payload)` sends one ClipAnalysed payload."""
        self.detectors = detectors
        self.publish = publish

    def handle(self, submitted: dict) -> dict:
        """Analyse one ClipSubmitted payload; returns the final payload."""
        clip_id = submitted["clip_id"]
        video = submitted["video_path"]
        clip_dir = Path(video).parent
        result_path = clip_dir / RESULT_FILE
        if result_path.exists():
            log.info("clip %s already analysed -- republishing its result", clip_id)
            final = json.loads(result_path.read_text())
            self.publish(final)
            return final
        self.publish(analysed_payload(clip_id, "ANALYSING"))
        last = [time.monotonic()]

        def progress(p: float) -> None:
            if time.monotonic() - last[0] >= PROGRESS_EVERY_S:
                last[0] = time.monotonic()
                self.publish(analysed_payload(clip_id, "ANALYSING", progress=p))

        try:
            _fps, duration = video_info(video)
            started = time.monotonic()
            analysis = analyse_clip(read_frames(video), self.detectors,
                                    duration_s=duration or None, on_progress=progress)
            snapshot = None
            main = analysis.main
            if main is not None:
                snapshot = save_snapshot(video, main.start_s, main.box_norm,
                                         clip_dir / SNAPSHOT_FILE, self.detectors.vehicles)
            final = analysed_payload(clip_id, "DONE", progress=1.0, analysis=analysis,
                                     snapshot=snapshot)
            log.info("clip %s: %s in %.0f s of video (%.0f s to analyse)", clip_id,
                     f"{main.anomaly_type}/{main.severity} at {main.start_s:.1f} s" if main
                     else "nothing found", analysis.duration_s, time.monotonic() - started)
        except Exception as e:  # a bad file must not stop the worker
            log.exception("clip %s failed", clip_id)
            final = analysed_payload(clip_id, "FAILED", error=f"{type(e).__name__}: {e}")
        result_path.write_text(json.dumps(final))
        self.publish(final)
        return final


def run_forever(redis_url: str) -> None:
    from itms_common import RedisStreamsSyncBus  # noqa: PLC0415
    from itms_common.bus import RedisStreamsSyncConsumer  # noqa: PLC0415
    from itms_common.events import decode_envelope, encode_envelope  # noqa: PLC0415

    detectors = build_detectors()
    if not detectors.names():
        raise SystemExit("no detector is installed -- put the models in data/models "
                         "(see vision_service/clips/worker.py) and install the vision extras")
    bus = RedisStreamsSyncBus(redis_url)
    consumer = RedisStreamsSyncConsumer([SUBMITTED_TOPIC], group=CONSUMER_GROUP,
                                        consumer="clips-1", url=redis_url)

    def publish(payload: dict) -> None:
        payload = dict(payload)
        if isinstance(payload.get("analysed_at"), int):
            payload["analysed_at"] = dt.datetime.fromtimestamp(
                payload["analysed_at"] / 1000, tz=dt.UTC)
        bus.publish(ANALYSED_TOPIC, encode_envelope(
            event_type="ClipAnalysed", source="vision-service", payload=payload,
            partition_key=payload["clip_id"]))

    worker = ClipWorker(detectors, publish)
    log.info("clip worker ready (%s), waiting on %s", ", ".join(detectors.names()), SUBMITTED_TOPIC)
    while True:
        messages = consumer.drain(max_messages=10)
        for msg in messages:
            try:
                worker.handle(decode_envelope(msg.raw)["payload"])
            finally:
                consumer.ack(msg.topic, msg.message_id)
        if not messages:
            time.sleep(0.5)

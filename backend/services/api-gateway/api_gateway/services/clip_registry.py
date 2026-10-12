"""Uploaded road videos: storage, the analysis read model, and the operator's
review -- the api-gateway's half of clip-based incident detection. The HTTP
side is api/routes/clips.py; this module holds the state and rules.

Flow:

1. `POST /v1/clips` stores the upload as `<CLIPS_DIR>/<clip_id>/source<ext>`
   with a `meta.json`, and publishes `ClipSubmitted` on
   `vision.clip-submitted`.
2. vision-service's clip worker (`python -m vision_service.clips`) analyses
   it and publishes `ClipAnalysed` on `vision.clip-analysed`; this registry
   folds those in (`apply_analysed`). A DONE result with a finding becomes a
   review item: PENDING.
3. An operator confirms or rejects it (`X-API-Key`, like incidents -- ADR-006's
   human gate). Confirm publishes an `AnomalyCreateRequested` on
   `commands.operator`, exactly what the map's Create Anomaly panel sends, so
   the live simulation applies it and the existing response chain (dispatch,
   green corridor, hospital) takes over. The reviewer may correct the type
   and severity before confirming.

The registry is rebuilt from disk at start-up (`meta.json` per clip, plus the
worker's `result.json`), so clips survive an api-service restart.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from dataclasses import asdict
from pathlib import Path

from api_gateway.models.clips import Clip

log = logging.getLogger("api-service.clips")

SUBMITTED_TOPIC = "vision.clip-submitted"
ANALYSED_TOPIC = "vision.clip-analysed"
ALLOWED_EXTENSIONS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"})
META_FILE = "meta.json"
RESULT_FILE = "result.json"   # written by vision-service's worker

# itms_domain.anomaly.AnomalyType value -> AnomalyCreateRequested's OperatorAnomalyType
OPERATOR_TYPE: dict[str, str] = {
    "accident": "ACCIDENT",
    "vehicle_breakdown": "VEHICLE_BREAKDOWN",
    "stalled_vehicle": "VEHICLE_BREAKDOWN",
    "lane_blockage": "LANE_BLOCKAGE",
    "road_obstruction": "ROAD_OBSTRUCTION",
    "heavy_congestion": "HEAVY_CONGESTION",
    "fire": "FIRE",
}
SEVERITIES = ("low", "medium", "high", "blocked")


class ClipStateError(Exception):
    """The clip is not in a state that allows the requested review action."""


def _json_ready(value):
    """Decoded Avro timestamps arrive as datetimes; store milliseconds."""
    if isinstance(value, dt.datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    return value


class ClipRegistry:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._clips: dict[str, Clip] = {}
        self._load()

    # ---- storage ---------------------------------------------------

    def _load(self) -> None:
        if not self.root.exists():
            return
        for meta in self.root.glob(f"*/{META_FILE}"):
            try:
                clip = Clip(**json.loads(meta.read_text()))
            except (TypeError, ValueError):
                log.warning("skipping unreadable clip record %s", meta)
                continue
            result = meta.parent / RESULT_FILE
            if clip.result is None and result.exists():
                self.apply_analysed(json.loads(result.read_text()), persist=False, clip=clip)
            self._clips[clip.clip_id] = clip
        if self._clips:
            log.info("loaded %d clips from %s", len(self._clips), self.root)

    def _save(self, clip: Clip) -> None:
        d = self.root / clip.clip_id
        d.mkdir(parents=True, exist_ok=True)
        (d / META_FILE).write_text(json.dumps(asdict(clip)))

    def new_clip_dir(self) -> tuple[str, Path]:
        clip_id = str(uuid.uuid4())
        d = self.root / clip_id
        d.mkdir(parents=True, exist_ok=False)
        return clip_id, d

    # ---- read model --------------------------------------------------

    def get(self, clip_id: str) -> Clip | None:
        return self._clips.get(clip_id)

    def all(self) -> list[Clip]:
        return sorted(self._clips.values(), key=lambda c: c.submitted_ms, reverse=True)

    def add(self, clip: Clip) -> Clip:
        self._clips[clip.clip_id] = clip
        self._save(clip)
        return clip

    def apply_analysed(self, payload: dict, *, persist: bool = True,
                       clip: Clip | None = None) -> Clip | None:
        clip = clip or self._clips.get(str(payload.get("clip_id")))
        if clip is None:
            log.warning("ClipAnalysed for unknown clip %s", payload.get("clip_id"))
            return None
        if clip.status in ("DONE", "FAILED") and payload.get("status") == "ANALYSING":
            return clip                   # a late progress event after the result
        clip.status = str(payload["status"])
        clip.progress = float(payload.get("progress") or 0.0)
        if clip.status in ("DONE", "FAILED"):
            clip.result = _json_ready(dict(payload))
            if clip.review is None:
                clip.review = "PENDING" if clip.result.get("anomaly_type") else None
            if persist:
                self._save(clip)
        return clip

    # ---- review ------------------------------------------------------

    def _reviewable(self, clip_id: str) -> Clip:
        clip = self._clips.get(clip_id)
        if clip is None:
            raise KeyError(clip_id)
        if clip.review in ("CONFIRMED", "REJECTED"):
            raise ClipStateError(f"this clip was already {clip.review.lower()}")
        if clip.review != "PENDING":
            raise ClipStateError(
                "nothing to review: the analysis has not finished or found nothing")
        return clip

    def confirm(self, clip_id: str, *, actor: str, at_ms: int, anomaly_type: str | None = None,
                severity: str | None = None, note: str = "") -> Clip:
        clip = self._reviewable(clip_id)
        assert clip.result is not None
        atype = (anomaly_type or clip.result["anomaly_type"]).lower()
        sev = (severity or clip.result["severity"]).lower()
        if atype not in OPERATOR_TYPE:
            raise ValueError(f"unknown anomaly type {atype!r}")
        if sev not in SEVERITIES:
            raise ValueError(f"unknown severity {sev!r}")
        clip.review, clip.reviewed_by, clip.reviewed_ms, clip.review_note = (
            "CONFIRMED", actor, at_ms, note)
        clip.anomaly_id = str(uuid.uuid4())
        clip.confirmed_type, clip.confirmed_severity = atype, sev
        self._save(clip)
        return clip

    def reject(self, clip_id: str, *, actor: str, at_ms: int, note: str = "") -> Clip:
        clip = self._reviewable(clip_id)
        clip.review, clip.reviewed_by, clip.reviewed_ms, clip.review_note = (
            "REJECTED", actor, at_ms, note)
        self._save(clip)
        return clip


def submitted_payload(clip: Clip) -> dict:
    return {
        "clip_id": clip.clip_id,
        "video_path": clip.video_path,
        "filename": clip.filename,
        "edge_id": clip.edge_id,
        "road_name": clip.road_name,
        "latitude": clip.latitude,
        "longitude": clip.longitude,
        "operator": clip.operator,
        "submitted_at": dt.datetime.fromtimestamp(clip.submitted_ms / 1000, tz=dt.UTC),
    }


def anomaly_request_payload(clip: Clip) -> dict:
    """The `AnomalyCreateRequested` a confirmation publishes -- the same
    command the Create Anomaly panel sends, carrying the clip in `detail`."""
    assert clip.anomaly_id and clip.confirmed_type and clip.confirmed_severity
    reason = (clip.result or {}).get("reasons") or []
    detail = f"confirmed from video clip {clip.filename}"
    if reason:
        detail += f": {reason[0]}"
    return {
        "anomaly_id": clip.anomaly_id,
        "edge_id": clip.edge_id,
        "lane_id": None,
        "anomaly_type": OPERATOR_TYPE[clip.confirmed_type],
        "severity": clip.confirmed_severity.upper(),
        "duration_s": None,
        "position_m": None,
        "operator": clip.reviewed_by or clip.operator,
        "detail": detail,
        "requested_at": dt.datetime.fromtimestamp((clip.reviewed_ms or 0) / 1000, tz=dt.UTC),
    }


def clip_to_json(clip: Clip) -> dict:
    """What the console gets: no server paths, links to the video and
    snapshot instead, and the analysis' JSON fields parsed."""
    result = clip.result or {}
    findings = json.loads(result.get("findings_json") or "[]")
    timeline = json.loads(result.get("timeline_json") or "{}")
    base = f"/v1/clips/{clip.clip_id}"
    return {
        "clip_id": clip.clip_id,
        "filename": clip.filename,
        "edge_id": clip.edge_id,
        "road_name": clip.road_name,
        "latitude": clip.latitude,
        "longitude": clip.longitude,
        "operator": clip.operator,
        "submitted_ms": clip.submitted_ms,
        "status": clip.status,
        "progress": clip.progress,
        "video_url": f"{base}/video",
        "snapshot_url": f"{base}/snapshot" if result.get("snapshot_path") else None,
        "anomaly_type": result.get("anomaly_type"),
        "severity": result.get("severity"),
        "confidence": result.get("confidence"),
        "flagged_at_s": result.get("flagged_at_s"),
        "reasons": result.get("reasons") or [],
        "findings": findings,
        "timeline": timeline,
        "detectors": result.get("detectors") or [],
        "duration_s": result.get("duration_s"),
        "error": result.get("error") or "",
        "review": clip.review,
        "reviewed_by": clip.reviewed_by,
        "reviewed_ms": clip.reviewed_ms,
        "review_note": clip.review_note,
        "anomaly_id": clip.anomaly_id,
        "confirmed_type": clip.confirmed_type,
        "confirmed_severity": clip.confirmed_severity,
    }

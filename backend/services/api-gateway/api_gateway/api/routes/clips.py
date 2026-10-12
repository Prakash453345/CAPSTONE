"""Uploaded road videos: upload, read, stream, and the operator's review.

The rules and state live in services/clip_registry.py; this module is only
the HTTP layer.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from itms_common import encode_envelope

from api_gateway.api.deps import BusDep, ClipsDep, SettingsDep
from api_gateway.core.config import COMMANDS_TOPIC, EVENT_SOURCE
from api_gateway.core.security import require_api_key
from api_gateway.models.clips import Clip, ClipConfirmRequest, ClipRejectRequest
from api_gateway.services.clip_registry import (
    ALLOWED_EXTENSIONS,
    SUBMITTED_TOPIC,
    ClipRegistry,
    ClipStateError,
    anomaly_request_payload,
    clip_to_json,
    submitted_payload,
)

log = logging.getLogger("api-service.clips")
router = APIRouter(prefix="/v1/clips", tags=["clips"])

_VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
                ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo"}


def _clip_or_404(clips: ClipRegistry, clip_id: str) -> Clip:
    clip = clips.get(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="unknown clip_id")
    return clip


def _inside(root: Path, path: str) -> Path:
    """Serve only files under the clips directory, whatever a stored path says."""
    p = Path(path).resolve()
    if root.resolve() not in p.parents or not p.is_file():
        raise HTTPException(status_code=404, detail="file not available")
    return p


@router.post("", status_code=201)
async def upload_clip(
    file: Annotated[UploadFile, File()],
    edge_id: Annotated[str, Form(min_length=1)],
    clips: ClipsDep,
    settings: SettingsDep,
    bus: BusDep,
    road_name: Annotated[str, Form()] = "",
    latitude: Annotated[float | None, Form()] = None,
    longitude: Annotated[float | None, Form()] = None,
    operator: Annotated[str, Form()] = "operator:console",
) -> dict:
    """Store a road video and queue it for analysis. The video stands in for
    a camera on `edge_id`; anything found becomes a review item, never a
    dispatch on its own."""
    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type {ext or '(none)'}; use one of "
                   f"{', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    clip_id, clip_dir = clips.new_clip_dir()
    dest = clip_dir / f"source{ext}"
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > settings.clip_max_bytes:
                    limit_mb = settings.clip_max_bytes // (1024 * 1024)
                    raise HTTPException(status_code=413,
                                        detail=f"video is over the {limit_mb} MB limit")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="the uploaded file is empty")
    except HTTPException:
        shutil.rmtree(clip_dir, ignore_errors=True)
        raise

    clip = clips.add(Clip(
        clip_id=clip_id, filename=name, video_path=str(dest), edge_id=edge_id,
        road_name=road_name, latitude=latitude, longitude=longitude, operator=operator,
        submitted_ms=int(time.time() * 1000),
    ))
    raw = encode_envelope(event_type="ClipSubmitted", source=EVENT_SOURCE,
                          payload=submitted_payload(clip), partition_key=clip_id)
    await bus.publish(SUBMITTED_TOPIC, raw)
    log.info("clip %s uploaded (%s, %.1f MB) for edge %s", clip_id, name, size / 1e6, edge_id)
    return clip_to_json(clip)


@router.get("")
async def list_clips(clips: ClipsDep) -> list[dict]:
    """Every uploaded clip, newest first."""
    return [clip_to_json(c) for c in clips.all()]


@router.get("/{clip_id}")
async def get_clip(clip_id: str, clips: ClipsDep) -> dict:
    return clip_to_json(_clip_or_404(clips, clip_id))


@router.get("/{clip_id}/video")
async def clip_video(clip_id: str, clips: ClipsDep) -> FileResponse:
    """The uploaded video, with range requests so a player can seek to the
    flagged moment."""
    path = _inside(clips.root, _clip_or_404(clips, clip_id).video_path)
    return FileResponse(path, media_type=_VIDEO_TYPES.get(path.suffix.lower(), "video/mp4"))


@router.get("/{clip_id}/snapshot")
async def clip_snapshot(clip_id: str, clips: ClipsDep) -> FileResponse:
    """The flagged moment as a JPEG, people and plates pixelated."""
    snap = (_clip_or_404(clips, clip_id).result or {}).get("snapshot_path") or ""
    if not snap:
        raise HTTPException(status_code=404, detail="no snapshot for this clip")
    return FileResponse(_inside(clips.root, snap), media_type="image/jpeg")


@router.post("/{clip_id}/confirm", dependencies=[Depends(require_api_key)])
async def confirm_clip(
    clip_id: str,
    body: ClipConfirmRequest,
    clips: ClipsDep,
    bus: BusDep,
) -> dict:
    """ADR-006's human gate for a clip finding: confirm it into a live
    anomaly. Publishes the same `AnomalyCreateRequested` the Create Anomaly
    panel sends, so the simulation (SIM_MODE=live) applies it and the
    response chain dispatches."""
    try:
        clip = clips.confirm(clip_id, actor=body.actor, at_ms=int(time.time() * 1000),
                             anomaly_type=body.anomaly_type, severity=body.severity,
                             note=body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown clip_id") from None
    except ClipStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    raw = encode_envelope(event_type="AnomalyCreateRequested", source=EVENT_SOURCE,
                          payload=anomaly_request_payload(clip))
    await bus.publish(COMMANDS_TOPIC, raw)
    log.info("clip %s confirmed by %s as %s/%s -> anomaly %s", clip_id, body.actor,
             clip.confirmed_type, clip.confirmed_severity, clip.anomaly_id)
    return clip_to_json(clip)


@router.post("/{clip_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_clip(
    clip_id: str, body: ClipRejectRequest, clips: ClipsDep
) -> dict:
    """Dismiss a clip finding as a false alarm."""
    try:
        clip = clips.reject(clip_id, actor=body.actor, at_ms=int(time.time() * 1000),
                            note=body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown clip_id") from None
    except ClipStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return clip_to_json(clip)

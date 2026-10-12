from __future__ import annotations

from fastapi import APIRouter, Depends

from api_gateway.controllers import clips
from api_gateway.core.security import require_api_key

router = APIRouter(prefix="/v1/clips", tags=["clips"])
operator_only = [Depends(require_api_key)]

router.add_api_route("", clips.upload_clip, methods=["POST"], status_code=201)
router.add_api_route("", clips.list_clips, methods=["GET"])
router.add_api_route("/{clip_id}", clips.get_clip, methods=["GET"])
router.add_api_route("/{clip_id}/video", clips.clip_video, methods=["GET"])
router.add_api_route("/{clip_id}/snapshot", clips.clip_snapshot, methods=["GET"])
router.add_api_route("/{clip_id}/confirm", clips.confirm_clip, methods=["POST"],
                     dependencies=operator_only)
router.add_api_route("/{clip_id}/reject", clips.reject_clip, methods=["POST"],
                     dependencies=operator_only)

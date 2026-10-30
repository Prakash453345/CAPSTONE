from __future__ import annotations

from fastapi import APIRouter, Depends

from api_gateway.controllers import clips
from api_gateway.core.security import operator_only, require_reviewer, require_uploader

router = APIRouter(prefix="/v1/clips", tags=["clips"])
reviewer_only = [Depends(require_reviewer)]
signed_in = [Depends(operator_only)]

router.add_api_route("", clips.upload_clip, methods=["POST"], status_code=201,
                     dependencies=[Depends(require_uploader)])
router.add_api_route("", clips.list_clips, methods=["GET"], dependencies=signed_in)
router.add_api_route("/{clip_id}", clips.get_clip, methods=["GET"], dependencies=signed_in)
router.add_api_route("/{clip_id}/video", clips.clip_video, methods=["GET"],
                     dependencies=signed_in)
router.add_api_route("/{clip_id}/snapshot", clips.clip_snapshot, methods=["GET"],
                     dependencies=signed_in)
router.add_api_route("/{clip_id}/confirm", clips.confirm_clip, methods=["POST"],
                     dependencies=reviewer_only)
router.add_api_route("/{clip_id}/reject", clips.reject_clip, methods=["POST"],
                     dependencies=reviewer_only)

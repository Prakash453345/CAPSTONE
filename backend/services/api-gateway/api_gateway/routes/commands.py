from __future__ import annotations

from fastapi import APIRouter

from api_gateway.controllers import commands

router = APIRouter(prefix="/v1", tags=["commands"])
router.add_api_route("/commands", commands.post_command, methods=["POST"])

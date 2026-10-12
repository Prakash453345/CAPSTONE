from __future__ import annotations

from fastapi import APIRouter

from api_gateway.controllers import stream

router = APIRouter(prefix="/v1", tags=["stream"])
router.add_api_websocket_route("/stream", stream.stream)

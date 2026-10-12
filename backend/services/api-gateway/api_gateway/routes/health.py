from __future__ import annotations

from fastapi import APIRouter

from api_gateway.controllers import health

router = APIRouter(tags=["health"])
router.add_api_route("/health", health.health, methods=["GET"])

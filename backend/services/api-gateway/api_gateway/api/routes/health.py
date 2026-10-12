from __future__ import annotations

from fastapi import APIRouter

from api_gateway.api.deps import ConnectionsDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(connections: ConnectionsDep) -> dict:
    return {"status": "ok", "connected_clients": len(connections)}

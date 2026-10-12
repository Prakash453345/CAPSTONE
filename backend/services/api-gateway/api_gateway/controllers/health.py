"""Controller: liveness and connected-client count."""

from __future__ import annotations

from api_gateway.dependencies import ConnectionsDep


async def health(connections: ConnectionsDep) -> dict:
    return {"status": "ok", "connected_clients": len(connections)}

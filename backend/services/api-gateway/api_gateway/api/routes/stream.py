"""The live WebSocket: every relayed bus event, pushed to every client."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/v1", tags=["stream"])


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    connections = ws.app.state.connections
    await connections.connect(ws)
    try:
        while True:
            # Push-only from server to client; receiving keeps the connection
            # alive and detects disconnects. Client->server messages
            # (subscribe/bbox filters, ARCH §7.2) are future work.
            await ws.receive_text()
    except WebSocketDisconnect:
        connections.disconnect(ws)

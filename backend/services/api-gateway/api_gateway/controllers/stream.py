"""Controller: the live WebSocket -- every relayed bus event, pushed to every client."""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from api_gateway.core.security import ws_signed_in


async def stream(ws: WebSocket) -> None:
    if ws.app.state.settings.require_sign_in and not ws_signed_in(ws):
        # 1008 = policy violation: the browser shows the stream as offline and
        # the page's own sign-in check sends the person to /login.
        await ws.close(code=1008)
        return
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

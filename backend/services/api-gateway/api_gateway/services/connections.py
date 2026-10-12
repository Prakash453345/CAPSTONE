"""Connected WebSocket clients, and broadcasting to them."""

from __future__ import annotations

import logging

from fastapi import WebSocket

log = logging.getLogger("api-service.connections")


class ConnectionManager:
    def __init__(self) -> None:
        self._sockets: set[WebSocket] = set()

    def __len__(self) -> int:
        return len(self._sockets)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._sockets.add(ws)
        log.info("client connected, %d total", len(self._sockets))

    def disconnect(self, ws: WebSocket) -> None:
        self._sockets.discard(ws)
        log.info("client disconnected, %d total", len(self._sockets))

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in self._sockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

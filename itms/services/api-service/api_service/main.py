"""api-service, M1 slice.

Eventually: incidents, dispatch, routing, corridor, notification, analytics,
config, audit, and the viewport-filtered WebSocket fan-out [ARCH ADR-007].
Today: three topics (heartbeat + M1's vehicle positions and edge state), no
viewport filtering, no auth. Viewport filtering is real architecture, not
gold-plating -- ARCH §7.2's whole point is that a client shouldn't receive
2 million vehicles when it can see 200 -- but this milestone's network has
16 junctions and low triple-digit vehicle counts at most, so broadcasting
every event to every client is still cheap enough not to be worth the
complexity yet. Add it when the network is big enough that it isn't -- there
will be an obvious moment (the dashboard visibly falling behind, or a much
larger network landing) rather than guessing preemptively. Auth arrives in
M6/M7 alongside dispatch.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from itms_common import RedisStreamsBus, decode_envelope
from api_service.incidents import router as incidents_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s api-service %(message)s")
log = logging.getLogger("api-service")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
TOPICS = ["system.heartbeat", "traffic.vehicle-positions", "traffic.updated", "incident.candidate"]
CONSUMER_GROUP = "api-service"


class ConnectionManager:
    def __init__(self) -> None:
        self._sockets: set[WebSocket] = set()

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


manager = ConnectionManager()


def _json_safe(envelope: dict) -> dict:
    """fastavro decodes the envelope's timestamp-millis field into a datetime;
    make the whole envelope plain-JSON-serializable before it hits the socket."""
    out = dict(envelope)
    occurred_at = out.get("occurred_at")
    if isinstance(occurred_at, dt.datetime):
        out["occurred_at"] = occurred_at.isoformat()
    return out


async def consume_forever(bus: RedisStreamsBus) -> None:
    async for msg in bus.subscribe(
        TOPICS, group=CONSUMER_GROUP, consumer="api-service-1"
    ):
        try:
            envelope = decode_envelope(msg.raw)
            await manager.broadcast(_json_safe(envelope))
        except Exception:
            log.exception("failed to handle message %s on %s", msg.message_id, msg.topic)
        else:
            await bus.ack(msg.topic, CONSUMER_GROUP, msg.message_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus = RedisStreamsBus(REDIS_URL)
    app.state.bus = bus
    consumer_task = asyncio.create_task(consume_forever(bus))
    log.info("consuming %s from %s", TOPICS, REDIS_URL)
    try:
        yield
    finally:
        consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer_task
        await bus.close()


app = FastAPI(title="ITMS api-service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incidents_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "connected_clients": len(manager._sockets)}


@app.websocket("/v1/stream")
async def stream(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            # M0 is push-only from server to client; the receive() call just
            # keeps the connection alive and detects disconnects. Client->server
            # messages (subscribe/bbox filters per ARCH §7.2) arrive in M1+.
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)

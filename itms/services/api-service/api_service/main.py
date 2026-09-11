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

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from itms_common import RedisStreamsBus, decode_envelope, encode_envelope
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s api-service %(message)s")
log = logging.getLogger("api-service")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
TOPICS = [
    "system.heartbeat",
    "traffic.vehicle-positions",
    "traffic.updated",
    "signal.changed",  # from SIM_MODE=live's arbitration ladder
    "signal.faulted",
    "anomaly.updated",  # operator / detector anomalies (SIM_MODE=live)
    "emergency.request-updated",  # emergency dispatch + routing (SIM_MODE=live)
    "emergency.vehicle-updated",  # live EV position while in transit (SIM_MODE=live)
    "emergency.corridor-updated",  # green corridor lifecycle (SIM_MODE=live)
]
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


def _json_safe(value):
    """fastavro decodes every timestamp-millis field (envelope `occurred_at`
    and any in a payload -- e.g. AnomalyUpdated's `start_time_ms`) into a
    datetime. Walk the structure and isoformat them so the whole thing is
    plain-JSON-serializable before it hits the socket."""
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _json_safe_envelope(envelope: dict) -> dict:
    safe = _json_safe(envelope)
    assert isinstance(safe, dict)  # a dict in always yields a dict out
    return safe


async def consume_forever(bus: RedisStreamsBus) -> None:
    async for msg in bus.subscribe(
        TOPICS, group=CONSUMER_GROUP, consumer="api-service-1"
    ):
        try:
            envelope = decode_envelope(msg.raw)
            await manager.broadcast(_json_safe_envelope(envelope))
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "connected_clients": len(manager._sockets)}


COMMANDS_TOPIC = "commands.operator"


class CommandRequest(BaseModel):
    """An operator action to run against the live simulation. `event_type`
    selects the payload schema in `contracts/events/`; `payload` must match
    it. The command is wrapped in the standard EventEnvelope and published on
    `commands.operator`, which `sim-service` (SIM_MODE=live) drains each tick.

    Deliberately thin: the api-service does no business logic here -- it is
    the adapter that gets an operator intent onto the bus. sim-service owns
    applying it to SUMO, and the Signal Controller stays the only thing that
    can command a signal."""

    event_type: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    operator: str = Field(default="operator:console", min_length=1)


@app.post("/v1/commands")
async def post_command(cmd: CommandRequest, request: Request) -> dict:
    payload = {**cmd.payload, "operator": cmd.payload.get("operator", cmd.operator)}
    try:
        raw = encode_envelope(
            event_type=cmd.event_type,
            source="api-service",
            payload=payload,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown command event_type {cmd.event_type!r} -- "
                "no schema in contracts/events/"
            ),
        ) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=422, detail=f"payload does not match schema: {exc}"
        ) from exc

    bus: RedisStreamsBus = request.app.state.bus
    message_id = await bus.publish(COMMANDS_TOPIC, raw)
    log.info("command %s published to %s (%s)", cmd.event_type, COMMANDS_TOPIC, message_id)
    return {"published": True, "topic": COMMANDS_TOPIC, "message_id": message_id}


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

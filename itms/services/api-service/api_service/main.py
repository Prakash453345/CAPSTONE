"""api-service.

Eventually: dispatch, routing, corridor, notification, analytics, config,
audit, and the viewport-filtered WebSocket fan-out [ARCH ADR-007]. Today:
M1's three traffic topics (heartbeat, vehicle positions, edge state) plus
M6's incident lifecycle -- consuming `incident.candidate`/`.detected`/
`.updated`, broadcasting them over the same WebSocket, and exposing the one
piece of M6 that belongs in this service rather than sim-service: ADR-006's
human-in-the-loop gate. sim-service's `LiveIncidentDetector` may only ever
*raise* a candidate; only an operator, through `POST /v1/incidents/{id}
/confirm|reject` here, may turn one into a real incident or dismiss it. See
`api_service/incidents.py` for the registry that makes this possible without
api-service depending on sim-service.

No viewport filtering yet. Real architecture, not gold-plating -- ARCH
§7.2's whole point is that a client shouldn't receive 2 million vehicles
when it can see 200 -- but this milestone's network has 16 junctions and
low triple-digit vehicle counts at most, so broadcasting every event to
every client is still cheap enough not to be worth the complexity yet. Add
it when the network is big enough that it isn't -- there will be an obvious
moment (the dashboard visibly falling behind, or a much larger network
landing) rather than guessing preemptively.

Auth is a single shared-secret header (`X-API-Key`), checked only on the two
mutating incident endpoints -- everything else (the traffic/incident stream,
reading incident state) stays open, matching this milestone's actual threat
model (a local demo, not a multi-tenant deployment) rather than building a
user/session system nothing here needs yet. See `API_KEY`'s own comment for
what happens when it isn't set.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from itms_common import RedisStreamsBus, decode_envelope, encode_envelope
from itms_domain.incident import IllegalTransition, IncidentClass
from pydantic import BaseModel, Field

from api_service.incidents import (
    IncidentRegistry,
    incident_to_json,
    publish_detected,
    publish_updated,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s api-service %(message)s")
log = logging.getLogger("api-service")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
TOPICS = [
    "system.heartbeat",
    "traffic.vehicle-positions",
    "traffic.updated",
    "incident.candidate",
    "incident.detected",
    "incident.updated",
    "signal.changed",  # from SIM_MODE=live's arbitration ladder
    "signal.faulted",
    "anomaly.updated",  # operator / detector anomalies (SIM_MODE=live)
    "emergency.request-updated",  # emergency dispatch + routing (SIM_MODE=live)
    "emergency.vehicle-updated",  # live EV position while in transit (SIM_MODE=live)
    "emergency.corridor-updated",  # green corridor lifecycle (SIM_MODE=live)
    "emergency.dispatched",  # incident -> authority alert (SIM_MODE=live)
    "vision.link-state",  # M8 camera-measured link state (vision-service)
    "vision.camera-status",  # M8 camera health changes (vision-service)
]
_INCIDENT_EVENT_TYPES = {"IncidentCandidate", "IncidentDetected", "IncidentUpdated"}
CONSUMER_GROUP = "api-service"

# A simple shared secret, not a user/session system -- see this module's
# docstring for why that's the right depth for what this service actually
# needs to protect right now (two mutating endpoints, one operator role).
# Left unset, a fresh one is generated per process start so `make dev` never
# needs extra setup and the endpoints are never silently unprotected -- but
# that also means it changes on every restart, so anything beyond local dev
# should set API_KEY explicitly.
_env_api_key = os.environ.get("API_KEY")
API_KEY: str = _env_api_key or secrets.token_urlsafe(24)
if not _env_api_key:
    log.warning(
        "API_KEY not set -- generated one for this process so incident confirm/reject "
        "stay protected without extra setup (X-API-Key: %s). It changes every restart; "
        "set API_KEY yourself for anything beyond local dev.",
        API_KEY,
    )


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key header")


class ConfirmRequest(BaseModel):
    actor: str
    classification: str = IncidentClass.UNKNOWN.value
    detail: str = ""


class RejectRequest(BaseModel):
    actor: str
    detail: str = ""


registry = IncidentRegistry()


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


async def _consume_topic(bus: RedisStreamsBus, topic: str, consumer: str) -> None:
    """Relay one topic with its own cursor so busy traffic cannot starve alarms."""
    while True:
        try:
            async for msg in bus.subscribe(
                # This is a viewport/UI fan-out, not an archival processor. A
                # newly created API group begins at the live edge; replaying a
                # retained stream can leave the command center showing
                # hours-old congestion before current vehicle positions.
                [topic], group=CONSUMER_GROUP, consumer=consumer, start_id="$"
            ):
                try:
                    envelope = decode_envelope(msg.raw)
                    event_type = envelope["event_type"]
                    if event_type in _INCIDENT_EVENT_TYPES:
                        # Builds/updates the registry from the stream -- see
                        # api_service/incidents.py's module docstring for why
                        # this is safe to do even for events this same process
                        # just published itself (the chain_hash idempotency check).
                        registry.apply_event(event_type, envelope["payload"])
                    await manager.broadcast(_json_safe_envelope(envelope))
                except Exception:
                    log.exception("failed to handle message %s on %s", msg.message_id, msg.topic)
                else:
                    await bus.ack(msg.topic, CONSUMER_GROUP, msg.message_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("live stream consumer failed; retrying")
            await asyncio.sleep(1)
        else:
            # A subscription is designed never to finish. If it does, keep the
            # live bridge alive instead of leaving connected browsers stale.
            log.warning("live stream consumer ended; restarting")
            await asyncio.sleep(1)


async def consume_forever(bus: RedisStreamsBus) -> None:
    """Relay all live topics concurrently without starvation or silent death."""
    tasks = [
        asyncio.create_task(_consume_topic(bus, topic, f"api-service-{i}"))
        for i, topic in enumerate(TOPICS, start=1)
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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


@app.get("/v1/incidents")
async def list_incidents() -> list[dict]:
    """Every incident this process has seen since it started (the registry
    is in-memory, rebuilt from the bus on each restart -- see
    `api_service/incidents.py`), newest first."""
    return [incident_to_json(inc) for inc in sorted(
        registry.all(), key=lambda inc: inc.first_seen_ms, reverse=True
    )]


@app.get("/v1/incidents/{incident_id}")
async def get_incident(incident_id: str) -> dict:
    inc = registry.get(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="unknown incident_id")
    return incident_to_json(inc)


@app.post("/v1/incidents/{incident_id}/confirm", dependencies=[Depends(require_api_key)])
async def confirm_incident(incident_id: str, body: ConfirmRequest) -> dict:
    """ADR-006's human gate, the affirmative half: turn a raised CANDIDATE
    into a real, dispatch-worthy incident. Requires `X-API-Key`."""
    try:
        classification = IncidentClass(body.classification)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"unknown classification {body.classification!r}"
        ) from None

    at_ms = int(time.time() * 1000)
    try:
        inc = registry.confirm(
            incident_id,
            at_ms=at_ms,
            actor=body.actor,
            classification=classification,
            detail=body.detail,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown incident_id") from None
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    await publish_detected(app.state.bus, inc, confirmed_at_ms=at_ms)
    return incident_to_json(inc)


@app.post("/v1/incidents/{incident_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_incident(incident_id: str, body: RejectRequest) -> dict:
    """ADR-006's human gate, the negative half: dismiss a raised CANDIDATE
    as a false alarm -- plan 4.4's feedback signal for the conformal
    calibrator, once something consumes `incident.updated` to fold it back
    in (not yet wired; see contracts/events/README.md). Requires
    `X-API-Key`."""
    at_ms = int(time.time() * 1000)
    try:
        inc = registry.reject(incident_id, at_ms=at_ms, actor=body.actor, detail=body.detail)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown incident_id") from None
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    await publish_updated(app.state.bus, inc)
    return incident_to_json(inc)

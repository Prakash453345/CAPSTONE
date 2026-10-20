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
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from itms_common import RedisStreamsBus, decode_envelope, encode_envelope
from itms_domain.incident import IllegalTransition, IncidentClass
from pydantic import BaseModel, Field

from api_service import auth as auth_mod
from api_service import crew_roster
from api_service.auth import router as auth_router
from api_service.clips import (
    ALLOWED_EXTENSIONS,
    SUBMITTED_TOPIC,
    Clip,
    ClipRegistry,
    ClipStateError,
    anomaly_request_payload,
    clip_to_json,
    submitted_payload,
)
from api_service.incidents import (
    IncidentRegistry,
    incident_to_json,
    publish_detected,
    publish_updated,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s api-service %(message)s")
log = logging.getLogger("api-service")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_PROCESS_ID = secrets.token_hex(4)
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
    "crew.offer",  # a call offered to a crew, and how they answered
    "vision.link-state",  # M8 camera-measured link state (vision-service)
    "vision.camera-status",  # M8 camera health changes (vision-service)
    "vision.clip-analysed",  # uploaded-clip analysis progress/results (vision-service clip worker)
]
_INCIDENT_EVENT_TYPES = {"IncidentCandidate", "IncidentDetected", "IncidentUpdated"}
_INCIDENT_TOPICS = frozenset({"incident.candidate", "incident.detected", "incident.updated"})
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

# Uploaded road videos (see api_service/clips.py). The directory is shared with
# vision-service's clip worker, which reads the video and writes its result
# and snapshot beside it.
_REPO = Path(__file__).resolve().parents[3]
CLIPS_DIR = Path(os.environ.get("CLIPS_DIR", _REPO / "var" / "clips")).resolve()
CLIP_MAX_BYTES = int(float(os.environ.get("CLIP_MAX_MB", "300")) * 1024 * 1024)
clips = ClipRegistry(CLIPS_DIR)


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
    """Relay one topic with its own cursor so busy traffic cannot starve alarms.

    `incident.*` topics feed the in-memory `IncidentRegistry`, which is empty
    after a restart, so they are read from the start of the stream through a
    group private to this process (a shared group resumes at its old cursor and
    never replays). Everything else is a live-edge UI fan-out."""
    replay = topic in _INCIDENT_TOPICS
    group = f"{CONSUMER_GROUP}-registry-{_PROCESS_ID}" if replay else CONSUMER_GROUP
    while True:
        try:
            async for msg in bus.subscribe(
                # This is a viewport/UI fan-out, not an archival processor. A
                # newly created API group begins at the live edge; replaying a
                # retained stream can leave the command center showing
                # hours-old congestion before current vehicle positions.
                [topic], group=group, consumer=consumer, start_id="0" if replay else "$"
            ):
                try:
                    envelope = decode_envelope(msg.raw)
                    event_type = envelope["event_type"]
                    if event_type == "ClipAnalysed":
                        clips.apply_analysed(envelope["payload"])
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
                    await bus.ack(msg.topic, group, msg.message_id)
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
    # api-service owns the accounts database, so it is the one that can say
    # which crews exist; sim-service does the matching and should not hold
    # Postgres credentials to find out.
    roster_task = asyncio.create_task(crew_roster.publish_forever(bus))
    log.info("consuming %s from %s", TOPICS, REDIS_URL)
    try:
        yield
    finally:
        for task in (consumer_task, roster_task):
            task.cancel()
        for task in (consumer_task, roster_task):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await bus.close()


app = FastAPI(title="ITMS api-service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


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


# Anyone who can reach api-service could otherwise drive the simulation and
# read the live stream. With the site shared beyond one laptop, both need a
# signed-in account (the same session cookie the pages use). API_REQUIRE_SIGN_IN
# =false turns this off for scripts on a trusted machine.
REQUIRE_SIGN_IN = os.environ.get("API_REQUIRE_SIGN_IN", "true").strip().lower() not in {
    "0", "false", "no", "off",
}
# What a crew account may send: answer its own call, pick its hospital, ask for
# a new route. Everything else (incidents, dispatch, corridors) is operators'.
_CREW_COMMANDS = {"CrewOfferResponse", "CrewHospitalChoice", "EmergencyCommand"}


def _session_user(request: Request) -> auth_mod.UserRecord | None:
    """The signed-in account, None when sign-in is not required; else 401."""
    if not REQUIRE_SIGN_IN:
        return None
    return auth_mod.current_user(request, auth_mod.get_user_store())


def _check_crew_command(user: auth_mod.UserRecord, cmd: CommandRequest) -> None:
    if user.role != "responder":
        return
    allowed = cmd.event_type in _CREW_COMMANDS and (
        cmd.event_type != "EmergencyCommand"
        or str(cmd.payload.get("action", "")).upper() == "RECALCULATE"
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Crew accounts can't send that command.")
    if cmd.event_type == "CrewHospitalChoice":
        # A crew chooses the hospital for its own ambulance only.
        cmd.payload["unit_id"] = user.unit_id or ""


@app.post("/v1/commands")
async def post_command(
    cmd: CommandRequest,
    request: Request,
    user: Annotated[auth_mod.UserRecord | None, Depends(_session_user)] = None,
) -> dict:
    if user is not None:
        _check_crew_command(user, cmd)
        cmd.operator = f"{user.role}:{user.username}"
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
    if REQUIRE_SIGN_IN and not _ws_signed_in(ws):
        # 1008 = policy violation: the browser shows the stream as offline and
        # the page's own sign-in check sends the person to /login.
        await ws.close(code=1008)
        return
    await manager.connect(ws)
    try:
        while True:
            # M0 is push-only from server to client; the receive() call just
            # keeps the connection alive and detects disconnects. Client->server
            # messages (subscribe/bbox filters per ARCH §7.2) arrive in M1+.
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


def _ws_signed_in(ws: WebSocket) -> bool:
    claims = auth_mod.read_token(ws.cookies.get(auth_mod.COOKIE_NAME, ""))
    if claims is None:
        return False
    try:
        record = auth_mod.get_user_store().get(claims[0])
    except auth_mod.StoreUnavailable:
        return False
    return bool(record and record.is_active and record.session_version == claims[1])


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


# ---- uploaded road videos -------------------------------------------------


class ClipConfirmRequest(BaseModel):
    actor: str = Field(min_length=1)
    anomaly_type: str | None = None  # the reviewer's correction; default: what the analysis found
    severity: str | None = None
    note: str = ""


class ClipRejectRequest(BaseModel):
    actor: str = Field(min_length=1)
    note: str = ""


_VIDEO_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
                ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo"}


def _clip_or_404(clip_id: str) -> Clip:
    clip = clips.get(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="unknown clip_id")
    return clip


def _inside_clips_dir(path: str) -> Path:
    """Serve only files under CLIPS_DIR, whatever a stored path says."""
    p = Path(path).resolve()
    if CLIPS_DIR not in p.parents or not p.is_file():
        raise HTTPException(status_code=404, detail="file not available")
    return p


@app.post("/v1/clips", status_code=201)
async def upload_clip(
    request: Request,
    file: UploadFile = File(...),
    edge_id: str = Form(..., min_length=1),
    road_name: str = Form(""),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    operator: str = Form("operator:console"),
) -> dict:
    """Store a road video and queue it for analysis. The video stands in for
    a camera on `edge_id`; anything found becomes a review item, never a
    dispatch on its own."""
    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type {ext or '(none)'}; use one of "
                   f"{', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    clip_id, clip_dir = clips.new_clip_dir()
    dest = clip_dir / f"source{ext}"
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > CLIP_MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"video is over the {CLIP_MAX_BYTES // (1024 * 1024)} MB limit",
                    )
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="the uploaded file is empty")
    except HTTPException:
        shutil.rmtree(clip_dir, ignore_errors=True)
        raise

    clip = clips.add(Clip(
        clip_id=clip_id, filename=name, video_path=str(dest), edge_id=edge_id,
        road_name=road_name, latitude=latitude, longitude=longitude, operator=operator,
        submitted_ms=int(time.time() * 1000),
    ))
    raw = encode_envelope(event_type="ClipSubmitted", source="api-service",
                          payload=submitted_payload(clip), partition_key=clip_id)
    bus: RedisStreamsBus = request.app.state.bus
    await bus.publish(SUBMITTED_TOPIC, raw)
    log.info("clip %s uploaded (%s, %.1f MB) for edge %s", clip_id, name, size / 1e6, edge_id)
    return clip_to_json(clip)


@app.get("/v1/clips")
async def list_clips() -> list[dict]:
    """Every uploaded clip, newest first."""
    return [clip_to_json(c) for c in clips.all()]


@app.get("/v1/clips/{clip_id}")
async def get_clip(clip_id: str) -> dict:
    return clip_to_json(_clip_or_404(clip_id))


@app.get("/v1/clips/{clip_id}/video")
async def clip_video(clip_id: str) -> FileResponse:
    """The uploaded video, with range requests so a player can seek to the
    flagged moment."""
    path = _inside_clips_dir(_clip_or_404(clip_id).video_path)
    return FileResponse(path, media_type=_VIDEO_TYPES.get(path.suffix.lower(), "video/mp4"))


@app.get("/v1/clips/{clip_id}/snapshot")
async def clip_snapshot(clip_id: str) -> FileResponse:
    """The flagged moment as a JPEG, people and plates pixelated."""
    snap = (_clip_or_404(clip_id).result or {}).get("snapshot_path") or ""
    if not snap:
        raise HTTPException(status_code=404, detail="no snapshot for this clip")
    return FileResponse(_inside_clips_dir(snap), media_type="image/jpeg")


@app.post("/v1/clips/{clip_id}/confirm", dependencies=[Depends(require_api_key)])
async def confirm_clip(clip_id: str, body: ClipConfirmRequest, request: Request) -> dict:
    """ADR-006's human gate for a clip finding: confirm it into a live
    anomaly. Publishes the same `AnomalyCreateRequested` the Create Anomaly
    panel sends, so the simulation (SIM_MODE=live) applies it and the
    response chain dispatches. Requires `X-API-Key`."""
    try:
        clip = clips.confirm(clip_id, actor=body.actor, at_ms=int(time.time() * 1000),
                             anomaly_type=body.anomaly_type, severity=body.severity,
                             note=body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown clip_id") from None
    except ClipStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    raw = encode_envelope(event_type="AnomalyCreateRequested", source="api-service",
                          payload=anomaly_request_payload(clip))
    bus: RedisStreamsBus = request.app.state.bus
    await bus.publish(COMMANDS_TOPIC, raw)
    log.info("clip %s confirmed by %s as %s/%s -> anomaly %s", clip_id, body.actor,
             clip.confirmed_type, clip.confirmed_severity, clip.anomaly_id)
    return clip_to_json(clip)


@app.post("/v1/clips/{clip_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_clip(clip_id: str, body: ClipRejectRequest) -> dict:
    """Dismiss a clip finding as a false alarm. Requires `X-API-Key`."""
    try:
        clip = clips.reject(clip_id, actor=body.actor, at_ms=int(time.time() * 1000),
                            note=body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown clip_id") from None
    except ClipStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return clip_to_json(clip)


# ---- one address for everything (servers) ---------------------------------
#
# On a server the browser loads the site, calls `/api/...` and opens
# `/ws/v1/stream` all on one address -- sign-in is a same-origin cookie, so they
# must share it. In development the Vite dev server does this; on a server,
# setting WEB_DIST (the built web app, `npm run build` -> web-app/dist) makes
# api-service do it itself, so one port is the whole product and no separate
# web server is needed (deploy/README.md).

WEB_DIST = os.environ.get("WEB_DIST", "").strip()


class _StripPrefixes:
    """`/api/x` -> `/x` and `/ws/x` -> `/x`, as the dev server's proxy does."""

    def __init__(self, inner) -> None:
        self.inner = inner

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            for prefix in ("/api", "/ws"):
                if path == prefix or path.startswith(prefix + "/"):
                    path = path[len(prefix):] or "/"
                    scope = {**scope, "path": path, "raw_path": path.encode()}
                    break
        await self.inner(scope, receive, send)


if WEB_DIST and (Path(WEB_DIST) / "index.html").is_file():
    _WEB_ROOT = Path(WEB_DIST).resolve()
    app.add_middleware(_StripPrefixes)

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str) -> FileResponse:
        """A file of the built site, else index.html (the app's own routes)."""
        target = (_WEB_ROOT / path).resolve()
        if path and target.is_file() and _WEB_ROOT in target.parents:
            immutable = target.parent.name == "assets"  # hashed names never change
            return FileResponse(
                target,
                headers={"Cache-Control": "public, max-age=31536000, immutable"}
                if immutable else {"Cache-Control": "no-cache"},
            )
        return FileResponse(_WEB_ROOT / "index.html", headers={"Cache-Control": "no-cache"})

    log.info("serving the web app from %s", _WEB_ROOT)

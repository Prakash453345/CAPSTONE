"""api-gateway: the one HTTP/WebSocket entry point the console talks to.

It relays the live event bus to browsers (services/event_relay.py), puts
operator commands onto the bus, and holds ADR-006's human gate -- the
confirm/reject endpoints for detector incidents and uploaded-clip findings.
Everything else (simulation, signal control, routing, vision) lives in the
other services and talks to this one only through the bus.

Layers, each calling only the one below it:
    routes/        the URL map: path + method -> controller, route policy (API key)
    controllers/   request handling: read input, call a service, map errors to HTTP
    services/      business logic and state: registries, the bus relay, WebSocket clients
    models/        request bodies and stored records
    core/          settings and the API-key check; dependencies.py hands shared
                   state (registries, bus) to controllers

Run: uvicorn api_gateway.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from itms_common import RedisStreamsBus

from api_gateway.core.config import Settings
from api_gateway.routes import api_router
from api_gateway.services import crew_roster
from api_gateway.services.auth import router as auth_router
from api_gateway.services.clip_registry import ClipRegistry
from api_gateway.services.connections import ConnectionManager
from api_gateway.services.event_relay import EventRelay
from api_gateway.services.incident_registry import IncidentRegistry

log = logging.getLogger("api-service")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    bus = RedisStreamsBus(settings.redis_url)
    app.state.bus = bus
    relay = EventRelay(bus, app.state.connections, app.state.incidents, app.state.clips,
                       settings.topics)
    relay_task = asyncio.create_task(relay.run_forever())
    # The gateway owns the accounts database, so it is the one that can say
    # which crews exist; sim-service does the matching and should not hold
    # Postgres credentials to find out.
    roster_task = asyncio.create_task(crew_roster.publish_forever(bus))
    log.info("consuming %s from %s", list(settings.topics), settings.redis_url)
    try:
        yield
    finally:
        for task in (relay_task, roster_task):
            task.cancel()
        for task in (relay_task, roster_task):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await bus.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app with its own state. Tests pass their own `Settings` and
    set `app.state.bus` to a fake instead of starting the lifespan."""
    settings = settings or Settings.from_env()
    app = FastAPI(title="ITMS api-gateway", lifespan=_lifespan)
    app.state.settings = settings
    app.state.connections = ConnectionManager()
    app.state.incidents = IncidentRegistry()
    app.state.clips = ClipRegistry(settings.clips_dir)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(api_router)
    _serve_web_app(app, settings)
    return app


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


def _serve_web_app(app: FastAPI, settings: Settings) -> None:
    """One address for everything: with WEB_DIST set the gateway serves the
    built site, `/api/...` and `/ws/v1/stream` itself, so one port is the whole
    product and no separate web server is needed."""
    if not (settings.web_dist and (Path(settings.web_dist) / "index.html").is_file()):
        return
    web_root = Path(settings.web_dist).resolve()
    app.add_middleware(_StripPrefixes)

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str) -> FileResponse:
        """A file of the built site, else index.html (the app's own routes)."""
        target = (web_root / path).resolve()
        if path and target.is_file() and web_root in target.parents:
            immutable = target.parent.name == "assets"  # hashed names never change
            return FileResponse(
                target,
                headers={"Cache-Control": "public, max-age=31536000, immutable"}
                if immutable else {"Cache-Control": "no-cache"},
            )
        return FileResponse(web_root / "index.html", headers={"Cache-Control": "no-cache"})

    log.info("serving the web app from %s", web_root)


logging.basicConfig(level=logging.INFO, format="%(asctime)s api-gateway %(message)s")
app = create_app()

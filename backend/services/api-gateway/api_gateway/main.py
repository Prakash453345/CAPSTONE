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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from itms_common import RedisStreamsBus

from api_gateway.core.config import Settings
from api_gateway.routes import api_router
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
    log.info("consuming %s from %s", list(settings.topics), settings.redis_url)
    try:
        yield
    finally:
        relay_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay_task
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
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s api-gateway %(message)s")
app = create_app()

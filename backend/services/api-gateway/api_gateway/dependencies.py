"""Request-scoped access to the app's shared state, for route handlers.

Everything a controller needs is created once in `main.create_app` and kept
on `app.state`, so a test builds its own isolated app instead of patching
module globals.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from itms_common import RedisStreamsBus

from api_gateway.core.config import Settings
from api_gateway.services.clip_registry import ClipRegistry
from api_gateway.services.connections import ConnectionManager
from api_gateway.services.incident_registry import IncidentRegistry


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_bus(request: Request) -> RedisStreamsBus:
    return request.app.state.bus


def get_incidents(request: Request) -> IncidentRegistry:
    return request.app.state.incidents


def get_clips(request: Request) -> ClipRegistry:
    return request.app.state.clips


def get_connections(request: Request) -> ConnectionManager:
    return request.app.state.connections


# Annotated aliases, so a route declares what it needs by type:
#     async def handler(clips: ClipsDep) -> dict
SettingsDep = Annotated[Settings, Depends(get_settings)]
BusDep = Annotated[RedisStreamsBus, Depends(get_bus)]
IncidentsDep = Annotated[IncidentRegistry, Depends(get_incidents)]
ClipsDep = Annotated[ClipRegistry, Depends(get_clips)]
ConnectionsDep = Annotated[ConnectionManager, Depends(get_connections)]

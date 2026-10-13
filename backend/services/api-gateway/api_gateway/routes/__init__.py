"""Routes: the URL map, and nothing else.

Each module maps paths and methods to controller functions and declares the
route-level policy (which endpoints need the API key, response status codes).
No request handling lives here -- that is controllers/ -- and no business
logic -- that is services/.
"""

from __future__ import annotations

from fastapi import APIRouter

from api_gateway.routes import clips, commands, health, incidents, stream

api_router = APIRouter()
for module in (health, commands, stream, incidents, clips):
    api_router.include_router(module.router)

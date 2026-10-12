"""The shared-secret check for endpoints that change state (see core/config.py)."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request


def require_api_key(request: Request, x_api_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_api_key, request.app.state.settings.api_key):
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key header")

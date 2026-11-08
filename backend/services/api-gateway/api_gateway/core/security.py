"""Who may call what.

Two ways in, both kept from before the gateway was split into layers:

* a signed-in console account (the session cookie the pages use), required on
  every route unless `API_REQUIRE_SIGN_IN=false` (scripts on a trusted machine);
* the shared `X-API-Key` (core/config.py), for scripts and camera services that
  have no browser session. It also lets a script confirm or reject reports.

Crew accounts ("responder" role) are operators' lesser sibling: they may answer
their own call, pick a hospital and ask for a new route, and nothing else.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request, WebSocket

from api_gateway.models.commands import CommandRequest
from api_gateway.services import auth as auth_mod
from api_gateway.services.crew_ownership import CrewOwnership

# What a crew account may send: answer its own call, pick its hospital, ask for
# a new route. Everything else (incidents, dispatch, corridors) is operators'.
CREW_COMMANDS = {"CrewOfferResponse", "CrewHospitalChoice", "EmergencyCommand"}


def _key_matches(request: Request, x_api_key: str) -> bool:
    return bool(x_api_key) and secrets.compare_digest(x_api_key, request.app.state.settings.api_key)


def require_api_key(request: Request, x_api_key: str = Header(default="")) -> None:
    if not _key_matches(request, x_api_key or ""):
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key header")


def session_user(request: Request) -> auth_mod.UserRecord | None:
    """The signed-in account, None when sign-in is not required; else 401."""
    if not request.app.state.settings.require_sign_in:
        return None
    return auth_mod.current_user(request, auth_mod.get_user_store())


def operator_only(request: Request) -> None:
    """Clips and incidents are operator data: crew accounts get 403."""
    user = session_user(request)
    if user is not None and user.role == "responder":
        raise HTTPException(status_code=403, detail="Crew accounts can't open this.")
    if user is not None:
        request.state.reviewer = f"{user.role}:{user.username}"


def require_uploader(request: Request, x_api_key: str = Header(default="")) -> None:
    """Who may add a clip: an operator session, or a camera service holding the key."""
    if _key_matches(request, x_api_key):
        return
    operator_only(request)


def require_reviewer(request: Request, x_api_key: str = Header(default="")) -> None:
    """Who may confirm or reject a candidate: a signed-in operator (the console's
    own session), or a script holding the API key. Crew accounts may not."""
    if _key_matches(request, x_api_key):
        return
    if request.app.state.settings.require_sign_in:
        user = auth_mod.current_user(request, auth_mod.get_user_store())
        if user.role == "responder":
            raise HTTPException(status_code=403, detail="Crew accounts can't review reports.")
        request.state.reviewer = f"{user.role}:{user.username}"
        return
    raise HTTPException(status_code=401, detail="missing or invalid X-API-Key header")


def acting_as(request: Request, claimed: str) -> str:
    """Who to record as having done something. A signed-in account is recorded
    as itself, whatever name the request body claims; only an API-key caller
    (a script or camera service, which has no account) names itself."""
    return getattr(request.state, "reviewer", None) or claimed


def check_crew_command(
    user: auth_mod.UserRecord, cmd: CommandRequest, ownership: CrewOwnership
) -> None:
    if user.role != "responder":
        return
    allowed = cmd.event_type in CREW_COMMANDS and (
        cmd.event_type != "EmergencyCommand"
        or str(cmd.payload.get("action", "")).upper() == "RECALCULATE"
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Crew accounts can't send that command.")
    unit = user.unit_id or ""
    if not unit:
        raise HTTPException(status_code=403, detail="This crew account has no vehicle.")
    if cmd.event_type == "CrewHospitalChoice":
        # A crew chooses the hospital for its own ambulance only.
        cmd.payload["unit_id"] = unit
    elif cmd.event_type == "CrewOfferResponse":
        # Answer only a call offered to this crew: accepting or declining
        # another unit's call would send the wrong vehicle or skip the right one.
        owner = ownership.offer_unit(str(cmd.payload.get("offer_id", "")))
        _require_own(owner, unit, "That call is not open any more.",
                     "That call is for another crew.")
    elif cmd.event_type == "EmergencyCommand":
        owner = ownership.request_unit(str(cmd.payload.get("request_id", "")))
        _require_own(owner, unit, "That trip is not known yet. Try again in a moment.",
                     "That trip belongs to another crew.")


def _require_own(owner: str | None, unit: str, unknown: str, other: str) -> None:
    if owner is None:
        raise HTTPException(status_code=409, detail=unknown)
    if not secrets.compare_digest(owner, unit):
        raise HTTPException(status_code=403, detail=other)


def ws_origin_allowed(ws: WebSocket) -> bool:
    """Refuse a browser connecting from another website.

    Browsers send the session cookie with a WebSocket handshake whatever page
    started it, and CORS does not apply to WebSockets, so without this a page
    on any other site an operator opened could read the live stream as them.
    No Origin header means a script or service, not a browser, which still
    needs a valid session. Allowed: the configured CORS origins, and the
    gateway's own address (WEB_DIST serves the site from the same host)."""
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    if origin in ws.app.state.settings.cors_origins:
        return True
    host = ws.headers.get("host", "")
    return bool(host) and urlsplit(origin).netloc.lower() == host.lower()


def ws_signed_in(ws: WebSocket) -> bool:
    claims = auth_mod.read_token(ws.cookies.get(auth_mod.COOKIE_NAME, ""))
    if claims is None:
        return False
    try:
        record = auth_mod.get_user_store().get(claims[0])
    except auth_mod.StoreUnavailable:
        return False
    return bool(record and record.is_active and record.session_version == claims[1])

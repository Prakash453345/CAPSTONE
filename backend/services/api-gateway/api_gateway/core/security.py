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

from fastapi import Header, HTTPException, Request, WebSocket

from api_gateway.models.commands import CommandRequest
from api_gateway.services import auth as auth_mod

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
        return
    raise HTTPException(status_code=401, detail="missing or invalid X-API-Key header")


def reviewer_actor(request: Request, claimed: str) -> str:
    """Who to record as having confirmed or rejected something. A signed-in
    reviewer is recorded as themselves -- the body's `actor` used to be taken
    as is, so any account could write anyone into the review record and the
    incident's hash-chained audit trail. A script holding the API key has no
    account, so its own `actor` stands."""
    if request.app.state.settings.require_sign_in:
        try:
            user = auth_mod.current_user(request, auth_mod.get_user_store())
        except HTTPException:
            return claimed  # no session: require_reviewer already checked the key
        return f"{user.role}:{user.username}"
    return claimed


def check_crew_command(user: auth_mod.UserRecord, cmd: CommandRequest) -> None:
    if user.role != "responder":
        return
    allowed = cmd.event_type in CREW_COMMANDS and (
        cmd.event_type != "EmergencyCommand"
        or str(cmd.payload.get("action", "")).upper() == "RECALCULATE"
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Crew accounts can't send that command.")
    if cmd.event_type == "CrewHospitalChoice":
        # A crew chooses the hospital for its own ambulance only.
        cmd.payload["unit_id"] = user.unit_id or ""
    elif cmd.event_type == "EmergencyCommand":
        # A crew may re-plan its own trip only: request ids are on the live
        # stream every crew page receives. sim-service checks the vehicle.
        if not user.unit_id:
            raise HTTPException(status_code=403, detail="This crew account has no vehicle.")
        cmd.payload["unit_id"] = user.unit_id
    elif cmd.event_type == "CrewOfferResponse":
        # A crew answers only offers made to its own vehicle: every offer id is
        # on the live stream every crew page receives, so without this one crew
        # could decline (or accept) another's call. sim-service checks it.
        if not user.unit_id:
            raise HTTPException(status_code=403, detail="This crew account has no vehicle.")
        cmd.payload["unit_id"] = user.unit_id


def ws_signed_in(ws: WebSocket) -> bool:
    claims = auth_mod.read_token(ws.cookies.get(auth_mod.COOKIE_NAME, ""))
    if claims is None:
        return False
    try:
        record = auth_mod.get_user_store().get(claims[0])
    except auth_mod.StoreUnavailable:
        return False
    return bool(record and record.is_active and record.session_version == claims[1])

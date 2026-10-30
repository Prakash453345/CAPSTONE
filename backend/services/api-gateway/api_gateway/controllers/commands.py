"""Controller: operator commands onto the bus (`commands.operator`)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException
from itms_common import encode_envelope

from api_gateway.core.config import COMMANDS_TOPIC, EVENT_SOURCE
from api_gateway.core.security import check_crew_command, session_user
from api_gateway.dependencies import BusDep
from api_gateway.models.commands import CommandRequest
from api_gateway.services.auth import UserRecord

log = logging.getLogger("api-service.commands")


async def post_command(
    cmd: CommandRequest,
    bus: BusDep,
    user: Annotated[UserRecord | None, Depends(session_user)] = None,
) -> dict:
    if user is not None:
        check_crew_command(user, cmd)
        cmd.operator = f"{user.role}:{user.username}"
    payload = {**cmd.payload, "operator": cmd.payload.get("operator", cmd.operator)}
    try:
        raw = encode_envelope(event_type=cmd.event_type, source=EVENT_SOURCE, payload=payload)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"unknown command event_type {cmd.event_type!r} -- "
                   "no schema in contracts/events/",
        ) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422,
                            detail=f"payload does not match schema: {exc}") from exc

    message_id = await bus.publish(COMMANDS_TOPIC, raw)
    log.info("command %s published to %s (%s)", cmd.event_type, COMMANDS_TOPIC, message_id)
    return {"published": True, "topic": COMMANDS_TOPIC, "message_id": message_id}

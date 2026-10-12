"""Operator commands onto the bus (`commands.operator`)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from itms_common import encode_envelope

from api_gateway.api.deps import BusDep
from api_gateway.core.config import COMMANDS_TOPIC, EVENT_SOURCE
from api_gateway.models.commands import CommandRequest

log = logging.getLogger("api-service.commands")
router = APIRouter(prefix="/v1", tags=["commands"])


@router.post("/commands")
async def post_command(cmd: CommandRequest, bus: BusDep) -> dict:
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

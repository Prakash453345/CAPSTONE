"""Controller for ADR-006's human-in-the-loop gate on detector incidents.

The simulation service's `LiveIncidentDetector` may only ever *raise* a
candidate; only an operator, through confirm/reject here, may turn one into a
real incident or dismiss it. The registry (services/incident_registry.py)
makes this possible without this service depending on the simulation service.
"""

from __future__ import annotations

import time

from fastapi import HTTPException, Request
from itms_domain.incident import IllegalTransition, IncidentClass

from api_gateway.core.security import acting_as
from api_gateway.dependencies import BusDep, IncidentsDep
from api_gateway.models.incidents import ConfirmRequest, RejectRequest
from api_gateway.services.incident_registry import (
    incident_to_json,
    publish_detected,
    publish_updated,
)


def _classification(raw: str) -> IncidentClass | None:
    """The enum by value ("stall") or by name ("STALL"), in any case. The
    console sends names -- the wire contract's symbols -- and this used to
    accept only values, so every confirm from the console failed with 422."""
    text = (raw or "").strip()
    for candidate in (text.lower(), text.upper()):
        try:
            return IncidentClass(candidate) if candidate.islower() else IncidentClass[candidate]
        except (ValueError, KeyError):
            continue
    return None


async def list_incidents(incidents: IncidentsDep) -> list[dict]:
    """Every incident this process has seen since it started (the registry is
    in-memory, rebuilt from the bus on each restart), newest first."""
    return [incident_to_json(inc) for inc in sorted(
        incidents.all(), key=lambda inc: inc.first_seen_ms, reverse=True
    )]


async def get_incident(incident_id: str,
                       incidents: IncidentsDep) -> dict:
    inc = incidents.get(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="unknown incident_id")
    return incident_to_json(inc)


async def confirm_incident(
    incident_id: str,
    body: ConfirmRequest,
    incidents: IncidentsDep,
    bus: BusDep,
    request: Request,
) -> dict:
    """Turn a raised CANDIDATE into a real, dispatch-worthy incident."""
    body.actor = acting_as(request, body.actor)
    classification = _classification(body.classification)
    if classification is None:
        raise HTTPException(
            status_code=422, detail=f"unknown classification {body.classification!r}"
        )
    at_ms = int(time.time() * 1000)
    try:
        inc = incidents.confirm(incident_id, at_ms=at_ms, actor=body.actor,
                                classification=classification, detail=body.detail)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown incident_id") from None
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await publish_detected(bus, inc, confirmed_at_ms=at_ms)
    return incident_to_json(inc)


async def reject_incident(
    incident_id: str,
    body: RejectRequest,
    incidents: IncidentsDep,
    bus: BusDep,
    request: Request,
) -> dict:
    """Dismiss a raised CANDIDATE as a false alarm -- plan 4.4's feedback
    signal for the conformal calibrator, once something consumes
    `incident.updated` to fold it back in (not yet wired)."""
    body.actor = acting_as(request, body.actor)
    at_ms = int(time.time() * 1000)
    try:
        inc = incidents.reject(incident_id, at_ms=at_ms, actor=body.actor, detail=body.detail)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown incident_id") from None
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await publish_updated(bus, inc)
    return incident_to_json(inc)

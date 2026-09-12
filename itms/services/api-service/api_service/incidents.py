"""M6 incident lifecycle endpoints [ARCH ADR-006, §2.3].

REST endpoints for the operator-in-the-loop incident confirmation flow.
Created as a separate router module -- main.py includes it via
``app.include_router``, preserving the existing M0/M1 code untouched.

Confirm/reject actions publish the corresponding Avro event onto the bus
so downstream services (dispatch, routing, corridor engine) can react,
and update the ``incident`` table in Postgres.  Rejections also feed the
fused_score back into the ``conformal_calibration`` table -- the online
recalibration loop described in the M6 planning document §10.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from itms_common.bus import RedisStreamsBus
from itms_common.events import encode_envelope

log = logging.getLogger("api-service.incidents")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://itms:itms@localhost:5432/itms"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])


# ---- request bodies ----

class ConfirmRequest(BaseModel):
    confirmed_by: str = "operator"
    severity: str = "unknown"


class RejectRequest(BaseModel):
    reason: str | None = None


# ---- helpers ----

def _row_to_dict(cur, row) -> dict:
    columns = [desc[0] for desc in cur.description]
    d = dict(zip(columns, row))
    for k in ("detected_at", "confirmed_at", "resolved_at"):
        if isinstance(d.get(k), dt.datetime):
            d[k] = d[k].isoformat()
    return d


# ---- endpoints ----

@router.get("")
async def list_incidents(status: str | None = None, limit: int = 50):
    """List incidents, optionally filtered by status."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        if status:
            cur.execute(
                "SELECT candidate_id, incident_id, link_id, intersection_id, "
                "graph_score, fused_score, threshold, status, severity, "
                "detected_at, confirmed_at, features "
                "FROM incident WHERE status = %s "
                "ORDER BY detected_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute(
                "SELECT candidate_id, incident_id, link_id, intersection_id, "
                "graph_score, fused_score, threshold, status, severity, "
                "detected_at, confirmed_at, features "
                "FROM incident ORDER BY detected_at DESC LIMIT %s",
                (limit,),
            )
        rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    return {"incidents": rows, "count": len(rows)}


@router.get("/{candidate_id}")
async def get_incident(candidate_id: str):
    """Detail view for one incident candidate."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM incident WHERE candidate_id = %s",
            (candidate_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"Candidate {candidate_id} not found")
        return _row_to_dict(cur, row)


@router.post("/{candidate_id}/confirm")
async def confirm_incident(candidate_id: str, req: ConfirmRequest):
    """Operator confirms a candidate → publish IncidentDetected."""
    incident_id = str(uuid.uuid4())
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE incident SET status = 'detected', incident_id = %s, "
            "confirmed_by = %s, severity = %s, confirmed_at = NOW() "
            "WHERE candidate_id = %s AND status = 'candidate' "
            "RETURNING link_id, intersection_id",
            (incident_id, req.confirmed_by, req.severity, candidate_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                404, "Candidate not found or already processed"
            )
        conn.commit()
        link_id, intersection_id = row

    # Publish IncidentDetected event
    bus = RedisStreamsBus(REDIS_URL)
    try:
        raw = encode_envelope(
            event_type="IncidentDetected",
            source="api-service",
            payload={
                "incident_id": incident_id,
                "candidate_id": candidate_id,
                "link_id": link_id,
                "intersection_id": intersection_id,
                "confirmed_by": req.confirmed_by,
                "severity": req.severity,
            },
            partition_key=link_id,
        )
        await bus.publish("incident.detected", raw)
    finally:
        await bus.close()

    return {"incident_id": incident_id, "status": "detected"}


@router.post("/{candidate_id}/reject")
async def reject_incident(candidate_id: str, req: RejectRequest):
    """Operator rejects → publish IncidentUpdated, feed back to calibration."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT fused_score, link_id FROM incident "
            "WHERE candidate_id = %s AND status = 'candidate'",
            (candidate_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                404, "Candidate not found or already processed"
            )
        fused_score, link_id = row

        cur.execute(
            "UPDATE incident SET status = 'rejected', resolved_at = NOW() "
            "WHERE candidate_id = %s",
            (candidate_id,),
        )

        # Feed back to conformal calibration set -- the online
        # recalibration loop (M6 plan §10).
        if fused_score is not None:
            cur.execute(
                "INSERT INTO conformal_calibration "
                "(link_id, fused_score, demand_level, source) "
                "VALUES (%s, %s, 'unknown', 'online_rejection')",
                (link_id, fused_score),
            )
        conn.commit()

    # Publish IncidentUpdated event
    bus = RedisStreamsBus(REDIS_URL)
    try:
        raw = encode_envelope(
            event_type="IncidentUpdated",
            source="api-service",
            payload={
                "incident_id": "",
                "candidate_id": candidate_id,
                "new_status": "rejected",
                "reason": req.reason,
            },
            partition_key=candidate_id,
        )
        await bus.publish("incident.updated", raw)
    finally:
        await bus.close()

    return {"candidate_id": candidate_id, "status": "rejected"}

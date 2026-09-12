"""Conformal-calibrated incident gate [M6 plan §10].

Checks whether a fused anomaly score exceeds the conformal threshold τ,
persists the candidate into the ``incident`` table, and publishes the
appropriate lifecycle event onto the bus.

The three public methods map 1-to-1 onto the incident state machine:
  check_and_raise  →  candidate  (new row, status='candidate')
  confirm          →  detected   (status='detected', IncidentDetected event)
  reject           →  rejected   (status='rejected', IncidentUpdated event,
                                  score fed back to conformal calibration)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import psycopg

from itms_common.events import encode_envelope

log = logging.getLogger("incident-service.gate")


class IncidentGate:
    def __init__(self, calibrator, db_url: str, bus):
        self.calibrator = calibrator
        self.db_url = db_url
        self.bus = bus

    async def check_and_raise(
        self,
        link_id: str,
        graph_score: float,
        fused_score: float,
        features: dict,
        signal_phase: str | None,
        intersection_id: str | None = None,
    ) -> str | None:
        """If fused_score > τ, publish IncidentCandidate and persist."""
        if self.calibrator is None:
            return None
        threshold = self.calibrator.threshold
        if fused_score <= threshold:
            return None

        candidate_id = str(uuid.uuid4())

        # Persist to Postgres
        with psycopg.connect(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO incident "
                "(candidate_id, link_id, intersection_id, graph_score, "
                " fused_score, threshold, status, features) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'candidate', %s)",
                (
                    candidate_id,
                    link_id,
                    intersection_id,
                    graph_score,
                    fused_score,
                    threshold,
                    json.dumps(features),
                ),
            )
            conn.commit()

        # Publish IncidentCandidate event
        # Convert feature values to float for Avro map<string, float>
        features_map = {
            k: float(v) for k, v in features.items()
            if isinstance(v, (int, float))
        }

        raw = encode_envelope(
            event_type="IncidentCandidate",
            source="incident-service",
            payload={
                "candidate_id": candidate_id,
                "link_id": link_id,
                "intersection_id": intersection_id,
                "graph_score": float(graph_score),
                "vision_score": None,
                "fused_score": float(fused_score),
                "threshold": float(threshold),
                "signal_phase": signal_phase,
                "features": features_map,
                "confidence": 1.0,
            },
            partition_key=link_id,
        )
        await self.bus.publish("incident.candidate", raw)

        log.info(
            "raised incident candidate %s on %s (fused=%.3f > τ=%.3f)",
            candidate_id, link_id, fused_score, threshold,
        )
        return candidate_id

    async def confirm(
        self,
        candidate_id: str,
        confirmed_by: str = "operator",
        severity: str = "unknown",
    ) -> str:
        """Operator confirms → publish IncidentDetected, update DB."""
        incident_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        with psycopg.connect(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE incident SET incident_id = %s, status = 'detected', "
                "confirmed_by = %s, severity = %s, confirmed_at = %s "
                "WHERE candidate_id = %s "
                "RETURNING link_id, intersection_id",
                (incident_id, confirmed_by, severity, now, candidate_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Candidate {candidate_id} not found")
            link_id, intersection_id = row
            conn.commit()

        raw = encode_envelope(
            event_type="IncidentDetected",
            source="incident-service",
            payload={
                "incident_id": incident_id,
                "candidate_id": candidate_id,
                "link_id": link_id,
                "intersection_id": intersection_id,
                "confirmed_by": confirmed_by,
                "severity": severity,
            },
            partition_key=link_id,
        )
        await self.bus.publish("incident.detected", raw)
        return incident_id

    async def reject(
        self, candidate_id: str, reason: str | None = None
    ) -> None:
        """Operator rejects → feed back to calibration, publish update."""
        now = datetime.now(timezone.utc)

        with psycopg.connect(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE incident SET status = 'rejected', resolved_at = %s "
                "WHERE candidate_id = %s "
                "RETURNING incident_id, fused_score, link_id",
                (now, candidate_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Candidate {candidate_id} not found")
            incident_id, fused_score, link_id = row

            # Feed back to conformal calibration set
            if fused_score is not None:
                cur.execute(
                    "INSERT INTO conformal_calibration "
                    "(link_id, fused_score, demand_level, source) "
                    "VALUES (%s, %s, 'unknown', 'online_rejection')",
                    (link_id, fused_score),
                )
            conn.commit()

        # Online recalibration
        if self.calibrator is not None and fused_score is not None:
            self.calibrator.update(fused_score)

        raw = encode_envelope(
            event_type="IncidentUpdated",
            source="incident-service",
            payload={
                "incident_id": incident_id or "",
                "candidate_id": candidate_id,
                "new_status": "rejected",
                "reason": reason,
            },
            partition_key=candidate_id,
        )
        await self.bus.publish("incident.updated", raw)

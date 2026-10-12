"""Payload shapes for the three M6 incident events, matching
`contracts/events/incident_*.avsc` field-for-field -- shared, not owned by
either service that publishes them.

Two different processes construct these payloads: `sim-service` (raising
candidates, via `IncidentPublisher` in `sim_service/control/anomaly/events.py`,
which imports this module rather than redefining it -- see that module for
why it's now a thin re-export) and `api-service` (confirming/rejecting them,
per ADR-006's human gate -- `api_gateway/services/incident_registry.py`). Both need the exact
same field mapping; a hand-copied second version drifting from this one the
moment a schema changes is exactly the kind of contract bug ADR-001 exists to
prevent. This module has no dependency on either service, or on any bus
implementation -- `candidate_payload`/`detected_payload`/`updated_payload`
are pure functions of an `Incident`, so a sync producer (`RedisStreamsSyncBus`)
and an async one (`RedisStreamsBus`) both encode-and-publish the identical
dict; only the publish call itself differs, and that's each caller's own
business, not this module's.
"""

from __future__ import annotations

from collections.abc import Mapping

from itms_domain.incident import Incident, IncidentAction, IncidentState

CANDIDATE_TOPIC = "incident.candidate"
DETECTED_TOPIC = "incident.detected"
UPDATED_TOPIC = "incident.updated"

_STATE_TO_SYMBOL: Mapping[IncidentState, str] = {
    IncidentState.CANDIDATE: "CANDIDATE",
    IncidentState.CONFIRMED: "CONFIRMED",
    IncidentState.REJECTED: "REJECTED",
    IncidentState.EXPIRED: "EXPIRED",
    IncidentState.CLEARED: "CLEARED",
}


def candidate_payload(inc: Incident, *, sim_tick: int | None = None) -> dict:
    """Matches incident_candidate.avsc. Call on a freshly raised CANDIDATE."""
    return {
        "incident_id": inc.incident_id,
        "detected_at": inc.first_seen_ms,
        "sim_tick": sim_tick,
        "intersection_id": inc.intersection_id,
        "link_id": inc.link_id,
        "graph_score": float(inc.graph_score),
        "vision_score": None if inc.vision_score is None else float(inc.vision_score),
        "fused_probability": float(inc.fused_probability),
        "threshold_tau": float(inc.threshold_tau),
        "false_alarm_budget": float(inc.false_alarm_budget),
        "detector_version": inc.detector_version,
    }


def detected_payload(inc: Incident, *, confirmed_at_ms: int | None = None) -> dict:
    """Matches incident_detected.avsc. Call after a CONFIRM transition."""
    confirm = next(
        (t for t in reversed(inc.history) if t.action is IncidentAction.CONFIRM), None
    )
    if confirm is None:
        raise ValueError("detected_payload called on an incident that was never confirmed")
    return {
        "incident_id": inc.incident_id,
        "confirmed_at": confirmed_at_ms if confirmed_at_ms is not None else confirm.at_ms,
        "candidate_detected_at": inc.first_seen_ms,
        "confirmed_by": confirm.actor,
        "intersection_id": inc.intersection_id,
        "link_id": inc.link_id,
        "classification": inc.classification.name,
        "graph_score": float(inc.graph_score),
        "vision_score": None if inc.vision_score is None else float(inc.vision_score),
        "fused_probability": float(inc.fused_probability),
        "chain_hash": inc.chain_head,
    }


def updated_payload(inc: Incident, *, sim_tick: int | None = None) -> dict:
    """Matches incident_updated.avsc. Call after any non-first, non-confirm
    transition (reject / expire / refresh / clear); reads the last history
    entry for the actor and detail."""
    last = inc.history[-1]
    refreshed = last.action is IncidentAction.REFRESH
    return {
        "incident_id": inc.incident_id,
        "updated_at": last.at_ms,
        "sim_tick": sim_tick,
        "new_state": _STATE_TO_SYMBOL[inc.state],
        "actor": last.actor,
        "detail": last.detail,
        "fused_probability": float(inc.fused_probability) if refreshed else None,
        "chain_hash": inc.chain_head,
    }

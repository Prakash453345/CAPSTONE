"""Turn an `itms_domain.incident.Incident` transition into a bus event that
matches `contracts/events/incident_*.avsc` field-for-field, and publish it --
the same encode-and-publish shape `runner._publish_decision_events` uses for
signal events.

The domain layer owns the incident rules and the hash chain; this module is
the (thin) bridge from a transition to the wire. Kept out of the domain
package because that package has no dependency on `contracts/`.
"""

from __future__ import annotations

from collections.abc import Iterable

from itms_common.bus import RedisStreamsSyncBus
from itms_common.events import encode_envelope
from itms_domain.incident import Incident, IncidentAction, IncidentState

CANDIDATE_TOPIC = "incident.candidate"
DETECTED_TOPIC = "incident.detected"
UPDATED_TOPIC = "incident.updated"

_STATE_TO_SYMBOL = {
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


class IncidentPublisher:
    """Encode-and-publish for the three incident events. Wraps a
    `RedisStreamsSyncBus`; `partition_key` is the intersection id so all of an
    incident's events stay ordered on one partition."""

    def __init__(self, bus: RedisStreamsSyncBus, *, source: str = "sim-service"):
        self._bus = bus
        self._source = source

    def _publish(self, topic: str, event_type: str, payload: dict, key: str) -> str:
        return self._bus.publish(
            topic,
            encode_envelope(
                event_type=event_type, source=self._source, payload=payload, partition_key=key
            ),
        )

    def candidate(self, inc: Incident, *, sim_tick: int | None = None) -> str:
        return self._publish(
            CANDIDATE_TOPIC, "IncidentCandidate",
            candidate_payload(inc, sim_tick=sim_tick), inc.intersection_id,
        )

    def detected(self, inc: Incident, *, confirmed_at_ms: int | None = None) -> str:
        return self._publish(
            DETECTED_TOPIC, "IncidentDetected",
            detected_payload(inc, confirmed_at_ms=confirmed_at_ms), inc.intersection_id,
        )

    def updated(self, inc: Incident, *, sim_tick: int | None = None) -> str:
        return self._publish(
            UPDATED_TOPIC, "IncidentUpdated",
            updated_payload(inc, sim_tick=sim_tick), inc.intersection_id,
        )

    def publish_all(self, incidents: Iterable[Incident], *, sim_tick: int | None = None) -> int:
        n = 0
        for inc in incidents:
            self.candidate(inc, sim_tick=sim_tick)
            n += 1
        return n

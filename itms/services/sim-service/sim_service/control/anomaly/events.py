"""Publish an `itms_domain.incident.Incident` transition onto the bus as a
real event -- the same encode-and-publish shape `runner._publish_decision_events`
uses for signal events.

The payload field mapping itself (`candidate_payload`/`detected_payload`/
`updated_payload`, matching `contracts/events/incident_*.avsc`) now lives in
`itms_common.incident_events`, re-exported here unchanged: `api-service`
needs the exact same mapping to publish `IncidentDetected`/`IncidentUpdated`
from its own confirm/reject endpoints (ADR-006's human gate), and sim-service
can't be a dependency of api-service, so the shared logic moved to the one
package both already depend on rather than being hand-copied a second time.
See that module's docstring for the full reasoning. `IncidentPublisher`
itself stays here: it's a synchronous convenience wrapper around
`RedisStreamsSyncBus`, the transport sim-service's per-tick loop uses --
api-service's async bus needs its own await-based publish call, which is
`api_service/incidents.py`'s business, not this module's.

The domain layer owns the incident rules and the hash chain; this module (and
`itms_common.incident_events`) is the (thin) bridge from a transition to the
wire. Kept out of the domain package because that package has no dependency
on `contracts/`.
"""

from __future__ import annotations

from collections.abc import Iterable

from itms_common.bus import RedisStreamsSyncBus
from itms_common.events import encode_envelope
from itms_common.incident_events import (
    CANDIDATE_TOPIC,
    DETECTED_TOPIC,
    UPDATED_TOPIC,
    candidate_payload,
    detected_payload,
    updated_payload,
)
from itms_domain.incident import Incident

__all__ = [
    "CANDIDATE_TOPIC",
    "DETECTED_TOPIC",
    "UPDATED_TOPIC",
    "candidate_payload",
    "detected_payload",
    "updated_payload",
    "IncidentPublisher",
]


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

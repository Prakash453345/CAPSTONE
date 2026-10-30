"""The human-in-the-loop incident registry -- api-service's side of the M6
pipeline (ADR-006's human gate). `sim-service`'s `LiveIncidentDetector`
raises candidates and publishes `IncidentCandidate` events; nothing else in
the system may confirm or reject one. This module is the "human" half: an
in-memory read model built by replaying the `incident.*` bus topics, plus
the two mutating actions (`confirm`/`reject`) this service's REST endpoints
call.

Rebuilding, not just recording: `Incident.raise_candidate`/`Incident.apply`
(`packages/domain/itms_domain/incident.py`) are pure functions of their
inputs, so replaying a candidate event's exact fields through
`raise_candidate` reproduces the exact same SHA-256 genesis hash
sim-service's own `Incident` object has -- api-service never receives that
object itself, only the event, and this is what lets it apply further
transitions and publish an event whose `chain_hash` traces back to
sim-service's original chain. (Confirmed by round-tripping a real event
through encode/decode: the reconstructed `chain_head` matches bit for bit.)

Idempotency: every `IncidentDetected`/`IncidentUpdated` event carries the
resulting `chain_hash`. `apply_event` compares it against the registry's
current `chain_head` for that incident and skips re-applying a transition
already reflected there -- which is exactly what happens when this
service's own confirm/reject endpoint mutates the registry directly *and*
the same event it just published arrives back through `consume_forever`
moments later (this is a single process today, but the check is what makes
replaying the stream from scratch, or running a second replica, safe too).
"""

from __future__ import annotations

import logging

from itms_common.incident_events import detected_payload, updated_payload
from itms_domain.incident import (
    IllegalTransition,
    Incident,
    IncidentAction,
    IncidentClass,
    IncidentState,
)

log = logging.getLogger("api-service.incidents")

# Only `IncidentUpdated` ever names IncidentState.CONFIRMED as `new_state`
# (a REFRESH, incident ongoing) -- the *first* CONFIRM always arrives as an
# `IncidentDetected` event instead, handled separately in `_on_detected`.
_ACTION_FOR_NEW_STATE: dict[IncidentState, IncidentAction] = {
    IncidentState.CONFIRMED: IncidentAction.REFRESH,
    IncidentState.REJECTED: IncidentAction.REJECT,
    IncidentState.EXPIRED: IncidentAction.EXPIRE,
    IncidentState.CLEARED: IncidentAction.CLEAR,
}


def _ms(value) -> int:
    """`decode_envelope` turns a timestamp-millis field into a `datetime`;
    convert back to the integer milliseconds `Incident` fields are in."""
    return int(value.timestamp() * 1000)


class IncidentRegistry:
    """`incident_id -> Incident`, kept current by replaying the bus (via
    `apply_event`, called from `consume_forever` for every `incident.*`
    event) and by this service's own confirm/reject endpoints, which call
    `confirm`/`reject` directly for an immediate, consistent HTTP response,
    then publish the resulting event for any other consumer -- including
    this same registry, idempotently, when it comes back around."""

    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}

    def __len__(self) -> int:
        return len(self._incidents)

    def get(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    def all(self) -> list[Incident]:
        return list(self._incidents.values())

    # ---- replay from the bus ---------------------------------------

    def apply_event(self, event_type: str, payload: dict) -> Incident | None:
        """Fold one decoded `incident.*` event into the registry. Returns
        the resulting `Incident`, or None if the event was ignored (an
        unknown incident_id for a non-candidate event, an out-of-order
        transition, or one already applied)."""
        if event_type == "IncidentCandidate":
            return self._on_candidate(payload)
        if event_type == "IncidentDetected":
            return self._on_detected(payload)
        if event_type == "IncidentUpdated":
            return self._on_updated(payload)
        return None

    def _on_candidate(self, payload: dict) -> Incident:
        inc = Incident.raise_candidate(
            incident_id=payload["incident_id"],
            link_id=payload["link_id"],
            intersection_id=payload["intersection_id"],
            at_ms=_ms(payload["detected_at"]),
            graph_score=payload["graph_score"],
            fused_probability=payload["fused_probability"],
            threshold_tau=payload["threshold_tau"],
            vision_score=payload["vision_score"],
            false_alarm_budget=payload["false_alarm_budget"],
            detector_version=payload["detector_version"],
        )
        self._incidents[inc.incident_id] = inc
        log.info("incident candidate registered: %s (%s)", inc.incident_id, inc.intersection_id)
        return inc

    def _on_detected(self, payload: dict) -> Incident | None:
        current = self._incidents.get(payload["incident_id"])
        if current is None:
            log.warning(
                "IncidentDetected for unknown incident %s -- no candidate seen yet",
                payload["incident_id"],
            )
            return None
        if current.chain_head == payload["chain_hash"]:
            return current  # already applied -- this service's own confirm() did it
        try:
            updated = current.apply(
                IncidentAction.CONFIRM,
                at_ms=_ms(payload["confirmed_at"]),
                actor=payload["confirmed_by"],
                classification=IncidentClass[payload["classification"]],
                graph_score=payload["graph_score"],
                vision_score=payload["vision_score"],
                fused_probability=payload["fused_probability"],
                detail=payload.get("detail", ""),
            )
        except IllegalTransition:
            log.warning(
                "out-of-order IncidentDetected for %s (currently %s) -- ignoring",
                payload["incident_id"], current.state.value,
            )
            return None
        self._incidents[updated.incident_id] = updated
        return updated

    def _on_updated(self, payload: dict) -> Incident | None:
        current = self._incidents.get(payload["incident_id"])
        if current is None:
            log.warning(
                "IncidentUpdated for unknown incident %s -- no candidate seen yet",
                payload["incident_id"],
            )
            return None
        if current.chain_head == payload["chain_hash"]:
            return current
        new_state = IncidentState[payload["new_state"]]
        action = _ACTION_FOR_NEW_STATE.get(new_state)
        if action is None:
            log.warning("IncidentUpdated with unrecognized new_state %r", payload["new_state"])
            return None
        try:
            updated = current.apply(
                action,
                at_ms=_ms(payload["updated_at"]),
                actor=payload["actor"],
                detail=payload["detail"],
                fused_probability=payload["fused_probability"],
            )
        except IllegalTransition:
            log.warning(
                "out-of-order IncidentUpdated for %s (currently %s) -- ignoring",
                payload["incident_id"], current.state.value,
            )
            return None
        self._incidents[updated.incident_id] = updated
        return updated

    # ---- operator actions (called by the confirm/reject endpoints) ----

    def confirm(
        self,
        incident_id: str,
        *,
        at_ms: int,
        actor: str,
        classification: IncidentClass,
        detail: str = "",
    ) -> Incident:
        """Raises `KeyError` for an unknown id, `IllegalTransition` (from
        `Incident.apply`) if it isn't currently a CANDIDATE -- both are the
        caller's (the HTTP endpoint's) job to translate into a 404/409."""
        current = self._require(incident_id)
        updated = current.apply(
            IncidentAction.CONFIRM,
            at_ms=at_ms,
            actor=actor,
            classification=classification,
            detail=detail,
        )
        self._incidents[incident_id] = updated
        return updated

    def reject(self, incident_id: str, *, at_ms: int, actor: str, detail: str = "") -> Incident:
        current = self._require(incident_id)
        updated = current.apply(IncidentAction.REJECT, at_ms=at_ms, actor=actor, detail=detail)
        self._incidents[incident_id] = updated
        return updated

    def _require(self, incident_id: str) -> Incident:
        current = self._incidents.get(incident_id)
        if current is None:
            raise KeyError(incident_id)
        return current


def incident_to_json(inc: Incident) -> dict:
    """A plain-JSON summary for the REST endpoints -- not the full hash-chain
    history (that's an audit-trail detail, not something a dashboard needs
    on every poll); `chain_head` alone lets a caller check they're looking
    at the current tip."""
    return {
        "incident_id": inc.incident_id,
        "link_id": inc.link_id,
        "intersection_id": inc.intersection_id,
        "state": inc.state.value,
        "classification": inc.classification.value,
        "first_seen_ms": inc.first_seen_ms,
        "graph_score": inc.graph_score,
        "vision_score": inc.vision_score,
        "fused_probability": inc.fused_probability,
        "threshold_tau": inc.threshold_tau,
        "detector_version": inc.detector_version,
        "chain_head": inc.chain_head,
        "confirmation_latency_ms": inc.confirmation_latency_ms(),
    }


async def publish_detected(bus, inc: Incident, *, confirmed_at_ms: int | None = None) -> None:
    """Encode-and-publish `IncidentDetected` on the async bus api-service
    uses. `IncidentPublisher` (sim_service.control.anomaly.events) is the
    sync equivalent for sim-service's own producer -- kept separate because
    the two buses' `publish` calls are sync vs. async, not because the
    payload shape differs (it's the same `itms_common.incident_events`
    functions either way)."""
    from itms_common.events import encode_envelope
    from itms_common.incident_events import DETECTED_TOPIC

    raw = encode_envelope(
        event_type="IncidentDetected",
        source="api-service",
        payload=detected_payload(inc, confirmed_at_ms=confirmed_at_ms),
        partition_key=inc.intersection_id,
    )
    await bus.publish(DETECTED_TOPIC, raw)


async def publish_updated(bus, inc: Incident, *, sim_tick: int | None = None) -> None:
    """Encode-and-publish `IncidentUpdated` -- see `publish_detected`."""
    from itms_common.events import encode_envelope
    from itms_common.incident_events import UPDATED_TOPIC

    raw = encode_envelope(
        event_type="IncidentUpdated",
        source="api-service",
        payload=updated_payload(inc, sim_tick=sim_tick),
        partition_key=inc.intersection_id,
    )
    await bus.publish(UPDATED_TOPIC, raw)

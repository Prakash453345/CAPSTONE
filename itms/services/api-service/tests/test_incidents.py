"""`IncidentRegistry` -- the human-in-the-loop read model + operator actions
(ADR-006). No bus, no HTTP: pure logic, exercised the same way an event
actually arrives (round-tripped through the real Avro schemas via
`encode_envelope`/`decode_envelope`), so a schema/field-name mismatch would
fail here exactly as it would in production."""

from __future__ import annotations

from api_service.incidents import IncidentRegistry, incident_to_json
from itms_common.events import decode_envelope, encode_envelope
from itms_common.incident_events import (
    CANDIDATE_TOPIC,
    detected_payload,
    updated_payload,
)
from itms_domain.incident import (
    IllegalTransition,
    Incident,
    IncidentAction,
    IncidentClass,
    IncidentState,
)


def _candidate_event(incident_id: str = "inc-1") -> dict:
    """A real IncidentCandidate envelope, decoded exactly as `consume_forever`
    would see it -- `detected_at` comes back as a `datetime`, not the
    original int ms, which is exactly the wrinkle `IncidentRegistry` has to
    handle."""
    inc = Incident.raise_candidate(
        incident_id=incident_id,
        link_id="L4",
        intersection_id="J3",
        at_ms=1_725_600_123_456,
        graph_score=6.1,
        fused_probability=0.94,
        threshold_tau=0.80,
        detector_version="graph-ae@abcd1234/conformal@deadbeef",
    )
    from itms_common.incident_events import candidate_payload

    raw = encode_envelope(
        event_type="IncidentCandidate",
        source="sim-service",
        payload=candidate_payload(inc, sim_tick=42),
        partition_key="J3",
    )
    return decode_envelope(raw)


def test_on_candidate_registers_a_matching_incident():
    reg = IncidentRegistry()
    env = _candidate_event()
    inc = reg.apply_event(env["event_type"], env["payload"])
    assert inc is not None
    assert inc.incident_id == "inc-1"
    assert inc.state is IncidentState.CANDIDATE
    assert inc.link_id == "L4"
    assert inc.intersection_id == "J3"
    assert inc.first_seen_ms == 1_725_600_123_456
    assert reg.get("inc-1") is inc
    assert len(reg) == 1


def test_confirm_transitions_to_confirmed_and_records_classification():
    reg = IncidentRegistry()
    env = _candidate_event()
    reg.apply_event(env["event_type"], env["payload"])

    updated = reg.confirm(
        "inc-1", at_ms=123, actor="op-1",
        classification=IncidentClass.STALL, detail="checked camera",
    )
    assert updated.state is IncidentState.CONFIRMED
    assert updated.classification is IncidentClass.STALL
    assert reg.get("inc-1") is updated


def test_confirm_unknown_id_raises_keyerror():
    reg = IncidentRegistry()
    try:
        reg.confirm("nope", at_ms=1, actor="op-1", classification=IncidentClass.UNKNOWN)
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


def test_confirm_twice_raises_illegal_transition():
    reg = IncidentRegistry()
    env = _candidate_event()
    reg.apply_event(env["event_type"], env["payload"])
    reg.confirm("inc-1", at_ms=1, actor="op-1", classification=IncidentClass.STALL)
    try:
        reg.confirm("inc-1", at_ms=2, actor="op-1", classification=IncidentClass.STALL)
        raise AssertionError("expected IllegalTransition")
    except IllegalTransition:
        pass


def test_reject_transitions_to_rejected():
    reg = IncidentRegistry()
    env = _candidate_event()
    reg.apply_event(env["event_type"], env["payload"])
    updated = reg.reject("inc-1", at_ms=5, actor="op-2", detail="false alarm")
    assert updated.state is IncidentState.REJECTED


def test_replaying_own_confirm_event_is_idempotent():
    """The exact scenario that happens in production: the confirm endpoint
    mutates the registry directly, publishes IncidentDetected, and that same
    event streams back through consume_forever moments later. It must not
    raise or double-apply."""
    reg = IncidentRegistry()
    env = _candidate_event()
    reg.apply_event(env["event_type"], env["payload"])
    confirmed = reg.confirm("inc-1", at_ms=999, actor="op-1", classification=IncidentClass.STALL)

    raw = encode_envelope(
        event_type="IncidentDetected",
        source="api-service",
        payload=detected_payload(confirmed, confirmed_at_ms=999),
        partition_key="J3",
    )
    echoed = decode_envelope(raw)
    result = reg.apply_event(echoed["event_type"], echoed["payload"])
    assert result is confirmed
    assert reg.get("inc-1").state is IncidentState.CONFIRMED


def test_replaying_a_detected_event_for_an_unknown_incident_is_ignored():
    reg = IncidentRegistry()
    inc = Incident.raise_candidate(
        incident_id="ghost", link_id="L1", intersection_id="J1", at_ms=1,
        graph_score=5.0, fused_probability=0.9, threshold_tau=0.5,
    ).apply(
        IncidentAction.CONFIRM, at_ms=2, actor="op", classification=IncidentClass.STALL,
    )
    raw = encode_envelope(
        event_type="IncidentDetected", source="api-service",
        payload=detected_payload(inc), partition_key="J1",
    )
    env = decode_envelope(raw)
    result = reg.apply_event(env["event_type"], env["payload"])
    assert result is None
    assert reg.get("ghost") is None


def test_replaying_a_reject_event_from_another_writer_applies_it():
    """A different writer (e.g. another api-service replica) rejected the
    incident; this registry only saw the candidate. Replaying the resulting
    IncidentUpdated must fold the rejection in."""
    reg = IncidentRegistry()
    env = _candidate_event()
    candidate = reg.apply_event(env["event_type"], env["payload"])
    assert candidate is not None
    rejected_elsewhere = candidate.apply(
        IncidentAction.REJECT, at_ms=77, actor="other-replica", detail="dup",
    )
    raw = encode_envelope(
        event_type="IncidentUpdated", source="api-service",
        payload=updated_payload(rejected_elsewhere), partition_key="J3",
    )
    env2 = decode_envelope(raw)
    result = reg.apply_event(env2["event_type"], env2["payload"])
    assert result is not None
    assert result.state is IncidentState.REJECTED
    assert reg.get("inc-1").state is IncidentState.REJECTED


def test_incident_to_json_shape():
    reg = IncidentRegistry()
    env = _candidate_event()
    inc = reg.apply_event(env["event_type"], env["payload"])
    out = incident_to_json(inc)
    assert out["incident_id"] == "inc-1"
    assert out["state"] == "candidate"
    assert out["chain_head"] == inc.chain_head
    assert out["confirmation_latency_ms"] is None


def test_candidate_topic_constant_matches_schema_topic_name():
    assert CANDIDATE_TOPIC == "incident.candidate"

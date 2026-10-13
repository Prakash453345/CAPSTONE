"""Incident event payload builders + `IncidentPublisher`. The payload builders
are checked by round-tripping through the real Avro schemas."""

from __future__ import annotations

from datetime import datetime

import pytest
from itms_common.events import decode_envelope
from itms_domain.incident import Incident, IncidentAction, IncidentClass
from sim_service.control.anomaly.events import (
    CANDIDATE_TOPIC,
    DETECTED_TOPIC,
    UPDATED_TOPIC,
    IncidentPublisher,
    candidate_payload,
    detected_payload,
    updated_payload,
)


def _candidate() -> Incident:
    return Incident.raise_candidate(
        incident_id="inc-9",
        link_id="L4",
        intersection_id="J3",
        at_ms=1_725_600_000_000,
        graph_score=6.1,
        fused_probability=0.94,
        threshold_tau=0.80,
        detector_version="graph-ae@abcd1234",
    )


class _FakeBus:
    def __init__(self):
        self.published: list[tuple[str, bytes]] = []

    def publish(self, topic: str, raw: bytes) -> str:
        self.published.append((topic, raw))
        return f"id-{len(self.published)}"


# ---- payload builders roundtrip through the schemas -----------------


def _roundtrip(event_type: str, payload: dict) -> dict:
    from itms_common.events import encode_envelope

    return decode_envelope(
        encode_envelope(event_type=event_type, source="pytest", payload=payload)
    )["payload"]


def test_candidate_payload_matches_schema():
    p = candidate_payload(_candidate(), sim_tick=1234)
    out = _roundtrip("IncidentCandidate", p)
    assert out["incident_id"] == "inc-9"
    assert out["link_id"] == "L4"
    assert out["sim_tick"] == 1234
    assert out["vision_score"] is None
    assert out["graph_score"] == pytest.approx(6.1)
    assert isinstance(out["detected_at"], datetime)


def test_detected_payload_after_confirmation():
    inc = _candidate().apply(
        IncidentAction.CONFIRM, at_ms=1_725_600_030_000, actor="operator:sam",
        classification=IncidentClass.STALL,
    )
    p = detected_payload(inc)
    out = _roundtrip("IncidentDetected", p)
    assert out["confirmed_by"] == "operator:sam"
    assert out["classification"] == "STALL"
    assert out["chain_hash"] == inc.chain_head
    assert isinstance(out["candidate_detected_at"], datetime)


def test_detected_payload_rejects_an_unconfirmed_incident():
    with pytest.raises(ValueError):
        detected_payload(_candidate())


def test_updated_payload_for_a_rejection_has_no_probability():
    inc = _candidate().apply(
        IncidentAction.REJECT, at_ms=1_725_600_020_000, actor="operator:sam",
        detail="recurring queue",
    )
    out = _roundtrip("IncidentUpdated", updated_payload(inc))
    assert out["new_state"] == "REJECTED"
    assert out["detail"] == "recurring queue"
    assert out["fused_probability"] is None


def test_updated_payload_for_a_score_refresh_carries_probability():
    inc = (
        _candidate()
        .apply(IncidentAction.CONFIRM, at_ms=2, actor="operator:sam")
        .apply(IncidentAction.REFRESH, at_ms=3, actor="detector", fused_probability=0.99)
    )
    out = _roundtrip("IncidentUpdated", updated_payload(inc, sim_tick=77))
    assert out["new_state"] == "CONFIRMED"
    assert out["fused_probability"] == pytest.approx(0.99)
    assert out["sim_tick"] == 77


# ---- IncidentPublisher --------------------------------------------


def test_publisher_sends_each_event_on_its_topic_keyed_by_intersection():
    bus = _FakeBus()
    pub = IncidentPublisher(bus)  # type: ignore[arg-type]
    inc = _candidate()
    pub.candidate(inc, sim_tick=10)
    inc = inc.apply(IncidentAction.CONFIRM, at_ms=5, actor="operator:sam")
    pub.detected(inc)
    inc = inc.apply(IncidentAction.CLEAR, at_ms=9, actor="operator:sam")
    pub.updated(inc, sim_tick=99)

    topics = [t for t, _ in bus.published]
    assert topics == [CANDIDATE_TOPIC, DETECTED_TOPIC, UPDATED_TOPIC]

    env0 = decode_envelope(bus.published[0][1])
    assert env0["event_type"] == "IncidentCandidate"
    assert env0["partition_key"] == "J3"
    assert env0["payload"]["link_id"] == "L4"

    env2 = decode_envelope(bus.published[2][1])
    assert env2["payload"]["new_state"] == "CLEARED"


def test_publish_all_emits_one_candidate_per_incident():
    bus = _FakeBus()
    pub = IncidentPublisher(bus)  # type: ignore[arg-type]
    incs = [
        Incident.raise_candidate(
            incident_id=f"inc-{i}", link_id=f"L{i}", intersection_id="J1",
            at_ms=1, graph_score=4.0, fused_probability=0.9, threshold_tau=0.8,
        )
        for i in range(3)
    ]
    assert pub.publish_all(incs, sim_tick=1) == 3
    assert all(t == CANDIDATE_TOPIC for t, _ in bus.published)

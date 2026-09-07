"""Roundtrip the three M6 incident schemas through the envelope encode/decode
path -- pure Avro, no Redis. Proves contracts/events/incident_*.avsc parse,
that the payload field names/types match what a producer will hand them, and
that the nullable/defaulted fields behave.

fastavro decodes a `timestamp-millis` logical type back to an aware
`datetime`, not the raw int it was given, so timestamp fields are compared
via `_epoch_millis` rather than by identity with the input dict.
"""

from __future__ import annotations

from datetime import UTC, datetime

from itms_common.events import decode_envelope, encode_envelope

_TS_FIELDS = frozenset(
    {"detected_at", "confirmed_at", "candidate_detected_at", "updated_at"}
)


def _epoch_millis(dt: datetime) -> int:
    return round(dt.replace(tzinfo=dt.tzinfo or UTC).timestamp() * 1000)


def _roundtrip(event_type: str, payload: dict) -> dict:
    decoded = decode_envelope(
        encode_envelope(event_type=event_type, source="pytest", payload=payload)
    )["payload"]
    for key, value in payload.items():
        if key in _TS_FIELDS:
            assert _epoch_millis(decoded[key]) == value, key
        else:
            assert decoded[key] == value, key
    return decoded


def test_incident_candidate_roundtrip_graph_only():
    payload = {
        "incident_id": "inc-abc123",
        "detected_at": 1_725_600_000_000,
        "sim_tick": 4213,
        "intersection_id": "J5",
        "link_id": "L2",
        "graph_score": 5.7,
        "vision_score": None,
        "fused_probability": 0.93,
        "threshold_tau": 0.81,
        "false_alarm_budget": 0.05,
        "detector_version": "graph-ae@9f2a/conformal@1b40",
    }
    env = decode_envelope(
        encode_envelope(
            event_type="IncidentCandidate",
            source="sim-service",
            payload=payload,
            partition_key="J5",
        )
    )
    assert env["event_type"] == "IncidentCandidate"
    assert env["partition_key"] == "J5"
    assert _epoch_millis(env["payload"]["detected_at"]) == payload["detected_at"]
    assert env["payload"]["graph_score"] == 5.7
    assert env["payload"]["vision_score"] is None


def test_incident_candidate_defaults_fill_in():
    decoded = decode_envelope(
        encode_envelope(
            event_type="IncidentCandidate",
            source="sim-service",
            payload={
                "incident_id": "inc-1",
                "detected_at": 1,
                "intersection_id": "J1",
                "link_id": "L0",
                "graph_score": 3.0,
                "fused_probability": 0.9,
                "threshold_tau": 0.8,
                "detector_version": "v1",
            },
        )
    )["payload"]
    assert decoded["sim_tick"] is None
    assert decoded["vision_score"] is None
    assert decoded["false_alarm_budget"] == 0.05


def test_incident_detected_roundtrip_with_enum_classification():
    decoded = _roundtrip(
        "IncidentDetected",
        {
            "incident_id": "inc-abc123",
            "confirmed_at": 1_725_600_030_000,
            "candidate_detected_at": 1_725_600_000_000,
            "confirmed_by": "operator:alice",
            "intersection_id": "J5",
            "link_id": "L2",
            "classification": "LANE_BLOCK",
            "graph_score": 5.7,
            "vision_score": None,
            "fused_probability": 0.95,
            "chain_hash": "a" * 64,
        },
    )
    assert decoded["classification"] == "LANE_BLOCK"


def test_incident_updated_roundtrip_rejection():
    decoded = _roundtrip(
        "IncidentUpdated",
        {
            "incident_id": "inc-abc123",
            "updated_at": 1_725_600_020_000,
            "sim_tick": None,
            "new_state": "REJECTED",
            "actor": "operator:bob",
            "detail": "recurring red-light queue, not an incident",
            "fused_probability": None,
            "chain_hash": "b" * 64,
        },
    )
    assert decoded["new_state"] == "REJECTED"
    assert decoded["fused_probability"] is None


def test_incident_updated_score_refresh_defaults():
    decoded = decode_envelope(
        encode_envelope(
            event_type="IncidentUpdated",
            source="sim-service",
            payload={
                "incident_id": "inc-1",
                "updated_at": 2,
                "new_state": "CONFIRMED",
                "actor": "detector",
                "fused_probability": 0.97,
                "chain_hash": "c" * 64,
            },
        )
    )["payload"]
    assert decoded["detail"] == ""
    assert decoded["sim_tick"] is None
    assert decoded["fused_probability"] == 0.97

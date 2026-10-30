"""`itms_domain.anomaly.Anomaly` -- the normalised anomaly model."""

from __future__ import annotations

import pytest
from itms_domain.anomaly import (
    Anomaly,
    AnomalySeverity,
    AnomalySource,
    AnomalyStatus,
    AnomalyType,
)


def _op_anomaly(**over) -> Anomaly:
    kw = dict(
        anomaly_id="an-1",
        source=AnomalySource.OPERATOR,
        anomaly_type=AnomalyType.LANE_BLOCKAGE,
        severity=AnomalySeverity.HIGH,
        edge_id="E42",
        at_ms=1_000,
        estimated_impact=0.7,
        operator="operator:sam",
    )
    kw.update(over)
    return Anomaly.create(**kw)


def test_create_makes_an_active_anomaly_starting_now():
    a = _op_anomaly(duration_s=600)
    assert a.status is AnomalyStatus.ACTIVE
    assert a.start_time_ms == a.created_at_ms == 1_000
    assert a.expires_at_ms() == 1_000 + 600_000
    assert not a.is_terminal


def test_open_ended_anomaly_never_expires_on_its_own():
    a = _op_anomaly(duration_s=None)
    assert a.expires_at_ms() is None
    assert a.is_active_at(10_000_000)


def test_time_boxed_anomaly_stops_being_active_after_its_duration():
    a = _op_anomaly(duration_s=30)
    assert a.is_active_at(1_000)
    assert a.is_active_at(1_000 + 29_000)
    assert not a.is_active_at(1_000 + 31_000)


def test_blocked_severity_flags_is_blocking():
    assert _op_anomaly(severity=AnomalySeverity.BLOCKED, estimated_impact=1.0).is_blocking
    assert not _op_anomaly(severity=AnomalySeverity.HIGH).is_blocking


def test_resolved_and_cancelled_are_terminal_and_idempotent():
    a = _op_anomaly()
    r = a.resolved(at_ms=5_000, reason="cleared by unit")
    assert r.status is AnomalyStatus.RESOLVED and r.is_terminal
    assert r.metadata["resolved_reason"] == "cleared by unit"
    assert not r.is_active_at(6_000)
    assert r.resolved(at_ms=9_000) is r  # already terminal -> unchanged

    c = a.cancelled(at_ms=4_000, reason="wrong edge")
    assert c.status is AnomalyStatus.CANCELLED and c.is_terminal
    assert c.metadata["cancelled_reason"] == "wrong edge"


def test_the_original_is_untouched_by_a_transition():
    a = _op_anomaly()
    a.resolved(at_ms=2_000)
    assert a.status is AnomalyStatus.ACTIVE


def test_impact_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        _op_anomaly(estimated_impact=1.5)
    with pytest.raises(ValueError):
        _op_anomaly(estimated_impact=-0.1)


def test_non_positive_duration_is_rejected():
    with pytest.raises(ValueError):
        _op_anomaly(duration_s=0)


def test_every_source_and_type_round_trips_as_a_string_enum():
    for src in AnomalySource:
        assert str(src) == src.value
    a = _op_anomaly(source=AnomalySource.GRAPH_MODEL, anomaly_type=AnomalyType.STALLED_VEHICLE)
    assert a.source == "graph_model" and a.anomaly_type == "stalled_vehicle"


def test_fire_is_a_type_the_vision_candidate_can_carry():
    assert AnomalyType.FIRE == "fire"
    a = _op_anomaly(source=AnomalySource.VISION, anomaly_type=AnomalyType.FIRE)
    assert a.anomaly_type == "fire"

"""`OperatorAnomalyController` -- operator anomalies applied to SUMO. TraCI is
monkeypatched (lane max-speed get/set), so no SUMO process."""

from __future__ import annotations

import pytest
from sim_service.live import anomaly_control as ac
from sim_service.live.anomaly_control import AnomalyImpactConfig, OperatorAnomalyController


class _FakeLanes:
    def __init__(self, edges: dict[str, int], speeds: dict[str, float]):
        self.lane_count = edges
        self.max_speed = speeds
        self.set_calls: list[tuple[str, float]] = []

    def getLaneNumber(self, edge_id: str) -> int:
        if edge_id not in self.lane_count:
            raise ac.traci.TraCIException(f"no edge {edge_id}")
        return self.lane_count[edge_id]

    def getMaxSpeed(self, lane_id: str) -> float:
        if lane_id not in self.max_speed:
            raise ac.traci.TraCIException(f"no lane {lane_id}")
        return self.max_speed[lane_id]

    def setMaxSpeed(self, lane_id: str, speed: float) -> None:
        self.set_calls.append((lane_id, speed))
        self.max_speed[lane_id] = speed


@pytest.fixture
def lanes(monkeypatch):
    fl = _FakeLanes(
        edges={"E1": 2, "E2": 1},
        speeds={"E1_0": 14.0, "E1_1": 14.0, "E2_0": 10.0},
    )
    monkeypatch.setattr(ac.traci.edge, "getLaneNumber", fl.getLaneNumber)
    monkeypatch.setattr(ac.traci.lane, "getMaxSpeed", fl.getMaxSpeed)
    monkeypatch.setattr(ac.traci.lane, "setMaxSpeed", fl.setMaxSpeed)
    return fl


def _create(**over):
    p = dict(
        anomaly_id="an-1",
        edge_id="E1",
        anomaly_type="LANE_BLOCKAGE",
        severity="HIGH",
        requested_at=1_000_000,
        operator="operator:sam",
    )
    p.update(over)
    return p


def test_high_severity_reduces_every_lane_of_the_edge(lanes):
    c = OperatorAnomalyController()
    c.handle_create(_create(severity="HIGH"), step=10, sim_time_s=10.0)
    # keep-frac for HIGH is 0.20 -> 14.0 * 0.2 = 2.8 on both lanes of E1
    assert lanes.max_speed["E1_0"] == pytest.approx(2.8)
    assert lanes.max_speed["E1_1"] == pytest.approx(2.8)
    assert [a.anomaly_id for a in c.active_anomalies()] == ["an-1"]


def test_blocked_severity_crawls_the_lane_regardless_of_original(lanes):
    c = OperatorAnomalyController()
    c.handle_create(_create(severity="BLOCKED"), step=5, sim_time_s=5.0)
    assert lanes.max_speed["E1_0"] == pytest.approx(0.1)
    a = c.active_anomalies()[0]
    assert a.is_blocking and a.estimated_impact == 1.0


def test_lane_id_targets_just_that_lane(lanes):
    c = OperatorAnomalyController()
    c.handle_create(_create(lane_id="E1_1", severity="MEDIUM"), step=1, sim_time_s=1.0)
    assert lanes.max_speed["E1_1"] == pytest.approx(14.0 * 0.45)
    assert lanes.max_speed["E1_0"] == 14.0  # untouched


def test_clear_restores_original_speeds_and_emits_terminal_event(lanes):
    c = OperatorAnomalyController()
    c.handle_create(_create(severity="HIGH"), step=1, sim_time_s=1.0)
    c.drain_events()  # discard the ACTIVE event
    c.handle_clear(
        {"anomaly_id": "an-1", "resolution": "RESOLVED", "requested_at": 2_000_000},
        step=2, sim_time_s=2.0,
    )
    assert lanes.max_speed["E1_0"] == 14.0
    assert lanes.max_speed["E1_1"] == 14.0
    assert c.active_anomalies() == []
    (evt,) = c.drain_events()
    assert evt["status"] == "RESOLVED" and evt["anomaly_id"] == "an-1"


def test_time_boxed_anomaly_auto_resolves_after_its_duration(lanes):
    c = OperatorAnomalyController(AnomalyImpactConfig(republish_interval_s=1e9))
    c.handle_create(_create(duration_s=30.0), step=1, sim_time_s=100.0)
    c.drain_events()
    c.tick(step=2, sim_time_s=120.0)  # 20s in -- still active
    assert c.active_anomalies()
    assert c.drain_events() == []
    c.tick(step=3, sim_time_s=131.0)  # 31s in -- expired
    assert c.active_anomalies() == []
    assert lanes.max_speed["E1_0"] == 14.0
    (evt,) = c.drain_events()
    assert evt["status"] == "RESOLVED"
    assert "duration elapsed" in evt["detail"]


def test_periodic_republish_re_emits_active_anomalies(lanes):
    c = OperatorAnomalyController(AnomalyImpactConfig(republish_interval_s=10.0))
    c.handle_create(_create(), step=1, sim_time_s=0.0)
    c.drain_events()
    c.tick(step=2, sim_time_s=5.0)
    assert c.drain_events() == []           # not yet
    c.tick(step=3, sim_time_s=12.0)
    (evt,) = c.drain_events()               # republished
    assert evt["anomaly_id"] == "an-1" and evt["status"] == "ACTIVE"


def test_create_event_payload_matches_the_schema(lanes):
    from itms_common.events import decode_envelope, encode_envelope

    c = OperatorAnomalyController()
    c.handle_create(
        _create(severity="MEDIUM", duration_s=60.0, position_m=42.0), step=7, sim_time_s=7.0
    )
    (payload,) = c.drain_events()
    env = decode_envelope(
        encode_envelope(event_type="AnomalyUpdated", source="t", payload=payload)
    )["payload"]
    assert env["source"] == "OPERATOR"
    assert env["severity"] == "medium"
    assert env["status"] == "ACTIVE"
    assert env["edge_id"] == "E1"
    assert env["estimated_impact"] == pytest.approx(0.5)
    assert env["position_m"] == pytest.approx(42.0)
    assert env["expires_at_ms"] is not None


def test_unknown_edge_and_duplicate_and_unknown_clear_are_all_non_fatal(lanes, caplog):
    c = OperatorAnomalyController()
    c.handle_create(_create(edge_id="NOPE"), step=1, sim_time_s=1.0)
    assert c.active_anomalies() == []
    c.handle_create(_create(), step=2, sim_time_s=2.0)
    c.handle_create(_create(), step=3, sim_time_s=3.0)  # duplicate id -> ignored
    assert len(c.active_anomalies()) == 1
    c.handle_clear({"anomaly_id": "ghost"}, step=4, sim_time_s=4.0)  # unknown -> ignored


def test_restore_all_puts_every_lane_back(lanes):
    c = OperatorAnomalyController()
    c.handle_create(_create(anomaly_id="a", edge_id="E1", severity="HIGH"), step=1, sim_time_s=1.0)
    c.handle_create(
        _create(anomaly_id="b", edge_id="E2", severity="BLOCKED"), step=1, sim_time_s=1.0
    )
    c.restore_all()
    assert lanes.max_speed["E1_0"] == 14.0
    assert lanes.max_speed["E2_0"] == 10.0
    assert c.active_anomalies() == []

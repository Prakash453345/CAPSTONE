"""Regression: an operator command's `requested_at` (an epoch-ms number the UI
sends) is written as an Avro `timestamp-millis` and comes back from
`decode_envelope` as a `datetime`. The live command handlers must accept that
without crashing -- they used to do `int(payload["requested_at"])` and raise
`TypeError` on the datetime."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from itms_common.events import decode_envelope, encode_envelope
from sim_service.live import anomaly_control as ac
from sim_service.live import emergency_control as ec
from sim_service.live.anomaly_control import OperatorAnomalyController
from sim_service.live.emergency_control import EmergencyController
from sim_service.live.green_corridor import CorridorController
from sim_service.live.timeparse import epoch_ms
from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph


def _roundtrip(event_type: str, payload: dict) -> dict:
    raw = encode_envelope(event_type=event_type, source="test", payload=payload)
    return decode_envelope(raw)["payload"]


# ---- epoch_ms -----------------------------------------------------------


def test_epoch_ms_handles_datetime_int_float_and_missing():
    now_ms = int(time.time() * 1000)
    aware = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    assert epoch_ms(aware, 0) == pytest.approx(now_ms, abs=1000)
    naive = datetime.fromtimestamp(now_ms / 1000, tz=UTC).replace(tzinfo=None)
    assert epoch_ms(naive, 0) == pytest.approx(now_ms, abs=1000)
    assert epoch_ms(1_700_000_000_000, 0) == 1_700_000_000_000
    assert epoch_ms(1_700_000_000_000.0, 0) == 1_700_000_000_000
    assert epoch_ms(None, 42_000) == 42_000
    assert epoch_ms("garbage", 42_000) == 42_000
    assert epoch_ms(True, 42_000) == 42_000  # bool is not a timestamp


# ---- anomaly commands survive the round-trip --------------------------


@pytest.fixture
def patched_lanes(monkeypatch):
    monkeypatch.setattr(ac.traci.edge, "getLaneNumber", lambda e: 1)
    monkeypatch.setattr(ac.traci.lane, "getMaxSpeed", lambda ln: 13.9)
    monkeypatch.setattr(ac.traci.lane, "setMaxSpeed", lambda ln, v: None)


def test_anomaly_create_and_clear_accept_a_decoded_timestamp(patched_lanes):
    c = OperatorAnomalyController()
    created = _roundtrip(
        "AnomalyCreateRequested",
        {
            "anomaly_id": "an-1", "edge_id": "E1", "lane_id": None,
            "anomaly_type": "LANE_BLOCKAGE", "severity": "HIGH",
            "duration_s": None, "position_m": None,
            "requested_at": int(time.time() * 1000),
        },
    )
    assert isinstance(created["requested_at"], datetime)  # this is what broke it
    c.handle_create(created, step=1, sim_time_s=1.0)
    (evt,) = c.drain_events()
    assert evt["status"] == "ACTIVE" and evt["anomaly_id"] == "an-1"

    cleared = _roundtrip(
        "AnomalyClearRequested",
        {"anomaly_id": "an-1", "resolution": "RESOLVED", "reason": "cleared",
         "requested_at": int(time.time() * 1000)},
    )
    c.handle_clear(cleared, step=2, sim_time_s=2.0)
    (evt,) = c.drain_events()
    assert evt["status"] == "RESOLVED"


# ---- emergency commands survive the round-trip -----------------------


def _edge(eid: str, length: float = 120.0) -> EdgeInfo:
    return EdgeInfo(eid, length, 1, 10.0, f"{eid}_a", f"{eid}_b", (0.0, 0.0), (length, 0.0))


def _graph() -> RoadGraph:
    edges = {k: _edge(k) for k in ("S", "A", "T")}
    adjacency = {
        "S": (GraphEdge("A", "J1", True, "J1"),),
        "A": (GraphEdge("T", "J2", True, "J2"),),
    }
    return RoadGraph(
        edges=edges, adjacency=adjacency,
        signalised_junctions=frozenset({"J1", "J2"}),
        link_movements={"J1": {("S", "A"): frozenset({"L0"})},
                        "J2": {("A", "T"): frozenset({"L0"})}},
    )


class _NoAnoms:
    def active_anomalies(self):
        return []


@pytest.fixture
def patched_edges(monkeypatch):
    monkeypatch.setattr(ec.traci.edge, "getLastStepOccupancy", lambda e: 0.0)
    monkeypatch.setattr(ec.traci.edge, "getLastStepMeanSpeed", lambda e: -1.0)


def test_emergency_create_and_command_accept_a_decoded_timestamp(patched_edges):
    graph = _graph()
    c = EmergencyController(graph, _NoAnoms(), corridor_controller=CorridorController(graph))

    created = _roundtrip(
        "EmergencyRequestCreated",
        {
            "request_id": "er-1", "vehicle_id": "amb-1", "vehicle_kind": "AMBULANCE",
            "source_edge": "S", "destination_edge": "T", "priority": 1,
            "requested_at": int(time.time() * 1000),
        },
    )
    assert isinstance(created["requested_at"], datetime)
    c.handle_create(created, step=1, sim_time_s=1.0)
    (evt,) = c.drain_events()
    assert evt["state"] == "ROUTE_READY"
    assert isinstance(evt["updated_at"], int)  # payload still emits a plain epoch-ms

    cmd = _roundtrip(
        "EmergencyCommand",
        {"request_id": "er-1", "action": "CANCEL", "reason": "stand down",
         "requested_at": int(time.time() * 1000)},
    )
    c.handle_command(cmd, step=2, sim_time_s=2.0)
    (evt,) = c.drain_events()
    assert evt["state"] == "CANCELLED"

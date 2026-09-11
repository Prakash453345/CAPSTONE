"""`publish_traffic_state` -- the shared M1 per-tick publisher. Monkeypatches
TraCI and captures what lands on the bus, asserting the event types, payload
fields and topics match what `adapters/sumo/traci_loop.run` emits."""

from __future__ import annotations

import pytest
from itms_common.events import decode_envelope
from sim_service.adapters.sumo import state_publish as sp


class _FakeBus:
    def __init__(self):
        self.published: list[tuple[str, bytes]] = []

    def publish(self, topic: str, raw: bytes) -> str:
        self.published.append((topic, raw))
        return f"id-{len(self.published)}"


@pytest.fixture
def patched_traci(monkeypatch):
    t = sp.traci
    pos = {"v1": (10.0, 20.0), "v2": (30.0, 40.0)}
    monkeypatch.setattr(t.vehicle, "getIDList", lambda: ("v1", "v2"))
    monkeypatch.setattr(t.vehicle, "getPosition", lambda v: pos[v])
    monkeypatch.setattr(t.simulation, "convertGeo", lambda x, y: (80.6 + x / 1e5, 16.5 + y / 1e5))
    monkeypatch.setattr(t.vehicle, "getSpeed", lambda v: {"v1": 8.0, "v2": 0.0}[v])
    monkeypatch.setattr(t.vehicle, "getAngle", lambda v: {"v1": 90.0, "v2": 270.0}[v])
    monkeypatch.setattr(t.vehicle, "getRoadID", lambda v: {"v1": "E1", "v2": ":J3_0"}[v])
    monkeypatch.setattr(t.edge, "getIDList", lambda: ("E1", "E2", ":J3_0"))
    monkeypatch.setattr(t.edge, "getLastStepVehicleNumber", lambda e: {"E1": 3, "E2": 0}[e])
    monkeypatch.setattr(t.edge, "getLastStepOccupancy", lambda e: {"E1": 25.0, "E2": 0.0}[e])


def test_publishes_one_vehicle_event_per_vehicle_and_skips_internal_edges(patched_traci):
    bus = _FakeBus()
    sp.publish_traffic_state(bus, step_length=1.0)  # type: ignore[arg-type]

    by_topic: dict[str, list[dict]] = {}
    for topic, raw in bus.published:
        by_topic.setdefault(topic, []).append(decode_envelope(raw))

    veh = by_topic[sp.VEHICLE_TOPIC]
    assert [e["event_type"] for e in veh] == ["VehiclePositionUpdated", "VehiclePositionUpdated"]
    assert {e["payload"]["vehicle_id"] for e in veh} == {"v1", "v2"}
    v1 = next(e["payload"] for e in veh if e["payload"]["vehicle_id"] == "v1")
    assert v1["speed_mps"] == pytest.approx(8.0)
    assert v1["edge_id"] == "E1"
    assert v1["source"] == "sumo"

    appr = by_topic[sp.APPROACH_TOPIC]
    assert {e["payload"]["movement_id"] for e in appr} == {"E1", "E2"}  # ":J3_0" skipped
    e1 = next(e["payload"] for e in appr if e["payload"]["movement_id"] == "E1")
    assert e1["q_pcu"] == pytest.approx(3.0)
    assert e1["occupancy"] == pytest.approx(0.25)
    assert e1["arrival_rate_pcu_s"] == pytest.approx(3.0)
    assert e1["model"] == "ground_truth_sim"


def test_arrival_rate_scales_with_step_length(patched_traci):
    bus = _FakeBus()
    sp.publish_traffic_state(bus, step_length=0.5)  # type: ignore[arg-type]
    appr = [
        decode_envelope(raw)
        for topic, raw in bus.published
        if topic == sp.APPROACH_TOPIC
    ]
    e1 = next(e["payload"] for e in appr if e["payload"]["movement_id"] == "E1")
    assert e1["arrival_rate_pcu_s"] == pytest.approx(6.0)  # 3 vehicles / 0.5 s

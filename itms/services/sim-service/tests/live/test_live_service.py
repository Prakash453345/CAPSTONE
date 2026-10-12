"""`sim_service.live.service.run_live` -- the command-drain wiring, unit
level. `run_controlled_scenario` is replaced with a stub that just calls the
`on_tick` closure a few times with scripted messages, so no SUMO or Redis is
needed. The corridor loader is stubbed too."""

from __future__ import annotations

from itms_common.events import encode_envelope
from sim_service.live import service as live_service


class _Msg:
    def __init__(self, topic: str, mid: str, raw: bytes) -> None:
        self.topic, self.message_id, self.raw = topic, mid, raw


class _FakeConsumer:
    """Yields a scripted list of message batches, one per drain() call."""

    def __init__(self, batches: list[list[_Msg]]) -> None:
        self._batches = list(batches)
        self.acked: list[tuple[str, str]] = []
        self.closed = False

    def drain(self, *, max_messages: int = 500) -> list[_Msg]:
        return self._batches.pop(0) if self._batches else []

    def ack(self, topic: str, message_id: str) -> None:
        self.acked.append((topic, message_id))

    def close(self) -> None:
        self.closed = True


class _FakeBus:
    def __init__(self) -> None:
        self.closed = False
        self.published: list[tuple[str, bytes]] = []

    def publish(self, topic: str, raw: bytes) -> str:
        self.published.append((topic, raw))
        return f"{len(self.published)}-0"

    def close(self) -> None:
        self.closed = True


class _CorridorStub:
    sumocfg_path = "x.sumocfg"
    route_path = "x.rou.xml"
    configs: dict = {}
    strategy: dict = {}
    link_lanes: dict = {}
    receiving_lanes: dict = {}
    vtype_pcu: dict = {}


def test_run_live_drains_and_dispatches_each_command(monkeypatch):
    calls: list[tuple[str, int]] = []

    def handler(envelope: dict, step: int, sim_time: float) -> None:
        calls.append((envelope["event_type"], step))

    hb = encode_envelope(
        event_type="SystemHeartbeat", source="t", payload={"service": "s", "seq": 1}
    )
    batch1 = [_Msg("commands.operator", "1-0", hb), _Msg("commands.operator", "1-1", hb)]
    batch2 = [_Msg("commands.operator", "2-0", hb)]

    consumer = _FakeConsumer([batch1, batch2])
    monkeypatch.setattr(live_service, "load_corridor", lambda demand="medium", network="corridor": _CorridorStub())
    monkeypatch.setattr(live_service, "RedisStreamsSyncBus", lambda url: _FakeBus())
    monkeypatch.setattr(
        live_service, "RedisStreamsSyncConsumer",
        lambda *a, **k: consumer,
    )

    seen_on_tick: list = []

    def fake_run(*args, on_tick, **kwargs):
        # drive three ticks
        on_tick(10, 10.0)
        on_tick(11, 11.0)
        on_tick(12, 12.0)
        seen_on_tick.append(kwargs.get("publish_traffic_state"))
        return {"steps": 3, "interlock_violations": 0}

    monkeypatch.setattr(live_service, "run_controlled_scenario", fake_run)

    summary = live_service.run_live(command_handler=handler, realtime_factor=0.0)

    assert [c[0] for c in calls] == ["SystemHeartbeat", "SystemHeartbeat", "SystemHeartbeat"]
    assert [c[1] for c in calls] == [10, 10, 11]  # 2 in tick 10, 1 in tick 11
    assert consumer.acked == [
        ("commands.operator", "1-0"),
        ("commands.operator", "1-1"),
        ("commands.operator", "2-0"),
    ]
    assert summary["commands_drained"] == 3
    assert seen_on_tick == [True]  # publish_traffic_state passed through
    assert consumer.closed


def test_undecodable_command_is_acked_and_skipped_not_fatal(monkeypatch):
    handled: list[str] = []
    consumer = _FakeConsumer([[_Msg("commands.operator", "9-0", b"\x00not-avro")]])
    monkeypatch.setattr(live_service, "load_corridor", lambda demand="medium", network="corridor": _CorridorStub())
    monkeypatch.setattr(live_service, "RedisStreamsSyncBus", lambda url: _FakeBus())
    monkeypatch.setattr(live_service, "RedisStreamsSyncConsumer", lambda *a, **k: consumer)
    monkeypatch.setattr(
        live_service, "run_controlled_scenario",
        lambda *a, on_tick, **k: (on_tick(1, 1.0), {"steps": 1, "interlock_violations": 0})[1],
    )

    summary = live_service.run_live(
        command_handler=lambda e, s, t: handled.append(e["event_type"]),
        realtime_factor=0.0,
    )
    assert handled == []                       # handler never saw the bad message
    assert consumer.acked == [("commands.operator", "9-0")]  # but it was acked (no poison loop)
    assert summary["commands_drained"] == 0


def test_built_in_dispatch_routes_anomaly_commands_to_the_controller(monkeypatch):
    """No `command_handler` override -> `_build_dispatch` sends
    AnomalyCreateRequested / AnomalyClearRequested to OperatorAnomalyController."""
    seen: list[tuple[str, dict]] = []

    class _StubController:
        def handle_create(self, payload, *, step, sim_time_s):
            seen.append(("create", dict(payload)))

        def handle_clear(self, payload, *, step, sim_time_s):
            seen.append(("clear", dict(payload)))

        def tick(self, step, sim_time_s):
            pass

        def drain_events(self):
            return []

        def restore_all(self):
            pass

        def active_anomalies(self):
            return []

    create = encode_envelope(
        event_type="AnomalyCreateRequested",
        source="t",
        payload={
            "anomaly_id": "an-9", "edge_id": "E7",
            "anomaly_type": "ACCIDENT", "severity": "HIGH",
            "requested_at": 1, "operator": "operator:sam",
        },
    )
    other = encode_envelope(
        event_type="SystemHeartbeat", source="t", payload={"service": "s", "seq": 1}
    )
    consumer = _FakeConsumer([[_Msg("commands.operator", "1-0", create),
                              _Msg("commands.operator", "1-1", other)]])
    monkeypatch.setattr(live_service, "load_corridor", lambda demand="medium", network="corridor": _CorridorStub())
    monkeypatch.setattr(live_service, "RedisStreamsSyncBus", lambda url: _FakeBus())
    monkeypatch.setattr(live_service, "RedisStreamsSyncConsumer", lambda *a, **k: consumer)
    monkeypatch.setattr(
        live_service, "OperatorAnomalyController", lambda *a, **k: _StubController()
    )
    monkeypatch.setattr(
        live_service, "run_controlled_scenario",
        lambda *a, on_tick, **k: (on_tick(3, 3.0), {"steps": 1, "interlock_violations": 0})[1],
    )

    live_service.run_live(realtime_factor=0.0)  # built-in dispatch
    assert [kind for kind, _ in seen] == ["create"]
    assert seen[0][1]["anomaly_id"] == "an-9"

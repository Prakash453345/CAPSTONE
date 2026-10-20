"""Every publish path caps its stream, so Redis memory cannot grow without
bound while the simulation runs (it once reached 2.2 million vehicle
positions and crashed the simulation on a Redis timeout)."""

from __future__ import annotations

from itms_common import bus as bus_module
from itms_common.bus import RedisStreamsBus, RedisStreamsSyncBus


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def xadd(self, topic, fields, **kwargs):
        self.calls.append(kwargs)
        return b"1-0"


class _AsyncRecorder(_Recorder):
    async def xadd(self, topic, fields, **kwargs):  # type: ignore[override]
        self.calls.append(kwargs)
        return b"1-0"


CAPPED = {"maxlen": bus_module.STREAM_MAXLEN, "approximate": True}


def test_sync_publish_caps_the_stream():
    bus = RedisStreamsSyncBus.__new__(RedisStreamsSyncBus)
    bus._redis = _Recorder()
    bus.publish("t", b"x")
    assert bus._redis.calls == [CAPPED]


async def test_async_publish_caps_the_stream():
    bus = RedisStreamsBus.__new__(RedisStreamsBus)
    bus._redis = _AsyncRecorder()
    await bus.publish("t", b"x")
    assert bus._redis.calls == [CAPPED]


def test_the_cap_holds_minutes_of_vehicle_positions_and_can_be_turned_off(monkeypatch):
    assert bus_module.STREAM_MAXLEN >= 30_000      # > 2 minutes at ~250 positions a second
    monkeypatch.setattr(bus_module, "STREAM_MAXLEN", 0)
    rec = _Recorder()
    bus = RedisStreamsSyncBus.__new__(RedisStreamsSyncBus)
    bus._redis = rec
    bus.publish("t", b"x")
    assert rec.calls == [{}]

"""`RedisStreamsSyncConsumer` -- unit-level, no real Redis. A stub client
stands in for `redis.from_url(...)` so the response parsing (bytes vs str),
the group bootstrap, and the NOGROUP self-heal are exercised without the
docker-compose stack. The real round-trip is covered by
`test_bus_integration.py` (gated on RUN_INTEGRATION_TESTS)."""

from __future__ import annotations

import redis as redis_sync
from itms_common import bus as bus_module
from itms_common.bus import RedisStreamsSyncConsumer


class _StubRedis:
    def __init__(self):
        self.groups_created: list[tuple[str, str]] = []
        self.acked: list[tuple[str, str, str]] = []
        self.closed = False
        self._responses: list = []
        self._raise_nogroup_once = False

    # -- test knobs --
    def queue_response(self, response):
        self._responses.append(response)

    def raise_nogroup_once(self):
        self._raise_nogroup_once = True

    # -- redis client surface the consumer uses --
    def xgroup_create(self, *, name, groupname, id, mkstream):
        self.groups_created.append((name, groupname))

    def xreadgroup(self, *, groupname, consumername, streams, count, block):
        if self._raise_nogroup_once:
            self._raise_nogroup_once = False
            raise redis_sync.ResponseError("NOGROUP No such key '...' or consumer group '...'")
        return self._responses.pop(0) if self._responses else None

    def xack(self, topic, group, message_id):
        self.acked.append((topic, group, message_id))

    def close(self):
        self.closed = True


def _consumer(monkeypatch) -> tuple[RedisStreamsSyncConsumer, _StubRedis]:
    stub = _StubRedis()
    monkeypatch.setattr(bus_module.redis_sync, "from_url", lambda url: stub)
    c = RedisStreamsSyncConsumer(
        ["commands.a", "commands.b"], group="g", consumer="c1", url="redis://x"
    )
    return c, stub


def test_creates_a_group_per_topic_on_construction(monkeypatch):
    _, stub = _consumer(monkeypatch)
    assert stub.groups_created == [("commands.a", "g"), ("commands.b", "g")]


def test_busygroup_on_create_is_swallowed(monkeypatch):
    stub = _StubRedis()

    def boom(**_):
        raise redis_sync.ResponseError("BUSYGROUP Consumer Group name already exists")

    stub.xgroup_create = boom  # type: ignore[method-assign]
    monkeypatch.setattr(bus_module.redis_sync, "from_url", lambda url: stub)
    RedisStreamsSyncConsumer(["commands.a"], group="g", consumer="c1")  # must not raise


def test_drain_returns_empty_list_when_stream_is_quiet(monkeypatch):
    c, _ = _consumer(monkeypatch)
    assert c.drain() == []


def test_drain_parses_bytes_and_str_shapes(monkeypatch):
    c, stub = _consumer(monkeypatch)
    stub.queue_response(
        [
            (b"commands.a", [(b"1-0", {b"raw": b"payload-1"}), (b"1-1", {b"raw": b"payload-2"})]),
            ("commands.b", [("2-0", {"raw": b"payload-3"})]),
        ]
    )
    msgs = c.drain()
    assert [(m.topic, m.message_id, m.raw) for m in msgs] == [
        ("commands.a", "1-0", b"payload-1"),
        ("commands.a", "1-1", b"payload-2"),
        ("commands.b", "2-0", b"payload-3"),
    ]


def test_drain_recreates_a_vanished_group_and_returns_empty(monkeypatch):
    c, stub = _consumer(monkeypatch)
    stub.groups_created.clear()
    stub.raise_nogroup_once()
    assert c.drain() == []
    assert ("commands.a", "g") in stub.groups_created
    assert ("commands.b", "g") in stub.groups_created


def test_ack_and_close_delegate(monkeypatch):
    c, stub = _consumer(monkeypatch)
    c.ack("commands.a", "1-0")
    assert stub.acked == [("commands.a", "g", "1-0")]
    c.close()
    assert stub.closed

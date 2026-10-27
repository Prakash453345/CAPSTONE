"""Event bus abstraction. [ARCH ADR-003]: one interface, Redis Streams today
(Phase-1, per build guide §6.1), swappable for a Kafka-backed implementation
later without touching any caller. Topic names and payloads are identical
either way — only this module changes.

Consumer-group semantics map directly: XADD ~ produce, XREADGROUP ~ consume-group
read, XACK ~ commit offset. That mapping is *why* Redis Streams was chosen as the
Phase-1 stand-in rather than plain pub/sub (build guide §6.1).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, cast

import redis as redis_sync
import redis.asyncio as redis

# Every stream is capped on publish. Redis keeps the newest ~STREAM_MAXLEN
# entries per topic (approximate trimming: whole internal nodes are dropped,
# so it costs nothing per write). Without a cap a stream grows forever: the
# live simulation publishes ~250 vehicle positions a second, which reached
# 2.2 million entries and 0.5 GB of Redis memory before Redis became too slow
# to answer and the simulation crashed on a read timeout.
#
# 50,000 is ~3 minutes of vehicle positions -- every consumer of that topic
# reads at the live edge -- and far more than the low-volume topics
# (commands, incidents, clips) ever hold. ITMS_STREAM_MAXLEN=0 turns the cap
# off (e.g. to record a run for later replay).
STREAM_MAXLEN = int(os.environ.get("ITMS_STREAM_MAXLEN", "50000"))


def _cap() -> dict[str, Any]:
    return {"maxlen": STREAM_MAXLEN, "approximate": True} if STREAM_MAXLEN > 0 else {}


@dataclass(frozen=True)
class Message:
    topic: str
    message_id: str
    raw: bytes


class EventBus(Protocol):
    async def publish(self, topic: str, raw: bytes) -> str:
        """Publish raw (already-encoded envelope) bytes to `topic`. Returns the
        broker-assigned message id."""
        ...

    def subscribe(
        self, topics: list[str], *, group: str, consumer: str
    ) -> AsyncIterator[Message]:
        """Yield messages from `topics` as a member of consumer group `group`.
        At-least-once delivery [ARCH §6.3] — callers must be idempotent and must
        call ack() once a message is durably handled."""
        ...

    async def ack(self, topic: str, group: str, message_id: str) -> None: ...

    async def close(self) -> None: ...


class RedisStreamsBus:
    """Redis Streams implementation of EventBus."""

    def __init__(self, url: str = "redis://localhost:6379/0"):
        self._url = url
        self._redis = redis.from_url(url)

    async def publish(self, topic: str, raw: bytes) -> str:
        message_id = await self._redis.xadd(topic, {"raw": raw}, **_cap())
        return message_id.decode() if isinstance(message_id, bytes) else message_id

    async def _ensure_group(self, topic: str, group: str, *, start_id: str = "0") -> None:
        try:
            await self._redis.xgroup_create(
                name=topic, groupname=group, id=start_id, mkstream=True
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def subscribe(
        self,
        topics: list[str],
        *,
        group: str,
        consumer: str,
        block_ms: int = 5000,
        start_id: str = "0",
    ) -> AsyncIterator[Message]:
        for topic in topics:
            await self._ensure_group(topic, group, start_id=start_id)

        streams = {topic: ">" for topic in topics}
        while True:
            try:
                # redis-py's async stubs can't express the decode_responses-dependent
                # return shape precisely; at runtime (bytes mode, our default) this is
                # list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]] or None.
                response = cast(
                    list[tuple[Any, list[tuple[Any, dict[Any, Any]]]]] | None,
                    await self._redis.xreadgroup(
                        groupname=group,
                        consumername=consumer,
                        streams=cast(Any, streams),
                        count=100,
                        block=block_ms,
                    ),
                )
            except redis.ResponseError as exc:
                # A group can vanish out from under a long-lived consumer --
                # Redis restart with no persistence, a stream deleted and
                # recreated, an ops FLUSHALL. Recreate and keep going rather
                # than letting the whole consume_forever task die silently
                # (asyncio only logs "Task exception was never retrieved",
                # easy to miss, and the dashboard just goes quiet with no
                # visible error).
                if "NOGROUP" not in str(exc):
                    raise
                for topic in topics:
                    await self._ensure_group(topic, group, start_id=start_id)
                continue
            except (redis.TimeoutError, redis.ConnectionError):
                # A blocking XREADGROUP that elapses with nothing to return is a
                # normal poll timeout, not a failure -- but under some event
                # loops (notably WindowsSelectorEventLoop, which uvicorn forces
                # on Windows) redis-py surfaces it as TimeoutError rather than an
                # empty response. Treat it, and a transient connection blip, the
                # same as "no messages": back off briefly and retry, so the
                # consumer is genuinely forever instead of dying on the first
                # quiet interval.
                await asyncio.sleep(0.1)
                continue
            if not response:
                await asyncio.sleep(0)  # yield control; caller can cancel us here
                continue
            for stream_name, entries in response:
                topic = (
                    stream_name.decode()
                    if isinstance(stream_name, bytes)
                    else stream_name
                )
                for message_id, fields in entries:
                    mid = (
                        message_id.decode()
                        if isinstance(message_id, bytes)
                        else message_id
                    )
                    # publish() always writes the "raw" field; absence would be
                    # a different bug worth a loud KeyError, not a silent None.
                    raw = cast(bytes, fields.get(b"raw") or fields.get("raw"))
                    yield Message(topic=topic, message_id=mid, raw=raw)

    async def ack(self, topic: str, group: str, message_id: str) -> None:
        await self._redis.xack(topic, group, message_id)

    async def close(self) -> None:
        await self._redis.aclose()


class RedisStreamsSyncBus:
    """Synchronous producer-side counterpart to RedisStreamsBus. Same wire
    format (XADD to the same topics, same envelope bytes) -- the only
    difference is the transport call isn't async.

    Exists for producers driven by something that's already blocking and has
    no concurrency to gain from asyncio -- the TraCI loop is the case this
    was built for (traci.simulationStep() blocks on subprocess IPC every
    tick regardless). ADR-003's "one bus abstraction" still holds: this is
    the producer half of the same Redis Streams contract the async
    RedisStreamsBus consumes, not a second bus design.
    """

    def __init__(self, url: str = "redis://localhost:6379/0"):
        self._redis = redis_sync.from_url(url)

    def publish(self, topic: str, raw: bytes) -> str:
        message_id = self._redis.xadd(topic, {"raw": raw}, **_cap())
        return message_id.decode() if isinstance(message_id, bytes) else message_id

    def publish_many(self, messages: list[tuple[str, bytes]]) -> list[str]:
        """XADD every (topic, raw) in one pipelined round trip, in order.
        Same entries `publish` would write one by one; a tick's worth of
        vehicle positions costs one network wait instead of hundreds."""
        if not messages:
            return []
        pipe = self._redis.pipeline(transaction=False)
        for topic, raw in messages:
            pipe.xadd(topic, {"raw": raw}, **_cap())
        return [m.decode() if isinstance(m, bytes) else m for m in pipe.execute()]

    def close(self) -> None:
        self._redis.close()


class RedisStreamsSyncConsumer:
    """Synchronous, NON-blocking consumer-group reader -- the consume-side
    counterpart to RedisStreamsSyncBus, for a consumer that is itself a
    blocking loop (the controlled SUMO tick loop, which calls
    `traci.simulationStep()` every tick regardless).

    `drain()` returns every message currently pending for this consumer and
    returns immediately when the stream is quiet, so it costs one cheap
    XREADGROUP per simulation step. Same wire format, same consumer-group
    semantics (XREADGROUP / XACK), same ADR-003 bus contract as the async
    RedisStreamsBus -- only the transport call isn't async.
    """

    def __init__(
        self,
        topics: list[str],
        *,
        group: str,
        consumer: str,
        url: str = "redis://localhost:6379/0",
    ):
        self._redis = redis_sync.from_url(url)
        self._topics = list(topics)
        self._group = group
        self._consumer = consumer
        for topic in self._topics:
            self._ensure_group(topic)

    def _ensure_group(self, topic: str) -> None:
        try:
            self._redis.xgroup_create(
                name=topic, groupname=self._group, id="0", mkstream=True
            )
        except redis_sync.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def drain(self, *, max_messages: int = 500) -> list[Message]:
        """Read up to `max_messages` new messages across all topics without
        blocking. A group that vanished (Redis restart with no persistence, a
        stream recreated) is recreated and this call returns [] -- the next
        `drain()` picks up from there, same recovery as the async bus."""
        streams = {topic: ">" for topic in self._topics}
        try:
            response = cast(
                list[tuple[Any, list[tuple[Any, dict[Any, Any]]]]] | None,
                self._redis.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer,
                    streams=cast(Any, streams),
                    count=max_messages,
                    block=None,  # non-blocking: return whatever is available now
                ),
            )
        except redis_sync.ResponseError as exc:
            if "NOGROUP" not in str(exc):
                raise
            for topic in self._topics:
                self._ensure_group(topic)
            return []

        out: list[Message] = []
        for stream_name, entries in response or []:
            topic = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
            for message_id, fields in entries:
                mid = message_id.decode() if isinstance(message_id, bytes) else message_id
                raw = cast(bytes, fields.get(b"raw") or fields.get("raw"))
                out.append(Message(topic=topic, message_id=mid, raw=raw))
        return out

    def ack(self, topic: str, message_id: str) -> None:
        self._redis.xack(topic, self._group, message_id)

    def close(self) -> None:
        self._redis.close()

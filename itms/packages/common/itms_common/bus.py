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
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, cast

import redis.asyncio as redis


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
        message_id = await self._redis.xadd(topic, {"raw": raw})
        return message_id.decode() if isinstance(message_id, bytes) else message_id

    async def _ensure_group(self, topic: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(
                name=topic, groupname=group, id="0", mkstream=True
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
    ) -> AsyncIterator[Message]:
        for topic in topics:
            await self._ensure_group(topic, group)

        streams = {topic: ">" for topic in topics}
        while True:
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

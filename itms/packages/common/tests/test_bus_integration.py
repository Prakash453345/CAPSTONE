"""Integration test — needs a real Redis. Skipped unless RUN_INTEGRATION_TESTS=1,
so `make test` stays runnable without the docker-compose stack up; `make dev`
(or CI, once it starts a redis service container) sets the env var and runs it."""

import os
import uuid

import pytest
from itms_common.bus import RedisStreamsBus

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 with a Redis reachable at REDIS_URL to run this",
)


@pytest.mark.asyncio
async def test_publish_subscribe_ack_roundtrip():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    bus = RedisStreamsBus(url)
    topic = f"test.{uuid.uuid4()}"
    group = "test-group"

    await bus.publish(topic, b"hello-world")

    got = None
    async for msg in bus.subscribe([topic], group=group, consumer="c1", block_ms=2000):
        got = msg
        await bus.ack(topic, group, msg.message_id)
        break

    await bus.close()

    assert got is not None
    assert got.raw == b"hello-world"

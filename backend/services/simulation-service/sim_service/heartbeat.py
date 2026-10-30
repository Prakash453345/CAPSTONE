"""M0's hello-event loop. Superseded as sim-service's default entrypoint by
the real TraCI loop (M1, see adapters/sumo/traci_loop.py and main.py) but
kept as its own module -- it's still the fastest way to sanity-check "is the
bus plumbing itself OK" without SUMO in the loop at all, and M0's tests may
still exercise it.
"""

from __future__ import annotations

import asyncio
import logging
import os

from itms_common import RedisStreamsBus, encode_envelope

logging.basicConfig(level=logging.INFO, format="%(asctime)s sim-service %(message)s")
log = logging.getLogger("sim-service.heartbeat")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
HEARTBEAT_TOPIC = "system.heartbeat"


async def run() -> None:
    bus = RedisStreamsBus(REDIS_URL)
    seq = 0
    log.info("starting, publishing to %s via %s", HEARTBEAT_TOPIC, REDIS_URL)
    try:
        while True:
            seq += 1
            raw = encode_envelope(
                event_type="SystemHeartbeat",
                source="sim-service",
                payload={"service": "sim-service", "seq": seq, "message": "hello"},
                partition_key="sim-service",
            )
            message_id = await bus.publish(HEARTBEAT_TOPIC, raw)
            log.info("published seq=%d id=%s", seq, message_id)
            await asyncio.sleep(1.0)
    finally:
        await bus.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

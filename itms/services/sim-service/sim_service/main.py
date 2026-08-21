"""sim-service, M0 slice.

Eventually: the TraCI loop (M1), traffic state (M1), the safety kernel and
optimizer (M2/M4), the IoT/GPS adapters (M1). Today: publish a SystemHeartbeat
once a second so there's something flowing through the bus to prove the plumbing
works end to end before any of that exists. This function gets replaced by the
real TraCI loop in M1, not extended in place — a heartbeat and a simulation tick
are different loops.
"""

from __future__ import annotations

import asyncio
import logging
import os

from itms_common import RedisStreamsBus, encode_envelope

logging.basicConfig(level=logging.INFO, format="%(asctime)s sim-service %(message)s")
log = logging.getLogger("sim-service")

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

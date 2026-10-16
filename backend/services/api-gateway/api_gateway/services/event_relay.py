"""Bus -> browsers: relays live topics to every WebSocket client, folding the
ones this service keeps a read model of (incidents, uploaded clips) into
their registries on the way.

No viewport filtering yet. ARCH §7.2's point is that a client should not
receive 2 million vehicles when it can see 200, but this network has 16
junctions and low triple-digit vehicle counts, so broadcasting everything is
still cheap. Add it when the network is big enough that it is not -- there
will be an obvious moment (the dashboard visibly falling behind).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import secrets

from itms_common import RedisStreamsBus, decode_envelope

from api_gateway.core.config import CONSUMER_GROUP
from api_gateway.services.clip_registry import ClipRegistry
from api_gateway.services.connections import ConnectionManager
from api_gateway.services.incident_registry import IncidentRegistry

log = logging.getLogger("api-service.relay")

INCIDENT_EVENT_TYPES = frozenset({"IncidentCandidate", "IncidentDetected", "IncidentUpdated"})
INCIDENT_TOPICS = frozenset({"incident.candidate", "incident.detected", "incident.updated"})
_PROCESS_ID = secrets.token_hex(4)


def json_safe(value):
    """fastavro decodes every timestamp-millis field (envelope `occurred_at`
    and any in a payload -- e.g. AnomalyUpdated's `start_time_ms`) into a
    datetime. Walk the structure and isoformat them so the whole thing is
    plain-JSON-serializable before it hits the socket."""
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


class EventRelay:
    def __init__(
        self,
        bus: RedisStreamsBus,
        connections: ConnectionManager,
        incidents: IncidentRegistry,
        clips: ClipRegistry,
        topics: tuple[str, ...],
    ) -> None:
        self.bus = bus
        self.connections = connections
        self.incidents = incidents
        self.clips = clips
        self.topics = topics

    async def handle(self, envelope: dict) -> None:
        """Fold one decoded event into the read models, then broadcast it."""
        event_type = envelope["event_type"]
        if event_type == "ClipAnalysed":
            self.clips.apply_analysed(envelope["payload"])
        if event_type in INCIDENT_EVENT_TYPES:
            # Safe even for events this process just published itself: the
            # registry skips a transition its chain_hash already reflects
            # (see services/incident_registry.py).
            self.incidents.apply_event(event_type, envelope["payload"])
        await self.connections.broadcast(json_safe(envelope))

    async def _consume_topic(self, topic: str, consumer: str) -> None:
        """Relay one topic with its own cursor so busy traffic cannot starve alarms.

        `incident.*` topics feed the in-memory `IncidentRegistry`, which is empty
        after a restart, so they are read from the start of the stream through a
        group private to this process (a shared group resumes at its old cursor and
        never replays). Everything else is a live-edge UI fan-out."""
        replay = topic in INCIDENT_TOPICS
        group = f"{CONSUMER_GROUP}-registry-{_PROCESS_ID}" if replay else CONSUMER_GROUP
        while True:
            try:
                async for msg in self.bus.subscribe(
                    # A UI fan-out, not an archival processor: a new group
                    # starts at the live edge. Replaying a retained stream
                    # would show hours-old congestion before current positions.
                    [topic], group=group, consumer=consumer, start_id="0" if replay else "$"
                ):
                    try:
                        await self.handle(decode_envelope(msg.raw))
                    except Exception:
                        log.exception("failed to handle message %s on %s",
                                      msg.message_id, msg.topic)
                    else:
                        await self.bus.ack(msg.topic, group, msg.message_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("live stream consumer failed; retrying")
                await asyncio.sleep(1)
            else:
                # A subscription is designed never to finish. If it does, keep
                # the live bridge alive instead of leaving browsers stale.
                log.warning("live stream consumer ended; restarting")
                await asyncio.sleep(1)

    async def run_forever(self) -> None:
        """Relay all topics concurrently without starvation or silent death."""
        tasks = [
            asyncio.create_task(self._consume_topic(topic, f"api-service-{i}"))
            for i, topic in enumerate(self.topics, start=1)
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

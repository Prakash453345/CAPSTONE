"""Drive the signal controller from the cameras (M8) instead of SUMO's own
queue sampler -- the live counterpart of `vision_service.sim.closed_loop`.

The vision service publishes `LinkStateEstimated` on `vision.link-state`:
per junction, per link `L{i}`, exactly the four `QueueSample` quantities the
controller already consumes, plus a confidence. `VisionFeed` keeps the latest
of those per link; `VisionFedStrategy` wraps each junction's strategy and
swaps the four fields in its `JunctionContext` for the camera estimate before
the controller sees them. Nothing else about the controller changes.

**Confidence policy: `failsafe`** -- the controller hears about confidence
only when it is below 0.5 (a camera offline, a lane nobody sees, a camera
caught blind). The M8 closed loop found A-CA-MP's ladder, with no demand
memory, dropping a junction to M2's green-cutting min-green cycler for any
value below 0.8, which cost +8 to +21 % person-delay against ignoring
confidence (`baselines/2026-09-25_m8_review/`). That rung now controls on
the live estimate (`acamp.py`), and `honest` makes the same decisions as
`failsafe` (`baselines/2026-09-25_m8_ladder_blindcheck/`); `failsafe` stays
the default for a controller that has a memory to blend toward. Passing
real failures on recovers about half of what a half-hour camera outage
costs a controller that trusts its cameras blindly.

**Staleness.** A link whose last estimate is older than `max_age_s` (the
vision service stopped, the bus lagged) is reported with the last values it
had and confidence 0 -- a hard failure, so the ladder falls back rather
than acting on state from a minute ago. A link the vision service has never
reported gets the same treatment. Staleness is judged on the envelope's
`occurred_at`, so a consumer group that replays yesterday's stream on
start-up does not mistake it for now.

**A camera that has gone blind** -- frames still arriving, the detector no
longer finding vehicles -- reads as an empty road at full confidence, and
nothing inside the vision service can tell that from a road that emptied.
The controller can: `itms_domain.camera.BlindCameraCheck` compares each
link with its stop-bar loop (`signal_controller.detectors.StopBarLoops`,
emulated over TraCI here), and a link whose loop keeps seeing vehicles
while the camera sees none becomes a hard failure until the camera sees a
vehicle again. On by default except in `trust` mode
(`VISION_BLIND_CHECK=0` turns it off).

What stays SUMO ground truth, as in the M8 gates: `has_demand` and
`wait_times_s` -- the safety kernel's max-wait inputs, which a deployment
takes from stop-bar presence detection, not from the camera estimate.

The swap, the confidence policy and the cross-check are
`itms_domain.camera`, shared with the gates' adapter
(`vision_service.sim.closed_loop`), so the two cannot drift apart.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from itms_domain.camera import (
    CAMERA_FIELDS,
    HARD_FAILURE,
    MODES,
    BlindCameraCheck,
    with_camera_state,
)

log = logging.getLogger("sim-service.vision-feed")

LINK_STATE_TOPIC = "vision.link-state"
_FIELDS = CAMERA_FIELDS
__all__ = ["HARD_FAILURE", "LINK_STATE_TOPIC", "VisionFeed", "VisionFedStrategy",
           "start_feed_thread"]


@dataclass
class _Row:
    values: dict[str, float]
    confidence: float
    at: float  # wall-clock seconds the estimate was made
    vehicles_seen: float = -1.0  # -1: not reported


class VisionFeed:
    """The latest camera estimate per (junction, link), thread-safe."""

    def __init__(self, *, max_age_s: float = 3.0, clock: Callable[[], float] = time.time):
        self.max_age_s = max_age_s
        self.clock = clock
        self._rows: dict[tuple[str, str], _Row] = {}
        self._lock = threading.Lock()
        self.received = 0
        # junction-ticks the controller ran on, and how many of them had a
        # link in hard failure (stale, unseen, or a camera down) -- logged by
        # the feed thread, so a dead feed is visible, not just quiet
        self.junction_ticks = 0
        self.failed_junction_ticks = 0

    def on_envelope(self, envelope: Mapping[str, Any]) -> None:
        """A decoded envelope. Its `occurred_at` arrives as a datetime (Avro
        `timestamp-millis`); the first version divided it by 1000, which
        raised on every message -- caught, logged, and the controller ran
        on confidence 0 for the whole run. The live end-to-end run found it;
        the unit tests had fed integers."""
        from itms_common.events import occurred_at_s  # noqa: PLC0415

        if envelope.get("event_type") != "LinkStateEstimated":
            return
        at = occurred_at_s(dict(envelope))
        self.on_payload(envelope["payload"], at=self.clock() if at is None else at)

    def on_payload(self, payload: Mapping[str, Any], *, at: float | None = None) -> None:
        at = self.clock() if at is None else at
        tls = payload["intersection_id"]
        with self._lock:
            for row in payload.get("links", []):
                key = (tls, row["link_id"])
                old = self._rows.get(key)
                if old is not None and old.at > at:
                    continue  # out of order: keep the newer one
                self._rows[key] = _Row({f: float(row[f]) for f in _FIELDS},
                                       float(row["confidence"]), at,
                                       float(row.get("vehicles_seen", -1)))
            self.received += 1

    def junction(self, tls: str, links) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
        """`(fields, confidence)` for `links` of one junction: each field
        `{link: value}` as `JunctionContext` wants it; a stale or missing
        link reads confidence 0."""
        now = self.clock()
        fields: dict[str, dict[str, float]] = {f: {} for f in _FIELDS}
        conf: dict[str, float] = {}
        with self._lock:
            for link in links:
                row = self._rows.get((tls, link))
                fresh = row is not None and now - row.at <= self.max_age_s
                for f in _FIELDS:
                    fields[f][link] = row.values[f] if row is not None else 0.0
                conf[link] = row.confidence if fresh and row is not None else 0.0
        return fields, conf


    def vehicles_seen(self, tls: str, links) -> dict[str, float]:
        """Vehicles the cameras track on each link's approach; -1 when not
        reported or stale (the cross-check skips those)."""
        now = self.clock()
        with self._lock:
            out = {}
            for link in links:
                row = self._rows.get((tls, link))
                fresh = row is not None and now - row.at <= self.max_age_s
                out[link] = row.vehicles_seen if fresh and row is not None else -1.0
            return out


class VisionFedStrategy:
    """Wraps one junction's strategy. Forwards `set_sim_time` and `stats`
    explicitly so the runner's duck-typing sees the wrapped interface."""

    def __init__(self, inner: Any, feed: VisionFeed, tls_id: str, mode: str = "failsafe",
                 *, stopbar: Callable[[], Mapping[str, bool]] | None = None,
                 blind_check: bool | None = None):
        """`stopbar()` returns this junction's stop-bar loop presence per
        link; without it there is nothing to cross-check the camera against."""
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        self.inner, self.feed, self.tls_id, self.mode = inner, feed, tls_id, mode
        on = mode != "trust" if blind_check is None else blind_check
        self.stopbar = stopbar
        self.check = BlindCameraCheck() if on and stopbar is not None else None
        self._t = 0.0
        self.blind_ticks = 0

    def set_sim_time(self, sim_time_s: float) -> None:
        self._t = sim_time_s
        if hasattr(self.inner, "set_sim_time"):
            self.inner.set_sim_time(sim_time_s)

    @property
    def stats(self) -> dict[str, int]:
        return getattr(self.inner, "stats", {})

    def __call__(self, cfg, ctx):
        links = set(ctx.queue_pcu) | set(ctx.approaching_pcu)
        fields, conf = self.feed.junction(self.tls_id, sorted(links))
        blind: frozenset[str] = frozenset()
        if self.check is not None and self.stopbar is not None:
            seen = self.feed.vehicles_seen(self.tls_id, sorted(links))
            blind = self.check.update(self._t, self.stopbar(), seen)
            self.blind_ticks += bool(blind)
        new = with_camera_state(ctx, fields, conf, mode=self.mode, blind=blind)
        self.feed.junction_ticks += 1
        self.feed.failed_junction_ticks += any(v < HARD_FAILURE for v in new.confidence.values())
        return self.inner(cfg, new)


def start_feed_thread(feed: VisionFeed, redis_url: str, *, poll_s: float = 0.2,
                      stop: threading.Event | None = None) -> threading.Thread:
    """Consume `vision.link-state` into `feed` on a daemon thread."""
    from itms_common.bus import RedisStreamsSyncConsumer  # noqa: PLC0415
    from itms_common.events import decode_envelope  # noqa: PLC0415

    consumer = RedisStreamsSyncConsumer([LINK_STATE_TOPIC], group="sim-service-vision",
                                        consumer="sim-1", url=redis_url)
    stop = stop or threading.Event()

    def loop() -> None:
        next_log = time.monotonic() + 60.0
        while not stop.is_set():
            if time.monotonic() >= next_log:
                n = max(1, feed.junction_ticks)
                log.info("vision feed: %d link-state messages so far; %.1f%% of %d junction-ticks "
                         "had a link in hard failure", feed.received,
                         100.0 * feed.failed_junction_ticks / n, feed.junction_ticks)
                next_log += 60.0
            try:
                for msg in consumer.drain(max_messages=1000):
                    try:
                        feed.on_envelope(decode_envelope(msg.raw))
                    except Exception:  # noqa: BLE001 -- one bad message must not stop the feed
                        log.exception("undecodable vision.link-state message")
                    consumer.ack(msg.topic, msg.message_id)
            except Exception:  # noqa: BLE001 -- Redis blips: keep trying; staleness covers the gap
                log.exception("vision feed read failed; retrying")
                time.sleep(1.0)
            time.sleep(poll_s)

    th = threading.Thread(target=loop, name="vision-feed", daemon=True)
    th.start()
    return th

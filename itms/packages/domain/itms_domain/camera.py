"""Camera state in a `JunctionContext` (M8) -- the one implementation both
controller adapters use: sim-service's live `control/vision_feed.py`, which
reads `vision.link-state` off the bus, and vision-service's
`sim/closed_loop.py`, which the gates run. Kept here, in the package both
already depend on, so what the gates measure and what the live controller
does cannot drift apart.

Three pieces:

- `with_camera_state`: swap the four `QueueSample` quantities in a context
  for the camera estimate. Nothing else changes; in particular
  `has_demand` / `wait_times_s` -- the safety kernel's max-wait inputs --
  stay stop-bar detection.
- `confidence_policy`: which confidence the controller hears. `failsafe`
  (the default everywhere) passes only hard failures, below 0.5; `honest`
  passes everything; `trust` passes nothing.
- `BlindCameraCheck`: the stop-bar cross-check. A camera whose detector has
  stopped finding vehicles keeps sending frames, so nothing in the vision
  service can tell its "empty road" from a road that emptied -- the
  activity check can only warn an operator. The controller can: it also
  has a stop-bar loop. A link whose loop has had vehicles over it for
  `hold_s` in all (on and off -- a queue moves up) while the camera has not
  seen a single vehicle on the link is treated as a hard failure until the
  camera sees one.

The loop is the stop-bar zone, not the whole approach: the camera sees
that zone (every planned camera covers 60 m or more from the stop line),
so a vehicle there that the camera cannot find is evidence against the
camera. The first version used `has_demand`, which the simulation's
`ActuationDetector` raises for a vehicle anywhere on a lane up to 600 m
long; vehicles far upstream, out of view, kept it high for minutes at a
time, and on TRAIN seeds it false-alarmed 34 times an hour across the
corridor at a one-minute hold.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from itms_domain.signal import JunctionContext

CAMERA_FIELDS = ("queue_pcu", "approaching_pcu", "receiving_occupancy", "receiving_queue_pcu")
HARD_FAILURE = 0.5  # the ladder's own blended threshold: below it, estimates are unusable
MODES = ("failsafe", "honest", "trust")


def confidence_policy(conf: Mapping[str, float], mode: str) -> dict[str, float]:
    """What the controller is told, per link, under `mode`."""
    if mode == "honest":
        return dict(conf)
    if mode == "failsafe":
        return {k: v for k, v in conf.items() if v < HARD_FAILURE}
    if mode == "trust":
        return {}
    raise ValueError(f"unknown mode {mode!r}")


@dataclass
class BlindCameraCheck:
    """Per junction. `update` once per controller tick with the stop-bar
    loops' presence and what the camera reports; returns the links to treat
    as a hard failure.

    Evidence is counted in *seconds the loop is occupied while the camera
    sees nothing on the link*. It is wiped the moment the camera sees a
    vehicle there, and when the loop has been empty for `gap_s` (the road
    emptied; nothing is left that the camera could be missing). `hold_s` of
    it is blindness, and the link stays failed until the camera sees a
    vehicle on it -- not merely until the loop goes quiet: the first
    version released it then, and a blinded junction flickered in and out
    of fixed-time (3.8 % of junction-ticks where a dark camera's outage
    gave 7 %), each re-entry cutting a green. Counting occupied seconds
    rather than elapsed time matters too: the first version timed an episode
    from its start and kept it alive for a while after the loop emptied, so
    once the last car had left -- the camera rightly seeing nothing -- the
    empty road counted against the camera; with its lane-long loop as well,
    it false-alarmed 266 times an hour on TRAIN seeds at a 30 s hold.

    Chosen on TRAIN seeds (`scripts/m8_blind_check_calibration.py`: 8
    fault-free runs, medium and heavy, in-domain and stock detectors, and 2
    with a junction's cameras blinded): 30 s is the shortest hold that
    still caught every blinded link (32 of 32, median 85 s) with under two
    false alarms an hour across the corridor (1.6) -- none with the
    in-domain detector on those seeds; with the stock one, in two of four
    runs, 27 s and 47 s of a junction flagged. At 20 s: 3.6 an hour; at
    45 s, a quarter of the blinded links were never caught. `gap_s` changed
    neither between 5 and 20 s (at 5 s the median detection was 94 s rather
    than 85 s)."""

    hold_s: float = 30.0
    gap_s: float = 10.0
    _evidence: dict[str, float] = field(default_factory=dict)
    _latched: set[str] = field(default_factory=set)
    _last_occupied: dict[str, float] = field(default_factory=dict)
    _last_t: dict[str, float] = field(default_factory=dict)

    def update(self, t: float, occupied: Mapping[str, bool],
               vehicles_seen: Mapping[str, float]) -> frozenset[str]:
        """`vehicles_seen[link]`: vehicles the camera tracks on the link's
        approach; a link missing from it, or reported as -1 (unknown), is
        not judged."""
        blind = set()
        for link, here in occupied.items():
            seen = vehicles_seen.get(link, -1.0)
            if seen < 0:
                continue
            dt = max(0.0, t - self._last_t.get(link, t))
            self._last_t[link] = t
            if here:
                self._last_occupied[link] = t
            if seen >= 1:                        # the camera sees traffic here: working
                self._evidence.pop(link, None)
                self._latched.discard(link)
                continue
            if link in self._latched:            # caught: failed until it sees a vehicle
                blind.add(link)
                continue
            if t - self._last_occupied.get(link, -1e18) > self.gap_s:
                self._evidence.pop(link, None)   # no traffic to be missing
                continue
            if here:
                self._evidence[link] = self._evidence.get(link, 0.0) + (dt or 1.0)
            if self._evidence.get(link, 0.0) >= self.hold_s:
                self._latched.add(link)
                blind.add(link)
        return frozenset(blind)


def with_camera_state(
    ctx: JunctionContext,
    fields: Mapping[str, Mapping[str, float]],
    confidence: Mapping[str, float],
    *,
    mode: str = "failsafe",
    blind: Iterable[str] = (),
) -> JunctionContext:
    """`ctx` with the camera's estimate in place of the four queue-state
    fields. `fields[name][link]`; a link the camera did not report reads 0.
    `confidence` is the estimator's; `blind` links (from `BlindCameraCheck`)
    are forced to 0 on top of `mode`'s policy."""
    links = set(ctx.queue_pcu) | set(ctx.approaching_pcu)

    def pick(name: str, keys: Iterable[str]) -> dict[str, float]:
        got = fields.get(name, {})
        return {k: float(got.get(k, 0.0)) for k in keys}

    conf = confidence_policy(confidence, mode)
    for link in blind:
        conf[link] = 0.0
    return replace(
        ctx,
        queue_pcu=pick("queue_pcu", ctx.queue_pcu.keys() or links),
        approaching_pcu=pick("approaching_pcu", ctx.approaching_pcu.keys() or links),
        receiving_occupancy=pick("receiving_occupancy", ctx.receiving_occupancy.keys()),
        receiving_queue_pcu=pick("receiving_queue_pcu", ctx.receiving_queue_pcu.keys()),
        confidence=conf,
    )

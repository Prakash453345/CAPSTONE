"""Perception in the loop: drive the signal controller from camera estimates
instead of SUMO ground truth, inside an ordinary `run_controlled_scenario`.

`VisionLoop` owns one `VisionSystem` fed by SimCam from the live TraCI
connection. `VisionSensor` wraps each junction's strategy exactly the way
`scripts/m5_sensor_degradation.py`'s `DegradedSensor` does: the runner builds
its `JunctionContext` from ground truth as always, and the wrapper swaps the
four queue-state fields -- and, in `"honest"` mode, the per-movement
`confidence` -- for the vision system's estimate before the controller sees
them. The runner and the controller are untouched; the difference between a
truth run and a vision run on the same seed is the perception pipeline and
nothing else.

Modes:

- `"honest"`: camera estimates plus the estimator's own confidence, so the
  controller's degradation ladder (full >= 0.8 > blended >= 0.5 > fixed-time)
  reacts to coverage, health and truncation;
- `"trust"`: camera estimates with confidence withheld (treated as 1.0) --
  what a controller that believes its cameras unconditionally would do;
- `"failsafe"`: confidence passed on only when it signals a *hard* failure
  (below 0.5: a camera offline or failed, a lane nobody sees), withheld
  otherwise. The adapter policy the M8 closed loop argued for while the
  ladder's middle rung, with no demand memory, was `fixed_time.propose` --
  M2's min-green cycler, which cut any green older than 7 s. Since the M8
  review that rung controls on the live estimate (`acamp.py`), and
  `honest` and `failsafe` make the same decisions; `failsafe` stays the
  default for a controller that has a memory to blend toward.

The stop-bar cross-check (`itms_domain.camera.BlindCameraCheck`) runs in
`honest` and `failsafe` unless `blind_check=False`: a link whose stop-bar
loop (`VisionLoop.stopbar`, emulated from the snapshot SimCam films) has
had vehicles over it for 30 s in all while the camera tracked none on that
approach is a hard failure until the camera sees a vehicle. It is what
catches a camera that still sends frames but no longer finds vehicles.
The swap and both policies are `itms_domain.camera`, shared with the live
adapter (`sim_service.control.vision_feed`).

Comparing them answers whether the ladder, fed real camera confidence,
helps or hurts -- and, with a camera outage injected, whether confidence
earns its keep when a camera really fails.

What stays ground truth, stated rather than hidden: `has_demand` and
`wait_times_s` (the safety kernel's max-wait inputs, from
`ActuationDetector`), which in a deployment would come from stop-bar
presence detection. Only the controller's *optimisation* inputs are swapped.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from itms_domain.camera import (
    HARD_FAILURE,
    MODES,
    BlindCameraCheck,
    with_camera_state,
)

from vision_service.classes import ClassTable
from vision_service.incidents.rules import TraciSignalState
from vision_service.pipeline import VisionSystem
from vision_service.simcam.world import TraciWorld, WorldSnapshot

STOPBAR_ZONE_M = 20.0  # a stop-bar loop plus the car length it detects over


class VisionLoop:
    def __init__(self, factory: Callable[[ClassTable], VisionSystem], tls_ids):
        """`factory(classes)` builds the `VisionSystem` on first use, once the
        simulation's own vehicle dimensions are known (so the twin's class
        table matches the vehicles it films)."""
        self.factory = factory
        self.world = TraciWorld()
        self.signal = TraciSignalState(tls_ids)
        self.system: VisionSystem | None = None
        self._prev: WorldSnapshot | None = None
        self._t: float | None = None
        self.ticks = 0
        # what the controller was actually fed, summarised for the report
        self.conf_n = 0
        self.conf_sum = 0.0
        self.conf_below_08 = 0
        self.conf_below_05 = 0
        self._front: dict[str, float] = {}
        self._front_t: float | None = None

    def ensure(self, sim_time: float) -> VisionSystem:
        if self._t == sim_time and self.system is not None:
            return self.system
        snap = self.world.snapshot()
        if self.system is None:
            dims = self.world.vtype_dimensions()
            classes = ClassTable.default().with_dimensions(dims) if dims else ClassTable.default()
            self.system = self.factory(classes)
            self.system.incidents.signal = self.signal
        self.signal.refresh(snap.t)
        self.system.step_world(self._prev, snap)
        res = self.system.tick(snap.t)
        for e in res.links.values():
            self.conf_n += 1
            self.conf_sum += e.confidence
            self.conf_below_08 += int(e.confidence < 0.8)
            self.conf_below_05 += int(e.confidence < 0.5)
        self._prev = snap
        self._t = sim_time
        self.ticks += 1
        return self.system

    def stopbar(self, tls_id: str, zone_m: float = STOPBAR_ZONE_M) -> dict[str, bool]:
        """The stop-bar loops of one junction, emulated from the snapshot the
        cameras film: a link's loop is occupied when some vehicle's front is
        within `zone_m` of its approach lane's end.

        An empty lane is never occupied. The first version compared a
        missing lane's position of -1 with `length - zone_m`, which is below
        -1 on a lane shorter than the zone, so on Berlin's short approach
        lanes the loop read "occupied" with nobody there, the cross-check
        called the camera blind 30 s into every run, and the controller fell
        back to fixed time about 5,000 times a run. The corridor's approach
        lanes are all longer than the zone, so its runs never met it."""
        snap, system = self._prev, self.system
        if snap is None or system is None:
            return {}
        if self._front_t != snap.t:
            front: dict[str, float] = {}
            for lane_id, pos in zip(snap.lane_id, snap.lane_pos, strict=True):
                if pos == pos and pos > front.get(lane_id, -1.0):  # NaN-safe
                    front[lane_id] = float(pos)
            self._front, self._front_t = front, snap.t
        lanes = system.rig.network.lanes
        out = {}
        for link, lane_id in system.estimator.approach_links.get(tls_id, {}).items():
            lane = lanes.get(lane_id)
            front = self._front.get(lane_id)  # type: ignore[assignment]
            out[link] = lane is not None and front is not None and front >= lane.length - zone_m
        return out

    def confidence_summary(self) -> dict:
        n = max(1, self.conf_n)
        return {"mean": self.conf_sum / n, "below_0.8": self.conf_below_08 / n,
                "below_0.5": self.conf_below_05 / n, "link_ticks": self.conf_n}


__all__ = ["HARD_FAILURE", "STOPBAR_ZONE_M", "VisionLoop", "VisionSensor"]


class VisionSensor:
    """Strategy wrapper; see module docstring. Forwards `set_sim_time` and
    `stats` explicitly (not via `__getattr__`) so the runner's `hasattr`
    duck-typing sees exactly the wrapped strategy's interface."""

    def __init__(self, inner: Any, loop: VisionLoop, tls_id: str, mode: str = "honest",
                 *, blind_check: bool | None = None):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        self.inner = inner
        self.loop = loop
        self.tls_id = tls_id
        self.mode = mode
        on = mode != "trust" if blind_check is None else blind_check
        self.check = BlindCameraCheck() if on else None
        self._t = 0.0
        self.swaps = 0
        self.blind_ticks = 0

    def set_sim_time(self, sim_time_s: float) -> None:
        self._t = sim_time_s
        self.inner.set_sim_time(sim_time_s)

    @property
    def stats(self) -> dict[str, int]:
        return self.inner.stats

    def __call__(self, cfg, ctx):
        system = self.loop.ensure(self._t)
        qs = system.estimator.queue_sample(self.tls_id)
        fields = {name: qs[name] for name in ("queue_pcu", "approaching_pcu",
                                              "receiving_occupancy", "receiving_queue_pcu")}
        blind: frozenset[str] = frozenset()
        if self.check is not None:
            blind = self.check.update(self._t, self.loop.stopbar(self.tls_id),
                                      qs.get("vehicles_seen", {}))
            self.blind_ticks += bool(blind)
        new = with_camera_state(ctx, fields, qs["confidence"], mode=self.mode, blind=blind)
        # which lanes are blocked at their head is the cameras' reading too
        # (empty without a junction-overview camera), never the simulator's
        new = replace(new, blocked_by=dict(system.estimator.blocked.get(self.tls_id, {})))
        self.swaps += 1
        return self.inner(cfg, new)

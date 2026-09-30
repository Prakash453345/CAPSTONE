"""Self-generated, exactly-labelled incidents -- the plan's pillar 4.2. A real
traffic-incident dataset can almost never tell you the exact instant an
incident began or ended; here the injector *causes* the incident, so the tick
window is known to the tick. That is what makes rigorous recall / detection-
latency scoring possible in `scripts/m6_incident_injection_gate.py`, in the
same honest gate-table style as M3-M5.

Two mechanisms, both minimal and fully reversible:

    stall       traci.vehicle.setSpeed(veh, 0) on one real vehicle for a fixed
                duration, then setSpeed(veh, -1) to hand control back to SUMO's
                car-following model. Models a broken-down vehicle holding a
                live lane.
    lane_block  traci.lane.setMaxSpeed(lane, ~0) for a duration, then restore
                the lane's original limit. Models debris / a stopped-and-
                abandoned obstruction across a lane.

The schedule is fixed at construction (typically from a seed via
`random_schedule`), so a run reproduces exactly and an incident-on vs
incident-off pair on the same seed differs *only* by these interventions --
the paired-seed design M3/M4 already use.

This is deliberately the same family of intervention as
`run_controlled_scenario`'s existing `bottleneck_lane_speeds_mps` hook
(`traci.lane.setMaxSpeed` applied once at start); the injector generalises it
to timed, per-vehicle, self-labelling events and adds the ground-truth record.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import traci

# Max speed a blocked lane is throttled to. Not a hard 0 -- SUMO treats a
# zero-speed lane as a network error in some builds, and a near-zero crawl is
# already an obstruction for every detection purpose here.
_BLOCK_SPEED_MPS = 0.1

# SUMO's own halting-speed convention (matches queue_state.py). A candidate
# stall vehicle must currently be moving faster than this -- freezing a vehicle
# that is already stopped in a queue injects nothing.
_HALTING_SPEED_MPS = 0.1

# SUMO sentinel for traci.vehicle.setSpeed: -1 releases the override and
# returns the vehicle to the car-following model.
_RELEASE_SPEED = -1.0

# A stalled vehicle must stay in its lane. `setSpeed(veh, 0)` alone does not
# do that: SUMO's lane-change model keeps moving a stationary vehicle
# sideways (observed in the M8 incident gate: one stall hopped lanes
# 1 -> 2 -> 1 -> 0 within a minute), which no broken-down car does and
# which moves the obstruction off the lane the ground truth names. Mode 0
# disables every autonomous lane change for the duration of the stall; the
# vehicle's own mode is restored on release.
_NO_LANE_CHANGES = 0


@dataclass(frozen=True)
class PlannedIncident:
    """One scheduled intervention. `start_tick` is the simulation step it is
    *requested* to begin; the realised start can be later for a stall if no
    vehicle is on the lane yet (see `IncidentWindow.actual_start_tick`)."""

    kind: str  # "stall" | "lane_block"
    lane_id: str
    start_tick: int
    duration_ticks: int

    def __post_init__(self) -> None:
        if self.kind not in ("stall", "lane_block"):
            raise ValueError(f"unknown incident kind {self.kind!r}")
        if self.duration_ticks <= 0:
            raise ValueError(f"duration_ticks must be > 0, got {self.duration_ticks}")


@dataclass(frozen=True)
class IncidentWindow:
    """The ground-truth record of one incident, finalised after the run.

    `actual_start_tick` is None iff the incident never realised (a stall whose
    lane stayed empty for its whole requested window); the gate counts only
    realised windows. `end_tick` is exclusive -- the first tick the lane/
    vehicle was back to normal. `link_ids` are the controlled movements the
    lane feeds (`L{index}`), for localization scoring; empty if the lane is
    not a signal-controlled approach.
    """

    kind: str
    lane_id: str
    intersection_id: str | None
    link_ids: tuple[str, ...]
    requested_start_tick: int
    actual_start_tick: int | None
    end_tick: int | None
    vehicle_id: str | None
    ended_reason: str  # "released" | "vehicle_gone" | "run_ended" | "never_started"

    @property
    def realised(self) -> bool:
        return self.actual_start_tick is not None

    def contains(self, tick: int) -> bool:
        """Is `tick` inside the realised ground-truth window?"""
        if self.actual_start_tick is None:
            return False
        end = self.end_tick if self.end_tick is not None else tick + 1
        return self.actual_start_tick <= tick < end


@dataclass
class _ActiveStall:
    plan: PlannedIncident
    vehicle_id: str
    started_tick: int
    lane_change_mode: int | None = None


@dataclass
class _ActiveBlock:
    plan: PlannedIncident
    original_max_speed_mps: float
    started_tick: int


def _reverse_link_lanes(
    link_lanes: Mapping[str, Mapping[str, str]],
) -> dict[str, list[tuple[str, str]]]:
    """`{tls: {L{i}: lane}}` -> `{lane: [(tls, L{i}), ...]}`. A lane can feed
    more than one link index (through + right out of one lane), so the value
    is a list."""
    rev: dict[str, list[tuple[str, str]]] = {}
    for tls_id, links in link_lanes.items():
        for link_id, lane_id in links.items():
            rev.setdefault(lane_id, []).append((tls_id, link_id))
    return rev


class IncidentInjector:
    """Drives a fixed schedule of incidents into a running SUMO scenario and
    records each one's exact tick window.

    Wire it into `run_controlled_scenario` via the `incident_injector`
    parameter: the runner calls `tick(step)` once per simulation step (after
    `traci.simulationStep()`), then `finalize(step)` once the loop ends. Read
    the labels back with `ground_truth()`.
    """

    def __init__(
        self,
        schedule: Sequence[PlannedIncident],
        *,
        link_lanes: Mapping[str, Mapping[str, str]] | None = None,
    ):
        # Sorted so `tick` can walk it with a moving cursor rather than
        # rescanning every step.
        self._schedule = sorted(schedule, key=lambda p: p.start_tick)
        self._rev_links = _reverse_link_lanes(link_lanes or {})
        self._cursor = 0
        self._active_stalls: dict[str, _ActiveStall] = {}  # keyed by lane_id
        self._active_blocks: dict[str, _ActiveBlock] = {}
        # Requested-but-not-yet-started stalls whose lane was empty at
        # start_tick -- retried each tick until their window would be over.
        self._pending_stalls: list[PlannedIncident] = []
        self._windows: list[IncidentWindow] = []

    # ---- ground truth ------------------------------------------------------

    def ground_truth(self) -> list[IncidentWindow]:
        """Every incident's finalised window, realised or not. Call after
        `finalize`."""
        return list(self._windows)

    def realised_windows(self) -> list[IncidentWindow]:
        return [w for w in self._windows if w.realised]

    def _links_for(self, lane_id: str) -> tuple[str | None, tuple[str, ...]]:
        pairs = self._rev_links.get(lane_id, [])
        if not pairs:
            return None, ()
        tls_id = pairs[0][0]
        return tls_id, tuple(link_id for _, link_id in pairs)

    # ---- per-tick driving ------------------------------------------------

    def tick(self, step: int) -> None:
        """Apply/maintain/release interventions for simulation step `step`."""
        self._release_due(step)
        self._advance_schedule(step)
        self._retry_pending(step)
        self._maintain_active(step)

    def _advance_schedule(self, step: int) -> None:
        while (
            self._cursor < len(self._schedule)
            and self._schedule[self._cursor].start_tick <= step
        ):
            plan = self._schedule[self._cursor]
            self._cursor += 1
            if plan.kind == "lane_block":
                self._start_block(plan, step)
            else:
                if not self._try_start_stall(plan, step):
                    self._pending_stalls.append(plan)

    def _retry_pending(self, step: int) -> None:
        still_pending: list[PlannedIncident] = []
        for plan in self._pending_stalls:
            if step >= plan.start_tick + plan.duration_ticks:
                # The whole requested window elapsed with the lane empty --
                # this incident never happened. Record it as such.
                tls_id, link_ids = self._links_for(plan.lane_id)
                self._windows.append(
                    IncidentWindow(
                        kind="stall",
                        lane_id=plan.lane_id,
                        intersection_id=tls_id,
                        link_ids=link_ids,
                        requested_start_tick=plan.start_tick,
                        actual_start_tick=None,
                        end_tick=None,
                        vehicle_id=None,
                        ended_reason="never_started",
                    )
                )
                continue
            if not self._try_start_stall(plan, step):
                still_pending.append(plan)
        self._pending_stalls = still_pending

    def _maintain_active(self, step: int) -> None:
        # Re-assert the stall each tick, and detect a vehicle that SUMO
        # removed under us (teleport-on-jam, or it reached its destination
        # somehow) -- end the window at this tick rather than pretending it
        # continued.
        present = set(traci.vehicle.getIDList())
        for lane_id, active in list(self._active_stalls.items()):
            if active.vehicle_id not in present:
                self._finish_stall(lane_id, step, "vehicle_gone")
                continue
            traci.vehicle.setSpeed(active.vehicle_id, 0.0)

    def _release_due(self, step: int) -> None:
        for lane_id, stall in list(self._active_stalls.items()):
            if step >= stall.started_tick + stall.plan.duration_ticks:
                self._finish_stall(lane_id, step, "released")
        for lane_id, block in list(self._active_blocks.items()):
            if step >= block.started_tick + block.plan.duration_ticks:
                traci.lane.setMaxSpeed(lane_id, block.original_max_speed_mps)
                self._close_window(
                    "lane_block",
                    lane_id,
                    requested_start_tick=block.plan.start_tick,
                    actual_start_tick=block.started_tick,
                    end_tick=step,
                    reason="released",
                    vehicle_id=None,
                )
                del self._active_blocks[lane_id]

    def finalize(self, step: int) -> None:
        """Close every still-open window at run end, and turn every
        never-realised pending stall into a `never_started` record."""
        for lane_id, stall in list(self._active_stalls.items()):
            present = stall.vehicle_id in set(traci.vehicle.getIDList())
            self._finish_stall(lane_id, step, "run_ended" if present else "vehicle_gone")
        for lane_id, block in list(self._active_blocks.items()):
            try:
                traci.lane.setMaxSpeed(lane_id, block.original_max_speed_mps)
            except traci.TraCIException:
                pass  # connection already closing -- the label is what matters
            self._close_window(
                "lane_block",
                lane_id,
                requested_start_tick=block.plan.start_tick,
                actual_start_tick=block.started_tick,
                end_tick=step,
                reason="run_ended",
                vehicle_id=None,
            )
            del self._active_blocks[lane_id]
        for plan in self._pending_stalls:
            tls_id, link_ids = self._links_for(plan.lane_id)
            self._windows.append(
                IncidentWindow(
                    kind="stall",
                    lane_id=plan.lane_id,
                    intersection_id=tls_id,
                    link_ids=link_ids,
                    requested_start_tick=plan.start_tick,
                    actual_start_tick=None,
                    end_tick=None,
                    vehicle_id=None,
                    ended_reason="never_started",
                )
            )
        self._pending_stalls = []

    # ---- mechanics ------------------------------------------------------

    def _try_start_stall(self, plan: PlannedIncident, step: int) -> bool:
        """Freeze one suitable vehicle on the lane. Returns False if the lane
        currently has none to freeze (caller retries next tick)."""
        if plan.lane_id in self._active_stalls:
            return True  # already running on this lane -- treat as started
        candidate = self._pick_stall_vehicle(plan.lane_id)
        if candidate is None:
            return False
        traci.vehicle.setSpeed(candidate, 0.0)
        mode = traci.vehicle.getLaneChangeMode(candidate)
        traci.vehicle.setLaneChangeMode(candidate, _NO_LANE_CHANGES)
        self._active_stalls[plan.lane_id] = _ActiveStall(
            plan=plan, vehicle_id=candidate, started_tick=step, lane_change_mode=mode
        )
        return True

    @staticmethod
    def _pick_stall_vehicle(lane_id: str) -> str | None:
        """The moving vehicle furthest along the lane (closest to the stop
        line) -- freezing it holds the most traffic behind it, and it is the
        least likely to be an artefact of a vehicle just entering."""
        best: tuple[float, str] | None = None
        for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
            if traci.vehicle.getSpeed(veh_id) <= _HALTING_SPEED_MPS:
                continue  # already stopped -- freezing it injects nothing
            pos = traci.vehicle.getLanePosition(veh_id)
            if best is None or pos > best[0]:
                best = (pos, veh_id)
        return best[1] if best is not None else None

    def _start_block(self, plan: PlannedIncident, step: int) -> None:
        if plan.lane_id in self._active_blocks:
            return
        original = traci.lane.getMaxSpeed(plan.lane_id)
        traci.lane.setMaxSpeed(plan.lane_id, _BLOCK_SPEED_MPS)
        self._active_blocks[plan.lane_id] = _ActiveBlock(
            plan=plan, original_max_speed_mps=original, started_tick=step
        )

    def _finish_stall(self, lane_id: str, step: int, reason: str) -> None:
        active = self._active_stalls.pop(lane_id)
        if reason != "vehicle_gone":
            try:
                traci.vehicle.setSpeed(active.vehicle_id, _RELEASE_SPEED)
                if active.lane_change_mode is not None:
                    traci.vehicle.setLaneChangeMode(active.vehicle_id, active.lane_change_mode)
            except traci.TraCIException:
                pass
        self._close_window(
            "stall",
            lane_id,
            requested_start_tick=active.plan.start_tick,
            actual_start_tick=active.started_tick,
            end_tick=step,
            reason=reason,
            vehicle_id=active.vehicle_id,
        )

    def _close_window(
        self,
        kind: str,
        lane_id: str,
        *,
        requested_start_tick: int,
        actual_start_tick: int,
        end_tick: int,
        reason: str,
        vehicle_id: str | None,
    ) -> None:
        tls_id, link_ids = self._links_for(lane_id)
        self._windows.append(
            IncidentWindow(
                kind=kind,
                lane_id=lane_id,
                intersection_id=tls_id,
                link_ids=link_ids,
                requested_start_tick=requested_start_tick,
                actual_start_tick=actual_start_tick,
                end_tick=end_tick,
                vehicle_id=vehicle_id,
                ended_reason=reason,
            )
        )


def random_schedule(
    candidate_lanes: Iterable[str],
    *,
    seed: int,
    n_incidents: int,
    run_ticks: int,
    kinds: Sequence[str] = ("stall", "lane_block"),
    duration_ticks_range: tuple[int, int] = (60, 120),
    warmup_ticks: int = 300,
    cooldown_ticks: int = 240,
    min_gap_ticks: int = 120,
) -> list[PlannedIncident]:
    """A reproducible incident schedule over `candidate_lanes` (normally the
    controlled approach lanes -- `link_to_lane_map`'s values).

    `seed` is the *incident* seed; pair it with the SUMO traffic seed so an
    incident-on run and its incident-off twin share identical base traffic.
    `warmup_ticks` keeps incidents out of the unsettled start of the run;
    `cooldown_ticks` leaves room for the longest incident to finish and be
    detected before vehicles stop arriving; `min_gap_ticks` keeps two
    incidents from overlapping in time so each contributes a clean label.
    """
    rng = random.Random(seed)
    lanes = list(candidate_lanes)
    if not lanes:
        raise ValueError("candidate_lanes is empty")

    earliest = warmup_ticks
    latest = run_ticks - cooldown_ticks - duration_ticks_range[1]
    if latest <= earliest:
        raise ValueError(
            f"run_ticks={run_ticks} too short for {n_incidents} incidents with "
            f"warmup={warmup_ticks}, cooldown={cooldown_ticks}"
        )

    starts: list[int] = []
    guard = 0
    while len(starts) < n_incidents and guard < 10_000:
        guard += 1
        t = rng.randint(earliest, latest)
        if all(abs(t - s) >= min_gap_ticks for s in starts):
            starts.append(t)
    starts.sort()

    return [
        PlannedIncident(
            kind=rng.choice(list(kinds)),
            lane_id=rng.choice(lanes),
            start_tick=t,
            duration_ticks=rng.randint(*duration_ticks_range),
        )
        for t in starts
    ]

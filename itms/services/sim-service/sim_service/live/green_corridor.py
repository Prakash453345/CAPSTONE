"""Green corridor: coordinate signals ahead of an emergency vehicle so it
meets a green at every signalised junction on its route -- without ever
commanding a signal directly.

Split in two, along the safety boundary the project direction draws:

* `GreenCorridorPlanner` turns a route + the EV's predicted progress into a
  `GreenCorridorRequest` -- an ordered set of `CorridorReservation`s
  ("hold these movements green at junction J from t0 to t1"). Pure planning,
  no TraCI, no signal commands.

* `CorridorController` holds the active corridors, advances them as the EV
  moves, and exposes `preemption_plan(cfg, ctx)` -- a *proposal* source the
  arbitration ladder consults at rung 3 (`SignalPlan(source=
  "corridor_preemption")`). The arbiter runs it through `interlocks.check`
  exactly like any strategy plan: a corridor plan that would truncate a
  min-green, skip a clearance interval, or blow the per-junction preemption
  budget is rejected there, and the junction falls back to its normal
  strategy. The controller never touches `TraCICabinet`.

Known simplification: `JunctionContext.preempt_seconds_last_hour` is not yet
fed back from the runner, so `interlocks.preempt_budget_ok` currently only
guards against a single over-long request (> `max_preempt_s_per_hour`), not
cumulative use across an hour. Sizing every hold to `<= max_green_s` keeps
that safe for a demo run; a production loop would accumulate real preemption
seconds per junction and pass them in.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field

from itms_domain import (
    CorridorReservation,
    CorridorStatus,
    EmergencyRoutingConfig,
    GreenCorridorRequest,
    JunctionContext,
    PlanStep,
    SignalPlan,
    Tier0Config,
)

from sim_service.routing import RoadGraph

log = logging.getLogger("sim-service.live.corridor")

PREEMPTION_SOURCE = "corridor_preemption"


@dataclass(frozen=True)
class JunctionCrossing:
    """One signalised junction an EV's route passes through."""

    tl_id: str
    order: int
    from_edge: str
    to_edge: str
    movements: tuple[str, ...]
    distance_m: float  # route distance from the EV's start to this junction
    eta_s: float  # free-flow travel time to it (filled by the planner)


class GreenCorridorPlanner:
    """Route + EV progress -> `GreenCorridorRequest`. No I/O."""

    def __init__(self, graph: RoadGraph, config: EmergencyRoutingConfig | None = None):
        self.graph = graph
        self.config = config or EmergencyRoutingConfig()

    def crossings(self, route_edges: tuple[str, ...]) -> list[JunctionCrossing]:
        """The signalised junctions on `route_edges`, in route order, each with
        the movement set the EV needs and the free-flow distance/time to it."""
        out: list[JunctionCrossing] = []
        dist_m = 0.0
        time_s = 0.0
        order = 0
        for i in range(len(route_edges) - 1):
            a, b = route_edges[i], route_edges[i + 1]
            info = self.graph.edges.get(a)
            if info is None:
                continue
            dist_m += info.length_m
            time_s += info.free_flow_time_s
            ge = next(
                (g for g in self.graph.neighbours(a) if g.to_edge == b),
                None,
            )
            if ge is None or not ge.signalised or not ge.tl_id:
                continue
            movements = self.graph.movements_for(ge.tl_id, a, b)
            if not movements:
                continue
            out.append(
                JunctionCrossing(
                    tl_id=ge.tl_id,
                    order=order,
                    from_edge=a,
                    to_edge=b,
                    movements=tuple(sorted(movements)),
                    distance_m=round(dist_m, 1),
                    eta_s=round(time_s, 1),
                )
            )
            order += 1
        return out

    def plan(
        self,
        *,
        corridor_id: str,
        request_id: str,
        vehicle_id: str,
        route_edges: tuple[str, ...],
        now_ms: int,
        progress_m: float = 0.0,
    ) -> GreenCorridorRequest | None:
        """Build the reservation set. `progress_m` is how far along the route
        the EV already is (0 at dispatch). Returns None if the route crosses no
        signalised junction -- there is nothing to coordinate."""
        crossings = self.crossings(tuple(route_edges))
        ahead = [c for c in crossings if c.distance_m > progress_m + 1.0]
        if not ahead:
            return None

        lead_ms = int(self.config.corridor_prepare_lead_s * 1000)
        lag_ms = int(self.config.corridor_release_lag_s * 1000)
        gap_ms = int(self.config.corridor_min_gap_s * 1000)
        # EV assumed to cruise at free-flow between here and each junction (it
        # has, by construction, a green wave): subtract the time already
        # covered so windows are anchored to *now*.
        covered_s = (
            ahead[0].eta_s * (progress_m / ahead[0].distance_m)
            if ahead[0].distance_m
            else 0.0
        )

        reservations: list[CorridorReservation] = []
        prev_close = now_ms
        for order, c in enumerate(ahead):
            arrival_ms = now_ms + max(0, int((c.eta_s - covered_s) * 1000))
            open_ms = max(now_ms, arrival_ms - lead_ms)
            close_ms = arrival_ms + lag_ms
            if open_ms < prev_close + gap_ms:
                shift = (prev_close + gap_ms) - open_ms
                open_ms += shift
                close_ms += shift
            reservations.append(
                CorridorReservation(
                    intersection_id=c.tl_id,
                    movements=c.movements,
                    open_at_ms=open_ms,
                    close_at_ms=close_ms,
                    order=order,
                )
            )
            prev_close = close_ms

        return GreenCorridorRequest(
            corridor_id=corridor_id,
            request_id=request_id,
            vehicle_id=vehicle_id,
            route_edges=tuple(route_edges),
            reservations=tuple(reservations),
            status=CorridorStatus.PROPOSED,
            created_at_ms=now_ms,
            max_simultaneous=self.config.corridor_max_simultaneous,
        )


@dataclass
class _ActiveCorridor:
    corridor: GreenCorridorRequest
    # route distance from EV start to each junction, for progress-based
    # "the EV has cleared this one" detection
    dist_by_tl: dict[str, float]
    passed: set[str] = field(default_factory=set)


class CorridorController:
    """Owns the live corridors and proposes preemptions to the arbiter."""

    def __init__(self, graph: RoadGraph, config: EmergencyRoutingConfig | None = None):
        self.graph = graph
        self.config = config or EmergencyRoutingConfig()
        self.planner = GreenCorridorPlanner(graph, self.config)
        self._active: dict[str, _ActiveCorridor] = {}
        self._by_tl: dict[str, list[str]] = {}  # tl_id -> request_ids wanting it
        self._events: list[dict] = []
        self._now_ms = 0
        self._ids = itertools.count(1)

    # ---- lifecycle ------------------------------------------------

    def activate(
        self,
        *,
        request_id: str,
        vehicle_id: str,
        route_edges: tuple[str, ...],
        now_ms: int,
        step: int | None = None,
    ) -> str | None:
        """Create and arm a corridor for `request_id`. Returns the new corridor
        id, or None if the route has no signalised junction to coordinate."""
        if request_id in self._active:
            self.deactivate(request_id, reason="superseded", step=step)
        corridor_id = f"gc-{next(self._ids):04d}"
        proposed = self.planner.plan(
            corridor_id=corridor_id,
            request_id=request_id,
            vehicle_id=vehicle_id,
            route_edges=tuple(route_edges),
            now_ms=now_ms,
        )
        if proposed is None:
            log.info("no green corridor for %s -- route crosses no signal", request_id)
            return None

        crossings = {c.tl_id: c.distance_m for c in self.planner.crossings(tuple(route_edges))}
        active = _ActiveCorridor(
            corridor=proposed.with_status(CorridorStatus.ACTIVE),
            dist_by_tl=crossings,
        )
        self._active[request_id] = active
        for r in proposed.reservations:
            self._by_tl.setdefault(r.intersection_id, []).append(request_id)
        self._emit(active.corridor, event="proposed", step=step)
        self._emit(active.corridor, event="activated", step=step)
        log.info(
            "green corridor %s armed for %s: %d junctions",
            corridor_id, request_id, len(proposed.reservations),
        )
        return corridor_id

    def deactivate(
        self, request_id: str, *, reason: str, step: int | None = None
    ) -> None:
        active = self._active.pop(request_id, None)
        if active is None:
            return
        for ids in self._by_tl.values():
            if request_id in ids:
                ids.remove(request_id)
        terminal = (
            CorridorStatus.CANCELLED
            if reason in ("request cancelled", "rerouted", "superseded")
            else CorridorStatus.COMPLETED
        )
        final = active.corridor.with_status(terminal)
        self._emit(final, event="terminated", detail=reason, step=step)
        log.info("green corridor %s ended (%s)", active.corridor.corridor_id, reason)

    # ---- per tick -----------------------------------------------

    def tick(
        self,
        step: int,
        sim_time_s: float,
        *,
        progress_by_request: dict[str, float] | None = None,
    ) -> None:
        """Advance corridor state: `_now_ms` for `preemption_plan`, and mark
        junctions the EV has physically cleared so they stop being held."""
        self._now_ms = int(sim_time_s * 1000)
        progress_by_request = progress_by_request or {}
        for request_id, active in list(self._active.items()):
            progress_m = progress_by_request.get(request_id)
            if progress_m is None:
                continue
            for tl_id, dist_m in active.dist_by_tl.items():
                if tl_id not in active.passed and progress_m > dist_m + 5.0:
                    active.passed.add(tl_id)
                    self._emit(
                        active.corridor, event="junction_passed",
                        detail=tl_id, step=step,
                    )
            if active.passed >= {r.intersection_id for r in active.corridor.reservations}:
                self.deactivate(request_id, reason="all junctions cleared", step=step)

    # ---- the arbiter hook -------------------------------------

    def preemption_plan(
        self, cfg: Tier0Config, ctx: JunctionContext, *, tick_s: float = 1.0
    ) -> SignalPlan | None:
        """Rung 3 of the arbitration ladder. Returns a
        `SignalPlan(source="corridor_preemption")` when an active corridor has
        an open window at `cfg.intersection_id` right now, else None.

        Two shapes, mirroring the strategies' own convention:

        * EV's phase already live -> a one-tick same-phase *hold* (always
          I2/I3-safe). Re-issued every tick while the window stays open.
        * EV needs a different phase -> a two-step *switch*: finish the current
          phase's remaining min-green, clear it (yellow + all-red from `cfg`),
          then the EV's phase. If the current phase hasn't served its minimum
          the first step still carries that remainder, so `min_green_satisfied`
          passes -- a corridor can delay a green, never truncate one. Genuine
          truncation (e.g. a hand-built plan with `green_s=0`) is what the
          interlock rejects, and then the arbiter falls back to the strategy.

        The arbiter runs whichever shape through `interlocks.check` before
        commanding it.
        """
        reservation = self._open_reservation(cfg.intersection_id)
        if reservation is None:
            return None

        wanted = frozenset(reservation.movements)
        target = self._phase_serving(cfg, wanted, prefer=ctx.current_phase_id)
        if target is None:
            return None

        if target == ctx.current_phase_id:
            steps: tuple[PlanStep, ...] = (PlanStep(phase_id=target, green_s=tick_s),)
        else:
            remaining_min_green = max(
                0.0,
                cfg.min_green_s.get(ctx.current_phase_id, 0.0) - ctx.current_phase_elapsed_s,
            )
            steps = (
                PlanStep(
                    phase_id=ctx.current_phase_id,
                    green_s=remaining_min_green,
                    yellow_s=cfg.yellow_s,
                    all_red_s=cfg.all_red_s,
                ),
                PlanStep(
                    phase_id=target,
                    green_s=cfg.min_green_s.get(target, 0.0),
                ),
            )
        return SignalPlan(
            intersection_id=cfg.intersection_id, steps=steps, source=PREEMPTION_SOURCE
        )

    # ---- queries ----------------------------------------------

    def active_corridor_ids(self) -> list[str]:
        return [a.corridor.corridor_id for a in self._active.values()]

    def corridor_for(self, request_id: str) -> GreenCorridorRequest | None:
        active = self._active.get(request_id)
        return active.corridor if active else None

    def drain_events(self) -> list[dict]:
        out, self._events = self._events, []
        return out

    # ---- internals ------------------------------------------

    def _open_reservation(self, tl_id: str) -> CorridorReservation | None:
        best: CorridorReservation | None = None
        for request_id in self._by_tl.get(tl_id, []):
            active = self._active.get(request_id)
            if active is None or tl_id in active.passed:
                continue
            for r in active.corridor.reservations:
                if r.intersection_id != tl_id:
                    continue
                if r.open_at_ms <= self._now_ms <= r.close_at_ms:
                    if best is None or r.close_at_ms < best.close_at_ms:
                        best = r
        return best

    @staticmethod
    def _phase_serving(
        cfg: Tier0Config, wanted: frozenset[str], *, prefer: str
    ) -> str | None:
        """The ring phase that serves the most of `wanted` *with
        protection*; `prefer` (usually the live phase) wins ties so the
        corridor doesn't switch needlessly.

        Overlap is counted over `protected_movements`, not
        `green_movements`. A movement that is only permissive in a phase
        (SUMO's 'g' -- a turn whose safety depends on the driver yielding)
        must not be what a preemption hands an emergency vehicle: the
        crew is told they hold the junction when they have only been told
        to proceed with caution (hazard D3/A5). `control/corridor/junction.
        protected_phase_for` refuses exactly this on the benchmarked path;
        the live path counted permissive greens as served and could
        preempt onto one. Four of this corridor's seven junctions carry
        such movements, each conflicting with a protected movement in its
        own phase. Same `if not None` idiom as `protected_phase_for`, for
        the reason given there: an empty protected set must read as
        "nothing protected", not fall back to the full green set."""
        best_phase: str | None = None
        best_overlap = 0
        for phase_id in cfg.ring_order:
            phase = cfg.phases.get(phase_id)
            if phase is None:
                continue
            protected = (
                phase.protected_movements
                if phase.protected_movements is not None
                else phase.green_movements
            )
            overlap = len(protected & wanted)
            if overlap > best_overlap or (
                overlap == best_overlap and overlap > 0 and phase_id == prefer
            ):
                best_phase, best_overlap = phase_id, overlap
        return best_phase if best_overlap > 0 else None

    def _emit(
        self,
        corridor: GreenCorridorRequest,
        *,
        event: str,
        detail: str = "",
        step: int | None = None,
    ) -> None:
        self._events.append(green_corridor_payload(corridor, event=event, detail=detail, step=step))


# ---------------------------------------------------------------------------
# payload builder  (matches contracts/events/green_corridor_updated.avsc)
# ---------------------------------------------------------------------------


def green_corridor_payload(
    corridor: GreenCorridorRequest,
    *,
    event: str,
    detail: str = "",
    step: int | None = None,
) -> dict:
    return {
        "corridor_id": corridor.corridor_id,
        "request_id": corridor.request_id,
        "vehicle_id": corridor.vehicle_id,
        "event": event,
        "status": corridor.status.name,
        "route_edges": list(corridor.route_edges),
        "reservations": [
            {
                "intersection_id": r.intersection_id,
                "movements": list(r.movements),
                "open_at_ms": r.open_at_ms,
                "close_at_ms": r.close_at_ms,
                "order": r.order,
            }
            for r in corridor.reservations
        ],
        "peak_concurrency": corridor.peak_concurrency(),
        "detail": detail,
        "sim_tick": step,
        "updated_at": corridor.created_at_ms,
    }

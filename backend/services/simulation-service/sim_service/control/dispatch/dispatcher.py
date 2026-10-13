"""Choosing where an emergency vehicle should go, and by which route.

The layer the project scoped to dispatch and never built, which is why
`m7_corridor_benchmark.py` carried a hardcoded arterial: the corridor
engine consumes a route, and until now nothing produced one. This
produces one.

---

**Where this sits.** Strictly above the Green Corridor Engine and
strictly outside the safety kernel. It answers "which facility, and by
what path"; the corridor engine answers "which signals, and when"; the
interlocks answer "is that legal". Nothing here can command a signal,
and a dispatch decision that is wrong produces a vehicle going to the
wrong hospital, never an unsafe junction.

That separation is also why routing is not inside `CorridorEngine`. The
engine treats the route as a live quantity it is *told* -- and already
handles it changing, which is what `ReleaseReason.ROUTE_CHANGED` is for
-- so a re-route computed here needs no cooperation from it beyond the
next position report.

---

**The decision, and its honest limits.**

    choose the facility minimising travel time,
    among those that can treat the incident,
    from the shortlist of the k nearest by air

Three things that are *not* modelled, each of which a real dispatcher
weighs and each of which would change the answer:

- **Bed and theatre availability.** The nearest capable hospital may be
  full. Nothing in OSM knows this, and a facility register that did
  would make it a filter rather than a redesign.
- **Diversion status.** Hospitals go on divert; a live feed would remove
  them from `with_capability` for the duration.
- **Clinical acuity beyond one capability token.** Real triage is not a
  single string, and `required_capability` is a deliberately thin model
  of it. See `facilities.py` for why the capability data underneath it
  cannot support more.

Stated rather than buried, because the difference between "nearest
capable facility by live travel time" and "correct hospital for this
patient" is a difference of kind, not of tuning.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sim_service.control.dispatch.facilities import GENERAL, Facility, FacilityIndex

RouteFn = Callable[[str, str], tuple[tuple[str, ...], float] | None]
"""`(from_edge, to_edge) -> (route edges, travel time s)`, or None when
no path exists.

Injected rather than imported so this module stays free of TraCI and
therefore unit-testable without a simulator -- the same split
`control/` and `signal_controller/` keep everywhere else. The live
implementation is `signal_controller.ev_routing.traci_route_fn`."""


@dataclass(frozen=True)
class IncidentRequest:
    """One call for service.

    `required_capability` defaults to `general`, which is what an
    undifferentiated emergency needs and what most of this corridor's
    hospitals offer. A specific token narrows the field, sometimes
    drastically -- this extract has 55 `general` facilities and one
    `trauma`, so a trauma request has exactly one legal destination and
    the dispatcher's job becomes trivial. That is a property of the data,
    not of the algorithm, and it is visible in `DispatchDecision.
    considered`."""

    incident_id: str
    origin_edge: str
    origin_lat: float
    origin_lon: float
    required_capability: str = GENERAL


@dataclass(frozen=True)
class DispatchDecision:
    """Where to go, how to get there, and what else was weighed.

    `considered` and `unreachable` exist so a decision can be audited
    after the fact. A dispatcher that only emits its answer cannot be
    told apart from one that had no choice -- and on this corridor,
    for several capabilities, it genuinely has no choice."""

    facility: Facility
    route_edges: tuple[str, ...]
    travel_time_s: float
    considered: int
    unreachable: int = 0
    runners_up: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    """`(facility name, travel time)` for the next-best options, so the
    margin the decision was made by is visible. A choice won by 2 seconds
    over a facility with more capacity is a different thing from one won
    by four minutes."""


def choose(
    request: IncidentRequest,
    index: FacilityIndex,
    route_fn: RouteFn,
    *,
    shortlist: int = 12,
) -> DispatchDecision | None:
    """Nearest capable facility by live travel time, or None.

    None means no capable facility was reachable -- either none has the
    capability at all, or every one of them is unroutable from the
    origin. Both are real conditions rather than errors, and the caller
    decides what to do about them; falling back to `general` is a policy
    choice this function deliberately does not make on its own, because
    "we could not reach an ophthalmic facility so we sent them to a
    general one" must be a decision someone owns.

    Routes are computed against *current* network conditions, so the
    same request answered a minute apart can legitimately choose
    different facilities. That is the point: a hospital 400 m further
    away down a clear road beats a nearer one behind a jam, and the
    corridor's own congestion state is what tells them apart."""
    candidates = index.nearest_by_air(
        request.origin_lat, request.origin_lon, request.required_capability, shortlist
    )
    if not candidates:
        return None

    scored: list[tuple[float, tuple[str, ...], Facility]] = []
    unreachable = 0
    for facility in candidates:
        routed = route_fn(request.origin_edge, facility.edge)
        if routed is None or not routed[0]:
            unreachable += 1
            continue
        edges, travel_time = routed
        scored.append((travel_time, tuple(edges), facility))

    if not scored:
        return None

    # Sorted on travel time alone; the facility id breaks exact ties so
    # the same inputs always give the same answer, for the same reason
    # the corridor engine's arbitration key is total.
    scored.sort(key=lambda row: (row[0], row[2].id))
    best_time, best_edges, best_facility = scored[0]
    return DispatchDecision(
        facility=best_facility,
        route_edges=best_edges,
        travel_time_s=best_time,
        considered=len(candidates),
        unreachable=unreachable,
        runners_up=tuple((f.name, t) for t, _, f in scored[1:4]),
    )


def should_redispatch(
    current: DispatchDecision,
    request: IncidentRequest,
    index: FacilityIndex,
    route_fn: RouteFn,
    *,
    shortlist: int = 12,
    improvement_s: float = 30.0,
) -> DispatchDecision | None:
    """A better destination, or None to stay the course.

    Re-evaluating is cheap and switching is not. A vehicle already
    committed to a hospital has a crew expecting it, and flapping between
    two facilities whose travel times cross and re-cross costs more than
    the seconds it chases -- so a new destination has to beat the current
    one by `improvement_s`, not merely beat it.

    Deliberately compares against the *current facility's* travel time
    recomputed now, not against the estimate made at dispatch. The
    original number is stale by construction; measuring improvement
    against a stale baseline would re-route on nothing more than the
    original estimate having been optimistic."""
    now = route_fn(request.origin_edge, current.facility.edge)
    current_time = now[1] if now is not None else float("inf")

    candidate = choose(request, index, route_fn, shortlist=shortlist)
    if candidate is None:
        return None
    if candidate.facility.id == current.facility.id:
        return None
    if current_time - candidate.travel_time_s < improvement_s:
        return None
    return candidate


def summarise(decision: DispatchDecision | None, request: IncidentRequest) -> str:
    """One line for a log or a demo."""
    if decision is None:
        return (
            f"{request.incident_id}: no reachable facility with "
            f"capability {request.required_capability!r}"
        )
    runners = ", ".join(f"{n} {t:.0f}s" for n, t in decision.runners_up)
    return (
        f"{request.incident_id}: {decision.facility.name} "
        f"({request.required_capability}, {decision.travel_time_s:.0f}s, "
        f"{len(decision.route_edges)} edges) "
        f"chosen from {decision.considered}"
        + (f"; next: {runners}" if runners else "")
    )


def capability_coverage(index: FacilityIndex) -> Sequence[tuple[str, int]]:
    """`(capability, facility count)`, commonest first -- the shape of
    the choice the dispatcher actually has."""
    return sorted(
        ((c, len(index.with_capability(c))) for c in index.capabilities),
        key=lambda row: (-row[1], row[0]),
    )

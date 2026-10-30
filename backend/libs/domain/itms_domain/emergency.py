"""Emergency-response domain types [project direction: EMERGENCY VEHICLE /
EMERGENCY REQUEST / GREEN CORRIDOR].

`EmergencyRequest` is a hash-chained state machine, same shape as
`incident.Incident` (shared `itms_domain.audit` primitive):

    CREATED --start_routing--> ROUTING --route_ready--> ROUTE_READY
    ROUTE_READY --activate_corridor--> GREEN_CORRIDOR_ACTIVE --depart--> IN_TRANSIT
    ROUTE_READY --dispatch--> IN_TRANSIT
    IN_TRANSIT --reroute--> IN_TRANSIT           (a new route mid-transit)
    * --arrive--> COMPLETED
    * (non-terminal) --cancel--> CANCELLED

Pure value objects: no I/O, no clock reads (times are passed in).
`RouteResult` is carried by reference (its own module); the chain only records
a route digest + score so an edit to the attached route is still detectable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from itms_domain.audit import GENESIS_HASH, entry_hash
from itms_domain.routing import RouteResult


class EmergencyKind(StrEnum):
    AMBULANCE = "ambulance"
    FIRE_TRUCK = "fire_truck"
    POLICE = "police"


class EmergencyVehicleStatus(StrEnum):
    IDLE = "idle"
    ASSIGNED = "assigned"
    EN_ROUTE = "en_route"
    ARRIVED = "arrived"


@dataclass(frozen=True)
class EmergencyVehicle:
    """A simulated responder. `home_edge` is where it waits; `current_edge` /
    `lat` / `lon` are updated from SUMO while `EN_ROUTE`. `priority` is a small
    integer, higher = outranks (used only to arbitrate two corridors wanting
    the same junction)."""

    vehicle_id: str
    kind: EmergencyKind
    status: EmergencyVehicleStatus = EmergencyVehicleStatus.IDLE
    priority: int = 1
    home_edge: str = ""
    current_edge: str = ""
    lat: float | None = None
    lon: float | None = None
    speed_mps: float = 0.0
    active_request_id: str | None = None

    def assigned_to(self, request_id: str) -> EmergencyVehicle:
        return replace(
            self,
            status=EmergencyVehicleStatus.ASSIGNED,
            active_request_id=request_id,
        )

    def released(self) -> EmergencyVehicle:
        return replace(
            self,
            status=EmergencyVehicleStatus.IDLE,
            active_request_id=None,
        )


# ---------------------------------------------------------------------------
# EmergencyRequest state machine
# ---------------------------------------------------------------------------


class EmergencyRequestState(StrEnum):
    CREATED = "created"
    ROUTING = "routing"
    ROUTE_READY = "route_ready"
    GREEN_CORRIDOR_ACTIVE = "green_corridor_active"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EmergencyRequestAction(StrEnum):
    CREATE = "create"  # genesis only
    START_ROUTING = "start_routing"
    ROUTE_READY = "route_ready"
    ROUTE_FAILED = "route_failed"
    ACTIVATE_CORRIDOR = "activate_corridor"
    DISPATCH = "dispatch"
    DEPART = "depart"
    REROUTE = "reroute"
    ARRIVE = "arrive"
    CANCEL = "cancel"


TERMINAL_REQUEST_STATES: frozenset[EmergencyRequestState] = frozenset(
    {EmergencyRequestState.COMPLETED, EmergencyRequestState.CANCELLED}
)

_S = EmergencyRequestState
_A = EmergencyRequestAction
_ALLOWED: Mapping[EmergencyRequestState, Mapping[EmergencyRequestAction, EmergencyRequestState]] = {
    _S.CREATED: {_A.START_ROUTING: _S.ROUTING, _A.CANCEL: _S.CANCELLED},
    _S.ROUTING: {
        _A.ROUTE_READY: _S.ROUTE_READY,
        _A.ROUTE_FAILED: _S.CANCELLED,
        _A.CANCEL: _S.CANCELLED,
    },
    _S.ROUTE_READY: {
        _A.ACTIVATE_CORRIDOR: _S.GREEN_CORRIDOR_ACTIVE,
        _A.DISPATCH: _S.IN_TRANSIT,
        _A.REROUTE: _S.ROUTE_READY,
        _A.CANCEL: _S.CANCELLED,
    },
    _S.GREEN_CORRIDOR_ACTIVE: {
        _A.DEPART: _S.IN_TRANSIT,
        _A.ARRIVE: _S.COMPLETED,
        _A.CANCEL: _S.CANCELLED,
    },
    _S.IN_TRANSIT: {
        _A.REROUTE: _S.IN_TRANSIT,
        _A.ARRIVE: _S.COMPLETED,
        _A.CANCEL: _S.CANCELLED,
    },
}


class IllegalRequestTransition(Exception):
    """Raised for an action the current state does not permit -- a caller bug,
    like `incident.IllegalTransition`."""


def _route_digest(route: RouteResult | None) -> str | None:
    if route is None:
        return None
    return entry_hash({"edges": list(route.edges)}, GENESIS_HASH)


@dataclass(frozen=True)
class RequestTransition:
    action: EmergencyRequestAction
    from_state: EmergencyRequestState | None
    to_state: EmergencyRequestState
    at_ms: int
    actor: str
    detail: str = ""
    route_score: float | None = None
    route_digest: str | None = None
    green_corridor_id: str | None = None
    prev_hash: str = GENESIS_HASH
    entry_hash_: str = ""

    def recomputed_hash(self) -> str:
        return entry_hash(
            {
                "action": self.action.value,
                "from_state": self.from_state.value if self.from_state is not None else None,
                "to_state": self.to_state.value,
                "at_ms": self.at_ms,
                "actor": self.actor,
                "detail": self.detail,
                "route_score": self.route_score,
                "route_digest": self.route_digest,
                "green_corridor_id": self.green_corridor_id,
            },
            self.prev_hash,
        )


@dataclass(frozen=True)
class EmergencyRequest:
    """One emergency dispatch, from creation to a terminal state. Immutable --
    every transition returns a new value. `route` is the current best route
    (None until ROUTE_READY); `green_corridor_id` is set once a corridor is
    activated."""

    request_id: str
    vehicle_id: str
    source_edge: str
    destination_edge: str
    created_at_ms: int
    state: EmergencyRequestState
    operator: str = ""
    route: RouteResult | None = None
    eta_s: float | None = None
    green_corridor_id: str | None = None
    history: tuple[RequestTransition, ...] = field(default_factory=tuple)

    # ---- derived -----------------------------------------------------

    @property
    def chain_head(self) -> str:
        return self.history[-1].entry_hash_ if self.history else GENESIS_HASH

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_REQUEST_STATES

    def routing_latency_ms(self) -> int | None:
        ready = next(
            (t for t in self.history if t.action is EmergencyRequestAction.ROUTE_READY), None
        )
        return None if ready is None else ready.at_ms - self.created_at_ms

    # ---- lifecycle -------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        vehicle_id: str,
        source_edge: str,
        destination_edge: str,
        at_ms: int,
        operator: str = "",
        detail: str = "",
    ) -> EmergencyRequest:
        genesis = _finalize(
            RequestTransition(
                action=EmergencyRequestAction.CREATE,
                from_state=None,
                to_state=EmergencyRequestState.CREATED,
                at_ms=at_ms,
                actor=operator or "system",
                detail=detail,
                prev_hash=GENESIS_HASH,
            )
        )
        return cls(
            request_id=request_id,
            vehicle_id=vehicle_id,
            source_edge=source_edge,
            destination_edge=destination_edge,
            created_at_ms=at_ms,
            state=EmergencyRequestState.CREATED,
            operator=operator,
            history=(genesis,),
        )

    def apply(
        self,
        action: EmergencyRequestAction,
        *,
        at_ms: int,
        actor: str,
        detail: str = "",
        route: RouteResult | None = None,
        eta_s: float | None = None,
        green_corridor_id: str | None = None,
    ) -> EmergencyRequest:
        """Apply `action`, returning the resulting new request. Raises
        `IllegalRequestTransition` for an action the current state disallows
        (including any action on a terminal state, and `CREATE`).

        `route` is normally passed on `ROUTE_READY` / `REROUTE`;
        `green_corridor_id` on `ACTIVATE_CORRIDOR`. Values left `None` carry
        the current ones forward.
        """
        allowed = _ALLOWED.get(self.state, {})
        if action not in allowed:
            raise IllegalRequestTransition(
                f"request {self.request_id} in {self.state.value} cannot {action.value} "
                f"(legal: {sorted(a.value for a in allowed)})"
            )
        to_state = allowed[action]

        new_route = self.route if route is None else route
        new_eta = self.eta_s if eta_s is None else eta_s
        new_corridor = self.green_corridor_id if green_corridor_id is None else green_corridor_id

        entry = _finalize(
            RequestTransition(
                action=action,
                from_state=self.state,
                to_state=to_state,
                at_ms=at_ms,
                actor=actor,
                detail=detail,
                route_score=new_route.score if new_route is not None else None,
                route_digest=_route_digest(new_route),
                green_corridor_id=new_corridor,
                prev_hash=self.chain_head,
            )
        )
        return replace(
            self,
            state=to_state,
            route=new_route,
            eta_s=new_eta,
            green_corridor_id=new_corridor,
            history=self.history + (entry,),
        )

    def verify_chain(self) -> bool:
        prev = GENESIS_HASH
        for t in self.history:
            if t.prev_hash != prev or t.entry_hash_ != t.recomputed_hash():
                return False
            prev = t.entry_hash_
        return True


def _finalize(t: RequestTransition) -> RequestTransition:
    return replace(t, entry_hash_=t.recomputed_hash())


# ---------------------------------------------------------------------------
# Green corridor
# ---------------------------------------------------------------------------


class CorridorStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    RESTORING = "restoring"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CorridorReservation:
    """One junction's slice of a green corridor: hold `movements` (link ids)
    green from `open_at_ms` to `close_at_ms`, sized around the emergency
    vehicle's predicted arrival. The Signal Controller turns this into a
    `SignalPlan(source="corridor_preemption")` and runs it through the
    interlocks -- this record never commands a signal itself."""

    intersection_id: str
    movements: tuple[str, ...]
    open_at_ms: int
    close_at_ms: int
    order: int  # position along the route, 0 = first junction the vehicle meets

    def overlaps(self, other: CorridorReservation) -> bool:
        return self.open_at_ms < other.close_at_ms and other.open_at_ms < self.close_at_ms


@dataclass(frozen=True)
class GreenCorridorRequest:
    """The full proposal handed to the Signal Controller: which junctions,
    when, in what order. Immutable; status changes return a new value."""

    corridor_id: str
    request_id: str
    vehicle_id: str
    route_edges: tuple[str, ...]
    reservations: tuple[CorridorReservation, ...]
    status: CorridorStatus = CorridorStatus.PROPOSED
    created_at_ms: int = 0
    max_simultaneous: int = 3

    def __post_init__(self) -> None:
        orders = [r.order for r in self.reservations]
        if orders != sorted(orders):
            raise ValueError("reservations must be ordered by `order` (route position)")

    @property
    def intersection_ids(self) -> tuple[str, ...]:
        return tuple(r.intersection_id for r in self.reservations)

    def peak_concurrency(self) -> int:
        """Max number of reservations whose windows overlap at once -- must
        stay <= `max_simultaneous` or the corridor gridlocks the network it is
        crossing."""
        edges: list[tuple[int, int]] = []
        for r in self.reservations:
            edges.append((r.open_at_ms, 1))
            edges.append((r.close_at_ms, -1))
        edges.sort()
        cur = peak = 0
        for _, delta in edges:
            cur += delta
            peak = max(peak, cur)
        return peak

    def with_status(self, status: CorridorStatus) -> GreenCorridorRequest:
        return replace(self, status=status)

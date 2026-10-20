"""Who gets the call: match an incident to the nearest crew, offer it, wait.

The console used to dispatch a *named* vehicle the operator picked from a
hardcoded list, which meant the operator had to know the fleet and the system
had no idea who was actually driving. Here the operator says only what the
incident needs -- an ambulance, police, a fire truck -- and this module answers
"which crew, and are they free to take it".

Shape of it, which is the Uber dispatch shape with one deliberate difference:

    incident on edge E, needs kind K
        -> candidates: on-duty, not-busy units of kind K            (roster)
        -> prefilter:  units whose cell is within `rings` of E's     (HexIndex)
        -> rank:       by RoutePlanner ETA from the unit to E        (seconds)
        -> offer to the best one, with a deadline
        -> accepted  -> the caller turns it into an emergency request
           declined  -> next candidate
           expired   -> next candidate
           exhausted -> nobody took it; the console says so

**Why ETA and not hex distance.** Uber's H3 exists to find candidates among
millions of drivers worldwide; its hexagons are an index, and the ranking that
follows is a real ETA. At this scale the index is almost free either way -- a
few dozen units -- but the ranking matters enormously, because straight-line
distance lies on this network. Two units 400 m apart across the Krishna are
6 km apart by road, and a hex-distance ranking would send the one on the wrong
bank. `RoutePlanner` with `EtaCostModel` already costs a route in seconds of
emergency-vehicle time, including signal delay and how well traffic can move
aside, so that is what decides. `HexIndex` is kept strictly as a prefilter: it
throws away units that are obviously far before the expensive planning runs,
and `rings=None` disables it entirely for small fleets.

**Why offers rather than assignment.** A crew that is at the wheel, out of the
vehicle, or already on something the system does not know about has to be able
to say no, and the next crew has to get the call without an operator noticing.
An assignment nobody acknowledged is the failure mode this avoids.

Timekeeping is the caller's simulation clock (`now_s`), never wall clock, so a
run at 10x real time expires offers at 10x too and a replay is deterministic.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from itms_domain import EmergencyKind

from sim_service.routing.graph import RoadGraph
from sim_service.routing.hexgrid import HexIndex
from sim_service.routing.planner import NoRouteError, RoutePlanner

log = logging.getLogger("sim-service.live.crew_dispatch")

OfferState = Literal["offered", "accepted", "declined", "expired", "withdrawn", "exhausted"]

# How long a crew has to answer before the call moves on. Long enough to read
# it and press a button at the wheel, short enough that an unattended tablet
# doesn't hold an ambulance out of the pool.
DEFAULT_OFFER_TIMEOUT_S = 25.0
# Candidate cells searched around the incident before planning. One cell is
# about a city block (HexIndex picks the size from the network), so 12 rings is
# roughly a 1-2 km radius. None searches the whole roster.
DEFAULT_PREFILTER_RINGS: int | None = 12
# Planning every candidate on a large roster is wasted work -- rank the nearest
# few by air distance first, then spend the planner on those.
DEFAULT_MAX_PLANNED = 8


@dataclass
class CrewUnit:
    """A vehicle and the person signed in to it.

    `crew_username` comes from the account (`app_user.unit_id`), so the system
    knows an ambulance from a patrol car without anyone choosing a "login
    type". A unit with no crew signed in is not dispatchable: there is nobody
    to answer the offer.
    """

    unit_id: str
    kind: EmergencyKind
    edge_id: str                       # where it is now (its depot while idle)
    crew_username: str | None = None
    on_duty: bool = False
    busy: bool = False
    call_sign: str = ""

    @property
    def available(self) -> bool:
        return self.on_duty and not self.busy and self.crew_username is not None

    def public(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "call_sign": self.call_sign or self.unit_id,
            "edge_id": self.edge_id,
            "crew": self.crew_username,
            "on_duty": self.on_duty,
            "busy": self.busy,
        }


@dataclass
class Offer:
    offer_id: str
    incident_id: str
    kind: EmergencyKind
    edge_id: str                       # where the incident is
    unit_id: str
    crew_username: str
    eta_s: float
    expires_at_s: float
    state: OfferState = "offered"
    # Units already asked, in order, so a decline never loops back to them.
    asked: tuple[str, ...] = ()

    def public(self) -> dict:
        return {
            "offer_id": self.offer_id,
            "incident_id": self.incident_id,
            "kind": self.kind.value,
            "edge_id": self.edge_id,
            "unit_id": self.unit_id,
            "crew": self.crew_username,
            "eta_s": round(self.eta_s, 1),
            "expires_at_s": round(self.expires_at_s, 1),
            "state": self.state,
        }


@dataclass
class _Pending:
    """An incident still looking for a crew: the open offer, and who is left."""

    incident_id: str
    kind: EmergencyKind
    edge_id: str
    queue: list[str]                   # unit ids, best ETA first
    etas: dict[str, float]
    asked: list[str] = field(default_factory=list)
    offer: Offer | None = None


class CrewRoster:
    """Which units exist, what they are, and who is signed in to them.

    Fed from the accounts database (api-service publishes it) rather than
    defined here: the fleet is whatever crew accounts exist, so creating a
    crew account *is* adding a vehicle, and there is no second list to keep
    in step.
    """

    def __init__(self, units: Iterable[CrewUnit] = ()) -> None:
        self._units: dict[str, CrewUnit] = {u.unit_id: u for u in units}

    def __len__(self) -> int:
        return len(self._units)

    def all(self) -> list[CrewUnit]:
        return list(self._units.values())

    def get(self, unit_id: str) -> CrewUnit | None:
        return self._units.get(unit_id)

    def of_kind(self, kind: EmergencyKind) -> list[CrewUnit]:
        return [u for u in self._units.values() if u.kind is kind]

    def available(self, kind: EmergencyKind) -> list[CrewUnit]:
        return [u for u in self.of_kind(kind) if u.available]

    def upsert(self, unit: CrewUnit) -> None:
        existing = self._units.get(unit.unit_id)
        # A roster refresh carries the account facts (kind, crew, duty); it must
        # not rewind live state (where the unit is, whether it is on a call).
        self._units[unit.unit_id] = (
            unit if existing is None
            else replace(unit, edge_id=existing.edge_id, busy=existing.busy)
        )

    def remove(self, unit_id: str) -> None:
        self._units.pop(unit_id, None)

    def set_position(self, unit_id: str, edge_id: str) -> None:
        u = self._units.get(unit_id)
        if u is not None:
            u.edge_id = edge_id

    def set_busy(self, unit_id: str, busy: bool) -> None:
        u = self._units.get(unit_id)
        if u is not None:
            u.busy = busy

    def set_duty(self, unit_id: str, on_duty: bool) -> None:
        u = self._units.get(unit_id)
        if u is not None:
            u.on_duty = on_duty

    def for_crew(self, username: str) -> CrewUnit | None:
        return next((u for u in self._units.values() if u.crew_username == username), None)


class CrewDispatcher:
    """Offers an incident to the nearest crew, and moves on when they don't take it.

    `on_accept(offer)` is called once, when a crew accepts; it is where the
    caller creates the emergency request and green corridor. Everything this
    class publishes goes through `drain_events()`, like the other live
    controllers, so the caller owns the bus.
    """

    def __init__(
        self,
        roster: CrewRoster,
        planner: RoutePlanner,
        graph: RoadGraph,
        *,
        on_accept: Callable[[Offer], None] | None = None,
        hex_index: HexIndex | None = None,
        offer_timeout_s: float = DEFAULT_OFFER_TIMEOUT_S,
        prefilter_rings: int | None = DEFAULT_PREFILTER_RINGS,
        max_planned: int = DEFAULT_MAX_PLANNED,
        auto_accept: bool = False,
    ) -> None:
        # auto_accept: the nearest crew is assigned the call outright instead of
        # being asked. This is a simulation with nobody at most wheels, and a
        # call that waits for a human to tap Accept never moves; the crew is
        # told by a notification on their page instead.
        self.auto_accept = auto_accept
        self.roster = roster
        self.planner = planner
        self.graph = graph
        self.hex = hex_index
        self.on_accept = on_accept
        self.offer_timeout_s = offer_timeout_s
        self.prefilter_rings = prefilter_rings
        self.max_planned = max_planned
        self._pending: dict[str, _Pending] = {}
        self._by_offer: dict[str, str] = {}      # offer_id -> incident_id
        self._events: list[dict] = []
        self._seq = 0

    # ---- events -------------------------------------------------------

    def drain_events(self) -> list[dict]:
        out, self._events = self._events, []
        return out

    def _emit(self, event_type: str, payload: dict) -> None:
        self._events.append({"event_type": event_type, "payload": payload})

    def roster_event(self) -> dict:
        return {
            "event_type": "CrewRosterUpdated",
            "payload": {"units": [u.public() for u in self.roster.all()]},
        }

    # ---- matching -----------------------------------------------------

    def _prefiltered(self, kind: EmergencyKind, edge_id: str) -> list[CrewUnit]:
        """Available units of `kind`, cheaply narrowed to ones near the incident.

        The hex prefilter is an optimisation and never the ranking: if it
        excludes everyone (a unit genuinely far away, or an incident in a part
        of the network no unit is near) we fall back to the full list rather
        than report "no crew" for a crew that exists.
        """
        units = self.roster.available(kind)
        if not units or self.hex is None or self.prefilter_rings is None:
            return units
        cells = self.hex.edge_cells.get(edge_id)
        if not cells:
            return units
        from sim_service.routing.hexgrid import disk  # noqa: PLC0415

        near: set = set()
        for c in cells:
            near |= disk(c, self.prefilter_rings)
        close = [
            u for u in units
            if any(c in near for c in self.hex.edge_cells.get(u.edge_id, ()))
        ]
        return close or units

    def rank(self, kind: EmergencyKind, edge_id: str) -> list[tuple[str, float]]:
        """(unit_id, eta_seconds) for every reachable available unit, best first.

        Unreachable units are dropped: a crew that cannot legally drive to the
        incident is not a candidate, however close it looks on the map.
        """
        units = self._prefiltered(kind, edge_id)
        if len(units) > self.max_planned:
            units = sorted(units, key=lambda u: self._air_m(u.edge_id, edge_id))[: self.max_planned]
        out: list[tuple[str, float]] = []
        for u in units:
            if u.edge_id == edge_id:
                out.append((u.unit_id, 0.0))
                continue
            try:
                routes = self.planner.plan(u.edge_id, edge_id, {})
            except NoRouteError:
                continue
            if routes:
                out.append((u.unit_id, float(routes[0].eta_s)))
        out.sort(key=lambda t: t[1])
        return out

    def _air_m(self, a: str, b: str) -> float:
        ea, eb = self.graph.edges.get(a), self.graph.edges.get(b)
        if ea is None or eb is None:
            return float("inf")
        (x0, y0), (x1, y1) = ea.start_xy, eb.start_xy
        return ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5

    # ---- lifecycle ----------------------------------------------------

    def request(
        self, incident_id: str, kind: EmergencyKind, edge_id: str, *, now_s: float
    ) -> Offer | None:
        """Start looking for a crew. Returns the first offer, or None if there
        is nobody of that kind available and reachable."""
        if incident_id in self._pending:
            return self._pending[incident_id].offer
        ranked = self.rank(kind, edge_id)
        pending = _Pending(
            incident_id=incident_id,
            kind=kind,
            edge_id=edge_id,
            queue=[uid for uid, _ in ranked],
            etas={uid: eta for uid, eta in ranked},
        )
        self._pending[incident_id] = pending
        return self._offer_next(pending, now_s=now_s)

    def _offer_next(self, pending: _Pending, *, now_s: float) -> Offer | None:
        while pending.queue:
            unit = self.roster.get(pending.queue.pop(0))
            if unit is None or not unit.available:
                continue          # went off duty or took something else meanwhile
            if self._asked_elsewhere(unit.unit_id):
                # Already being asked about another call: one question at a
                # time, or a crew that accepts both is sent two places at once.
                continue
            self._seq += 1
            offer = Offer(
                offer_id=f"off-{pending.incident_id}-{self._seq}",
                incident_id=pending.incident_id,
                kind=pending.kind,
                edge_id=pending.edge_id,
                unit_id=unit.unit_id,
                crew_username=unit.crew_username or "",
                eta_s=pending.etas.get(unit.unit_id, 0.0),
                expires_at_s=now_s + self.offer_timeout_s,
                asked=tuple(pending.asked),
            )
            pending.asked.append(unit.unit_id)
            pending.offer = offer
            self._by_offer[offer.offer_id] = pending.incident_id
            self._emit("CrewOfferUpdated", offer.public())
            log.info(
                "offered %s (%s) to %s, eta %.0fs",
                pending.incident_id, pending.kind.value, unit.unit_id, offer.eta_s,
            )
            if self.auto_accept:
                self.respond(offer.offer_id, accept=True, now_s=now_s)
            return offer
        # Nobody left. Say so rather than failing silently: the console needs to
        # tell the operator that no crew of this kind took the call.
        pending.offer = None
        self._emit(
            "CrewOfferUpdated",
            {
                "incident_id": pending.incident_id,
                "kind": pending.kind.value,
                "edge_id": pending.edge_id,
                "state": "exhausted",
                "asked": list(pending.asked),
            },
        )
        log.warning(
            "no %s crew took %s (asked %d)",
            pending.kind.value, pending.incident_id, len(pending.asked),
        )
        self._pending.pop(pending.incident_id, None)
        return None

    def respond(self, offer_id: str, *, accept: bool, now_s: float) -> Offer | None:
        """A crew answered. On accept the unit is marked busy and `on_accept`
        runs; on decline the call moves to the next nearest crew.

        Answering an offer that has already expired, been withdrawn, or been
        answered is ignored -- two taps on a flaky connection must not dispatch
        twice."""
        incident_id = self._by_offer.get(offer_id)
        pending = self._pending.get(incident_id or "")
        if pending is None or pending.offer is None or pending.offer.offer_id != offer_id:
            return None
        offer = pending.offer
        if offer.state != "offered":
            return None
        if accept:
            offer.state = "accepted"
            self.roster.set_busy(offer.unit_id, True)
            self._emit("CrewOfferUpdated", offer.public())
            self._pending.pop(pending.incident_id, None)
            if self.on_accept is not None:
                self.on_accept(offer)
            return offer
        offer.state = "declined"
        self._emit("CrewOfferUpdated", offer.public())
        return self._offer_next(pending, now_s=now_s)

    def tick(self, now_s: float) -> None:
        """Expire offers nobody answered and pass them on. Call every step."""
        for pending in list(self._pending.values()):
            offer = pending.offer
            if offer is None or offer.state != "offered" or now_s < offer.expires_at_s:
                continue
            offer.state = "expired"
            self._emit("CrewOfferUpdated", offer.public())
            log.info("offer %s expired, trying the next crew", offer.offer_id)
            self._offer_next(pending, now_s=now_s)

    def withdraw(self, incident_id: str, *, now_s: float) -> None:
        """The incident was cleared (a false alarm, or an operator stood it
        down) before anyone accepted."""
        pending = self._pending.pop(incident_id, None)
        if pending is None:
            return
        if pending.offer is not None and pending.offer.state == "offered":
            pending.offer.state = "withdrawn"
            self._emit("CrewOfferUpdated", pending.offer.public())

    def _asked_elsewhere(self, unit_id: str) -> bool:
        return any(
            p.offer is not None and p.offer.state == "offered" and p.offer.unit_id == unit_id
            for p in self._pending.values()
        )

    def release(self, unit_id: str) -> None:
        """A unit finished its call and is available again."""
        self.roster.set_busy(unit_id, False)

    @property
    def open_offers(self) -> list[Offer]:
        return [p.offer for p in self._pending.values() if p.offer is not None]


def units_from_accounts(accounts: Iterable[Mapping[str, object]]) -> list[CrewUnit]:
    """Crew accounts (api-service's roster payload) -> dispatchable units.

    An account without a unit or a crew kind is not a vehicle; operators and
    half-configured crew accounts are skipped rather than becoming phantom
    units that calls can be offered to.
    """
    out: list[CrewUnit] = []
    for a in accounts:
        unit_id = str(a.get("unit_id") or "").strip()
        raw_kind = str(a.get("crew_kind") or "").strip()
        if not unit_id or not raw_kind:
            continue
        try:
            kind = EmergencyKind(raw_kind)
        except ValueError:
            log.warning("account %s has unknown crew kind %r", a.get("username"), raw_kind)
            continue
        out.append(
            CrewUnit(
                unit_id=unit_id,
                kind=kind,
                edge_id=str(a.get("edge_id") or ""),
                crew_username=str(a.get("username") or "") or None,
                on_duty=bool(a.get("on_duty", False)),
                call_sign=str(a.get("display_name") or "") or unit_id,
            )
        )
    return out

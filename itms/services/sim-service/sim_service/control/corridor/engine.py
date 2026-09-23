"""The Green Corridor Engine: rung 3 of the arbitration ladder.

`signal_controller/arbiter.py` has reserved this rung since M2 ("3. Green
corridor preemption -- no requester yet"), deliberately absent rather than
stubbed, and `camp.py` named the thing that would eventually fill it: "the
Green Corridor Engine exists to publish real `Reservation`s". This is that
engine.

---

**What makes it a corridor engine and not seven preemptors.**

The per-junction design is the one the field actually deploys, and its
failures are structural rather than incidental. Two of them are worth
naming because the whole architecture here is a response to them.

*The emergency vehicle is blocked by the traffic its own preemption
released* (G2). A junction that reacts when the vehicle enters detector
range gives a green to an approach whose queue then has to discharge with
the vehicle behind it. Practitioner framing of the legacy design: it
"only activates when vehicles approach, leaving congestion ahead
unaddressed". The fix is not a longer green, it is an *earlier* one --
enough lead time for the queue ahead to dissipate before the vehicle
arrives -- and lead time is a route-level quantity that a junction
reacting to its own detector cannot compute.

*Adjacent junctions grant conflicting vehicles* (D11). One unit on the
arterial, another on a cross street, arriving at neighbouring junctions
seconds apart: junction n grants A, junction n+1 grants B, and A is
released into a junction being held against it. Neither controller is
wrong on its own information. Arbitration has to happen where both
requests are visible, which is here.

The measured case for route-level targeting: the University of Minnesota
dynamic route clearance work reports 10-16% emergency-vehicle travel-time
reduction on long or complex routes with "compatible network-wide
performance" -- targeting rather than blanketing, which is also the answer
to G4 (preempting junctions the vehicle never traverses is pure cost).

---

**Most of the benefit is not supposed to come from preemption.**

Preemption is expensive and the price is fixed by physics: a full
right-of-way transfer, a hold, and a recovery, paid by the cross street.
An average event runs about 25 seconds, and coordination recovery after
one has been measured at anywhere from 30 seconds to 7 minutes.

So this engine spends as little of it as possible. A junction on an active
route that is not yet being preempted is instead handed to A-CA-MP as
*anticipation* (`anticipation()` below, pressure term `A(p)`): ordinary,
legal, non-preemptive control, biased toward clearing the vehicle's path
before it arrives. That costs nothing from the preemption budget, holds no
cross street on red, and does the work G2 identifies -- dissipating the
queue ahead -- through the mechanism already proven to be throughput-
optimal. Preemption is then only the last-metre guarantee.

The complement is `DebtLedger` (pressure term `D(p)`): what preemption
does spend is recorded per movement and repaid by the same controller.
Together these two are the project's stated Contribution 1, and they are
the reason the corridor engine is a *pressure-function* contribution
rather than a preemption module bolted onto one.

---

**Authority.** This engine proposes; it never commands. Every plan it
produces goes through `interlocks.check` unchanged, and a plan that fails
is a denial that falls through to ordinary control, not a fault -- see
`junction.py`'s module docstring for why that distinction is the load-
bearing one in the whole design. NTCIP 1211 draws the same line for the
same reason: the Priority Request Generator asks, the Priority Request
Server decides, and the Coordinator retains authority -- "a CO cannot be
commanded to service a priority request".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from itms_domain import JunctionContext, SignalPlan, Tier0Config, Violation

from sim_service.control.corridor.debt import DebtLedger
from sim_service.control.corridor.junction import (
    Confirmation,
    DeferReason,
    JunctionPreemption,
    ReleaseReason,
    protected_phase_for,
    transfer_time,
)
from sim_service.control.corridor.requests import (
    PreemptionClass,
    Reservation,
    VehicleReport,
)

_ROLLING_HOUR_S = 3600.0
_EPS = 1e-9


@dataclass(frozen=True)
class CorridorConfig:
    """Tier-1 tunables for the engine. Every default here is sourced from
    a measurement or a published practice rather than chosen, and the
    source is named on each."""

    acceptance_dwell_s: float = 2.0
    """How long a request must persist before it is honoured. St. Paul's
    figure, adopted there specifically "to reduce the number of
    inadvertent preemptions triggered when preemption equipped vehicles
    make turns in areas with closely spaced parallel streets" (E8) -- a
    vehicle turning sweeps its emitter across detectors for junctions it
    never intends to use."""

    report_ttl_s: float = 6.0
    """How long a position report stays usable. This is the bound that
    makes E10 survivable: a corridor system commits to junctions ahead of
    the vehicle, so an ETA computed from a report that has stopped
    arriving is the specific way route-based preemption fails worse than
    the point-detection kind it improves on. Short enough that a stopped
    or diverted vehicle releases its corridor within a few seconds, long
    enough to ride through the detection dropouts of E4 -- a truck, a
    curve, heavy rain, direct sun into an optical receiver."""

    latency_margin_s: float = 1.0
    """Budgeted end-to-end request latency, added to every lead time.
    Li et al.'s "compensated distance" strategy for connected-vehicle EVP:
    trigger far enough upstream to absorb the delay from request to
    controller action, rather than discovering it at the stop line (E2).
    One second is this simulator's own step; a cellular deployment would
    need its measured value, and the parameter exists so that value has
    somewhere to go."""

    base_lead_s: float = 20.0
    """Ordinary advance, in seconds, under everything the lead-time
    formula computes. At this corridor's emergency speed that is roughly
    440 m -- between the 300 m the reactive baseline uses and the
    1,600-2,300 ft (490-700 m) of the Fairfax County and St. Paul
    installations, and *time* rather than distance so it adapts to how
    fast the vehicle is actually travelling, which is the one thing a
    fixed range cannot do. See `_should_claim` for the ablation that
    forced this floor to exist."""

    max_lead_s: float = 45.0
    """Ceiling on how far ahead of arrival a junction may be claimed.
    Without it, a jammed downstream link makes the computed lead time
    arbitrarily large and the engine claims the whole corridor minutes in
    advance for a vehicle that may turn off it (G4). Preemption's cost is
    paid whether or not the vehicle arrives."""

    max_dwell_s: float = 40.0
    """Hard bound on one junction's preemption, the controller-side half
    of E7/F9. FHWA on the vehicle side: an emergency vehicle stopped near
    an intersection with a running emitter "will hold the signal in the
    preemption phase indefinitely, causing significant traffic problems",
    and Fairfax County and Plano each built custom emitter power-interrupt
    hardware because nothing downstream of the emitter bounded it.
    Sized against the ~25 s average event duration with margin for a
    slow approach, not against a worst case -- a bound only reached in
    the worst case is not doing any work."""

    dwell_commit_s: float = 12.0
    """What an entry plan charges to the preemption-hour budget. A
    commitment, not a prediction: the budget check has to see the cost of
    the hold at the moment entry is decided, or a request is granted with
    the budget intact and released halfway through the hold, which spends
    the transfer time and gets none of the benefit."""

    headroom_margin_s: float = 20.0
    """I5 slack that must remain for a release to complete: yellow, all
    red, and enough of the recovering phase for the starved movement to
    actually be served. See `junction.max_wait_headroom_s`."""

    stopped_speed_mps: float = 1.0
    stopped_grace_s: float = 8.0
    """A track whose smoothed speed stays below `stopped_speed_mps` for
    `stopped_grace_s` is treated as stopped and its reservations released
    (E7 at the scene, E10 en route). The grace period is what
    distinguishes a vehicle stopped at an incident from one momentarily
    held in the queue it is about to be given a green through -- releasing
    on the second would make the engine abandon precisely the vehicles it
    is working hardest for."""

    speed_halflife_s: float = 3.0
    """Half-life of the speed EWMA the ETA is computed from. Short: this
    smooths sensor noise, it does not model the vehicle."""

    rho_couple: float = 0.4
    """Receiving-link occupancy above which the link to the next junction
    is treated as needing to be cleared *before* the vehicle arrives, not
    merely traversed -- G3, the short-link case where the clearance
    movement at junction n discharges into a link to n+1 that is still
    red, fills it, and gridlocks the junction with the emergency vehicle
    inside it. Structurally the Fox River Grove failure with a signal in
    place of a railroad. Handled by lengthening n's lead time by the
    downstream queue's discharge time, so the pair is cleared in sequence,
    rather than by refusing to open n -- refusing leaves the vehicle
    stopped just as surely."""

    confidence_floor: float = 0.4
    """Smallest fraction of `max_lead_s`/`max_dwell_s` a badly-degraded
    track may still commit. See `_Track.commitment_scale`: below this the
    commitment gets too short to complete a right-of-way transfer, which
    spends the entry cost and never reaches the dwell."""

    anticipation_horizon_s: float = 60.0
    """How far ahead of arrival `A(p)` starts biasing ordinary control
    toward the vehicle's path. Longer than `max_lead_s` on purpose:
    anticipation is free and preemption is not, so the cheap mechanism
    should start first and do as much of the work as it can."""


@dataclass
class _Track:
    """One emergency vehicle the engine is following."""

    vehicle_id: str
    priority: PreemptionClass
    first_seen_s: float
    report: VehicleReport
    smoothed_speed_mps: float
    moving_since_s: float
    previous_route: tuple[str, ...] = ()
    """The route as of the last report, kept solely to tell a *passage*
    apart from a *reroute*.

    Both look identical in one snapshot -- a junction that was on the
    route is not on it any more -- and they are opposite outcomes: a
    passage means the preemption did its job, a reroute means the
    corridor was held for a vehicle that went elsewhere (G4). Counting
    them together makes the release-reason distribution, which exists to
    answer "is this working", unable to answer it.

    The rule is positional. The route is ordered nearest-first, so
    junctions the vehicle drives past leave from the *front*; a junction
    that disappears from the middle or the end left because the route
    changed. A dropped prefix is a passage and anything else is a
    reroute."""

    def dropped_by_passing(self) -> frozenset[str]:
        remaining = set(self.report.route)
        prefix: set[str] = set()
        for junction_id in self.previous_route:
            if junction_id in remaining:
                break
            prefix.add(junction_id)
        return frozenset(prefix)

    def eta_s(self, junction_id: str, cfg: CorridorConfig) -> float:
        distance = self.report.distance_to_m.get(junction_id)
        if distance is None:
            return float("inf")
        speed = max(self.smoothed_speed_mps, _EPS)
        if speed < cfg.stopped_speed_mps:
            return float("inf")
        return distance / speed

    def stopped(self, now_s: float, cfg: CorridorConfig) -> bool:
        return (
            self.smoothed_speed_mps < cfg.stopped_speed_mps
            and now_s - self.moving_since_s >= cfg.stopped_grace_s
        )

    def accepted(self, now_s: float, cfg: CorridorConfig) -> bool:
        return now_s - self.first_seen_s >= cfg.acceptance_dwell_s

    def commitment_scale(self, cfg: CorridorConfig) -> float:
        """How far this track's detection quality justifies committing, in
        `[confidence_floor, 1]`.

        Degraded detection is the normal condition of a real corridor, not
        an exception: GPS in an urban canyon is worst exactly where
        junctions are densest (E14), an optical receiver loses a genuine
        signal to heavy rain or direct sun (E11), and a truck or a curve
        breaks line of sight for seconds at a time (E4). A system that
        only works on clean data does not work.

        So low confidence is never a reason to refuse a request -- an
        emergency vehicle seen poorly is still an emergency vehicle -- and
        always a reason to commit *less*: claim junctions later, and hold
        them for less time. Both are scaled together, because they fail
        the same way. A long lead time on a bad position estimate claims a
        junction for a vehicle that may not be where it is thought to be,
        and a long dwell on the same estimate holds it after the vehicle
        has gone.

        The floor keeps a badly-degraded track from collapsing to a
        commitment so short that the junction cannot complete a
        right-of-way transfer inside it -- which would spend the entry
        cost and never reach the dwell, the worst of both."""
        return max(cfg.confidence_floor, min(1.0, self.report.confidence))

    @property
    def coalesce_key(self) -> str:
        """Vehicles sharing this key are one interruption, not several
        (G5). Falls back to the vehicle's own id when dispatch has not
        supplied a response, so unknown never merges with unknown."""
        return self.report.response_id or f"vehicle:{self.vehicle_id}"


class CorridorEngine:
    """Corridor-wide preemption. One instance per corridor, shared by the
    arbiter (which asks it for plans) and by A-CA-MP (which asks it for
    anticipation and debt).

    Satisfies the arbiter's `CorridorPort` protocol: `propose` returns a
    plan or None, and `denied` is called when a plan it produced was
    rejected by the interlocks."""

    def __init__(
        self,
        cfg: CorridorConfig | None = None,
        *,
        authorized: Mapping[str, PreemptionClass] | None = None,
        debt_half_life_s: float = 120.0,
    ) -> None:
        self.cfg = cfg or CorridorConfig()
        self._authorized = dict(authorized or {})
        """Vehicle id -> class. The engine's answer to E13.

        A request does not get to say what it is. Homemade infrared
        transmitters reproducing a vendor's pulse-length-modulated
        protocol are demonstrated, not hypothetical -- an Arduino Nano and
        an infrared LED array -- and the deterrent that exists (SAFETEA,
        August 2005: six months' minimum imprisonment for illegal use) is
        deterrence rather than prevention. MUTCD 11th Ed. guidance is that
        EVP equipment "should encode vehicle IDs"; FHWA's rationale is
        that codes "provide a record of which operator drove the vehicle,
        as well as protect against unauthorized use". An id absent from
        this table is logged and dropped, and the drop is counted --
        H2's non-emergency use is found by auditing that counter against
        dispatch records, which is only possible if unauthorized requests
        leave a trace."""
        self.debt = DebtLedger(half_life_s=debt_half_life_s)
        self._tracks: dict[str, _Track] = {}
        self._junctions: dict[str, JunctionPreemption] = {}
        self._winner: dict[str, str] = {}
        self._preempt_log: dict[str, list[tuple[float, float]]] = {}
        self._now_s: float = 0.0
        self._tick_s: float = 1.0
        self.counters: dict[str, int] = {
            "reports": 0,
            "unauthorized": 0,
            "reservations_granted": 0,
            "denied_by_interlock": 0,
            "coalesced": 0,
            "arbitration_conflicts": 0,
        }

    # -- ingestion ----------------------------------------------------

    def authorize(self, vehicle_id: str, priority: PreemptionClass) -> None:
        self._authorized[vehicle_id] = priority

    def submit(self, report: VehicleReport) -> bool:
        """Ingest one observation. Returns whether it was accepted.

        Rejection here is an authorization failure, which is a security
        event; a *request* that is authorized but not served is a
        different thing entirely and is counted separately (see
        `JunctionPreemption.defers`)."""
        self.counters["reports"] += 1
        priority = self._authorized.get(report.vehicle_id)
        if priority is None:
            self.counters["unauthorized"] += 1
            return False

        existing = self._tracks.get(report.vehicle_id)
        if existing is None:
            self._tracks[report.vehicle_id] = _Track(
                vehicle_id=report.vehicle_id,
                priority=priority,
                first_seen_s=report.observed_at_s,
                report=report,
                smoothed_speed_mps=report.speed_mps,
                moving_since_s=report.observed_at_s,
            )
            return True

        elapsed = max(0.0, report.observed_at_s - existing.report.observed_at_s)
        decay = 0.5 ** (elapsed / max(_EPS, self.cfg.speed_halflife_s))
        smoothed = decay * existing.smoothed_speed_mps + (1.0 - decay) * report.speed_mps
        existing.smoothed_speed_mps = smoothed
        existing.previous_route = existing.report.route
        existing.report = report
        existing.priority = priority
        if smoothed >= self.cfg.stopped_speed_mps:
            existing.moving_since_s = report.observed_at_s
        return True

    # -- per-tick corridor-wide work ----------------------------------

    def begin_tick(self, now_s: float) -> None:
        """Age tracks, drop the ones that have gone quiet, and decide
        which vehicle holds each junction.

        Called once per simulation step, before any junction's `propose`.
        Arbitration is a pure function of the tracks -- priority, request
        time, identity, route -- so it needs no junction context and
        cannot disagree with itself between junctions within a tick, which
        is the property D11 requires."""
        if now_s > self._now_s:
            self._tick_s = now_s - self._now_s
        self._now_s = now_s
        self.debt.decay_to(now_s)

        for vehicle_id, track in list(self._tracks.items()):
            age = now_s - track.report.observed_at_s
            if age > self.cfg.report_ttl_s or track.stopped(now_s, self.cfg):
                del self._tracks[vehicle_id]

        self._winner = self._arbitrate(now_s)

        # Junctions whose winner changed, or which no longer have one,
        # release now rather than at their next `propose` -- a junction
        # mid-transition is skipped by the runner and would otherwise hold
        # a reservation for a vehicle that has already gone.
        for junction_id, jp in self._junctions.items():
            if jp.reservation is None:
                continue
            winner = self._winner.get(junction_id)
            held = jp.reservation.vehicle_id
            if winner == held:
                continue
            held_track = self._tracks.get(held)
            if held_track is None:
                jp.release(ReleaseReason.STALE_REPORT)
            elif junction_id in held_track.dropped_by_passing():
                jp.release(ReleaseReason.PASSED)
            elif junction_id not in held_track.report.route:
                jp.release(ReleaseReason.ROUTE_CHANGED)
            elif winner is not None:
                jp.release(ReleaseReason.SUPERSEDED)
            else:
                jp.release(ReleaseReason.PASSED)

    def _arbitrate(self, now_s: float) -> dict[str, str]:
        """Which vehicle holds each junction on its route.

        The comparison key is `(priority, first_seen_s, vehicle_id)`, in
        that order, and each element earns its place:

        - `priority` is MUTCD's controllability ordering, lower wins. See
          `PreemptionClass` -- and note the catalogue's warning that the
          *direction* of such orderings is the thing vendors and documents
          disagree about (D7), which is why a test enumerates every pair
          rather than trusting this comment.
        - `first_seen_s` is order of arrival within a class, NEMA TS2's
          rule for non-priority calls. It is not sufficient on its own:
          D6's failure is a continuously-asserted call starving an
          equal-priority one forever. It cannot happen here, because a
          track expires on `report_ttl_s` and a dwell expires on
          `max_dwell_s`, so no call is permanent and this decision is
          retaken every tick.
        - `vehicle_id` breaks exact ties. A tie-break that is not total is
          a tie-break that depends on dictionary ordering, and D1's
          scenario -- two units, conflicting approaches, within a second
          of each other -- is the one where a nondeterministic answer is
          least acceptable. This is the single most dangerous EVP
          scenario in the literature and the one that produced the 1972
          St. Paul fatality; the answer here is arbitrary but it is always
          the same arbitrary answer, and the loser gets a flashing
          confirmation rather than nothing.

        Coalescing (G5) happens before the comparison: units sharing a
        `response_id` at the same junction are one claimant, represented
        by whichever of them is nearest, so a multi-alarm response is one
        interruption per junction rather than one per appliance."""
        claims: dict[str, list[_Track]] = {}
        for track in self._tracks.values():
            if not track.accepted(now_s, self.cfg):
                continue
            for junction_id in track.report.route:
                claims.setdefault(junction_id, []).append(track)

        winners: dict[str, str] = {}
        for junction_id, contenders in claims.items():
            if len(contenders) > 1:
                self.counters["arbitration_conflicts"] += 1
            by_response: dict[str, _Track] = {}
            for track in contenders:
                key = track.coalesce_key
                incumbent = by_response.get(key)
                if incumbent is None:
                    by_response[key] = track
                    continue
                self.counters["coalesced"] += 1
                if track.eta_s(junction_id, self.cfg) < incumbent.eta_s(
                    junction_id, self.cfg
                ):
                    by_response[key] = track
            winners[junction_id] = min(
                by_response.values(),
                key=lambda t: (int(t.priority), t.first_seen_s, t.vehicle_id),
            ).vehicle_id
        return winners

    # -- the CorridorPort protocol ------------------------------------

    def propose(self, cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan | None:
        """This junction's preemption plan for this tick, or None."""
        junction_id = cfg.intersection_id
        jp = self._junctions.setdefault(junction_id, JunctionPreemption(junction_id))

        # Settle debt for whatever is green right now, before any branch
        # can return. Placed here and not in one of the branches below
        # because repayment has nothing to do with whether a preemption
        # is running: the overwhelming majority of the seconds that repay
        # a movement are ordinary green given by the ordinary controller,
        # long after the preemption that caused the debt has ended. A
        # repayment hook that only fired while preempting would never
        # settle anything. See `DebtLedger.repay` for what its absence
        # measured.
        current = cfg.phases.get(ctx.current_phase_id)
        if current is not None:
            self.debt.repay(junction_id, current.green_movements, self._tick_s)

        winner = self._winner.get(junction_id)
        if winner is None:
            return None
        track = self._tracks.get(winner)
        if track is None:
            return None

        movement = track.report.movement_at.get(junction_id)
        if movement is None:
            return None
        target = protected_phase_for(cfg, movement)
        if target is None:
            jp._defer(DeferReason.NO_PROTECTED_PHASE)  # noqa: SLF001
            return None

        if jp.reservation is None:
            if not self._should_claim(cfg, ctx, track, target, movement):
                return None
            jp.grant(
                Reservation(
                    vehicle_id=track.vehicle_id,
                    junction_id=junction_id,
                    priority=track.priority,
                    movement=movement,
                    granted_at_s=self._now_s,
                    expires_at_s=self._now_s
                    + self.cfg.max_dwell_s * track.commitment_scale(self.cfg),
                ),
                target,
                self._now_s,
            )
            self.counters["reservations_granted"] += 1

        before = jp.preempted_s
        plan = jp.propose(
            cfg,
            ctx,
            self._now_s,
            tick_s=1.0,
            dwell_commit_s=self.cfg.dwell_commit_s,
            headroom_margin_s=self.cfg.headroom_margin_s,
        )
        spent = jp.preempted_s - before
        if spent > 0.0:
            self._preempt_log.setdefault(junction_id, []).append((self._now_s, spent))
            phase = cfg.phases.get(target)
            served = phase.green_movements if phase is not None else frozenset()
            held = [m for m in _all_movements(cfg) if m not in served]
            self.debt.incur(junction_id, held, spent)
        return plan

    def denied(
        self, cfg: Tier0Config, ctx: JunctionContext, violations: list[Violation]
    ) -> None:
        """A plan this engine produced was rejected by the interlocks.

        That is a bug in this engine, not a fault at the junction: every
        rejection reachable from here is one `junction.py` computes for
        itself first, so reaching this method means one of those
        computations disagreed with the interlock. The reservation is
        dropped so the junction runs normally, and the event is counted --
        `denied_by_interlock` should be zero on every run, and the
        benchmark reports it precisely so that "should" is checked rather
        than assumed."""
        self.counters["denied_by_interlock"] += 1
        jp = self._junctions.get(cfg.intersection_id)
        if jp is not None:
            jp.release(ReleaseReason.SUPERSEDED)

    def _should_claim(
        self,
        cfg: Tier0Config,
        ctx: JunctionContext,
        track: _Track,
        target: str,
        movement: str,
    ) -> bool:
        """Is it time to claim this junction?

        Lead time, not distance. A fixed detection range is what the field
        deploys -- Fairfax County about 1,600 ft, St. Paul up to about
        2,300 ft "to accommodate police vehicles, which accelerate
        quickly" -- and it is a proxy for the quantity that actually
        matters, which is whether the junction can be ready in time. That
        proxy fails in both directions: too short and E1 happens (the
        vehicle outruns the preemption, arriving against a red it has
        learned to expect will be green), too long and G4 happens (cost
        paid at junctions the vehicle never reaches).

        The quantity itself is available here, so it is computed:

            lead = transfer + discharge_ahead + downstream_clear + latency

        `transfer` is how long the junction needs to legally show the
        vehicle's phase, which varies from zero to twenty-odd seconds
        depending on where in the cycle the request lands -- the exact
        variability E1 is about. `discharge_ahead` is how long the queue
        in front of the vehicle takes to clear at saturation flow, which
        is G2's requirement that the preemption dissipate the queue rather
        than merely hold a green. `downstream_clear` adds the same for the
        receiving link when it is loaded past `rho_couple`, which is G3's
        short-link coupling. `latency` is E2's compensated distance.

        Capped at `max_lead_s`, and requiring the vehicle to be genuinely
        inbound: a track with no distance to this junction, or one whose
        smoothed speed says it is stopped, has an infinite ETA and claims
        nothing.

        ---

        **`base_lead_s` is a floor under all of that, and leaving it out
        was a measured mistake.**

        The first version used the computed sum alone, on the reasoning
        that a lead time derived from what the junction actually needs
        must beat a fixed detection range. The M7 ablation says
        otherwise, and unambiguously: with both pressure terms zeroed so
        only the trigger differed, the computed-lead arm cost the
        emergency vehicle **+111.5 s of travel time [+93.5, +129.5]**
        against a plain 300 m fixed range.

        The error is in what the sum *is*. `transfer + discharge +
        downstream + latency` is a **lower bound on sufficiency** -- the
        least advance at which the junction could possibly be ready --
        and triggering on a lower bound means arriving at the moment of
        sufficiency with zero margin. Every source of error then costs
        the vehicle a stop: a speed estimate that was slightly high, a
        vehicle that joins the queue after the claim, the phase not yet
        settled. And the sum is small in the common case, because the
        dominant term is `transfer`, which collapses to yellow plus
        all-red once the current phase has served its minimum green --
        about 8 s, roughly 180 m at emergency speed, well inside the
        300 m the baseline used and far inside the 1,600-2,300 ft real
        installations use.

        So the computed terms do what they were derived to do -- *raise*
        the lead when a queue must be dissipated (G2) or a short
        downstream link cleared (G3) -- and `base_lead_s` supplies the
        ordinary advance underneath them. Claiming early is not free, but
        it is only wasted when the vehicle does not arrive, and G4's
        answer to that is route awareness, which this engine already
        has."""
        eta = track.eta_s(cfg.intersection_id, self.cfg)
        if eta == float("inf"):
            return False
        sat = max(cfg.sat_flow_pcu_s.get(movement, 0.0), _EPS)
        discharge_ahead = ctx.queue_pcu.get(movement, 0.0) / sat
        downstream = 0.0
        if ctx.receiving_occupancy.get(movement, 0.0) > self.cfg.rho_couple:
            downstream = ctx.receiving_queue_pcu.get(movement, 0.0) / sat
        lead = max(
            self.cfg.base_lead_s,
            transfer_time(cfg, ctx, target).total_s
            + discharge_ahead
            + downstream
            + self.cfg.latency_margin_s,
        )
        return eta <= min(lead, self.cfg.max_lead_s * track.commitment_scale(self.cfg))

    # -- what other subsystems read -----------------------------------

    def preempt_seconds_last_hour(self, junction_id: str, now_s: float) -> float:
        """Fills `JunctionContext.preempt_seconds_last_hour`, which nothing
        populated before M7 -- so `interlocks.preempt_budget_ok`, written
        in M2 specifically for this requester, had never once been able to
        fire. The interlock was correct and unreachable; this is the
        measurement that makes it reachable."""
        entries = self._preempt_log.get(junction_id)
        if not entries:
            return 0.0
        cutoff = now_s - _ROLLING_HOUR_S
        while entries and entries[0][0] < cutoff:
            entries.pop(0)
        return sum(seconds for _, seconds in entries)

    def anticipation(self, junction_id: str) -> Mapping[str, float]:
        """Per-movement urgency in [0, 1] for A-CA-MP's `A(p)` term.

        One means the vehicle is arriving now; zero means it is beyond the
        anticipation horizon or not coming. Only movements on a live
        track's route appear, so a corridor with no active response
        returns an empty mapping and `A(p)` is identically zero -- the
        controller is bit-for-bit its ordinary self whenever nothing is
        responding, which is what makes the term's effect attributable."""
        out: dict[str, float] = {}
        horizon = max(_EPS, self.cfg.anticipation_horizon_s)
        for track in self._tracks.values():
            if junction_id not in track.report.route:
                continue
            movement = track.report.movement_at.get(junction_id)
            if movement is None:
                continue
            eta = track.eta_s(junction_id, self.cfg)
            if eta == float("inf"):
                continue
            urgency = max(0.0, min(1.0, 1.0 - eta / horizon))
            out[movement] = max(out.get(movement, 0.0), urgency)
        return out

    def confirmation(
        self, junction_id: str, cfg: Tier0Config, ctx: JunctionContext
    ) -> Confirmation:
        jp = self._junctions.get(junction_id)
        return Confirmation.NONE if jp is None else jp.confirmation(cfg, ctx)

    def active_at(self, junction_id: str) -> bool:
        jp = self._junctions.get(junction_id)
        return jp is not None and jp.reservation is not None

    def stats(self) -> dict[str, float]:
        out: dict[str, float] = dict(self.counters)
        for junction_id, jp in self._junctions.items():
            for key, value in jp.stats().items():
                out[key] = out.get(key, 0.0) + value
            out[f"preempted_s/{junction_id}"] = jp.preempted_s
        return out


def _all_movements(cfg: Tier0Config) -> frozenset[str]:
    if not cfg.phases:
        return frozenset()
    return frozenset().union(*(p.green_movements for p in cfg.phases.values()))


def movements_of(cfg: Tier0Config, phase_ids: Iterable[str]) -> frozenset[str]:
    out: set[str] = set()
    for phase_id in phase_ids:
        phase = cfg.phases.get(phase_id)
        if phase is not None:
            out |= set(phase.green_movements)
    return frozenset(out)


__all__ = [
    "CorridorConfig",
    "CorridorEngine",
    "Confirmation",
    "DeferReason",
    "PreemptionClass",
    "ReleaseReason",
    "Reservation",
    "VehicleReport",
]

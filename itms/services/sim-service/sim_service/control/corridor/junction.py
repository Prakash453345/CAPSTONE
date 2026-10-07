"""One junction's preemption state machine: entry, dwell, release.

Pure functions and one small stateful class, no I/O and no clock reads --
time arrives as a parameter exactly as it does everywhere else in
`control/`, which is what lets the whole hazard catalogue below be
exercised in unit tests rather than only in a simulator.

---

**The rule the rest of this module is built around: never propose a plan
the interlocks will reject.**

This is not a style preference, it is forced by what rejection *means*
here. `signal_controller/arbiter.py` responds to a failing
`interlocks.check` by commanding all-red and returning a failsafe mode;
`control/runner.py` then logs a fault and resets the junction's context.
That is the correct response to a fixed-time plan failing, because
nothing sits below fixed-time to fall back to. It is the worst possible
response to a *preemption* plan failing: the emergency vehicle arrives at
a junction sitting in solid all-red, and the cross street it was meant to
be held against is stopped too.

So a rejected preemption is treated as a **denial**, not a fault: the
corridor rung withdraws and the ordinary adaptive controller runs the
junction as if no request had been made. Two consequences shape the code:

1. This module computes, before proposing anything, whether the proposal
   *could* be rejected -- remaining minimum green (I3), a pedestrian phase
   mid-interval (I4), a starved cross movement at its maximum wait (I5),
   the preemption-hour budget. Where it cannot yet act it holds the
   current phase rather than demanding a switch it knows will bounce.
2. The denial is never silent. H1 in the hazard catalogue is explicit
   that a frequency cap must "never silently deny a genuine emergency
   request -- alarm and log instead", and D5's failure mode is a second
   call during recovery being dropped with no record. Every deferral and
   every release carries a named reason and is counted.

---

**Why the yellow trap (A1/A2) cannot occur in this architecture**, which
is worth stating because it is the highest-severity hazard in the
catalogue and the answer here is structural rather than careful.

The canonical yellow trap needs one direction's through movement to be
carried across a transition while the opposing direction terminates: the
waiting left-turner sees his own head go yellow, applies the learned
model "yellow on my head means yellow on theirs", and turns across
opposing traffic that still has green. WisDOT's mitigation is to "exit
all phases (ensuring min green as well as full yellow and all red
clearance are displayed) before initiating the track clearance phase" --
a clean all-red break with nothing carried across.

`signal_controller/traci_cabinet.py` builds every phase's state string
from that phase's movements alone and every other index as 'r', and
`yellow_state_for` shows the departing phase's greens as yellow with
everything else red, followed by `all_red_state()`. So every transition
in this build is already the clean break WisDOT prescribes: no movement
is ever carried across one, and no phase overlaps another. The property
is checked directly rather than asserted --
`tests/control/test_corridor_junction.py::test_no_movement_carried_across_
any_transition` enumerates every ordered phase pair at every one of the
corridor's seven junctions.

One exception was added later and does not touch the corridor controller:
the blocking-aware controller (`control/strategies/hol_camp.py`) may go from
a ring phase to that phase's own alternate with the continuing greens kept
(`TraCICabinet.can_carry`, `runner._apply_decision`). The trap is avoided
there by construction instead -- an alternate only stops protected movements
and never a permissive one, and every way out of an alternate is again the
clean break described above. It needs a separate turn face per approach (a
flashing-yellow-arrow type head); with one shared face the trap returns.

The related hazard A5 -- a permissive left kept green during the preempt
phase, still inviting drivers across the path an emergency vehicle is
about to enter at speed -- was *not* structurally prevented, and was
live in this build until M7. See `traci_cabinet._build_state` for the
measurement and the fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config

from sim_service.control.corridor.requests import Reservation


def _charge(steps: tuple[PlanStep, ...]) -> float:
    """Seconds of preemption a plan asks for -- exactly what
    `interlocks.preempt_budget_ok` sums, expressed once so the engine's
    own pre-check and the interlock cannot disagree about it."""
    return sum(step.green_s for step in steps)


PLAN_SOURCE = "corridor_preemption"
"""Must match `interlocks.preempt_budget_ok`'s literal exactly: that
predicate applies the preemption-hour cap only to plans carrying this
source, and a typo would silently exempt the engine from the one
interlock written specifically for it."""


class PreemptState(Enum):
    IDLE = "idle"
    ENTRY_HOLD = "entry_hold"
    """A reservation exists but the junction may not legally leave its
    current phase yet -- remaining minimum green, or a pedestrian phase
    mid-interval. The current phase is held; the transition is not
    proposed. This is the state that makes hazard E1 ("outrunning the
    preemption") visible instead of surprising: the right-of-way transfer
    time is not a constant, it depends on where in the cycle the call
    landed, and this state is exactly the part of it that has not elapsed
    yet."""
    ENTRY_CLEAR = "entry_clear"
    """Legal to transition. The two-step plan is proposed; `runner.py`
    sequences the full yellow and all-red from it."""
    DWELL = "dwell"
    """The reserved movement is green and being held."""


class ReleaseReason(Enum):
    """Why a dwell ended. Counted separately per junction because the
    distribution is the diagnostic: a corridor whose preemptions mostly
    end in `PASSED` is working, and one whose preemptions mostly end in
    `MAX_DWELL` is holding signals for vehicles that are not arriving."""

    PASSED = "passed"
    """The vehicle was observed past the junction. E3's preferred release
    -- geometric, from the vehicle's own position, rather than a timeout.
    Cellular EVP systems have been measured taking "10 seconds or more to
    release the preemption of a traffic signal, even though the emergency
    vehicle has already cleared the intersection", which is a large
    per-junction cost on a corridor and, worse, trains drivers that
    preemption reds mean nothing (A11)."""

    ROUTE_CHANGED = "route_changed"
    """The vehicle's latest report no longer includes this junction (G4).
    Released on the tick the route shortens, not on a timeout."""

    STALE_REPORT = "stale_report"
    """No fresh observation within the track's time-to-live. Covers E9
    (requested, then diverted or cancelled), E10 (stopped en route, so a
    committed ETA has silently expired) and E4 (detection dropout).
    Releasing on staleness rather than persisting is the specific
    obligation route-based preemption takes on that point detection does
    not have."""

    MAX_DWELL = "max_dwell"
    """The hard bound fired. E7's stuck emitter and F9's indefinite hold
    both land here. FHWA's own framing of E7 is that a continuously
    running emitter "will hold the signal in the preemption phase
    indefinitely, causing significant traffic problems"; this is the
    controller-side bound that makes the vehicle-side interlock a second
    line of defence rather than the only one."""

    BUDGET = "budget"
    """`Tier0Config.max_preempt_s_per_hour` would be exceeded. H1's
    capacity argument: each event costs roughly 25 s of cross-street
    service plus 30 s to 7 minutes of degraded coordination, and Plano
    measured 10 to 20 minutes to recover near hospitals at peak. Released
    deliberately rather than left to be rejected by the interlock, because
    a planned release ends in a normal transition and a rejection ends in
    all-red."""

    MAX_WAIT_HEADROOM = "max_wait_headroom"
    """A cross movement is approaching I5's bound with demand. This
    release has no counterpart in the EVP literature, which is a comment
    on the literature rather than on the hazard: this build has a hard
    per-movement maximum-wait interlock, so an unbounded preemption hold
    does not degrade the cross street gradually, it hits a wall and the
    junction fails safe into all-red. Releasing with enough headroom left
    to complete a transition is what keeps the wall unreachable."""

    SUPERSEDED = "superseded"
    """A higher-priority reservation took the junction (D4). NEMA TS2
    supports preemptor *linking* -- a lower-priority sequence calling a
    higher-priority one on termination -- but, as the catalogue records,
    "does not explicitly detail mid-sequence preemption replacement
    scenarios". Under-specified in the standard means it has to be
    specified here: the outgoing reservation is released cleanly, its
    dwell ends, and the incoming one re-enters at ENTRY, so the
    replacement passes through the same full clearance any other
    transition does. It is never a jump between two green phases."""


class DeferReason(Enum):
    """Why preemption was not served this tick, while a reservation was
    live. `NONE` means it was served."""

    NONE = "none"
    MIN_GREEN = "min_green"
    PEDESTRIAN = "pedestrian"
    """St. Paul's rule, and the stricter of the two available readings.
    MUTCD 11th Ed. §4F.18 *permits* shortening or omitting both the walk
    and the pedestrian change interval under preemption, and NCHRP
    Synthesis 507 found 75% of agencies routinely truncate. TTI's
    assessment of what that buys -- "by shortening these intervals, some
    pedestrians may be trapped in the intersection facing oncoming
    vehicles" -- and INDOT Design Memo 25-19 (2025) moving the other way
    are the reasons this build does not take the permission. Note this
    costs nothing to decide: interlock I4 already refuses to truncate a
    pedestrian phase for any requester "including preemption", so
    truncating was never available here. This enum value exists so the
    deferral is *counted* rather than merely prevented."""
    NO_PROTECTED_PHASE = "no_protected_phase"
    """The reserved movement is served only permissively at this junction
    (D3/A5). Refused rather than served: a green plus a confirmation
    indication on a path whose safety depends on the driver yielding is
    worse than no preemption, because the crew is told they have the
    junction when they have only been told to proceed with caution."""
    FAULTED_PHASE = "faulted_phase"
    MAX_WAIT_HEADROOM = "max_wait_headroom"
    BUDGET = "budget"


class Confirmation(Enum):
    """What the emergency vehicle's confirmation ("notifier") indication
    should show, in St. Paul's convention: solid means you hold the
    junction, flashing means another approach has precedence and you must
    yield.

    This exists because of the 1972 St. Paul collision between a police
    car and a fire truck at an EVP-equipped intersection, after which the
    city required confirmation indications on *all* approaches rather than
    the two main ones. It is the only channel through which the system can
    tell a crew that hazard E1 is happening to them right now -- that the
    green they have learned to expect is not coming this time, because the
    call landed mid-pedestrian-interval or early in a minimum green.

    FHWA's training doctrine is the backstop and this does not replace it:
    "a green light is not guaranteed... be prepared to stop if provision
    of the preemption phase is delayed", and St. Paul's crews reported
    that "the main lesson learned was not to over-rely on the system"."""

    NONE = "none"
    FLASHING = "flashing"
    SOLID = "solid"


@dataclass(frozen=True)
class TransferTime:
    """The decomposition of right-of-way transfer time, kept as parts
    rather than a total because the parts are what a crew, a log and a
    designer each need separately (H3's minimum log record asks for
    "controller state at assert (phase, interval, time-in-phase, ped
    state)", which is this)."""

    remaining_min_green_s: float
    remaining_ped_s: float
    yellow_s: float
    all_red_s: float

    @property
    def total_s(self) -> float:
        return (
            max(self.remaining_min_green_s, self.remaining_ped_s)
            + self.yellow_s
            + self.all_red_s
        )

    @property
    def blocked(self) -> bool:
        return self.remaining_min_green_s > 0.0 or self.remaining_ped_s > 0.0


def transfer_time(cfg: Tier0Config, ctx: JunctionContext, target_phase: str) -> TransferTime:
    """How long until `target_phase` can legally be green.

    The two blocking terms take a `max`, not a sum: a pedestrian phase's
    walk-plus-clearance and its vehicular minimum green run concurrently,
    not one after the other. Summing them would overstate the transfer
    time, which sounds conservative and is not -- an overstated transfer
    time makes the engine trigger earlier and hold longer, spending
    cross-street service on a margin that does not exist.

    Returns zero clearance when the junction is already showing the target
    phase: there is nothing to clear from."""
    if ctx.current_phase_id == target_phase:
        return TransferTime(0.0, 0.0, 0.0, 0.0)

    remaining_min_green = 0.0
    if ctx.current_phase_id not in ctx.faulted_phases:
        required = cfg.min_green_s.get(ctx.current_phase_id, 0.0)
        remaining_min_green = max(0.0, required - ctx.current_phase_elapsed_s)

    remaining_ped = 0.0
    ped = ctx.ped_phase_in_progress
    if ped is not None and ped != target_phase:
        required_ped = cfg.ped_walk_s.get(ped, 0.0) + cfg.ped_clearance_s.get(ped, 0.0)
        remaining_ped = max(0.0, required_ped - ctx.ped_phase_elapsed_s)

    return TransferTime(remaining_min_green, remaining_ped, cfg.yellow_s, cfg.all_red_s)


def protected_phase_for(cfg: Tier0Config, movement: str) -> str | None:
    """The phase that serves `movement` with protection, or None.

    "With protection" is the whole content of this function. A movement
    can appear in a phase's `green_movements` while being absent from its
    `protected_movements` -- SUMO's lowercase 'g', a turn whose safety
    depends on the driver yielding to oncoming traffic. Four of this
    corridor's seven junctions have such movements, and every one of them
    conflicts with a protected movement in its own phase.

    Preempting onto a permissive path is refused rather than served
    (D3/A5). The reasoning is that the confirmation indication makes it
    worse, not better: without preemption the emergency vehicle's driver
    reads a permissive green as what it is and picks a gap; with it, the
    same display is accompanied by a signal asserting the junction is
    theirs. A system that upgrades the display's meaning without upgrading
    the display's protection has made the crossing more dangerous while
    appearing to make it safer.

    Ties broken by ring order so the choice is deterministic and
    reproducible -- D7's lesson about undocumented precedence conventions
    applies to a controller's own internal choices as much as to a
    vendor's input numbering."""
    for phase_id in cfg.ring_order:
        phase = cfg.phases.get(phase_id)
        if phase is None:
            continue
        # `protected_movements if not None`, deliberately not the
        # `protected_movements or green_movements` idiom used elsewhere in
        # this codebase. An *empty* protected set -- a phase every one of
        # whose movements is permissive -- is falsy, so `or` silently
        # substitutes the full green set and reports the phase as
        # protecting everything in it. Wherever that idiom appears in
        # `interlocks.no_conflicting_greens` the substitution is
        # conservative: I1 then checks more pairs than it strictly must.
        # Here it inverts, turning "nothing in this phase is protected"
        # into "everything is", which would hand an emergency vehicle
        # exactly the permissive path this function exists to refuse.
        protected = (
            phase.protected_movements
            if phase.protected_movements is not None
            else phase.green_movements
        )
        if movement in protected:
            return phase_id
    return None


def max_wait_headroom_s(
    cfg: Tier0Config, ctx: JunctionContext, target_phase: str
) -> float:
    """Seconds of preemption hold left before some cross movement with
    demand reaches I5's bound.

    Only movements the target phase does *not* serve count: a movement the
    preemption is about to give a green to is not being starved by it.
    Returns infinity when nothing at this junction is waiting with demand,
    which is the common case at light demand and is why this bound rarely
    binds there."""
    phase = cfg.phases.get(target_phase)
    served = phase.green_movements if phase is not None else frozenset()
    worst = 0.0
    any_waiting = False
    for movement, waited in ctx.wait_times_s.items():
        if movement in served or not ctx.has_demand.get(movement, False):
            continue
        any_waiting = True
        worst = max(worst, waited)
    if not any_waiting:
        return float("inf")
    return cfg.max_wait_s - worst


@dataclass
class JunctionPreemption:
    """One junction's preemption state. Advanced once per tick by
    `CorridorEngine`, which owns the reservations; this owns only what the
    junction itself must remember between ticks.

    Deliberately not a `Strategy`: it does not always have an opinion, and
    a strategy that can decline is a different contract from one that must
    always return a plan. `propose` returning None is the normal case."""

    junction_id: str
    state: PreemptState = PreemptState.IDLE
    reservation: Reservation | None = None
    target_phase: str | None = None
    entered_at_s: float = 0.0
    dwell_started_at_s: float | None = None
    last_defer: DeferReason = DeferReason.NONE
    releases: dict[ReleaseReason, int] | None = None
    defers: dict[DeferReason, int] | None = None
    preempted_s: float = 0.0
    """Total seconds this junction has actually spent in ENTRY or DWELL
    under a reservation. Distinct from the reservations' nominal
    durations: F8's "total interruption time" (preemption duration plus
    transition duration) is the metric the high-resolution event-data
    literature argues is the real cost, and it can only be measured, not
    predicted."""

    def __post_init__(self) -> None:
        if self.releases is None:
            self.releases = dict.fromkeys(ReleaseReason, 0)
        if self.defers is None:
            self.defers = dict.fromkeys(DeferReason, 0)

    # -- lifecycle ----------------------------------------------------

    def grant(self, reservation: Reservation, target_phase: str, now_s: float) -> None:
        if self.reservation is not None and self.reservation.vehicle_id != reservation.vehicle_id:
            self._count_release(ReleaseReason.SUPERSEDED)
        self.reservation = reservation
        self.target_phase = target_phase
        self.state = PreemptState.ENTRY_HOLD
        self.entered_at_s = now_s
        self.dwell_started_at_s = None

    def release(self, reason: ReleaseReason) -> None:
        if self.reservation is None:
            return
        self._count_release(reason)
        self.reservation = None
        self.target_phase = None
        self.state = PreemptState.IDLE
        self.dwell_started_at_s = None
        self.last_defer = DeferReason.NONE

    def _count_release(self, reason: ReleaseReason) -> None:
        assert self.releases is not None
        self.releases[reason] += 1

    def _defer(self, reason: DeferReason) -> None:
        assert self.defers is not None
        self.last_defer = reason
        self.defers[reason] += 1

    # -- per-tick decision --------------------------------------------

    def propose(
        self,
        cfg: Tier0Config,
        ctx: JunctionContext,
        now_s: float,
        *,
        tick_s: float,
        dwell_commit_s: float,
        headroom_margin_s: float,
    ) -> SignalPlan | None:
        """This junction's preemption plan for this tick, or None to let
        the ordinary controller run.

        `dwell_commit_s` is what the entry plan *charges* against the
        preemption-hour budget -- the commitment being made, not the
        seconds that will turn out to be used. `interlocks.preempt_budget_
        ok` sums `green_s` across the plan's steps, so an entry step
        claiming the expected dwell is what makes the budget check see a
        commitment rather than a single tick, and what makes it possible
        to be refused entry with the budget intact rather than halfway
        through a hold.

        `headroom_margin_s` is how much I5 slack must remain for the
        release to complete: a release still has to run yellow plus
        all-red plus at least one tick of the recovering phase before the
        starved movement is served, and a bound that is only reached at
        the moment of release has already been missed."""
        if self.reservation is None or self.target_phase is None:
            return None
        if not self.reservation.active_at(now_s):
            self.release(ReleaseReason.MAX_DWELL)
            return None

        target = self.target_phase
        if target in ctx.faulted_phases:
            # I6 would reject this, and a faulted phase is one the
            # junction genuinely cannot show -- there is no version of
            # this request that can be served here.
            self._defer(DeferReason.FAULTED_PHASE)
            return None

        # Both the phase being held *now* and the phase being moved to,
        # because they are different during entry and I5 judges each of
        # them at a different moment.
        #
        # `max_wait_not_exceeded` tests `plan.steps[0]`, and during both
        # entry states that step is the *current* phase -- the engine is
        # holding it, or ending it with clearance. So a movement already
        # at its bound that the current phase does not serve rejects an
        # entry plan even though the target phase would have served it.
        # Only checking the target, as this first did, let the property
        # test construct exactly that: a two-phase junction, `m1` at the
        # bound, target `P1` serving `m1`, and an entry plan holding `P0`
        # that I5 refused. Taking the minimum of the two headrooms is
        # slightly stronger than I5 strictly requires and is the version
        # that cannot be wrong in the direction that matters.
        headroom = min(
            max_wait_headroom_s(cfg, ctx, target),
            max_wait_headroom_s(cfg, ctx, ctx.current_phase_id),
        )
        if headroom <= headroom_margin_s:
            # Released whatever state the reservation was in, not only
            # from DWELL. The first version of this released from DWELL
            # only, which meant a request arriving at a junction whose
            # cross street was *already* near its bound sat in ENTRY_HOLD
            # forever: it could never be served, and it never gave up.
            # There is no version of this request that can be served
            # here, so holding it only delays the ordinary controller
            # from serving the movement that is actually starving.
            self._defer(DeferReason.MAX_WAIT_HEADROOM)
            self.release(ReleaseReason.MAX_WAIT_HEADROOM)
            return None

        transfer = transfer_time(cfg, ctx, target)

        # Every branch below builds its steps *first* and then asks
        # whether the budget covers them, rather than checking a
        # separately-derived number and emitting steps that might not
        # match it. The property test found that mismatch twice, in two
        # different branches, from the same root cause -- entry checked
        # `tick_s` while claiming the remaining pedestrian clearance, and
        # entry-clear checked `dwell_commit_s` while claiming
        # `tick_s + dwell_commit_s` across two steps. Fixing each
        # separately would have left the third instance waiting to be
        # written. Deriving the charge from the plan makes the class of
        # bug unreachable: `_charge` sums exactly what
        # `interlocks.preempt_budget_ok` sums.
        if ctx.current_phase_id == target:
            #                                                      DWELL
            if self.state is not PreemptState.DWELL:
                self.state = PreemptState.DWELL
                self.dwell_started_at_s = now_s
            steps: tuple[PlanStep, ...] = (PlanStep(phase_id=target, green_s=tick_s),)
            defer = DeferReason.NONE
        elif transfer.blocked:
            #                                                 ENTRY_HOLD
            # Hold the current phase rather than demand a switch I3 or I4
            # would reject. Holding is itself a preemption action -- the
            # ordinary controller might have switched away and back -- so
            # it is charged to the budget and counted as interruption
            # time.
            #
            # The held green must be long enough to *complete* a
            # pedestrian interval, not merely long enough not to leave
            # it. I4 checks `ped_elapsed + steps[0].green_s >= required`,
            # so a one-tick hold of a pedestrian phase fifteen seconds
            # from finishing its clearance is rejected -- and rejection
            # commands all-red, with pedestrians in the crosswalk and an
            # emergency vehicle approaching, which is the worst outcome
            # this whole module exists to avoid. Claiming the remaining
            # clearance is also the honest commitment: the engine is
            # undertaking to hold that phase until the pedestrians are
            # across, and the budget should be charged for it.
            self.state = PreemptState.ENTRY_HOLD
            steps = (
                PlanStep(
                    phase_id=ctx.current_phase_id,
                    green_s=max(tick_s, transfer.remaining_ped_s),
                ),
            )
            defer = (
                DeferReason.PEDESTRIAN
                if transfer.remaining_ped_s > 0.0
                else DeferReason.MIN_GREEN
            )
        else:
            #                                                ENTRY_CLEAR
            self.state = PreemptState.ENTRY_CLEAR
            steps = (
                PlanStep(
                    phase_id=ctx.current_phase_id,
                    green_s=tick_s,
                    yellow_s=cfg.yellow_s,
                    all_red_s=cfg.all_red_s,
                ),
                PlanStep(phase_id=target, green_s=dwell_commit_s),
            )
            defer = DeferReason.NONE

        if not self._budget_ok(cfg, ctx, _charge(steps)):
            self._defer(DeferReason.BUDGET)
            self.release(ReleaseReason.BUDGET)
            return None

        if defer is DeferReason.NONE:
            self.last_defer = DeferReason.NONE
        else:
            self._defer(defer)
        self.preempted_s += tick_s
        return SignalPlan(
            intersection_id=cfg.intersection_id, steps=steps, source=PLAN_SOURCE
        )

    def _budget_ok(self, cfg: Tier0Config, ctx: JunctionContext, requested_s: float) -> bool:
        """The same arithmetic `interlocks.preempt_budget_ok` performs,
        run here first so the answer is a release rather than a rejection.

        Duplicating a predicate is normally the wrong move and it is worth
        saying why it is right here: the interlock's *verdict* is what
        governs -- it still runs, on this plan, and still rejects it if
        this is wrong -- and what is duplicated is only the decision to
        stop short of it. The failure modes of the two copies drifting are
        asymmetric: a copy that is too permissive gets caught by the real
        interlock and downgraded to a denial, and a copy that is too
        strict releases a preemption early. Neither can produce an unsafe
        junction, which is the property that makes the duplication
        acceptable."""
        return ctx.preempt_seconds_last_hour + requested_s <= cfg.max_preempt_s_per_hour

    # -- outputs other subsystems read --------------------------------

    def confirmation(self, cfg: Tier0Config, ctx: JunctionContext) -> Confirmation:
        """What this junction's confirmation indication should show to the
        vehicle holding the reservation. See `Confirmation`."""
        if self.reservation is None:
            return Confirmation.NONE
        if self.state is PreemptState.DWELL and ctx.current_phase_id == self.target_phase:
            return Confirmation.SOLID
        return Confirmation.FLASHING

    def stats(self) -> dict[str, float]:
        assert self.releases is not None and self.defers is not None
        out: dict[str, float] = {"preempted_s": self.preempted_s}
        for release_reason, count in self.releases.items():
            out[f"release_{release_reason.value}"] = count
        for defer_reason, count in self.defers.items():
            if defer_reason is not DeferReason.NONE:
                out[f"defer_{defer_reason.value}"] = count
        return out

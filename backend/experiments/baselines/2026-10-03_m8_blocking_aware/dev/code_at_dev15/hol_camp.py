"""CC-A-CAMP that knows when a lane is blocked at its head (`hol.py` has the
problem and the static parts).

Two changes to the parent controller, both active only while a lane is
blocked on an approach that has a variant (below) -- with nothing blocked,
and at every junction whose approaches all have more than one lane, every
decision is the parent's, bit for bit:

1. **A blocked lane is not priced as if it could drain.** A lane whose front
   vehicle has stood behind a turner waiting in the box (`ctx.blocked_by`)
   for at least a change interval contributes to a phase's pressure only
   what that phase can actually release: everything if the phase gives the
   waiting turner a protected green, nothing if the turner must keep
   yielding to an oncoming stream that has traffic, nothing if the phase
   does not serve the turner at all.
   The parent prices it at full saturation flow, so the longest queue at the
   junction -- the blocked one -- argues for holding exactly the green that
   is doing nothing for it.

2. **A blocked approach can be served on its own.** Each base phase has
   *variants* (`hol.split_variants`): one approach alone, all movements
   protected. A variant becomes a candidate while its approach is blocked.
   The ring, the cycle supervisor, minimum green and every interlock keep
   working on base phases; a variant is a way of realising its base phase.

**The change into a variant is an ordinary one**: everything goes yellow,
then red, then the one approach starts with its turn protected. The first
version kept that approach green through the change and stopped only the
other one. That saves the blocked approach nothing (it is not moving) and
it is the "yellow trap" every signal manual warns of: a turner of the
*other* approach, waiting in the box, sees its own light go yellow, takes
the oncoming stream to be stopping too, and turns into traffic that still
has a green. A simulated driver never makes that mistake, so no result here
could have shown it; an independent review of the code did. The change
*back* does keep the approach green (`TraCICabinet.carried_clearance_states`):
its turn loses its protection through a yellow and a red of its own before
the other approach starts, which is how a leading protected turn ends
anywhere.

**How long a family (a base phase and its variants) may hold the green.**
Each realisation is held to the base phase's maximum green by the parent,
as before. A visit that has used a variant is also held, as a whole, to
twice that -- what serving the two approaches one after the other would be
allowed -- counted from when the ring arrived and including the change
intervals inside the family. The first version reset the clock at every
change inside the family, so a family could go base, variant, base, variant
for as long as the cycle supervisor and the other phases' maximum waits let
it (the review measured 63 s where the ceiling was 20 s).

What tells the controller a lane is blocked is a vehicle stopped *inside*
the junction with a stopped vehicle directly behind it -- visible to a
camera over the junction, invisible to a stop-bar loop, which reports the
same "occupied" for a discharging queue and a blocked one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config
from itms_domain.signal import BLOCKER_UNKNOWN

from sim_service.control.strategies import acamp
from sim_service.control.strategies.acamp import AdaptiveCamp


@dataclass(frozen=True)
class HolConfig:
    opposed_rate: float = 0.0
    """Share of saturation flow a lane keeps while its front vehicle yields
    to an oncoming stream that has traffic. 0: priced as not draining."""
    use_variants: bool = True
    """False keeps change 1 (pricing) and drops change 2 (split variants):
    the ablation arm."""
    variant_gain_margin: float = 0.1
    """How much more pressure a variant must release than its base phase
    (and the base phase than a running variant) before the controller moves
    to it, as a share of the pressure of the one it would leave."""
    min_blocked_changes: float = 1.0
    """How long an approach must have been blocked before it can be served
    alone, in change intervals (yellow + all-red) of the junction. Serving
    an approach alone costs a change interval; a blockage shorter than that
    clears by itself sooner than the change would. 0: a variant is a
    candidate on the first blocked tick.

    Chosen on TRAIN seeds (single-lane grid, 2026-10-03) among 0, 1 and 2:
    1 made half as many changes as 0 for the same or less delay at every
    demand level tried (light -2.3 % against CC-A-CAMP where 0 had +0.8 %,
    neither distinguishable from zero over 10 seeds; flow ratio 0.35 to
    0.45: -12.8 / -15.3 / -68.1 % against -9.0 / -15.3 / -65.4 %); 2 let the
    grid lock at 0.45 on some seeds (64 teleports in 5 runs, 4 for 1)."""
    single_lane_only: bool = True
    """Variants only for approaches whose movements all share one lane
    (`hol.split_variants`, which has the measurement). Read by whoever
    builds the variants; the controller itself takes the variants it is
    given."""
    whole_approach: bool = True
    """For a multi-lane approach that has a variant (`single_lane_only`
    False): serve it alone only while every one of its lanes that has a
    queue is blocked. False: one blocked lane is enough (the first
    version). On a single-lane approach the two are the same thing."""
    blocked_grace_s: float = 2.0
    """A break in the blockage shorter than this does not start the count
    again. A camera's reading flickers where the simulator's does not: a
    track is lost for a frame, a creeping vehicle crosses the stopped
    threshold (scored on a TRAIN seed, 73 % of the camera's blocked
    lane-seconds matched the simulator's to the second and 91 % within 2 s)."""
    family_budget: float = 2.0
    """A visit to a base phase that has used a variant may last this many
    times the base phase's maximum green in all (module docstring)."""
    carry_into_variant: bool = False
    """Measurement only, never for a street: enter a variant keeping its
    approach green through the change (the first version's yellow trap,
    module docstring). Read by whoever runs the scenario; it is how the
    cost of the ordinary change is measured."""


class HolAwareCamp(AdaptiveCamp):
    def __init__(
        self,
        cfg: acamp.AcampConfig | None = None,
        *,
        lane_of: Mapping[str, str],
        base_of: Mapping[str, str] | None = None,
        hol: HolConfig | None = None,
        **kwargs,
    ) -> None:
        super().__init__(cfg, **kwargs)
        self.lane_of = dict(lane_of)
        self.hol = hol or HolConfig()
        self.base_of = dict(base_of or {}) if self.hol.use_variants else {}
        self._variants: dict[str, list[str]] = {}
        for v, b in self.base_of.items():
            self._variants.setdefault(b, []).append(v)
        self._raw: dict[str, float] = {}
        self._priced: frozenset[str] | None = None
        self._realised: dict[str, str] = {}
        self._actual = ""
        self._blocked_s: dict[str, float] = {}
        """Per movement, for how long its lane has been blocked (counted in
        the ticks this controller is asked: not during a change interval)."""
        self._clear_s: dict[str, float] = {}
        """Per movement in `_blocked_s`, for how long it has not been (a
        break shorter than `blocked_grace_s` keeps the count)."""
        self._visit_base = ""
        self._visit_started_s = 0.0
        self._visit_used_variant = False
        self._visit_served: set[str] = set()
        """Movements shown a green since the ring arrived at the current base
        phase. A variant serves one approach of its base; before the ring
        moves on, the others are owed their turn (`_owed_to_family`)."""
        self.stats.update({"hol_blocked_ticks": 0, "hol_variant_ticks": 0,
                           "hol_variant_switch": 0, "hol_variant_entry": 0,
                           "hol_variant_exit": 0, "hol_variant_idle_exit": 0,
                           "hol_family_owed": 0, "hol_family_starving": 0,
                           "hol_family_budget_ticks": 0})

    # ---- pricing ---------------------------------------------------------

    def _rate(self, cfg_t0: Tier0Config, ctx: JunctionContext, phase_id: str, m: str) -> float:
        """Share of its saturation flow movement `m`'s lane keeps under
        `phase_id`, given what blocks it."""
        blocker = ctx.blocked_by.get(m)
        if blocker is None or not self._acts_on(cfg_t0, m):
            return 1.0
        phase = cfg_t0.phases[phase_id]
        protected = phase.protected_movements or frozenset()
        if blocker == BLOCKER_UNKNOWN:
            # A camera sees a vehicle waiting in the box ahead of this lane,
            # not which way it is going. Under this phase it can only be
            # waiting on a movement of the same lane that yields.
            lane = self.lane_of.get(m)
            waiting = [x for x in phase.green_movements - protected
                       if self.lane_of.get(x) == lane]
        elif blocker not in phase.green_movements:
            return 0.0
        elif blocker in protected:
            return 1.0
        else:
            waiting = [blocker]
        opposed = any(
            acamp.q_hat(ctx, self.cfg, o) > 0.0
            for b in waiting
            for o in cfg_t0.conflict_matrix.get(b, frozenset()) & phase.green_movements
        )
        return self.hol.opposed_rate if opposed else 1.0

    def _acts_on(self, cfg_t0: Tier0Config, m: str) -> bool:
        """Whether the controller does anything about a blockage of movement
        `m`'s lane. Only when both hold; otherwise the lane is priced and
        served exactly as the parent would:

        - the junction can do something about it: the movement's approach
          has a variant. The price exists to compare a base phase with its
          variants; with no variant to choose, a discounted price only
          argues for leaving the phase (on the single-lane grid pricing
          alone was no better than the parent at any demand level). The
          pricing-only arm, which has no variants, prices every lane.
        - the blockage has lasted (`min_blocked_changes`). The first version
          discounted a lane from the first blocked second while its variant
          had to wait for the fifth, so for those seconds the blocked
          approach's phase looked worth less and nothing could be done for
          it."""
        if self._blocked_s.get(m, 0.0) < self.hol.min_blocked_changes * (
                cfg_t0.yellow_s + cfg_t0.all_red_s):
            return False
        if not self.hol.use_variants:
            return True
        if self._priced is None:
            self._priced = frozenset(
                x for v in self.base_of if v in cfg_t0.phases
                for x in cfg_t0.phases[v].green_movements)
        return m in self._priced

    def _raw_pressure(self, cfg_t0, ctx, phase_id, urgency, owed_s, horizon_s) -> float:
        cfg = self.cfg
        total = 0.0
        for m in cfg_t0.phases[phase_id].green_movements:
            s = cfg_t0.sat_flow_pcu_s.get(m, 0.0)
            discharge = acamp.q_hat(ctx, cfg, m) * acamp.gate(
                ctx.receiving_occupancy.get(m, 0.0), cfg)
            term = s * (discharge - ctx.receiving_queue_pcu.get(m, 0.0))
            total += self._rate(cfg_t0, ctx, phase_id, m) * term
        return (
            total
            + acamp.fairness(cfg_t0, ctx, cfg, phase_id)
            + acamp.anticipation(cfg_t0, ctx, cfg, phase_id, urgency or {})
            + acamp.debt_recovery(cfg_t0, cfg, phase_id, owed_s or {}, horizon_s)
        )

    def _eligible(self, cfg_t0: Tier0Config, ctx: JunctionContext, variant: str) -> bool:
        """A variant is a candidate while its approach is blocked, or while
        it is the phase actually running (so it can be compared and kept)."""
        if variant == self._actual:
            return True
        own = cfg_t0.phases[variant].green_movements
        held = {m for m in own if m in ctx.blocked_by and self._acts_on(cfg_t0, m)}
        if not held:
            return False
        if self.hol.whole_approach:
            stalled = {self.lane_of.get(m) for m in held}
            for m in own:
                if self.lane_of.get(m) not in stalled and acamp.q_hat(ctx, self.cfg, m) > 0.0:
                    return False        # a lane of this approach is still discharging
        return self._family_can_wait(cfg_t0, ctx, variant)

    def _family_can_wait(self, cfg_t0: Tier0Config, ctx: JunctionContext, variant: str) -> bool:
        """Whether the movements of the base phase that `variant` leaves out
        can wait through it: none with demand would come within the
        starvation margin of its maximum wait before the change in, the
        variant's minimum green and the change back have run.
        (`_owed_to_family` brings the base phase back at that margin; this
        keeps the variant from starting when it would have to be abandoned
        at once.)"""
        base = self.base_of.get(variant, variant)
        lead_s = (acamp._SKIP_WAIT_MARGIN_S + cfg_t0.min_green_s.get(variant, 0.0)  # noqa: SLF001
                  + 2.0 * (cfg_t0.yellow_s + cfg_t0.all_red_s))
        left_out = cfg_t0.phases[base].green_movements - cfg_t0.phases[variant].green_movements
        return not any(
            ctx.has_demand.get(m, False)
            and cfg_t0.max_wait_s - ctx.wait_times_s.get(m, 0.0) <= lead_s
            for m in left_out
        )

    def _beats(self, gain: float | None, keep: float | None) -> bool:
        """Whether a realisation releasing `gain` is worth choosing over one
        releasing `keep`: more, by `variant_gain_margin` of what would be
        left. By difference, not by sign: pressures are relative
        (`acamp.py`), and a phase discharging into queued receiving lanes
        has a negative one. (The first version also required `gain > 0`, so
        with every receiving lane queued a variant could not be left.)"""
        if gain is None or keep is None:
            return False
        return gain > keep and gain - keep > self.hol.variant_gain_margin * abs(keep)

    def _pressure(self, cfg_t0, ctx, phase_id, urgency, owed_s, horizon_s) -> float:
        if self._actual not in self.base_of and not any(
                self._acts_on(cfg_t0, m) for m in ctx.blocked_by):
            # nothing blocked that this junction acts on, no variant running:
            # the parent's pressure, exactly
            self._realised[phase_id] = phase_id
            return super()._pressure(cfg_t0, ctx, phase_id, urgency, owed_s, horizon_s)
        base_raw = self._raw_pressure(cfg_t0, ctx, phase_id, urgency, owed_s, horizon_s)
        best_id, best = phase_id, base_raw
        self._raw[phase_id] = base_raw
        # Inside the running family every realisation competes as it is (the
        # move between them is weighed in `__call__`). A variant of another
        # base phase is how that phase would be entered, so it has to beat
        # its base phase by the margin here.
        running = self.base_of.get(self._actual, self._actual) == phase_id
        for v in self._variants.get(phase_id, ()):
            if v not in cfg_t0.phases or not self._eligible(cfg_t0, ctx, v):
                continue
            p = self._raw_pressure(cfg_t0, ctx, v, urgency, owed_s, horizon_s)
            self._raw[v] = p
            if p > best and (running or self._beats(p, base_raw)):
                best_id, best = v, p
        self._realised[phase_id] = best_id
        return best

    # ---- decision --------------------------------------------------------

    def __call__(self, cfg_t0: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        actual = ctx.current_phase_id
        base = self.base_of.get(actual, actual)
        elapsed = ctx.current_phase_elapsed_s
        self._actual = actual
        self._raw = {}
        self._realised = {}
        if ctx.blocked_by or self._blocked_s:
            for m in list(self._blocked_s):
                if m in ctx.blocked_by:
                    continue
                self._clear_s[m] = self._clear_s.get(m, 0.0) + self.tick_s
                if self._clear_s[m] > self.hol.blocked_grace_s:
                    del self._blocked_s[m]
                    del self._clear_s[m]
            for m in ctx.blocked_by:
                self._blocked_s[m] = self._blocked_s.get(m, 0.0) + self.tick_s
                self._clear_s.pop(m, None)
        if ctx.blocked_by:
            self.stats["hol_blocked_ticks"] += 1
        if base != self._visit_base:
            self._visit_base, self._visit_served = base, set()
            self._visit_started_s = self._sim_time_s - elapsed
            self._visit_used_variant = False
        if actual != base:
            self.stats["hol_variant_ticks"] += 1
            self._visit_used_variant = True
        self._visit_served |= cfg_t0.phases[actual].green_movements

        # What the parent is told has elapsed: the running realisation's own
        # green, or -- once the visit has used a variant -- the visit's
        # whole length less one maximum green, whichever is more, so that
        # its maximum-green rule ends the visit at `family_budget` times the
        # base phase's ceiling (module docstring).
        told = elapsed
        if self._visit_used_variant:
            spent = self._sim_time_s - self._visit_started_s
            allowance = (self.hol.family_budget - 1.0) * cfg_t0.max_green_s.get(base, 0.0)
            if spent - allowance > told:
                told = spent - allowance
                self.stats["hol_family_budget_ticks"] += 1
        view = ctx if (actual == base and told == elapsed) else replace(
            ctx, current_phase_id=base, current_phase_elapsed_s=told)
        plan = super().__call__(cfg_t0, view)
        min_g = cfg_t0.min_green_s.get(actual, 0.0)

        if actual != base:
            owed = self._owed_to_family(cfg_t0, ctx, actual, base, plan)
            if owed is not None:
                return owed
        if not plan.steps or plan.source != "acamp":
            return self._rename(plan, base, actual)

        if len(plan.steps) == 1 and plan.steps[0].phase_id == base:
            # the parent keeps the base phase: is another realisation of it
            # worth a change interval?
            target = None
            if elapsed >= min_g:
                if actual != base and self._idle(cfg_t0, ctx, actual, base):
                    target = base
                    self.stats["hol_variant_idle_exit"] += 1
                else:
                    best = self._realised.get(base, actual)
                    if best != actual and self._beats(self._raw.get(best),
                                                     self._raw.get(actual)):
                        target = best
                        self.stats["hol_variant_switch" if best != base
                                   else "hol_variant_exit"] += 1
            if target is None:
                return self._rename(plan, base, actual)
            self._current_phase_allocation_s = cfg_t0.min_green_s.get(target, 0.0)
            return SignalPlan(
                intersection_id=cfg_t0.intersection_id,
                steps=(
                    acamp._exit_step(cfg_t0, ctx, actual, min_g, self.tick_s),  # noqa: SLF001
                    PlanStep(phase_id=target,
                             green_s=cfg_t0.min_green_s.get(target, self.tick_s)),
                ),
                source="acamp",
            )

        # A switch to another base phase: leave the phase actually running
        # (its own minimum green, not the visit's clock, decides when), and
        # run the next one as its best realisation.
        steps = []
        for i, st in enumerate(plan.steps):
            if i == 0 and st.phase_id == base:
                own = acamp._exit_step(cfg_t0, ctx, actual, min_g, self.tick_s)  # noqa: SLF001
                steps.append(replace(st, phase_id=actual, green_s=max(st.green_s, own.green_s)
                                     if actual not in ctx.faulted_phases else st.green_s))
            elif i > 0:
                realised = self._realised.get(st.phase_id, st.phase_id)
                if realised != st.phase_id:
                    self.stats["hol_variant_entry"] += 1
                steps.append(replace(st, phase_id=realised))
            else:
                steps.append(st)
        return replace(plan, steps=tuple(steps))

    def _idle(self, cfg_t0: Tier0Config, ctx: JunctionContext, variant: str, base: str) -> bool:
        """The variant's own approach has nothing left to serve -- no queue,
        nothing arriving -- while another movement of its base phase has.
        The parent's gap-out looks at the base phase's movements, where the
        other approach's queue reads as demand, so it would hold the empty
        approach's green to the ceiling."""
        own = cfg_t0.phases[variant].green_movements
        if any(acamp.q_hat(ctx, self.cfg, m) > 0.0 for m in own):
            return False
        return any(acamp.q_hat(ctx, self.cfg, m) > 0.0
                   for m in cfg_t0.phases[base].green_movements - own)

    def _owed_to_family(self, cfg_t0, ctx, actual: str, base: str,
                        plan: SignalPlan) -> SignalPlan | None:
        """A variant serves one approach of its base phase. The parent's
        starvation guard and cycle supervisor see the base phase as running,
        so they cannot see that the base's other movements are being passed
        over. Two rules restore what they guarantee, by returning to the
        base phase (which serves every movement of the family):

        - a movement of the base that the variant does not serve is about to
          reach its maximum wait (the parent's own margin before I5's
          bound); the first version lacked this, ran one approach alone
          until the ring moved on, and hit the max-wait interlock 6 and 7
          times in two gridlocked training runs;
        - the ring is about to leave the base phase while a movement of it
          with demand has had no green on this visit.

        Inside the variant's minimum green it holds instead. When the parent
        is leaving and a movement of *another* phase could not wait through
        the detour (a change, the base phase's minimum green, a change), the
        parent's switch stands: it is leaving for that movement's sake."""
        unserved = cfg_t0.phases[base].green_movements - cfg_t0.phases[actual].green_movements
        starving = any(
            ctx.has_demand.get(m, False)
            and cfg_t0.max_wait_s - ctx.wait_times_s.get(m, 0.0) <= acamp._SKIP_WAIT_MARGIN_S  # noqa: SLF001
            for m in unserved
        )
        leaving = len(plan.steps) > 1 and plan.source == "acamp"
        owed = leaving and any(
            m not in self._visit_served
            and (ctx.queue_pcu.get(m, 0.0) > 0.0 or ctx.approaching_pcu.get(m, 0.0) > 0.0)
            for m in unserved
        )
        if not (starving or owed):
            return None
        if leaving:
            detour_s = (2.0 * (cfg_t0.yellow_s + cfg_t0.all_red_s)
                        + cfg_t0.min_green_s.get(base, 0.0) + acamp._SKIP_WAIT_MARGIN_S)  # noqa: SLF001
            family = cfg_t0.phases[base].green_movements
            if any(has and m not in family
                   and cfg_t0.max_wait_s - ctx.wait_times_s.get(m, 0.0) <= detour_s
                   for m, has in ctx.has_demand.items()):
                return None
        min_g = cfg_t0.min_green_s.get(actual, 0.0)
        if ctx.current_phase_elapsed_s < min_g:
            return SignalPlan(
                intersection_id=cfg_t0.intersection_id,
                steps=(PlanStep(phase_id=actual, green_s=self.tick_s),),
                source="acamp",
            )
        self.stats["hol_family_starving" if starving else "hol_family_owed"] += 1
        self._current_phase_allocation_s = cfg_t0.min_green_s.get(base, 0.0)
        return SignalPlan(
            intersection_id=cfg_t0.intersection_id,
            steps=(
                acamp._exit_step(cfg_t0, ctx, actual, min_g, self.tick_s),  # noqa: SLF001
                PlanStep(phase_id=base, green_s=cfg_t0.min_green_s.get(base, self.tick_s)),
            ),
            source="acamp",
        )

    @staticmethod
    def _rename(plan: SignalPlan, base: str, actual: str) -> SignalPlan:
        if base == actual or not plan.steps or plan.steps[0].phase_id != base:
            return plan
        return replace(plan, steps=(replace(plan.steps[0], phase_id=actual), *plan.steps[1:]))

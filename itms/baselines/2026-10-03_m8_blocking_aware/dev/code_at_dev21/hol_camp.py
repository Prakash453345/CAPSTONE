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

2. **The stream a blocked approach is waiting for can be stopped.** Each
   base phase has *variants* (`hol.split_variants`): the base phase without
   the protected streams one approach's turn yields to, everything else
   exactly as the base phase shows it. A variant becomes a candidate while
   its approach is blocked. The ring, the cycle supervisor, minimum green
   and every interlock keep working on base phases; a variant is a way of
   realising its base phase.

**Going into a variant keeps every green that continues** and puts only
the stopped streams through the change interval (`TraCICabinet.
carried_clearance_states`): the blocked approach does not lose a change
interval of its own for being helped. **Coming out of one is an ordinary
change**, everything through yellow and all-red, whether back to the base
phase or on to another: whatever starts, starts into an empty junction.
Three earlier designs, each caught by an independent review of the code
rather than by any result (a simulated driver never misreads a signal), are
described in `hol.py`. With the first of them made safe the obvious way --
an ordinary change into the variant too -- the gain at moderate demand went
with it on training seeds (flow ratio 0.35 / 0.40: +0.9 / +5.9 % against
CC-A-CAMP, where keeping the green had -11.5 / -19.7 %).

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

from itms_domain import JunctionContext, Phase, PlanStep, SignalPlan, Tier0Config
from itms_domain.signal import BLOCKER_UNKNOWN

from sim_service.control.strategies import acamp, hol
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
    exit_by_pressure: bool = False
    """Go back from a variant to its base phase as soon as the base phase
    would release more, by the margin. False (the default): only when the
    variant's own approach has run empty, or the other approach is owed its
    green. Going back is an ordinary change and costs both approaches a
    change interval. On TRAIN seeds (single-lane grid, flow ratio 0.35 /
    0.40 / 0.45 against CC-A-CAMP): -5.2 / -13.1 / -52.3 % with it (5
    seeds), -8.0 / -17.7 / -52.8 % without (10 seeds)."""
    terminal: bool = False
    """A variant is not left for its base phase while another phase has
    traffic waiting: when its own approach has run empty the ring moves on
    (the base phase's other approach waits for the next cycle) instead of
    paying a change interval to return. -6.8 / -14.2 / -59.4 % on the same
    ten seeds: not distinguishable from the default, which gives the other
    approach its green in the same visit."""
    family_budget: float = 2.0
    """A visit to a base phase that has used a variant may last this many
    times the base phase's maximum green in all (module docstring)."""


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
        self._own_of: dict[str, frozenset[str]] = {}
        self._served_of: dict[str, frozenset[str]] = {}
        self._pricing_cfg: tuple[Tier0Config, Tier0Config] | None = None
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
                           "hol_variant_moved_on": 0,
                           "hol_family_owed": 0, "hol_family_starving": 0,
                           "hol_family_budget_ticks": 0})

    def _own(self, cfg_t0: Tier0Config, phase_id: str) -> frozenset[str]:
        """The movements of the approach a variant exists for; for a base
        phase, everything it shows green."""
        base = self.base_of.get(phase_id)
        if base is None:
            return cfg_t0.phases[phase_id].green_movements
        own = self._own_of.get(phase_id)
        if own is None:
            own = self._own_of[phase_id] = hol.own_movements(
                cfg_t0, self.lane_of, phase_id, base)
        return own

    def _served(self, cfg_t0: Tier0Config, phase_id: str) -> frozenset[str]:
        """The movements a phase discharges: for a variant, its own approach
        and whatever protected movements of other approaches it leaves
        running -- not the other approaches' yielding turns, which it leaves
        permissive beside a through that it has stopped on the same lane."""
        phase = cfg_t0.phases[phase_id]
        base = self.base_of.get(phase_id)
        if base is None:
            return phase.green_movements
        got = self._served_of.get(phase_id)
        if got is None:
            # a kept protected movement counts only if its whole lane runs:
            # a kerb-side turn sharing a lane with a stopped through does not
            stopped = cfg_t0.phases[base].green_movements - phase.green_movements
            cut_lanes = {self.lane_of.get(m) for m in stopped}
            got = self._served_of[phase_id] = self._own(cfg_t0, phase_id) | frozenset(
                m for m in phase.protected_movements or frozenset()
                if self.lane_of.get(m) not in cut_lanes)
        return got

    def _priced_as(self, cfg_t0: Tier0Config) -> Tier0Config:
        """`cfg_t0` with each variant reduced to what it serves, for the
        parent's fairness, anticipation and debt terms (which sum over a
        phase's green movements)."""
        if self._pricing_cfg is None or self._pricing_cfg[0] is not cfg_t0:
            phases = dict(cfg_t0.phases)
            for v in self.base_of:
                if v in phases:
                    served = self._served(cfg_t0, v)
                    phases[v] = Phase(v, served, protected_movements=(
                        phases[v].protected_movements or frozenset()) & served)
            self._pricing_cfg = (cfg_t0, replace(cfg_t0, phases=phases))
        return self._pricing_cfg[1]

    # ---- pricing ---------------------------------------------------------

    def _rate(self, cfg_t0: Tier0Config, ctx: JunctionContext, phase_id: str, m: str) -> float:
        """Share of its saturation flow movement `m`'s lane keeps under
        `phase_id`, given what blocks it."""
        blocker = ctx.blocked_by.get(m)
        if blocker is None or not self._acts_on(cfg_t0, m):
            return 1.0
        if phase_id in self.base_of and m in self._own(cfg_t0, phase_id):
            # the variant exists to stop the streams this approach's turn
            # yields to: under it the lane drains
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
        held_s = self._blocked_s.get(m)      # None: not blocked under its own green
        if held_s is None or held_s < self.hol.min_blocked_changes * (
                cfg_t0.yellow_s + cfg_t0.all_red_s):
            return False
        if not self.hol.use_variants:
            return True
        if self._priced is None:
            self._priced = frozenset(
                x for v in self.base_of if v in cfg_t0.phases
                for x in self._own(cfg_t0, v))
        return m in self._priced

    def _raw_pressure(self, cfg_t0, ctx, phase_id, urgency, owed_s, horizon_s) -> float:
        cfg = self.cfg
        total = 0.0
        for m in self._served(cfg_t0, phase_id):
            s = cfg_t0.sat_flow_pcu_s.get(m, 0.0)
            discharge = acamp.q_hat(ctx, cfg, m) * acamp.gate(
                ctx.receiving_occupancy.get(m, 0.0), cfg)
            term = s * (discharge - ctx.receiving_queue_pcu.get(m, 0.0))
            total += self._rate(cfg_t0, ctx, phase_id, m) * term
        view = self._priced_as(cfg_t0)
        return (
            total
            + acamp.fairness(view, ctx, cfg, phase_id)
            + acamp.anticipation(view, ctx, cfg, phase_id, urgency or {})
            + acamp.debt_recovery(view, cfg, phase_id, owed_s or {}, horizon_s)
        )

    def _eligible(self, cfg_t0: Tier0Config, ctx: JunctionContext, variant: str) -> bool:
        """A variant is a candidate while its approach is blocked, or while
        it is the phase actually running (so it can be compared and kept)."""
        if variant == self._actual:
            return True
        own = self._own(cfg_t0, variant)
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
        left_out = cfg_t0.phases[base].green_movements - self._served(cfg_t0, variant)
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
            if running and self._actual in self.base_of and v != self._actual:
                continue    # from a variant the only way on inside the family is the base
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
            # A blockage counts while its lane has its green: every movement
            # of the lane that the base phase serves is green now. A turner
            # left in the box under a red, or one whose through the running
            # variant has stopped, is waiting for the signal, not holding up
            # a green.
            showing = cfg_t0.phases[actual].green_movements
            whole = cfg_t0.phases[base].green_movements
            lanes_on = {}
            for x in whole:
                lane = self.lane_of.get(x)
                lanes_on[lane] = lanes_on.get(lane, True) and x in showing
            blocked = {m for m in ctx.blocked_by if lanes_on.get(self.lane_of.get(m), False)}
            for m in list(self._blocked_s):
                if m in blocked:
                    continue
                self._clear_s[m] = self._clear_s.get(m, 0.0) + self.tick_s
                if self._clear_s[m] > self.hol.blocked_grace_s:
                    del self._blocked_s[m]
                    del self._clear_s[m]
            for m in blocked:
                self._blocked_s[m] = self._blocked_s.get(m, 0.0) + self.tick_s
                self._clear_s.pop(m, None)
            if blocked:
                self.stats["hol_blocked_ticks"] += 1
        if base != self._visit_base:
            self._visit_base, self._visit_served = base, set()
            self._visit_started_s = self._sim_time_s - elapsed
            self._visit_used_variant = False
        if actual != base:
            self.stats["hol_variant_ticks"] += 1
            self._visit_used_variant = True
        self._visit_served |= self._served(cfg_t0, actual)

        # What the parent is told has elapsed: the running realisation's own
        # green, or -- once the visit has used a variant -- the visit's
        # whole length less one maximum green, whichever is more, so that
        # its maximum-green rule ends the visit at `family_budget` times the
        # base phase's ceiling (module docstring).
        told = elapsed
        if (self.hol.terminal and actual != base and elapsed >= cfg_t0.min_green_s.get(actual, 0.0)
                and self._idle(cfg_t0, ctx, actual, base)
                and self._others_have_demand(cfg_t0, ctx, base)):
            # done here, and somebody else is waiting: tell the parent the
            # phase has had its time
            told = max(told, cfg_t0.max_green_s.get(base, told))
            self.stats["hol_variant_moved_on"] += 1
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
        if not plan.steps:
            return plan
        if plan.source != "acamp":
            # the confidence ladder's fixed-time fallback, a corridor plan:
            # not this controller's decision, but the phase it leaves is the
            # one actually running, judged on its own green
            return self._leaving(cfg_t0, ctx, plan, base, actual, min_g, realise=False)

        if len(plan.steps) == 1 and plan.steps[0].phase_id == base:
            # the parent keeps the base phase: is another realisation of it
            # worth a change interval?
            target = None
            if elapsed >= min_g and self._others_can_wait(cfg_t0, ctx, base):
                if actual != base and self._idle(cfg_t0, ctx, actual, base):
                    target = base
                    self.stats["hol_variant_idle_exit"] += 1
                elif actual == base or self.hol.exit_by_pressure:
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

        return self._leaving(cfg_t0, ctx, plan, base, actual, min_g, realise=True)

    def _leaving(self, cfg_t0, ctx, plan: SignalPlan, base: str, actual: str, min_g: float,
                 *, realise: bool) -> SignalPlan:
        """The parent's plan in terms of the phases actually shown. Its first
        step is the phase running now, and when the plan leaves it, its own
        minimum green decides how soon (the parent may have been told the
        visit's clock, `__call__`). With `realise`, a later step is entered
        as its base phase's best realisation."""
        steps = []
        for i, st in enumerate(plan.steps):
            if i == 0 and st.phase_id == base:
                green_s = st.green_s
                if len(plan.steps) > 1 and actual not in ctx.faulted_phases:
                    own = acamp._exit_step(cfg_t0, ctx, actual, min_g, self.tick_s)  # noqa: SLF001
                    green_s = max(green_s, own.green_s)
                steps.append(replace(st, phase_id=actual, green_s=green_s))
            elif i > 0 and realise:
                realised = self._realised.get(st.phase_id, st.phase_id)
                if realised != st.phase_id:
                    self.stats["hol_variant_entry"] += 1
                steps.append(replace(st, phase_id=realised))
            else:
                steps.append(st)
        return replace(plan, steps=tuple(steps))

    def _others_have_demand(self, cfg_t0: Tier0Config, ctx: JunctionContext, base: str) -> bool:
        family = cfg_t0.phases[base].green_movements
        return any(acamp.q_hat(ctx, self.cfg, m) > 0.0
                   for p in cfg_t0.ring_order if p != base
                   for m in cfg_t0.phases[p].green_movements - family)

    def _others_can_wait(self, cfg_t0: Tier0Config, ctx: JunctionContext, base: str) -> bool:
        """Whether a change inside the family leaves every other phase's
        movements inside their maximum wait: the parent's starvation margin
        covers one change and a minimum green, and a change inside the
        family puts another change and another minimum green in front of
        whatever is waiting for the family to finish."""
        hold_s = (2.0 * (cfg_t0.yellow_s + cfg_t0.all_red_s)
                  + cfg_t0.min_green_s.get(base, 0.0) + acamp._SKIP_WAIT_MARGIN_S)  # noqa: SLF001
        family = cfg_t0.phases[base].green_movements
        return not any(
            has and m not in family
            and cfg_t0.max_wait_s - ctx.wait_times_s.get(m, 0.0) <= hold_s
            for m, has in ctx.has_demand.items()
        )

    def _idle(self, cfg_t0: Tier0Config, ctx: JunctionContext, variant: str, base: str) -> bool:
        """The variant's own approach has nothing left to serve -- no queue,
        nothing arriving -- while another movement of its base phase has.
        The parent's gap-out looks at the base phase's movements, where the
        other approach's queue reads as demand, so it would hold the empty
        approach's green to the ceiling."""
        own = self._own(cfg_t0, variant)
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
        unserved = cfg_t0.phases[base].green_movements - self._served(cfg_t0, actual)
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
        if leaving and not self._others_can_wait(cfg_t0, ctx, base):
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

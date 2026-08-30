"""A-CA-MP -- Adaptive Corridor-Anticipatory Max-Pressure (M5).

`camp.py` is deliberately left untouched: M4's gate comparison is a
recorded experimental result, and a strategy module edited after the fact
makes the numbers in PROGRESS.md unreproducible. This is a second
strategy that the gate can run *against* CA-MP, not a rewrite of it.

Three defects in M4's pressure function are fixed here, and one whole
class of them is removed rather than fixed. Each is stated with the
evidence, because two of the three are visible in `camp.py`'s own
docstrings as accepted consequences rather than as bugs.

---

**Defect 1 (the serious one): M4's flow/block pair can never be
positive.**

`camp.py` computes, per movement:

    P_flow  = s_m · q_m
    P_block = s_m · q_m · θ_m,   θ_m = min(θ_max, 1 / max(ε, 1 − ρ_m))

and subtracts the second from the first, giving `s_m · q_m · (1 − θ_m)`.
But `1 / (1 − ρ)` is `≥ 1` for every `ρ ∈ [0, 1)`, so `θ_m ≥ 1` always,
so that product is `≤ 0` **always** -- and grows *more* negative as the
queue grows. The two terms that are supposed to constitute the
"max-pressure" core of a max-pressure controller are, jointly, a penalty
on having a queue at all. A phase with 20 PCU waiting scores strictly
worse than an identical phase with 0 PCU waiting.

`camp.py`'s docstring records the `ρ = 0` special case of this ("`P_flow`
and `P_block` cancel *exactly*... raw queue size alone cannot break a tie
between two candidate phases") and reasons about it as a faithful
consequence of following §4's reference code over §3.4's prose. It is
faithful to that code. It is also, at every `ρ > 0`, strictly worse than
cancellation, and it is sufficient on its own to explain the M4 gate's
central negative result -- CA-MP losing to Webster by ~2.3x at light and
~2.0x at medium demand, the two regimes where receiving links are
empty and nothing else in `𝒫(p)` scales with queue size either.

The root cause is the ambiguity `camp.py` flagged and resolved the wrong
way: §3.4's prose defines `P_block` over "the queue on the *receiving*
link", §4's reference code reuses `m`'s own upstream `q_pcu`, and M4
followed the code because no lane→downstream-lane queue source existed.
One did exist -- `link_lanes.link_to_receiving_lane_map()`, already used
for `receiving_occupancy` -- so `JunctionContext.receiving_queue_pcu` now
carries the real downstream queue and the prose reading is available:

    P_press(p) = Σ_m s_m · (q̂_m · gate(ρ_m) − r_m)

with `r_m` the receiving link's own queue. At free flow (`gate = 1`,
`r = 0`) this reduces to `Σ s_m · q̂_m`, textbook max-pressure [Varaiya,
*Max pressure control of a network of signalized intersections*, Transp.
Res. Part C 36 (2013)], monotone increasing in queue size -- the property
M4's version inverted. Under downstream congestion it goes negative, which
is the behaviour M4's θ term was *trying* to produce.

`gate(ρ) = max(0, 1 − (ρ/ρ_jam)^β) ∈ [0, 1]` replaces `θ ∈ [1, θ_max]` as
the spillback guard. A multiplicative discount on the discharge benefit
cannot flip the term's sign, which is exactly the failure θ had; and the
`− r_m` term supplies the genuine negative pressure that "do not
discharge into a jam" requires, from a real measurement rather than from
a scaled copy of the upstream queue.

---

**Defect 2: `q̂_l = q_l` -- blind to platoons it released itself.**

M4 scoped arrival augmentation to Layer 2's projected-outflow exchange
and set `q̂_l = q_l` meanwhile. But the part of `∫ â_l dτ` contributed by
vehicles *already on this junction's own approach* needs no exchange with
anyone -- only a look at the lane. `JunctionContext.approaching_pcu`
supplies it (see `queue_state.QueueStateSampler._approaching_pcu` for the
time-to-arrival test and why it is a time test, not Advanced-MP's fixed
distance), and:

    q̂_m = q_m + η · a_m

Zhang et al. [*Expression might be enough*, ICML 2022] measure this term's
value in isolation: adding running vehicles to an otherwise-unchanged
max-pressure controller is worth 1.7-6.0% average travel time across
JiNan/HangZhou/New York, with no training of any kind. Layer 2's exchange
remains the right source for arrivals still upstream of a *neighbour*;
this is the strictly-local part that never needed to wait for it.

---

**Defect 3, removed rather than fixed: the subtracted switching cost.**

M4's `S(p)` is a per-phase constant subtracted from pressure. PROGRESS.md
records what that produced, measured: 61x typical flow pressure at light
demand, 22x at medium, 5x at heavy; 100% of phase changes at every demand
level were `max_green_s` timeouts; the current phase was the outright
pressure maximum on 100% of 44,000+ extend-eligible ticks. The controller
was functionally fixed-time everywhere. The rescaling fix that followed
brought `S(p)` onto `P_flow`'s units and was correct as far as it went,
but a constant is `O(1)` against pressure differences that scale with
queue size, so *some* demand level below which it dominates always
exists -- and the rescale then produced a structural starvation deadlock
(PROGRESS.md's `cluster_1880441740_4393296791`, 10235 interlock
rejections) that needed a starvation override to contain.

Both failures are the same shape: a scale-free comparison being decided
by a term that does not scale. So there is no switching term in `𝒫(p)`
here at all. Switching is instead a separate *test* between the incumbent
and the challenger:

    switch iff  max_p 𝒫(p)  >  𝒫(current) + F(scale)

with `F` the sublinear hold bias of `memory.sublinear_hold_bias` -- see
that function for why `0 < α < 1` makes M4's failure mode unreachable by
construction rather than by tuning, and how it connects to the
throughput-optimality argument [Xu et al., Transp. Res. Part C 137
(2022)]. Two consequences worth naming:

- `hysteresis_frac` is gone. M4's own sweep found it bit-identical across
  `{0.0, 0.05, 0.15}` at every seed and demand level, because the
  incumbent's pressure was never close enough to the maximum for a
  tolerance band to matter. `F(scale)` is that tolerance band, made
  state-dependent and given a reason to exist.
- The starvation override is kept anyway. Its own justification in
  `camp.py` was specific to `S(p)`'s scale, which is gone; but `𝒫(p)` can
  still legitimately rank a starved movement's phase below others when
  its receiving link is jammed (`− r_m` is large), and I5 is a hard
  bound regardless of why a controller approached it. Kept as defence in
  depth, and expected to fire less; `scripts/m5_gate_comparison.py`
  reports how often it actually does.

---

**Statefulness, and why the `Strategy` type did not have to change.**

`runner.py` types a strategy as `Callable[[Tier0Config, JunctionContext],
SignalPlan]` and rebuilds `JunctionContext` from scratch every tick, so a
plain function strategy has no channel through which to remember
anything -- which is the architectural reason M4 could not have had a
memory even if `q_hist` had existed. A callable *object* satisfies that
same type while owning state, and the runner already binds per-junction
strategy state this way (`partial(camp.propose, nominal_cycle_s=...)`).
`AdaptiveCamp` is therefore an instance per junction, holding its
`DemandMemory` handle and its own notion of simulation time, and it drops
into every existing call site unchanged.

The pressure math itself stays a set of module-level pure functions, for
the same reason every other strategy in this package is pure: it is what
makes the Hypothesis property tests possible. The class is a thin
stateful shell around pure arithmetic, not a stateful algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config

from sim_service.control import memory as memory_mod
from sim_service.control.strategies import fixed_time

_CONFIDENCE_FULL_THRESHOLD = 0.8
_CONFIDENCE_BLENDED_THRESHOLD = 0.5

# Same 15s margin `camp._skippable`/`_critical_phases` use, kept identical
# rather than re-derived: it is the distance from I5's bound at which this
# build stops trusting a ranking decision, and having two different
# answers to that question in two strategies would be a latent
# inconsistency, not a tuning choice.
_SKIP_WAIT_MARGIN_S = 15.0


@dataclass(frozen=True)
class AcampConfig:
    """Tier-1 tunables. Every field here is a *learnable* parameter --
    `tuning.py` optimizes this exact dataclass -- with the deliberate
    exception of nothing: there is no hand-set constant in the pressure
    function that the tuner is not allowed to move.

    That is the point. PROGRESS.md documents a multi-session manual search
    over exactly these quantities (a hysteresis sweep that came back
    bit-identical, a diagnostic run to find `S(p)`'s scale, a rescale, a
    starvation deadlock, an override) and the honest reading of that
    history is not that the constants were picked badly -- it is that
    hand-picking ~10 interacting constants against a stochastic simulator
    is not a thing a person should be doing by hand at all. Defaults below
    are a *starting point for the search*, not claims about the optimum.

    Bounds for the search live in `tuning.PARAM_SPACE`, next to the
    optimizer that uses them, not here."""

    # -- pressure shape --
    eta_arrival: float = 0.5
    """Weight on `approaching_pcu` in `q̂_m = q_m + η·a_m`. Below 1.0 by
    default because an approaching vehicle is a *probable* arrival, not a
    committed one -- it can still turn off, or fail to clear the platoon
    ahead of it -- and weighting it equal to a vehicle already stopped at
    the line would overstate the phase's real claim."""

    rho_jam: float = 0.75
    """Receiving-link occupancy at which `gate` reaches zero and this
    movement's discharge benefit is fully withdrawn. Not 1.0: a link is
    functionally blocked well before it is bumper-to-bumper, and
    discharging into one at 0.9 occupancy is what creates the spillback
    the gate exists to prevent."""

    beta_gate: float = 2.0
    """Sharpness of the gate's rolloff. `1.0` is linear in occupancy;
    above 1.0 keeps the gate near-open through light downstream loading
    and closes it sharply near `rho_jam`, which matches how discharge
    capacity actually behaves against a filling link (roughly flat, then
    a knee) better than a linear ramp does."""

    # -- fairness --
    lambda_f: float = 0.6
    gamma: float = 3.0
    """§3.9's defaults, carried over unchanged. The fairness term is the
    one part of M4's `𝒫(p)` with no identified defect -- it was simply
    never exercised, because `S(p)` ensured phase changes were always
    timeouts. It is inherited as-is so that any behaviour change measured
    against M4 is attributable to the terms that did change."""

    # -- switching --
    kappa_switch: float = 0.5
    alpha_switch: float = 0.5
    """`F(scale) = κ · scale^α`, the sublinear hold bias replacing M4's
    constant `S(p)`. `α` is constrained to the open interval `(0, 1)` by
    `memory.sublinear_hold_bias` itself, which raises rather than clamps:
    a tuner that wandered to `α = 0` would silently reconstruct M4's
    original bug, and a silent reconstruction of a known bug is worse than
    a crash."""

    # -- ring --
    k: int = 2
    """§3.7's limited ring lookahead."""

    # -- degradation ladder --
    use_memory_blend: bool = True
    """Whether the "camp_blended" rung actually blends against
    `DemandMemory`, or falls through to fixed-time the way M4's did.
    An ablation switch for the gate, not a production setting -- the same
    role `camp.CampConfig.enable_blocking` plays for M4's θ ablation, and
    kept for the same reason: one codepath serving both arms beats two
    hand-maintained copies that can drift."""


# --------------------------------------------------------------------
# Pure pressure arithmetic. No I/O, no clock, no memory handle -- every
# historical value arrives pre-blended in `q_hat`, so these functions are
# unit- and property-testable exactly like `camp`'s and `webster`'s.
# --------------------------------------------------------------------


def gate(occupancy: float, cfg: AcampConfig) -> float:
    """`max(0, 1 − (ρ/ρ_jam)^β) ∈ [0, 1]`. Never negative and never
    greater than 1, which together are the whole reason this replaces
    `θ ∈ [1, θ_max]`: a multiplicative factor bounded in `[0, 1]` can
    discount a discharge benefit to nothing but cannot invert its sign,
    so `P_press` stays monotone increasing in `q̂` at every occupancy."""
    if occupancy <= 0.0:
        return 1.0
    if cfg.rho_jam <= 0.0:
        return 0.0
    ratio = occupancy / cfg.rho_jam
    if ratio >= 1.0:
        return 0.0
    return max(0.0, 1.0 - ratio**cfg.beta_gate)


def q_hat(ctx: JunctionContext, cfg: AcampConfig, movement: str) -> float:
    """`q̂_m = q_m + η·a_m` from already-blended context values."""
    return ctx.queue_pcu.get(movement, 0.0) + cfg.eta_arrival * ctx.approaching_pcu.get(
        movement, 0.0
    )


def press_pressure(cfg_t0: Tier0Config, ctx: JunctionContext, cfg: AcampConfig, phase_id: str) -> float:
    """`Σ_m s_m · (q̂_m · gate(ρ_m) − r_m)` -- Defect 1's fix."""
    total = 0.0
    for m in cfg_t0.phases[phase_id].green_movements:
        s = cfg_t0.sat_flow_pcu_s.get(m, 0.0)
        discharge = q_hat(ctx, cfg, m) * gate(ctx.receiving_occupancy.get(m, 0.0), cfg)
        receiving = ctx.receiving_queue_pcu.get(m, 0.0)
        total += s * (discharge - receiving)
    return total


def fairness(cfg_t0: Tier0Config, ctx: JunctionContext, cfg: AcampConfig, phase_id: str) -> float:
    """§3.4 Term 3, unchanged from `camp._fairness` in both shape and
    defaults -- see `AcampConfig.gamma`."""
    if cfg_t0.max_wait_s <= 0:
        return 0.0
    total = 0.0
    for m in cfg_t0.phases[phase_id].green_movements:
        if ctx.queue_pcu.get(m, 0.0) <= 0.0:
            continue
        wait_ratio = min(ctx.wait_times_s.get(m, 0.0) / cfg_t0.max_wait_s, 1.0)
        total += cfg_t0.sat_flow_pcu_s.get(m, 0.0) * (wait_ratio**cfg.gamma)
    return cfg.lambda_f * total


def pressure(cfg_t0: Tier0Config, ctx: JunctionContext, cfg: AcampConfig, phase_id: str) -> float:
    """`𝒫(p) = P_press(p) + F(p)`. No switching term -- Defect 3."""
    return press_pressure(cfg_t0, ctx, cfg, phase_id) + fairness(cfg_t0, ctx, cfg, phase_id)


def pressure_scale(cfg_t0: Tier0Config, ctx: JunctionContext, cfg: AcampConfig) -> float:
    """`Σ_m s_m · q̂_m` over every movement at the junction -- the
    magnitude the hold bias is computed against.

    Deliberately built from `q̂` alone, not from `|𝒫(p)|`: the hold bias
    must answer "how loaded is this junction", and `𝒫` can be near zero at
    a heavily-loaded junction whose receiving links are equally loaded
    (the `− r_m` term cancelling the discharge term). Sizing the bias off
    `𝒫` would therefore make a gridlocked junction look empty and switch
    it freely, which is the opposite of what congestion calls for."""
    total = 0.0
    for m in _all_movements(cfg_t0):
        total += cfg_t0.sat_flow_pcu_s.get(m, 0.0) * q_hat(ctx, cfg, m)
    return total


def _all_movements(cfg_t0: Tier0Config) -> frozenset[str]:
    if not cfg_t0.phases:
        return frozenset()
    return frozenset().union(*(p.green_movements for p in cfg_t0.phases.values()))


def select_mode(ctx: JunctionContext, movements: frozenset[str]) -> str:
    """§3.8's confidence ladder, identical to `camp.select_mode`. Unlike
    M4's, the "camp_blended" rung it returns now has a real
    implementation behind it (`AdaptiveCamp._blend_context`)."""
    if not movements:
        return "camp_full"
    c_i = min(ctx.confidence.get(m, 1.0) for m in movements)
    if c_i >= _CONFIDENCE_FULL_THRESHOLD:
        return "camp_full"
    if c_i >= _CONFIDENCE_BLENDED_THRESHOLD:
        return "camp_blended"
    return "profile_actuated"


def _ring_candidates(ring_order: tuple[str, ...], current: str, k: int) -> list[str]:
    n = len(ring_order)
    if n < 2:
        return []
    try:
        idx = ring_order.index(current)
    except ValueError:
        idx = -1
    span = min(k, n - 1)
    return [ring_order[(idx + offset) % n] for offset in range(1, span + 1)]


def _skippable(cfg_t0: Tier0Config, ctx: JunctionContext, phase_id: str) -> bool:
    phase = cfg_t0.phases[phase_id]
    if phase.is_pedestrian:
        return False
    q = sum(ctx.queue_pcu.get(m, 0.0) for m in phase.green_movements)
    a = sum(ctx.approaching_pcu.get(m, 0.0) for m in phase.green_movements)
    if q > 0 or a > 0:
        # Note the `a > 0` clause, absent from `camp._skippable`: a phase
        # with an empty stop line but a platoon 6 seconds out is exactly
        # the case anticipation exists to catch, and skipping it would
        # discard the information the arrival term was added to provide.
        return False
    w = max((ctx.wait_times_s.get(m, 0.0) for m in phase.green_movements), default=0.0)
    return w < cfg_t0.max_wait_s - _SKIP_WAIT_MARGIN_S


def _critical_phases(cfg_t0: Tier0Config, ctx: JunctionContext, live: list[str]) -> list[str]:
    """Kept from `camp._critical_phases` unchanged -- see this module's
    docstring, Defect 3, for why it is retained even though the specific
    deadlock that motivated it is gone."""
    urgency: list[tuple[float, str]] = []
    for p in live:
        margins = [
            cfg_t0.max_wait_s - ctx.wait_times_s.get(m, 0.0)
            for m in cfg_t0.phases[p].green_movements
            if ctx.has_demand.get(m, False)
        ]
        if not margins:
            continue
        margin = min(margins)
        if margin <= _SKIP_WAIT_MARGIN_S:
            urgency.append((margin, p))
    urgency.sort(key=lambda pair: pair[0])
    return [p for _, p in urgency]


def _exit_step(
    cfg_t0: Tier0Config, ctx: JunctionContext, current: str, min_g: float, tick_s: float
) -> PlanStep:
    green_s = 0.0 if current in ctx.faulted_phases else max(tick_s, min_g - ctx.current_phase_elapsed_s)
    return PlanStep(
        phase_id=current, green_s=green_s, yellow_s=cfg_t0.yellow_s, all_red_s=cfg_t0.all_red_s
    )


def allocate_green(
    cfg_t0: Tier0Config, phase_id: str, pressures: dict[str, float], nominal_cycle_s: float
) -> float:
    """§3.7's proportional allocation, with one change forced by Defect
    1's fix: pressures are now genuinely signed (a phase discharging into
    a fuller link than its own has negative pressure, correctly), so the
    proportional weight uses each pressure's *positive part*.

    M4's version guarded only the aggregate (`if total_pressure <= 0:
    return min_g`), which was sufficient there because its pressures were
    almost always non-positive together. Here a mix of signs is the normal
    case, and dividing a positive `𝒫(p)` by a sum that includes negative
    terms can produce a weight above 1 -- allocating a phase more than the
    whole nominal cycle. Clamping to `max_green_s` would hide that rather
    than fix it."""
    min_g = cfg_t0.min_green_s.get(phase_id, 0.0)
    max_g = cfg_t0.max_green_s.get(phase_id, min_g)
    positive = {p: max(0.0, v) for p, v in pressures.items()}
    total = sum(positive.values())
    if total <= 0.0 or positive.get(phase_id, 0.0) <= 0.0:
        return min_g
    proportional = nominal_cycle_s * (positive[phase_id] / total)
    return max(min_g, min(max_g, proportional))


class AdaptiveCamp:
    """One junction's A-CA-MP controller. Callable as
    `(Tier0Config, JunctionContext) -> SignalPlan`, so it satisfies
    `runner.Strategy` without any change to that type.

    Instances are stateful in exactly two ways, both of which exist to
    give the controller the memory `camp.propose` architecturally could
    not have: a handle on the shared `DemandMemory`, and its own view of
    simulation time (set by the runner via `set_sim_time`, since
    `JunctionContext` carries no clock and adding one would change a type
    four other strategies depend on).

    `stats` accumulates decision counts for the gate to report. It is
    instrumentation, not control -- nothing in `__call__` reads it -- so
    a benchmark can quantify *how* the controller behaved rather than only
    what delay resulted. M4's central diagnostic finding ("100% of phase
    changes were max_green timeouts") took a separate instrumented rerun
    to discover; making the controller count its own decisions means the
    equivalent question is answerable from any run, including the gate's.
    """

    def __init__(
        self,
        cfg: AcampConfig | None = None,
        *,
        nominal_cycle_s: float = 60.0,
        tick_s: float = 1.0,
        demand_memory: memory_mod.DemandMemory | None = None,
    ) -> None:
        self.cfg = cfg or AcampConfig()
        self.nominal_cycle_s = nominal_cycle_s
        self.tick_s = tick_s
        self.memory = demand_memory
        self._sim_time_s = 0.0
        self.stats: dict[str, int] = {
            "ticks": 0,
            "extend": 0,
            "switch_pressure": 0,
            "switch_max_green": 0,
            "switch_starvation": 0,
            "blended": 0,
            "fallback_fixed_time": 0,
        }

    def set_sim_time(self, sim_time_s: float) -> None:
        self._sim_time_s = sim_time_s

    def _blend_context(self, ctx: JunctionContext) -> JunctionContext:
        """The "camp_blended" rung, made real. Replaces `queue_pcu` and
        `approaching_pcu` with confidence-weighted blends of the live
        reading and this junction's own historical profile for this time
        of day, leaving every other field untouched.

        A movement with no usable history blends to itself
        (`memory.blend` returns `live` when `historical is None`), so a
        cold-start controller degrades to live-only rather than to zeros.
        Returns a new context rather than mutating: `JunctionContext` is
        frozen, and the interlocks check the *unblended* reality the
        cabinet actually faces -- blending is a control-side estimate, and
        it must not be able to reach the safety kernel's own view of the
        world."""
        if self.memory is None:
            return ctx
        blended_q: dict[str, float] = {}
        blended_a: dict[str, float] = {}
        for m, live_q in ctx.queue_pcu.items():
            hist = self.memory.profile(ctx.intersection_id, m, self._sim_time_s)
            c = ctx.confidence.get(m, 1.0)
            blended_q[m] = memory_mod.blend(live_q, None if hist is None else hist[0], c)
            blended_a[m] = memory_mod.blend(
                ctx.approaching_pcu.get(m, 0.0), None if hist is None else hist[1], c
            )
        return replace(ctx, queue_pcu=blended_q, approaching_pcu=blended_a)

    def __call__(self, cfg_t0: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        self.stats["ticks"] += 1
        cfg = self.cfg

        mode = select_mode(ctx, _all_movements(cfg_t0))
        if mode == "camp_blended" and cfg.use_memory_blend and self.memory is not None:
            ctx = self._blend_context(ctx)
            self.stats["blended"] += 1
        elif mode != "camp_full":
            # "profile_actuated" still has no plan library to actuate
            # against -- unchanged from M4, and still the honest fallback
            # rather than a half-implemented rung.
            self.stats["fallback_fixed_time"] += 1
            return fixed_time.propose(cfg_t0, ctx)

        current = ctx.current_phase_id
        elapsed = ctx.current_phase_elapsed_s
        current_faulted = current in ctx.faulted_phases

        live = [p for p in cfg_t0.ring_order if p not in ctx.faulted_phases]
        if not live:
            return SignalPlan(intersection_id=cfg_t0.intersection_id, steps=(), source="acamp")

        pressures = {p: pressure(cfg_t0, ctx, cfg, p) for p in live}
        min_g = cfg_t0.min_green_s.get(current, 0.0)
        max_g = cfg_t0.max_green_s.get(current, min_g)

        # I3 (minimum green) is absolute and checked before everything
        # else, exactly as in `camp.propose` -- no pressure, starvation or
        # memory consideration can cut a phase short of its safety floor.
        if not current_faulted and elapsed < min_g:
            self.stats["extend"] += 1
            return SignalPlan(
                intersection_id=cfg_t0.intersection_id,
                steps=(PlanStep(phase_id=current, green_s=self.tick_s),),
                source="acamp",
            )

        critical = _critical_phases(cfg_t0, ctx, live)
        if critical and current not in critical:
            self.stats["switch_starvation"] += 1
            return self._advance(cfg_t0, ctx, current, critical[0], pressures, min_g)

        if not current_faulted and elapsed < max_g:
            best = max(pressures.values())
            scale = pressure_scale(cfg_t0, ctx, cfg)
            hold_bias = memory_mod.sublinear_hold_bias(scale, cfg.kappa_switch, cfg.alpha_switch)
            if pressures[current] + hold_bias >= best:
                self.stats["extend"] += 1
                return SignalPlan(
                    intersection_id=cfg_t0.intersection_id,
                    steps=(PlanStep(phase_id=current, green_s=self.tick_s),),
                    source="acamp",
                )
            self.stats["switch_pressure"] += 1
        elif not current_faulted:
            self.stats["switch_max_green"] += 1

        ring = [p for p in _ring_candidates(cfg_t0.ring_order, current, cfg.k) if p not in ctx.faulted_phases]
        candidates = ring or live
        filtered = [p for p in candidates if not _skippable(cfg_t0, ctx, p)]
        if filtered:
            candidates = filtered

        next_phase = max(candidates, key=lambda p: pressures[p])
        return self._advance(cfg_t0, ctx, current, next_phase, pressures, min_g)

    def _advance(
        self,
        cfg_t0: Tier0Config,
        ctx: JunctionContext,
        current: str,
        next_phase: str,
        pressures: dict[str, float],
        min_g: float,
    ) -> SignalPlan:
        return SignalPlan(
            intersection_id=cfg_t0.intersection_id,
            steps=(
                _exit_step(cfg_t0, ctx, current, min_g, self.tick_s),
                PlanStep(
                    phase_id=next_phase,
                    green_s=allocate_green(cfg_t0, next_phase, pressures, self.nominal_cycle_s),
                ),
            ),
            source="acamp",
        )

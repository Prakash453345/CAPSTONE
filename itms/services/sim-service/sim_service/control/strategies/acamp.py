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
from sim_service.control.online_calibration import OnlineCalibration
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

    lost_time_weight: float = 1.0
    """Scales `memory.switch_cost_bias`, the *derived* half of the
    switching test -- the pressure advantage a challenger must show for a
    clearance interval to pay for itself, `P_best · L/T`. Default 1.0 is
    the untuned economic answer rather than a guess, and the parameter
    exists only so the search can disagree with a derivation it might find
    mis-specified for this corridor. Setting it to 0 recovers the
    sublinear-only behaviour measured in `m5_heavy_diag.json`, which is
    the ablation arm for this term."""

    startup_lost_s: float = 2.0
    """The start-up lost time component of `L = yellow + all_red +
    startup`, carried over unchanged from `camp.CampConfig` -- the
    conventional "first vehicle reaction" allowance neither `yellow_s` nor
    `all_red_s` carries, and still unmeasured per junction here."""

    switch_scale_ref: float = 4.0
    switch_scale_exponent: float = 3.0
    load_halflife_s: float = 300.0
    """The congestion gate on `switch_cost_bias` -- see
    `memory.congestion_weight` for the measurements that forced it, and
    why the gated quantity is a *smoothed* load rather than the
    instantaneous one.

    The first version of this gate read `pressure_scale` directly and did
    nothing at all, which is worth recording because the reason is not
    obvious from the run-level averages that motivated it. Averaged over a
    whole run, `pressure_scale` separates the regimes cleanly (~1.1 light
    against ~8.5 heavy). Sampled at the ticks where the switch test
    actually executes, it does not: median 0.21 at light against 0.28 at
    heavy, with the difference living entirely in the tail (p90 9.8
    against 37.8). A junction at light demand with a platoon arriving is
    instantaneously indistinguishable from a saturated one -- which is
    exactly the case the gate has to tell apart, since it is the case
    where refusing to switch costs a waiting movement its green for no
    capacity saving.

    So the gate reads an EWMA of `pressure_scale` instead: whether this
    junction has *been* loaded, not whether it is loaded this second.
    `load_halflife_s` of 300s is long relative to a cycle and short
    relative to a demand period, so it tracks the difference between a
    busy hour and a quiet one while ignoring individual platoons. This is
    the controller's fourth memory and the only one that feeds a control
    decision every tick -- the others are consulted, this one is
    accumulated.

    **`switch_scale_ref` is a *ratio to this junction's own baseline*, not
    an absolute PCU number -- a second correction forced by measurement,
    the same shape as the one above.** `scripts/m5_regime_threshold_probe.py`
    ran the tuned controller at all three demand levels and recorded each
    junction's own smoothed load, not just the corridor-wide mean the
    original tuning was justified against: at heavy demand the seven
    junctions read `[0.94, 1.02, 0.70, 1.86, 5.66, 3.39, 33.03]` -- a 47x
    spread, while their total discharge capacity (`Σ sat_flow_pcu_s`)
    spans only 2.4-6.8 (2.8x), so the spread is a real difference in how
    busy each junction actually is, not a scale artefact to normalize
    away by capacity. One junction (`cluster_1880441740_4393296791`, this
    corridor's heaviest) dominates the corridor-wide average the original
    `switch_scale_ref = 7.10` was fit against, clears it easily, and was
    already more than halfway there at *medium* demand (mean 6.86). The
    other six junctions never approach 7.10 even at heavy demand -- so a
    single global absolute reference gives six of this corridor's seven
    junctions essentially no congestion pricing at any demand level
    tested, which is exactly the shape of measurement mistake this
    module's own history already made once (a corridor-wide average
    hiding what individual ticks see) recurring one level up, at the
    junction rather than the tick.

    The fix is the same one used there: stop comparing to a fixed
    reference and compare to *this junction's own recent normal*
    instead. `AdaptiveCamp` also tracks a second, much slower EWMA of
    load (`baseline_halflife_s`) and feeds `congestion_weight` the ratio
    `load_ewma / baseline_load_ewma` rather than `load_ewma` itself.
    `switch_scale_ref` now reads as "how many times above its own recent
    normal counts as congested for this junction" -- a quantity that
    means the same thing on a two-lane approach and a fourteen-movement
    cluster, which an absolute PCU number provably does not on this
    corridor. Ratio semantics also make the parameter's scale interpretable
    without corridor-specific calibration, which the previous 7.10 was
    not: it was a fit to this corridor's one hottest junction and would
    need re-deriving from scratch on any other network."""

    baseline_halflife_s: float = 3600.0
    """Half-life of the slow EWMA `switch_scale_ref` is measured against
    when `use_relative_congestion_gate` is on -- see that field for why it
    defaults off. Deliberately much longer than `load_halflife_s`: the
    fast EWMA answers "how loaded is this junction right now", the slow
    one is meant to answer "what does loaded normally look like here"."""

    use_relative_congestion_gate: bool = False
    """Off by default -- a documented negative result, not a half-built
    feature. `relative_load` (this junction's smoothed load divided by its
    own slow baseline) genuinely fixes a real defect:
    `scripts/m5_regime_threshold_probe.py` measured this corridor's seven
    junctions' smoothed load at heavy demand spanning 0.70 to 33.03 (47x)
    while their discharge capacity spans only 2.4-6.8 (2.8x), so a single
    global *absolute* `switch_scale_ref` gives six of the seven junctions
    almost no congestion pricing at any demand level -- proven as a
    property in `test_relative_load_is_scale_invariant_across_junction_size`,
    which the raw absolute signal cannot pass.

    Turning it on does not, however, close the heavy-demand gap.
    `scripts/m5_relative_congestion_sweep.py` searched `switch_scale_ref`
    (now a ratio) on `TRAIN_SEEDS` and found every value that helped heavy
    materially hurt medium (e.g. ref=3.0: heavy -9.6% but medium +38%
    against the ref=7.10 control) -- the same "no single global value
    serves both regimes" shape `congestion_weight`'s own docstring already
    documents for `lost_time_weight`, recurring one level down. The
    likely reason is structural rather than a bad parameter choice: each
    `AdaptiveCamp` instance is constructed fresh per simulated run
    (`m5_harness.build_acamp`), so `_baseline_load_ewma` starts cold every
    time and a single demand-level run here lasts only ~2,400-3,700
    simulated seconds (PROGRESS.md's own recorded step counts) -- too
    short, at any baseline half-life slow enough to deserve the name, for
    the baseline to separate "this run's genuine normal" from "still
    catching up from a cold start". `DemandMemory` already solves exactly
    this shape of problem for queues (`q_hist`, persisted across seeds
    on disk, one seed treated as one day) but has no equivalent for this
    load signal yet.

    So this stays off by default -- flipping it on with today's
    infrastructure trades a documented medium-demand loss for an
    unreliable heavy-demand gain, which is not a trade this corridor
    should take -- and is kept, tested, and documented rather than deleted
    so the next attempt starts from "persist the baseline across seeds
    like `DemandMemory` does" instead of re-discovering this measurement
    from scratch."""

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
    than fix it.

    **Weights come from pressure's *rank*, not its sign** -- a correction
    forced by measurement. Taking each pressure's positive part, as this
    function first did, collapses the whole allocation to `min_green_s`
    whenever every phase is negative at once, and
    `scripts/m5_heavy_diagnostics.py` measured that happening on 47% of
    ticks at heavy demand and 41% at light: this corridor's receiving-link
    queues routinely exceed its approach queues, so a uniformly negative
    ranking is the *normal* case here, not a degenerate one. The result
    was 30% of all allocations pinned at the bare minimum green for no
    reason connected to the traffic.

    Pressure is a *relative* quantity. An offset common to every phase --
    which is exactly what corridor-wide downstream congestion applies --
    carries no information about which phase deserves the green, so the
    allocation must be invariant to it. Shifting by the minimum before
    normalizing makes it so: the phase ranked last gets the floor, the
    rest share the cycle in proportion to how far they beat it. When every
    phase is genuinely equal the shift leaves nothing to divide and
    `min_green_s` is then the correct answer rather than an artefact."""
    min_g = cfg_t0.min_green_s.get(phase_id, 0.0)
    max_g = cfg_t0.max_green_s.get(phase_id, min_g)
    if phase_id not in pressures:
        return min_g
    floor = min(pressures.values())
    relative = {p: v - floor for p, v in pressures.items()}
    total = sum(relative.values())
    if total <= 0.0:
        return min_g
    proportional = nominal_cycle_s * (relative[phase_id] / total)
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
        calibration: OnlineCalibration | None = None,
    ) -> None:
        self.cfg = cfg or AcampConfig()
        self.nominal_cycle_s = nominal_cycle_s
        self.tick_s = tick_s
        self.memory = demand_memory
        self.calibration = calibration
        self._sim_time_s = 0.0
        self._load_ewma = 0.0
        """Smoothed `pressure_scale` -- see `AcampConfig.load_halflife_s`
        for why the congestion gate reads this rather than the live value.
        Starts at 0, so a freshly-started controller treats itself as
        uncongested and prices no switching cost until it has actually
        observed sustained load, which is the correct cold-start
        behaviour: it degrades toward the light-demand controller, which
        is the arm that is never catastrophically wrong."""
        self._baseline_load_ewma = 0.0
        """This junction's own slow-moving 'normal' load -- see
        `AcampConfig.switch_scale_ref`'s docstring for why the congestion
        gate compares against this instead of a fixed number. Also starts
        at 0 for the same cold-start reason as `_load_ewma`; `relative_load`
        guards the division so an unwarmed baseline reads as
        'not congested' rather than dividing by zero."""
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

    def _phase_horizon_s(self, cfg_t0: Tier0Config) -> float:
        """How long one phase can expect to hold if it wins -- the horizon
        `switch_cost_bias` amortizes the clearance interval over.

        One phase's *share* of the nominal cycle, not the whole cycle.
        Getting this wrong is worth recording, because the first version
        of this term used the full `nominal_cycle_s` and the error was
        invisible at the demand level it was reasoned about: that cycle
        comes from `webster.compute_timing`, which correctly lengthens
        under load -- to 180s at this corridor's heavy demand against a
        40s floor at light. So `L/T` *shrank* from 17% to 4% exactly as
        demand rose, making the switching threshold most permissive
        precisely where a wasted clearance interval costs most, which is
        the failure the term was added to fix. Dividing by the ring length
        keeps the ratio near-constant across demand levels, because
        Webster lengthens the cycle and each phase's share together."""
        n = max(1, len(cfg_t0.ring_order))
        return max(1.0, self.nominal_cycle_s / n)

    def _update_load(self, cfg_t0: Tier0Config, ctx: JunctionContext) -> None:
        """Fold this tick's `pressure_scale` into both the fast and the
        slow EWMA -- see `AcampConfig.baseline_halflife_s` for why the
        congestion gate needs both rather than just the fast one."""
        scale = pressure_scale(cfg_t0, ctx, self.cfg)
        fast_half_life = max(1e-6, self.cfg.load_halflife_s)
        fast_decay = 0.5 ** (self.tick_s / fast_half_life)
        self._load_ewma = fast_decay * self._load_ewma + (1.0 - fast_decay) * scale

        slow_half_life = max(1e-6, self.cfg.baseline_halflife_s)
        slow_decay = 0.5 ** (self.tick_s / slow_half_life)
        self._baseline_load_ewma = slow_decay * self._baseline_load_ewma + (1.0 - slow_decay) * scale

    @property
    def smoothed_load(self) -> float:
        """Exposed for diagnostics and tests; nothing in the control path
        reads it except `__call__`'s own gate."""
        return self._load_ewma

    @property
    def baseline_load(self) -> float:
        """This junction's own slow-moving 'normal' load. Exposed for
        diagnostics and tests alongside `smoothed_load`."""
        return self._baseline_load_ewma

    @property
    def relative_load(self) -> float:
        """`smoothed_load / baseline_load`, guarded against an unwarmed
        or zero baseline -- the quantity `congestion_weight` is now
        measured against instead of the raw (absolute, junction-scale-
        dependent) smoothed load. See `AcampConfig.switch_scale_ref`'s
        docstring for the measurement that forced this. Reads 0.0 (not
        congested) rather than raising or reading infinite when the
        baseline hasn't accumulated any load yet, which is the correct
        cold-start answer for the same reason `_load_ewma` itself starts
        at 0: an unwarmed controller should degrade toward the
        never-catastrophic light-demand behaviour, not toward a division
        by a near-zero denominator."""
        if self._baseline_load_ewma <= 1e-9:
            return 0.0
        return self._load_ewma / self._baseline_load_ewma

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

    def _apply_calibration(
        self, cfg_t0: Tier0Config, ctx: JunctionContext
    ) -> tuple[Tier0Config, JunctionContext]:
        """Swap in what has been learned about this junction: corrected
        per-movement saturation flow, and `approaching_pcu` discounted by
        the fraction of predicted arrivals that historically materialize.

        Returns *copies*. `Tier0Config` is frozen and only its
        `sat_flow_pcu_s` field is replaced -- a Tier-1 measured quantity,
        explicitly not one of the interlock parameters. Min-green, the
        clearance intervals, the conflict matrix and the max-wait bound
        are carried through untouched, and in any case the arbiter checks
        the returned plan against the *original* config it holds, not this
        copy. So nothing learned here can reach the safety kernel even if
        a learned value were wildly wrong: it would produce a bad plan,
        and `interlocks.check` would reject it exactly as it rejects any
        other bad plan."""
        if self.calibration is None:
            return cfg_t0, ctx
        learned = self.calibration.sat_flow_overrides(
            cfg_t0.intersection_id, cfg_t0.sat_flow_pcu_s
        )
        discounted = {
            m: v * self.calibration.arrival_reliability_for(cfg_t0.intersection_id, m)
            for m, v in ctx.approaching_pcu.items()
        }
        return (
            replace(cfg_t0, sat_flow_pcu_s=learned),
            replace(ctx, approaching_pcu=discounted),
        )

    def __call__(self, cfg_t0: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        self.stats["ticks"] += 1
        cfg = self.cfg
        cfg_t0, ctx = self._apply_calibration(cfg_t0, ctx)
        # Updated on every tick, before any branch can return -- a load
        # average that only accumulated on ticks where a decision happened
        # would be sampled at a rate that itself depends on how often the
        # controller switches, which is the quantity it is meant to
        # influence.
        self._update_load(cfg_t0, ctx)

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
            # Two terms, doing two different jobs -- see each function's
            # docstring. The sublinear one guarantees the controller can
            # never freeze; the derived one decides whether a clearance
            # interval actually pays for itself, and is the term that
            # holds its proportion as demand rises.
            lost_time_s = cfg_t0.yellow_s + cfg_t0.all_red_s + cfg.startup_lost_s
            # `use_relative_congestion_gate` defaults off -- see that
            # field's docstring for the measured reason (a documented
            # negative result, not a placeholder). Default path is exactly
            # v2's validated behaviour, byte-for-byte.
            congestion_scale = self.relative_load if cfg.use_relative_congestion_gate else self._load_ewma
            congestion = memory_mod.congestion_weight(
                congestion_scale, cfg.switch_scale_ref, cfg.switch_scale_exponent
            )
            hold_bias = memory_mod.sublinear_hold_bias(
                scale, cfg.kappa_switch, cfg.alpha_switch
            ) + memory_mod.switch_cost_bias(
                best,
                lost_time_s,
                self._phase_horizon_s(cfg_t0),
                cfg.lost_time_weight * congestion,
            )
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

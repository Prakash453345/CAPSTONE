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

from collections.abc import Mapping
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

    rho_jam: float = 0.85
    """Receiving-link occupancy at which `gate` reaches zero and this
    movement's discharge benefit is fully withdrawn. Not 1.0: a link is
    functionally blocked well before it is bumper-to-bumper, and
    discharging into one at 0.9 occupancy is what creates the spillback
    the gate exists to prevent.

    **Re-tuned 0.75 -> 0.85 on 2026-09-18, together with `beta_gate`, and
    the reason is worth recording: until that date this parameter had
    never done anything at all.** `queue_state.py` divided
    `traci.lane.getLastStepOccupancy` (already a fraction) by 100, so every
    `receiving_occupancy` this corridor ever produced was under 0.0067 and
    `gate` never returned less than 0.99992 -- ablating the gate entirely
    reproduced the shipped results bit-for-bit on all 30 runs. With the
    unit fixed the shipped 0.75/2.0 pair discounts far too much
    (occupancy 0.6 -> gate 0.36) and cost +9% person-delay at heavy demand.
    Searched on `TRAIN_SEEDS[:5]` at medium and heavy
    (`rho_jam` 0.75/0.85/0.90/0.99 x `beta_gate` 2/4): 0.85 with beta 4 is
    -6.2% at heavy (5/5 seeds, CI excludes zero) and flat at medium, which
    is also the setting with the defensible shape -- near-open until the
    receiving link is genuinely close to jam, then a sharp knee."""

    beta_gate: float = 4.0
    """Sharpness of the gate's rolloff. `1.0` is linear in occupancy;
    above 1.0 keeps the gate near-open through light downstream loading
    and closes it sharply near `rho_jam`, which matches how discharge
    capacity actually behaves against a filling link (roughly flat, then
    a knee) better than a linear ramp does. Raised 2.0 -> 4.0 in the same
    2026-09-18 re-tune -- see `rho_jam`. At these values a receiving lane
    at 30% occupancy keeps 98.5% of its discharge benefit and one at 62%
    keeps 72%, against 84% and 36% under the old pair."""

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
    """Off by default -- two documented negative results and one small
    positive one, not a half-built feature. `relative_load` (this
    junction's smoothed load divided by its own slow baseline) genuinely
    fixes a real defect: `scripts/m5_regime_threshold_probe.py` measured
    this corridor's seven junctions' smoothed load at heavy demand
    spanning 0.70 to 33.03 (47x) while their discharge capacity spans only
    2.4-6.8 (2.8x), so a single global *absolute* `switch_scale_ref` gives
    six of the seven junctions almost no congestion pricing at any demand
    level -- proven as a property in
    `test_relative_load_is_scale_invariant_across_junction_size`, which
    the raw absolute signal cannot pass.

    **Attempt 1 (cold baseline) -- negative.**
    `scripts/m5_relative_congestion_sweep.py` searched `switch_scale_ref`
    (now a ratio) on `TRAIN_SEEDS` with each `AdaptiveCamp` instance built
    fresh per run (`_baseline_load_ewma` starting at 0 every time) and
    found every value that helped heavy materially hurt medium (e.g.
    ref=3.0: heavy -9.6% but medium +38% against the ref=7.10 control).
    Diagnosed as structural, not a bad parameter choice: a single
    demand-level run here lasts only ~2,400-3,700 simulated seconds, too
    short for a baseline half-life long enough to deserve the name to
    separate "this run's genuine normal" from "still catching up from a
    cold start".

    **Attempt 2 (cross-run-warmed baseline) -- fixed the diagnosed defect,
    did not close the gap it was diagnosed for.** `memory.LoadBaseline`
    persists `_baseline_load_ewma` across runs exactly the way
    `DemandMemory` persists `q_hist` (`scripts/m5_warm_load_baseline.py`
    chains 30 sequential `TRAIN_SEEDS` runs, interleaving light/medium/
    heavy, into one warmed per-junction baseline;
    `m5_harness.build_acamp`'s `load_baseline` parameter seeds
    `initial_baseline_load` from it). Re-running the same search
    (`scripts/m5_relative_congestion_sweep_warmed.py`) against this warmed
    baseline changed the shape of the result completely: every
    `switch_scale_ref` from 1.3 to 7.10 became statistically
    indistinguishable from every other at heavy demand, and **none**
    regressed medium the way the cold-baseline attempt did -- the
    medium-vs-heavy trade-off that killed Attempt 1 is gone. Held out on
    the full 10-seed `EVAL_SEEDS` gate against the recorded default arm
    (`scripts/results/m5_gate_results_reconciled_tuned.json`,
    `scripts/results/m5_warmed_relative_gate_verify.json`):

        level    default (shipped)          warmed relative gate
        light      66,915 +/-  4,353           67,107 +/-  4,626  (+0.3%, overlap)
        medium    213,622 +/- 29,446          183,719 +/- 12,238  (-14.0%, narrow overlap)
        heavy   1,491,441 +/- 52,477        1,468,934 +/- 54,001  (-1.5%, overlap)

    So: light unaffected, medium directionally better with tighter run-to-
    run variance (promising, but the 95% CIs still overlap at 10 seeds --
    not a proven win), and **heavy -- the demand level this whole
    investigation exists to fix -- is statistically flat**. Fixing the
    cold-start defect a real property test can demonstrate
    (`test_relative_load_is_scale_invariant_across_junction_size`,
    `test_warmed_baseline_avoids_the_cold_start_bias_a_short_run_cannot_correct`)
    did not translate into closing heavy demand's ~7% loss to Webster.
    The honest reading is that this mechanism was never the heavy-demand
    bottleneck: something else dominates there, and this line of
    investigation has now been exhausted rather than abandoned early --
    both the absolute-threshold defect and its cold-start-persistence
    follow-up are fixed and verified, and heavy demand needs a different
    hypothesis next, not a further turn of this same knob.

    Stays off by default because turning it on ships a real infrastructure
    dependency (a warmed `LoadBaseline` file that must be built and kept
    fresh) for a light-touch, not-yet-significant medium-demand gain and
    no heavy-demand gain -- not a trade this corridor should take yet.
    Kept, tested, and fully wired rather than reverted, because the
    infrastructure itself (`LoadBaseline`, the warm-up script, the verify
    script) is correct and now the right foundation for whoever tests the
    next heavy-demand hypothesis, rather than something to rebuild."""

    # -- corridor (M7) --
    lambda_anticipation: float = 1.0
    """Weight on `A(p)`, the corridor-anticipation term -- §3.4's Term 4,
    and half of the project's stated Contribution 1.

    Zero whenever no emergency vehicle is inbound, so the controller is
    bit-for-bit its M5 self on every ordinary tick and the term's effect
    is attributable rather than entangled.

    **Measured as not helping.** The M7 gate found no detectable effect
    from this term or `lambda_debt`, at medium demand (n=10) or heavy
    (n=30), on any of four metrics. Left default-on and documented rather
    than deleted, because neither weight has ever been through
    `tuning.PARAM_SPACE` -- "worthless" and "unoptimised" are still
    distinguishable, and only the tuner can separate them."""

    lambda_debt: float = 0.5
    """Weight on `D(p)`, the debt-recovery term -- §3.4's Term 5.

    Below `lambda_anticipation` on purpose. Anticipation is a claim about
    the next few seconds and debt is a claim about the last few minutes,
    and when they disagree at a junction an emergency vehicle is
    approaching, the vehicle should win. See `debt_recovery` for the
    magnitude failure this term shipped with and the measurement that
    caught it."""

    # -- ring --
    k: int = 2
    """§3.7's limited ring lookahead."""

    # -- allocation --
    protect_allocated_green: bool = True
    """**On by default -- verified on the full 10-seed held-out `EVAL_SEEDS`
    gate, not just a promising probe.** `scripts/m5_heavy_diagnostics.py` measures the gap this
    closes directly: at heavy demand, mean green *served* runs at 23.3s
    against a mean green *allocated* (this controller's own
    `allocate_green` output for the phase it just chose) of 59.4s -- less
    than half. At light demand the same two numbers are 29.4s served
    against 33.8s allocated -- close. The mechanism is the same either
    way: `allocate_green` computes a phase's fair share from *this tick's*
    pressures, but nothing about the switch test that runs on every
    subsequent tick remembers that number -- only the fixed, phase-
    independent `min_green_s` floor and `max_green_s` ceiling are ever
    enforced. Between those two bounds it is a fresh pressure contest
    every second, so a phase that was just granted a large allocation
    because its own queue justified it can be dethroned a few seconds
    later by any other movement whose pressure happens to tick upward --
    and heavy demand, with many movements queued at once and receiving-
    link occupancy fluctuating tick to tick, produces far more such
    reversals than light demand does. Every reversal pays a full clearance
    interval (`yellow_s + all_red_s + startup_lost_s`) for capacity that
    was never actually used, which is precisely backwards at the demand
    level where capacity is scarcest.

    When on, `AdaptiveCamp` remembers the allocation it granted the
    *current* phase when it last switched into it (`_current_phase_
    allocation_s`, updated in `_advance`) and, while `elapsed` is still
    under that number *and the phase still has demand on its own
    movements*, skips the pressure/hold-bias switch test entirely and
    extends -- the controller keeping the promise its own allocation
    function made, the way a fixed-time plan keeps its own schedule,
    instead of re-litigating it every second. This is checked strictly
    *after* the starvation override (`_critical_phases`): a movement stuck
    past its own wait bound still preempts immediately regardless of this
    flag, so the safety property that makes the controller impossible to
    starve is unaffected. It is also naturally bounded by `max_green_s`,
    since the branch this sits inside only runs while `elapsed < max_g`
    -- protection can never exceed the interlock ceiling already in
    force.

    **The demand guard is not optional polish -- the first version shipped
    without it and measured worse everywhere, not just at heavy demand.**
    `scripts/m5_protect_allocated_green_probe.py` on `TRAIN_SEEDS[:3]`: a
    purely time-based version (protect until `elapsed < allocation`,
    full stop) made light demand ~35% worse (63,195 -> ~85,600) and medium
    demand ~56% worse (209,860 -> ~328,000) before heavy was even reached.
    The reason is direct: `allocate_green` sizes an allocation from the
    pressures active *at the moment of the switch*, and a movement can
    clear its own queue well inside that window -- forcing the phase to
    sit out the rest of an allocation it no longer needs is pure wasted
    green, exactly the fixed-time rigidity this whole controller exists to
    avoid. Gating the protection on `current_has_demand` (the same
    `q > 0 or a > 0` test `_skippable` already uses, asked of the
    incumbent instead of a candidate) fixes this: the mechanism only ever
    overrides a *reversal driven by another movement's pressure*, never a
    phase's own legitimate "I'm done, let someone else go" signal.

    **The demand-gated version (iteration 2) fixed the light regression but
    reproduced `use_relative_congestion_gate` Attempt 1's exact trade-off
    shape -- helps heavy, hurts everywhere else.** Same probe, same three
    `TRAIN_SEEDS`: light still ~+24% worse (63,195 -> ~78,254) and medium
    still ~+23% worse (209,860 -> ~257,953), while heavy improved ~19%
    (1,524,423 -> ~1,237,822, on 2 of 3 seeds -- the probe was killed once
    the direction was clear rather than burning the third run on an
    already-decided comparison). The demand guard stops the mechanism from
    holding a phase *after its own queue clears*, but says nothing about
    whether protecting it was ever a good idea at *this* demand level in
    the first place -- at light and medium demand, where reversals are rare
    and cheap, unconditionally trusting every allocation still traded away
    genuine responsiveness to catch a problem that heavy demand alone
    exhibits at scale.

    **Iteration 3 -- gate on the corridor's own congestion signal instead
    of applying protection everywhere.** Adds one more condition,
    `congestion >= 0.5` where `congestion = memory.congestion_weight(
    self._load_ewma, cfg.switch_scale_ref, cfg.switch_scale_exponent)` --
    the same Hill-curve already computed for `switch_cost_bias` and tuned
    against this corridor's own load range, not a new threshold invented
    for this mechanism. The reasoning: light and medium demand rarely push
    a junction's smoothed load past its own switching-cost midpoint, so
    this should let the mechanism stay dormant there while still engaging
    once heavy demand's load genuinely crosses into congested territory --
    the same "is this junction actually busy" question the module already
    knows how to ask, asked once more here rather than left unasked.
    **Verified, and the result is cleaner than the hypothesis predicted.**
    `scripts/m5_protect_allocated_green_probe.py` on `TRAIN_SEEDS[:3]` first
    found light and medium coming back *bit-for-bit identical* to the
    unprotected arm (not just statistically indistinguishable -- the exact
    same `person_delay_s` on every seed) while heavy improved on all three
    seeds individually (6.5%/13.0%/9.1%). `scripts/
    m5_protect_allocated_green_verify.py` then held this out on the full
    10-seed `EVAL_SEEDS` gate these training seeds never touched, and the
    same shape reproduced exactly:

        level    default (unprotected)      protect_allocated_green
        light      57,928 +/-  2,631           57,928 +/-  2,631  (+0.0%, all 10 seeds identical)
        medium    212,741 +/- 35,358          212,741 +/- 35,358  (+0.0%, all 10 seeds identical)
        heavy   1,454,395 +/- 61,600        1,277,791 +/- 53,763
                (-12.1%, NO OVERLAP, 10/10 seeds improved)

    Zero interlock violations in either arm, at every demand level, on
    every seed. The light/medium identity is not a fluke or a rounding
    coincidence -- it means the congestion gate genuinely never lets the
    mechanism intervene below its threshold on this corridor's seeds, so
    turning it on carries no measured downside anywhere, and heavy demand's
    improvement is both large and consistent (every single held-out seed
    improved, not just the average). This is the clean win
    `use_relative_congestion_gate` was hoping to find and didn't: unlike
    that mechanism's "promising but the CIs still overlap" medium result,
    this one ships on by default rather than staying opt-in.

    See `m5_heavy_diagnostics.py`'s docstring for the two hypotheses (H1
    over-switching / H2 allocation collapse) this mechanism was diagnosed
    against, `scripts/results/m5_protect_allocated_green_verify.json` for
    the full per-seed record, and PROGRESS.md for the complete writeup of
    all three iterations (pure time-based -- failed; demand-gated -- traded
    heavy for light/medium; congestion-gated -- this verified result).

    **Known gap, investigated and left unresolved: this mechanism never
    engages at medium demand on this corridor, and lowering the threshold
    to reach it does not help.** `scripts/m5_congestion_profile.py`
    measured the actual `congestion_weight` value `protect_allocated_
    green_congestion_threshold` is checked against, at every tick, all
    three demand levels: light never exceeds 0.001; heavy's busiest
    junction saturates to 1.000 (mean 0.822); medium's same junction peaks
    at only 0.339 -- never close to the 0.5 default. That gave a
    plausible, principled hypothesis (medium independently measures a
    real, if smaller, served-vs-allocated gap -- `m5_heavy_diagnostics.py
    --level medium`: 38% of allocated green unserved, between light's
    ~15% and heavy's ~61% -- so maybe it just needs a lower threshold to
    reach). `scripts/m5_protect_threshold_sweep.py` tested it directly, on
    `TRAIN_SEEDS[:3]`, sweeping 0.5 down to 0.10: light stayed exactly
    unaffected at every value (its congestion never gets close regardless
    of threshold), but medium got monotonically *worse*, not better, as
    the threshold dropped -- 187,244 (0.5) -> 188,311 (0.35/0.30) ->
    188,373 (0.20) -> 194,820 (0.10), with the mechanism firing more often
    each step (223 -> 445 times) while consistently adding delay rather
    than removing it. Heavy stayed roughly flat down to 0.20 and looked
    better at 0.10 (1,334,727 -> 1,250,833), but that move was carried by
    one of the three seeds improving sharply while another got worse --
    not the clean, every-seed-agrees signal the verified 0.5 default
    showed, so it reads as three-seed noise rather than a second genuine
    win, and was not chased further with a full verification.

    **The honest conclusion:** medium demand's allocation-serving gap is
    real but is evidently not caused by the same "switch test overrides a
    still-needed allocation before it's served" mechanism heavy demand
    has -- protecting phases more aggressively at medium demand makes
    outcomes slightly worse, which is more consistent with the opposite
    problem (movements there often finish before their generous
    allocation is used, so *more* protection just holds a phase a little
    past when it was actually needed). Fixing medium demand's version of
    this gap needs a different diagnosis, not a lower copy of this same
    knob -- left as an open item rather than forced into a mechanism that
    measurably does not help it."""

    protect_allocated_green_congestion_threshold: float = 0.5
    """The `congestion_weight` cutoff `protect_allocated_green` requires
    before it will hold a phase past a competing pressure. Pulled out as
    its own field (rather than the `0.5` literal it started as) once
    `scripts/m5_congestion_profile.py` showed medium demand's own
    congestion never reaches the original hard-coded value, raising the
    question of whether a lower value would help it. `scripts/
    m5_protect_threshold_sweep.py` tested that directly and found the
    opposite of the hypothesis: lowering this value made medium
    *monotonically worse*, not better, while light stayed unaffected and
    heavy's apparent gain at the lowest value tested was carried by one
    noisy seed rather than a consistent effect. `0.5` therefore stays the
    default -- it remains the only value verified end-to-end on the full
    held-out gate (`m5_protect_allocated_green_verify.py`), and the
    sweep gave no principled reason to prefer anything lower. See
    `protect_allocated_green`'s own docstring for the full measurement
    and PROGRESS.md for the complete writeup."""

    rest_in_green: bool = False
    """At its green ceiling the running phase stays green while no other
    phase has anything to serve (`_skippable`: no queue, nothing
    approaching, no wait near its bound). Without it the ceiling always ends
    the green, and with nobody waiting the ring moves to an empty phase and
    pays a change interval for nothing. Off by default so recorded runs
    stay reproducible. Pedestrian phases are never skippable, so a junction
    that has one keeps cycling as before.

    Adopted as an **off-peak mode** (light-traffic hours only; the live
    service switches it on with SIGNAL_OFFPEAK_REST=1): on fresh seeds at
    light demand -9.0 % [-12.4, -5.7] over ten networks (lower on all ten),
    -15.3 % on the real Amaravati map (baselines/2026-10-13_rest_offpeak_v2).
    It lost on training seeds at medium and heavy demand (arterial_lh +5 %,
    +3.5 %), so it is not for busy hours."""

    rest_max_s: float | None = None
    """With `rest_in_green`: the longest a green may rest past its ceiling
    (None: no limit). A green that never ends also never leaves a gap, and
    a give-way junction just past the stop line can depend on those gaps:
    on the Vijayawada district a minor road merging 6 m after a signal's exit
    starved while the signal rested (2026-10-10)."""

    rest_max_congestion: float | None = None
    """With `rest_in_green`: rest only while the junction's congestion weight
    (`memory.congestion_weight` of its smoothed load, the signal
    `protect_allocated_green` gates on; about 0.01 at light demand, 0.9 at
    heavy) is below this. Resting is for quiet periods; on the Vijayawada
    district at medium demand it stranded vehicles (2026-10-07). None: no
    limit."""

    rest_needs_flow: bool = False
    """With `rest_in_green`: rest only while nothing stands halted on the
    running phase's own movements. Past the ceiling a halted vehicle on a
    green movement means its way out is blocked (a full junction box, a
    give-way just downstream), and holding the green only holds the jam."""
    rest_needs_own_demand: bool = False
    """With `rest_in_green`: rest only while the running phase itself still has
    demand (a queue or a vehicle arriving). When every phase is empty there is
    no one to rest for, and moving on puts the green where the next platoon
    may arrive instead of holding it where none is coming."""
    rest_needs_no_call: bool = False
    """With `rest_in_green`: rest only while no movement outside the running
    phase has a call (`JunctionContext.has_demand`: a vehicle anywhere on its
    approach, not only within the arrival horizon). A side-road vehicle seen
    as it enters its approach ends the rest early enough to change before it
    reaches the line; seen only 8 s out, it meets the change interval and
    stops (arterial_lh, medium demand, training seeds: rest +5 %)."""

    # -- cycle supervisor (CC-A-CAMP) --
    cycle_supervisor: bool = False
    """Whether the cyclical-structure supervisor is active. **Off by
    default**, so every recorded gate in this project stays reproducible
    byte-for-byte; the arm that turns it on is a gate arm, not a silent
    change of behaviour.

    **What it is for, and what it is not.** M5's losses were traced to an
    emergent cycle nothing bounded: A-CA-MP's effective cycle ran 1.77x
    Webster's delay-minimising optimum at light demand and 1.40x at
    medium, and delay tracked that ratio monotonically across all three
    demand levels. `max_green_s` set per phase from Webster's own greens
    fixes the *length* half of that and is measured doing so -- the
    controller goes from +43.4% worse than Webster at light to -18.8%
    better (`scripts/m5_cycle_ceiling_probe.py`).

    This supervisor is the *other* half, and it exists because a bound on
    cycle length does not imply every phase is served. Heavy demand's
    interlock violations survive every ceiling factor tried, and
    `m5_heavy_violation_diagnostic.py` shows why: at the corridor's only
    four-phase junction a movement reached its 452 s `max_wait_s` bound
    **9.0 s into another phase's 10 s minimum green**. I3 (minimum green)
    is absolute and is checked first -- correctly -- so the controller is
    obliged to return a plan that does not serve the starved movement,
    and I5 is obliged to reject it. Neither rule is wrong; the situation
    is unreachable only if the wait never gets that far.

    The remedy is the phase-order constraint of cyclical max-pressure
    (Levin, Hu & Odell, *Max-pressure signal control with cyclical phase
    structure*, Transportation Research Part C 120:102828, 2020), whose
    requirement is that each phase be actuated at least once per bounded
    cycle. Note their empirical result honestly: the constraint made
    max-pressure *worse* in their setting (~3 min more average travel
    time, a reduced stability region). It is cited for the structure and
    its stability proof, not as evidence that the constraint improves
    delay. The situations differ -- their unconstrained baseline worked,
    and here the absence of the constraint is the defect.

    **One deliberate departure from Levin.** Their rule actuates every
    phase unconditionally. This one exempts phases with no demand, which
    this corridor needs (`_skippable` exists for the same reason) and
    which weakens the guarantee: a movement whose demand is intermittent
    can still be passed over while it reads empty. `max_wait_s` remains
    the backstop for that case, and this supervisor does not replace it."""

    cycle_target_factor: float = 1.0
    """Multiplier on the derived cycle envelope, `sum(max_green_s +
    yellow + all_red)` over the live ring.

    The envelope is *derived rather than configured* on purpose: with
    `max_green_s` set from Webster's greens, that sum already is a
    Webster-referenced cycle, so the supervisor inherits its reference
    from the same place the ceiling gets it and there is no second number
    to keep in sync. The consequence is worth stating plainly -- with the
    shipped flat 90 s ceiling the envelope is enormous and the length
    trigger effectively never fires. **The ceiling and the supervisor are
    one design**; the ceiling supplies the reference the supervisor
    measures against."""

    # -- gap-out --
    gap_out_grace_s: float = 3.0
    """Seconds a phase may sit with no queue and no approaching vehicle before
    it yields to a phase that has one. `0.0` yields the instant it reads empty;
    a negative value disables the rule.

    This is the classic actuated gap-out, and it is here because the corridor's
    clearance interval changed. Measured under the old 7-8 s change interval
    (netconvert's inherited yellow), an instant gap-out was **+3.9% / +15.7%
    SIG / +3.1%** person-delay -- each extra phase change cost more than the
    empty green it saved. Under the corrected 5.5 s interval the trade is no
    longer negative, and the instrumented runs say why it is worth making at
    all: the controller extends a green whose own approaches are empty on
    43-65% of its extend ticks, because the pressure gap it is weighed against
    is 0.000 at the median decision tick.

    Grace searched on `TRAIN_SEEDS[:5]` (0 s / 3 s / 5 s): 0 s is still worse at
    light and heavy, 5 s wins medium (-7.3%) but costs heavy (+9.4%), 3 s is
    within noise everywhere and best on the wait distribution. Held out on the
    full 10-seed `EVAL_SEEDS` at 3 s, then on ten further unused seeds (11-20)
    at medium and heavy to test whether the delay trend was real:

        metric                     light        medium        heavy
        person-delay (10 seeds)    -1.4% n.s.   +0.1% n.s.    -7.6% n.s.
        person-delay (20 seeds)     --          -3.1% n.s.    -4.6% n.s.
        p95 wait                  -10.9% SIG    -3.4% n.s.   -11.9% n.s.
        stops per vehicle          -6.2% SIG    -0.5% n.s.    -2.9% n.s.

    **This is not a delay improvement and must not be reported as one.** The
    medium gain the training seeds showed did not reproduce; at twenty seeds
    medium is -3.1% with 15/20 seeds better and an interval that still touches
    zero. What is established is light demand's wait distribution and stop
    count, with nothing significantly worse at any level and zero interlock
    violations anywhere. It ships on for that reason and no other: the same
    delay for a measurably smoother ride, which is the fairness half of
    §8.2's metric set rather than the mean it warns against reading alone.

    Safety: the rule fires only once `elapsed >= min_green_s` (so I3 is already
    satisfied), is checked after the starvation override and the cycle
    supervisor (both are stronger claims), and builds its plan through
    `_advance`, so `interlocks.check` sees exactly the transition plan every
    other switch produces."""

    # -- degradation ladder --
    use_memory_blend: bool = True
    """Whether the "camp_blended" rung actually blends (against
    `DemandMemory` when one is configured, which with no memory is the live
    reading itself), or falls through to fixed-time the way M4's did.
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


def press_pressure(
    cfg_t0: Tier0Config, ctx: JunctionContext, cfg: AcampConfig, phase_id: str
) -> float:
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


def anticipation(
    cfg_t0: Tier0Config,
    ctx: JunctionContext,
    cfg: AcampConfig,
    phase_id: str,
    urgency: Mapping[str, float],
) -> float:
    """§3.4 Term 4, `A(p) = λ_A · Σ_m s_m · u_m · q̂_m`, where `u_m ∈ [0, 1]`
    is how imminent an emergency vehicle's arrival on movement `m` is
    (`corridor.CorridorEngine.anticipation`).

    The intent is G2's: a preemption granted on arrival gives a green to
    an approach whose queue then has to discharge with the emergency
    vehicle behind it. The remedy is beginning earlier, and beginning
    earlier does not require preempting -- a bias inside ordinary
    max-pressure control clears the same queue at no cost to the
    preemption budget and with no cross street held on red.

    The form is a *multiplier on discharge benefit*, not an additive
    bonus. `s_m · q̂_m` is what `press_pressure` already scores; this
    scales it by up to `λ_A`. So a movement with nothing waiting scores
    zero however imminent the arrival. An additive term would have M4's
    `S(p)` problem in reverse -- a constant that does not scale with
    traffic, dominating a comparison that does.

    Deliberately absent: `gate(ρ)` and the `− r_m` receiving term.
    Anticipation asks "should this movement be served sooner", and a
    jammed receiving link is already answering "no" through
    `press_pressure` at full weight. Applying the discount twice would
    let downstream congestion veto clearing the path ahead of an
    emergency vehicle, which is the situation where clearing it matters
    most."""
    if not urgency:
        return 0.0
    total = 0.0
    for m in cfg_t0.phases[phase_id].green_movements:
        u = urgency.get(m, 0.0)
        if u <= 0.0:
            continue
        total += cfg_t0.sat_flow_pcu_s.get(m, 0.0) * u * q_hat(ctx, cfg, m)
    return cfg.lambda_anticipation * total


def debt_recovery(
    cfg_t0: Tier0Config,
    cfg: AcampConfig,
    phase_id: str,
    owed_s: Mapping[str, float],
    horizon_s: float,
) -> float:
    """§3.4 Term 5, `D(p) = λ_D · Σ_m s_m · min(1, d_m / T)`, with `d_m`
    the decayed seconds movement `m` has been held on red by preemption
    (`corridor.DebtLedger`) and `T` one phase's share of the nominal
    cycle.

    Unlike Term 4 this one has no live-demand multiplier, and the
    asymmetry is intentional. Anticipation without a queue is meaningless;
    debt without a queue is not. A movement can be held on red long enough
    for its own arrivals to divert to parallel streets (G6) and is still
    owed the service, precisely because the demand it lost is invisible to
    any live measurement.

    ---

    **The saturating ratio is not decoration. Without it this term
    reproduced M4's `S(p)` bug, and the M7 gate measured the damage.**

    The first version was `λ_D · Σ_m s_m · d_m` -- raw seconds times
    saturation flow. Dimensionally that is PCU, the same unit as
    `s_m · q_m`, and the docstring argued from exactly that. Dimensional
    agreement is not magnitude agreement, and the magnitudes were not
    close.

    Debt accrues one second per tick for *every* movement a preemption
    holds, so after a 20-second preemption at
    `cluster_11608007559_1880441514` -- 10 movements in P0, `Σ s_m` of
    4.49 -- `D(P0)` is `0.5 × 4.49 × 20 = 44.9`. PROGRESS.md's M5
    diagnostics record `pressure_scale` sampled at the ticks where the
    switch test actually runs: **median 0.21, p90 9.8.** So the term ran
    at three to two-hundred times the entire pressure signal, at every
    junction on an emergency route, for the two minutes its half-life
    takes to decay, four times a run.

    Measured consequence, medium demand, ten paired seeds: the corridor
    arm was worse than plain reactive preemption on *both* axes --
    emergency-vehicle travel 837 s against 711 s, cross-street
    person-delay 314k against 245k.

    The fix follows `fairness`, the one term in `𝒫(p)` with no history of
    this failure: fairness clips `wait / max_wait` to 1 and is therefore
    bounded by `λ_f · Σ_m s_m` regardless of how long anything has waited.
    Debt now clips `d_m / T` the same way, so `D(p) ≤ λ_D · Σ_m s_m`.

    `T` is one phase's share of the nominal cycle, the quantity
    `AdaptiveCamp._phase_horizon_s` already computes for the switching
    test. It carries the right meaning: **debt saturates once a movement
    has lost a full green's worth of service.**"""
    if not owed_s:
        return 0.0
    horizon = max(1e-6, horizon_s)
    total = 0.0
    for m in cfg_t0.phases[phase_id].green_movements:
        d = owed_s.get(m, 0.0)
        if d <= 0.0:
            continue
        total += cfg_t0.sat_flow_pcu_s.get(m, 0.0) * min(1.0, d / horizon)
    return cfg.lambda_debt * total


def pressure(
    cfg_t0: Tier0Config,
    ctx: JunctionContext,
    cfg: AcampConfig,
    phase_id: str,
    urgency: Mapping[str, float] | None = None,
    owed_s: Mapping[str, float] | None = None,
    debt_horizon_s: float = 60.0,
) -> float:
    """`𝒫(p) = P_press(p) + F(p) + A(p) + D(p)`. No switching term --
    Defect 3.

    `urgency` and `owed_s` default to None and both terms are then
    identically zero, so every M5 call site and every M5 property test
    computes exactly the pressure it computed before M7. That is not
    politeness toward old callers: it is what keeps the M5 gate numbers
    meaningful after this change, and what lets the corridor benchmark
    attribute a difference to the corridor rather than to a pressure
    function that quietly moved underneath it."""
    return (
        press_pressure(cfg_t0, ctx, cfg, phase_id)
        + fairness(cfg_t0, ctx, cfg, phase_id)
        + anticipation(cfg_t0, ctx, cfg, phase_id, urgency or {})
        + debt_recovery(cfg_t0, cfg, phase_id, owed_s or {}, debt_horizon_s)
    )


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
    green_s = (
        0.0
        if current in ctx.faulted_phases
        else max(tick_s, min_g - ctx.current_phase_elapsed_s)
    )
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
        initial_baseline_load: float = 0.0,
        corridor=None,
    ) -> None:
        self.cfg = cfg or AcampConfig()
        self.nominal_cycle_s = nominal_cycle_s
        self.tick_s = tick_s
        self.memory = demand_memory
        self.calibration = calibration
        self.corridor = corridor
        """Optional `corridor.CorridorEngine`, read for terms 4 and 5 only.

        Deliberately untyped. Importing the engine would make
        `control/strategies/` depend on `control/corridor/`, and the real
        dependency runs the other way -- the engine reads nothing from
        this module, while the arbiter above composes both. Duck-typed on
        the two read-only members this class touches (`anticipation`,
        `.debt`), the same shape as the `set_sim_time` duck-typing
        `runner.py` already uses to detect a stateful strategy."""
        self._sim_time_s = 0.0
        self._empty_for_s = 0.0
        """How long the current phase has read "no queue, nothing approaching".
        Reset on entry to a phase and on every tick that sees demand -- see
        `AcampConfig.gap_out_grace_s`."""
        self._load_ewma = 0.0
        """Smoothed `pressure_scale` -- see `AcampConfig.load_halflife_s`
        for why the congestion gate reads this rather than the live value.
        Starts at 0, so a freshly-started controller treats itself as
        uncongested and prices no switching cost until it has actually
        observed sustained load, which is the correct cold-start
        behaviour: it degrades toward the light-demand controller, which
        is the arm that is never catastrophically wrong."""
        self._baseline_load_ewma = initial_baseline_load
        """This junction's own slow-moving 'normal' load -- see
        `AcampConfig.switch_scale_ref`'s docstring for why the congestion
        gate compares against this instead of a fixed number.

        Defaults to `0.0`, the same cold-start value it always had; every
        existing call site that does not pass `initial_baseline_load` is
        therefore unaffected byte-for-byte. `m5_harness.build_acamp` passes
        a nonzero value here when handed a `memory_mod.LoadBaseline` --
        see that class's docstring for why a *persisted* starting value
        is what actually fixes the cold-start problem `switch_scale_ref`'s
        docstring diagnoses, rather than only proving the ratio math
        correct in isolation. `relative_load` still guards the division so
        an unwarmed (0.0) baseline reads as 'not congested' rather than
        dividing by zero, regardless of which path set it."""
        self._current_phase_allocation_s = 0.0
        """The green duration `allocate_green` computed for the *current*
        phase when it was last switched into -- see
        `AcampConfig.protect_allocated_green`. Starts at `0.0`: the phase
        a controller is handed at cold start was never chosen by this
        controller's own `allocate_green`, so there is nothing of its own
        to protect until the first real switch happens, and `elapsed <
        0.0` is never true -- cold start correctly falls through to the
        ordinary pressure test rather than inventing a protection period
        for a decision this instance never made."""
        self._cycle_started_s = 0.0
        self._served_this_cycle: set[str] = set()
        """Phases actuated since the current cycle began. A cycle is
        *complete* when every live phase has either been served or has no
        demand to serve -- see `AcampConfig.cycle_supervisor` for why the
        no-demand exemption is a departure from Levin's rule rather than
        an implementation of it.

        Deliberately not seeded with the phase the controller starts in:
        at cold start that phase was handed over rather than chosen here,
        and counting it as served would let the first cycle complete
        without this controller having actuated anything -- the same
        reasoning `_current_phase_allocation_s` starts at 0.0 for."""
        self.stats: dict[str, int] = {
            "ticks": 0,
            "switch_cycle_supervisor": 0,
            "switch_gap_out": 0,
            "cycles_completed": 0,
            "extend": 0,
            "extend_allocation_protected": 0,
            "switch_pressure": 0,
            "switch_max_green": 0,
            "rest_in_green": 0,
            "rest_capped": 0,
            "rest_blocked": 0,
            "rest_congested": 0,
            "rest_called": 0,
            "rest_idle": 0,
            "switch_starvation": 0,
            "blended": 0,
            "blended_no_history": 0,
            "fallback_fixed_time": 0,
            "corridor_anticipating": 0,
            "corridor_repaying": 0,
        }

    def set_sim_time(self, sim_time_s: float) -> None:
        self._sim_time_s = sim_time_s

    def _pressure(
        self,
        cfg_t0: Tier0Config,
        ctx: JunctionContext,
        phase_id: str,
        urgency: Mapping[str, float],
        owed_s: Mapping[str, float],
        horizon_s: float,
    ) -> float:
        """One phase's pressure. A method only so a subclass can price a
        phase differently (`hol_camp.HolAwareCamp`); here it is exactly the
        module-level `pressure`."""
        return pressure(cfg_t0, ctx, self.cfg, phase_id, urgency, owed_s, horizon_s)

    def _may_rest(self, cfg_t0: Tier0Config, ctx: JunctionContext, current: str,
                  elapsed: float, max_g: float) -> bool:
        """`rest_max_s` and `rest_needs_flow` (both off by default)."""
        if self.cfg.rest_max_s is not None and elapsed >= max_g + self.cfg.rest_max_s:
            self.stats["rest_capped"] += 1
            return False
        if self.cfg.rest_max_congestion is not None and memory_mod.congestion_weight(
            self._load_ewma, self.cfg.switch_scale_ref, self.cfg.switch_scale_exponent
        ) >= self.cfg.rest_max_congestion:
            self.stats["rest_congested"] += 1
            return False
        if self.cfg.rest_needs_own_demand and not any(
            ctx.queue_pcu.get(m, 0.0) > 0.0 or ctx.approaching_pcu.get(m, 0.0) > 0.0
            for m in cfg_t0.phases[current].green_movements
        ):
            self.stats["rest_idle"] += 1
            return False
        if self.cfg.rest_needs_no_call and any(
            ctx.has_demand.get(m, False)
            for p, ph in cfg_t0.phases.items() if p != current
            for m in ph.green_movements if m not in cfg_t0.phases[current].shown_movements
        ):
            self.stats["rest_called"] += 1
            return False
        if self.cfg.rest_needs_flow and sum(
            ctx.queue_pcu.get(m, 0.0) for m in cfg_t0.phases[current].green_movements
        ) > 0.0:
            self.stats["rest_blocked"] += 1
            return False
        return True

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
        self._baseline_load_ewma = (
            slow_decay * self._baseline_load_ewma + (1.0 - slow_decay) * scale
        )

    def _track_gap(self, cfg_t0: Tier0Config, ctx: JunctionContext) -> None:
        """Maintain `_empty_for_s`, the gap-out clock -- see
        `AcampConfig.gap_out_grace_s`. Runs before any branch can return, for
        the same reason `_update_load` does: a clock that only advanced on the
        ticks where a decision happened would measure decisions, not seconds."""
        if ctx.current_phase_elapsed_s <= 0.0:
            self._empty_for_s = 0.0
            return
        phase = cfg_t0.phases.get(ctx.current_phase_id)
        if phase is None:
            self._empty_for_s = 0.0
            return
        has_demand = any(
            ctx.queue_pcu.get(m, 0.0) > 0.0 or ctx.approaching_pcu.get(m, 0.0) > 0.0
            for m in phase.green_movements
        )
        self._empty_for_s = 0.0 if has_demand else self._empty_for_s + self.tick_s

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

    def _corridor_state(
        self, cfg_t0: Tier0Config
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Terms 4 and 5's inputs, or two empty mappings.

        Read fresh every tick rather than cached, and read from the engine
        rather than pushed by it, because both quantities move on the
        engine's clock and not on this junction's: a vehicle's arrival
        gets nearer while this junction sits in the middle of a green, and
        debt decays while it sits in a transition this method is not even
        called during.

        Empty mappings when no corridor is wired, when nothing is
        responding, and when the responding vehicle is not routed through
        this junction -- so `A(p)` and `D(p)` are identically zero on the
        overwhelming majority of ticks, and `pressure()` reduces exactly
        to its M5 form."""
        if self.corridor is None:
            return {}, {}
        urgency = dict(self.corridor.anticipation(cfg_t0.intersection_id))
        owed = {
            m: self.corridor.debt.owed(cfg_t0.intersection_id, m)
            for m in _all_movements(cfg_t0)
        }
        owed = {m: d for m, d in owed.items() if d > 0.0}
        if urgency:
            self.stats["corridor_anticipating"] += 1
        if owed:
            self.stats["corridor_repaying"] += 1
        return urgency, owed

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
        self._track_gap(cfg_t0, ctx)

        mode = select_mode(ctx, _all_movements(cfg_t0))
        if mode == "camp_blended" and cfg.use_memory_blend:
            # With no demand memory there is no history to blend toward, and
            # a blend with nothing is the live reading (`memory.blend`'s own
            # rule, which `_blend_context` applies per movement): control on
            # the live estimate. The first version dropped to
            # `fixed_time.propose` here instead -- M2's min-green cycler,
            # which cuts any green older than 7 s -- so a camera estimate at
            # 0.7 confidence, far better than no estimate, truncated greens
            # whenever it appeared. Measured by M8's closed loop (baselines/
            # 2026-09-25_m8_review): +8 % person-delay at medium, +10 % at
            # heavy, +21 % with a stock detector, against ignoring that
            # confidence. M5's sensor-degradation finding points the same
            # way: history helps where live data is absent, not where it is
            # merely noisy. `use_memory_blend=False` keeps the fixed-time
            # fallback for that experiment's ablation arm.
            ctx = self._blend_context(ctx)
            self.stats["blended" if self.memory is not None else "blended_no_history"] += 1
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

        urgency, owed = self._corridor_state(cfg_t0)
        horizon = self._phase_horizon_s(cfg_t0)
        pressures = {
            p: self._pressure(cfg_t0, ctx, p, urgency, owed, horizon) for p in live
        }
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

        # Cycle bookkeeping runs unconditionally (instrumentation in the
        # supervisor-off arm too); only the *action* below is gated.
        cycle_elapsed_s, owed = self._cycle_state(cfg_t0, ctx, live, current)
        if self.cfg.cycle_supervisor and owed and cycle_elapsed_s > self._cycle_envelope_s(
            cfg_t0, live
        ):
            # The phase-order constraint, and the reason it sits exactly
            # here. Placed **after** the minimum-green gate, so it can
            # never cut a green below its I3 floor -- which is also why
            # this needs no interlock pre-check of its own: the only
            # invariant a forced switch could threaten is the one the
            # branch above has already enforced, and `_advance` builds
            # the same yellow/all-red transition every other switch uses.
            # Placed **after** the starvation override, because a
            # movement already at its `max_wait_s` bound is the more
            # urgent claim and this supervisor exists precisely to stop
            # that bound ever being reached.
            self.stats["switch_cycle_supervisor"] += 1
            return self._advance(
                cfg_t0, ctx, current, max(owed, key=lambda p: pressures[p]), pressures, min_g
            )

        # Gap-out. Placed after the starvation override and the supervisor,
        # both of which are stronger claims, and before the allocation
        # protection below, which is about a phase that still *has* demand.
        # `_empty_for_s` is maintained on every tick by `_track_gap`, so the
        # grace period measures wall-clock emptiness rather than the number of
        # ticks that happened to reach this branch.
        if (
            not current_faulted
            and self.cfg.gap_out_grace_s >= 0.0
            and self._empty_for_s > self.cfg.gap_out_grace_s
        ):
            waiting = [
                p
                for p in live
                if p != current and not _skippable(cfg_t0, ctx, p)
            ]
            if waiting:
                self.stats["switch_gap_out"] += 1
                self._empty_for_s = 0.0
                return self._advance(
                    cfg_t0, ctx, current, max(waiting, key=lambda p: pressures[p]),
                    pressures, min_g,
                )

        if not current_faulted and elapsed < max_g:
            # `protect_allocated_green` -- see that field's docstring.
            # Checked after the starvation override above (so a movement
            # past its own wait bound still preempts regardless) and only
            # while `elapsed < max_g` (so this can never outlast the
            # interlock ceiling already in force): while the phase hasn't
            # yet served the allocation this controller itself granted it,
            # skip the pressure contest entirely rather than re-litigate a
            # decision already made this cycle.
            # Guarded on the phase *still having demand* -- see
            # `AcampConfig.protect_allocated_green`'s docstring for why a
            # purely time-based version of this check was tried first and
            # measured to make things worse, not better: forcing an
            # already-cleared phase to sit out its full allocation just
            # wastes the green it no longer needs. Same "q > 0 or a > 0"
            # test `_skippable` uses to decide the opposite question
            # (whether an *empty* candidate phase is worth switching to).
            current_has_demand = any(
                ctx.queue_pcu.get(m, 0.0) > 0.0 or ctx.approaching_pcu.get(m, 0.0) > 0.0
                for m in cfg_t0.phases[current].green_movements
            )
            # Also gated on the junction actually being congested -- the
            # *same* Hill-curve signal `switch_cost_bias`'s weight already
            # uses (`memory.congestion_weight` on the smoothed load,
            # `AcampConfig.switch_scale_ref`/`switch_scale_exponent`),
            # reused rather than a second hand-picked threshold. Demanded
            # by measurement, not caution for its own sake: even with the
            # demand guard above, `m5_protect_allocated_green_probe.py`
            # still found light ~24% worse and medium ~23% worse on
            # `TRAIN_SEEDS[:3]` while heavy improved ~19% -- the same
            # "helps heavy, hurts everywhere else" shape this module's
            # other two congestion-scale attempts already had to solve.
            # A junction with some residual demand but no real contention
            # (the light-demand norm) still has *an* allocation to
            # protect, but nothing about that regime calls for refusing to
            # respond to a legitimately larger competing queue -- ~0.5 is
            # this Hill curve's own midpoint, already measured (this
            # module's other docstrings) to separate light's ~0.01 from
            # heavy's ~0.89 under the tuned reference.
            congestion = memory_mod.congestion_weight(
                self._load_ewma, cfg.switch_scale_ref, cfg.switch_scale_exponent
            )
            if (
                cfg.protect_allocated_green
                and elapsed < self._current_phase_allocation_s
                and current_has_demand
                and congestion >= cfg.protect_allocated_green_congestion_threshold
            ):
                self.stats["extend_allocation_protected"] += 1
                return SignalPlan(
                    intersection_id=cfg_t0.intersection_id,
                    steps=(PlanStep(phase_id=current, green_s=self.tick_s),),
                    source="acamp",
                )
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
            congestion_scale = (
                self.relative_load if cfg.use_relative_congestion_gate else self._load_ewma
            )
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
            # No hold-bias suppression here, and the absence is
            # deliberate. A branch that zeroed `hold_bias` under "cycle
            # over envelope and phases owed" was written first and
            # measured **never to fire**: `hold_bias_suppressed` came
            # back 0 across all 60 gate runs, because the forced switch
            # above tests the identical condition and returns, so this
            # point is unreachable whenever it would have applied. The
            # stronger action subsumes the weaker one; keeping both
            # leaves dead code that reads like a second mechanism.
            #
            # The bias itself stays, and should. Hsieh et al.
            # (*Throughput-Optimal Scheduling for Multi-Hop Networked
            # Transportation Systems With Switch-Over Delay*, 2017)
            # introduce exactly this kind of current-schedule bias as the
            # *remedy* for switch-over loss and prove throughput-
            # optimality with it. What it lacked was a delay-side bound,
            # which the envelope above now supplies.
            #
            # A graduated version -- soften the bias approaching the
            # envelope, force the switch on crossing it -- would make a
            # softer response reachable and is the obvious next
            # refinement. It is not implemented, so it is not claimed.
            if pressures[current] + hold_bias >= best:
                self.stats["extend"] += 1
                return SignalPlan(
                    intersection_id=cfg_t0.intersection_id,
                    steps=(PlanStep(phase_id=current, green_s=self.tick_s),),
                    source="acamp",
                )
            self.stats["switch_pressure"] += 1
        elif not current_faulted:
            if cfg.rest_in_green and all(
                _skippable(cfg_t0, ctx, p) for p in live if p != current
            ) and self._may_rest(cfg_t0, ctx, current, elapsed, max_g):
                self.stats["rest_in_green"] += 1
                return SignalPlan(
                    intersection_id=cfg_t0.intersection_id,
                    steps=(PlanStep(phase_id=current, green_s=self.tick_s),),
                    source="acamp",
                )
            self.stats["switch_max_green"] += 1

        ring = [
            p
            for p in _ring_candidates(cfg_t0.ring_order, current, cfg.k)
            if p not in ctx.faulted_phases
        ]
        candidates = ring or live
        filtered = [p for p in candidates if not _skippable(cfg_t0, ctx, p)]
        if filtered:
            candidates = filtered

        next_phase = max(candidates, key=lambda p: pressures[p])
        return self._advance(cfg_t0, ctx, current, next_phase, pressures, min_g)

    # -- cycle supervisor -------------------------------------------------

    def _cycle_envelope_s(self, cfg_t0: Tier0Config, live: list[str]) -> float:
        """The cycle this junction's own Tier-0 bounds already imply.

        `sum(max_green_s + yellow + all_red)` over the live ring: the
        duration of a cycle in which every phase runs to its ceiling. No
        new parameter and no second source of truth -- when `max_green_s`
        is Webster-derived this *is* a Webster-referenced cycle, and when
        it is the flat 90 s default the envelope is correspondingly
        enormous and the length trigger stays silent, which is the honest
        behaviour rather than a failure."""
        lost = cfg_t0.yellow_s + cfg_t0.all_red_s
        return self.cfg.cycle_target_factor * sum(
            cfg_t0.max_green_s.get(p, 0.0) + lost for p in live
        )

    def _cycle_state(
        self, cfg_t0: Tier0Config, ctx: JunctionContext, live: list[str], current: str
    ) -> tuple[float, list[str]]:
        """Advance the cycle bookkeeping one tick. Returns
        `(seconds elapsed in this cycle, phases still owed a green)`.

        Called on every tick regardless of whether the supervisor is
        enabled, so `cycles_completed` and the measured cycle are
        available as instrumentation in the arm that has the supervisor
        *off* too -- a control arm that cannot report the quantity under
        test is not much of a control."""
        self._served_this_cycle.add(current)
        owed = [
            p
            for p in live
            if p not in self._served_this_cycle
            and any(
                ctx.queue_pcu.get(m, 0.0) > 0.0 or ctx.approaching_pcu.get(m, 0.0) > 0.0
                for m in cfg_t0.phases[p].green_movements
            )
        ]
        if not owed:
            # Every live phase served or genuinely empty: the cycle is
            # complete. Reset from *now* rather than from the last tick a
            # phase was served, so the measured cycle is wall-clock and
            # comparable with Webster's, not a sum of green times.
            self.stats["cycles_completed"] += 1
            self._served_this_cycle = {current}
            self._cycle_started_s = self._sim_time_s
        return max(0.0, self._sim_time_s - self._cycle_started_s), owed

    def _advance(
        self,
        cfg_t0: Tier0Config,
        ctx: JunctionContext,
        current: str,
        next_phase: str,
        pressures: dict[str, float],
        min_g: float,
    ) -> SignalPlan:
        allocated = allocate_green(cfg_t0, next_phase, pressures, self.nominal_cycle_s)
        # Remembered regardless of `protect_allocated_green` -- cheap to
        # keep current always, and it means flipping the flag on mid-run
        # (a future calibration knob, or just a config change between
        # gate arms) never starts from a stale allocation belonging to a
        # different phase.
        self._current_phase_allocation_s = allocated
        return SignalPlan(
            intersection_id=cfg_t0.intersection_id,
            steps=(
                _exit_step(cfg_t0, ctx, current, min_g, self.tick_s),
                PlanStep(phase_id=next_phase, green_s=allocated),
            ),
            source="acamp",
        )

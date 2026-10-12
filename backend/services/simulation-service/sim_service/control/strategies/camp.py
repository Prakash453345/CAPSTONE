"""Corridor-Anticipatory Max-Pressure [build guide §3.4/§3.7/§3.8] -- M4's
job (build guide §7: "Pressure function (§3.4) minus the corridor terms,
cyclic ring selection (§3.7), degradation ladder (§3.8)").

**Scope, precisely.** §3.4 defines six pressure terms:

    𝒫(p) = P_flow(p) − P_block(p) + F(p) + A(p) + D(p) − S(p)

M4 builds Terms 1 (flow), 2 (block/gating), 3 (fairness), and 6
(switching) -- `pressure()` below. Terms 4 (corridor anticipation) and 5
(debt recovery) are explicitly Contribution 1 and scoped to M7, once the
Green Corridor Engine exists to publish real `Reservation`s -- coding
against a reservation source that doesn't exist yet would be guessing at
its shape, not implementing it. `A(p)` and `D(p)` are therefore always 0
in this build; the module docstring in M7's strategy (when it lands) is
where they get added, not a stub here.

**Term 1 simplification.** The guide's own `q̂_l = q_l + ∫ â_l dτ`
arrival-augmentation needs Layer 2's projected-outflow exchange (§3.5),
which is M5's job. `JunctionContext` carries no predicted-arrivals field
yet, so `q̂_l = q_l` throughout this build -- flow pressure sees only the
already-observed queue, not a platoon still inbound. Revisit once M5
publishes real `â_l` data.

**Term 2's `q` -- resolving an ambiguity in the guide's own pseudocode.**
§3.4's prose defines `P_block(p) = Σ s_lm · q_m · θ_m` with `q_m` read as
"queue on the receiving link" -- but §4's own reference implementation
computes it as `m.sat_flow * m.q_pcu * theta`, reusing the *same* q_pcu
field Term 1 uses (`m`'s own upstream queue), not a separate downstream-
link queue value. This build follows the code over the prose: `P_block`
uses `queue_pcu[m]` (movement m's own upstream queue -- the same value
`P_flow` sees) scaled by `θ_m` (built from `receiving_occupancy[m]`, the
*downstream* link's occupancy). Physically this reads as "how much this
phase would want to flow, tempered by how full the link it flows into
is" -- which reproduces the documented behaviour (pressure collapses as
the receiving link fills) without inventing a second per-movement queue
concept `link_lanes.py`/`extract_tier0_config.py` have no source for
today (that would need a lane -> downstream-lane map this build doesn't
have). Flagged here rather than silently picked.

One consequence worth naming explicitly: at zero receiving-link occupancy
(`theta_m == 1`, the baseline case whenever `receiving_occupancy` has no
entry for a movement), `P_flow` and `P_block` cancel *exactly* -- they're
the same `s_lm * queue_pcu[m]` product, scaled by 1. So in free flow (no
congestion anywhere downstream), Terms 1+2 contribute nothing and phase
selection is driven entirely by Term 3 (fairness/wait time) and Term 6
(switching cost) -- raw queue size alone cannot break a tie between two
candidate phases until some receiving link actually starts filling. This
is a direct, faithful consequence of following the reference code's
`q_pcu` reuse rather than an oversight; it matters for M4's gate/ablation
work later (the theta_m ablation needs genuine `receiving_occupancy`
values to show any effect at all -- see the live state-estimation sampler
still pending as of this module's authorship).

**Confidence and the degradation ladder (§3.8).** `select_mode()` below
implements the mode table's thresholds faithfully as a pure function.
Only two branches are behaviourally real in this build, though:
"CAMP_FULL" (this module's own logic) and everything else, which falls
back to `fixed_time.propose` -- the safety net's own property-tested-safe
strategy. "CAMP_BLENDED" needs a historical time-of-day queue profile
(`q_hist`) and "profile-actuated" needs a `signal_plan_library`; neither
data source exists before real state-estimation infrastructure does
(M8's vision pipeline is what would ever produce `confidence < 1.0` for
a real movement -- this build's state always comes straight from SUMO
ground truth, so `ctx.confidence` is always empty and `select_mode`
always returns "camp_full" in practice). Falling back to the proven-safe
strategy rather than half-implementing a blend against data that
doesn't exist is the honest choice; `select_mode` is still built and
tested for real so M8 has a real branch to wire into later, not a stub
to discover was never implemented.

Pure function of `(Tier0Config, JunctionContext)`, like every other
strategy in this package -- no I/O, no clock reads, unit-testable and
property-testable the same way `fixed_time`/`webster`/`semi_actuated`/
`coordinated_actuated` already are.
"""

from __future__ import annotations

from dataclasses import dataclass

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config

from sim_service.control.strategies import fixed_time

# [build guide §3.9] -- Tier-1, tunable, hot-reloadable defaults.
_CONFIDENCE_FULL_THRESHOLD = 0.8
_CONFIDENCE_BLENDED_THRESHOLD = 0.5

# Not given an explicit default in §3.9's table -- how far under the I5
# bound (`max_wait_s`) a phase must stay before §3.7's skip rule is
# allowed to pass over it, so skipping never trades away the safety
# margin the interlock itself depends on.
_SKIP_WAIT_MARGIN_S = 15.0


@dataclass(frozen=True)
class CampConfig:
    """Tier-1 tunables [§3.9], defaults exactly as tabulated there except
    where noted."""

    theta_max: float = 10.0
    eps: float = 0.05
    lambda_f: float = 0.6
    gamma: float = 3.0
    lambda_s: float = 0.143
    """§3.9's own tabulated default is `1.0` -- this is a corridor-
    calibrated override of it, not a silent substitution: derived from
    real measured data, flagged here exactly like `_switch`'s own
    deviation, not slipped in unnoted.

    `m4_camp_pressure_gap_diagnostics.py` measured, per tick at all three
    demand levels (light/medium/heavy, real per-lane sat_flow
    calibration, both starvation-deadlock fixes in place), the actual raw
    pressure gap `S(p)` was overriding: on 56-73% of every extend-eligible
    tick, some other live phase's flow/block/fairness signal already
    exceeded `current`'s -- `S(p)` (mean ≈1.6 corridor-wide, driven almost
    entirely by geometry: yellow/all-red/startup lost time and mean
    sat_flow, not by demand) was what pulled the decision back to
    "stay," even though the genuine raw gaps it was beating were
    overwhelmingly small (pooled across all three demand levels, n=28992:
    p50=0.011, p75=0.033, **p90=0.228**, p95=0.397, max=1.17) -- `S(p)`
    at `λ_s=1.0` was 7-14x larger than even the top-decile genuine
    signal, not just the median noise.

    The calibration: set `S(p)`'s typical corridor-wide magnitude to the
    pooled **90th percentile** of that measured raw-gap distribution
    (`0.228`) -- large enough that only a genuinely substantial pressure
    difference (not top-half noise) can justify paying the real
    clearance-time cost of switching, small enough that CA-MP can
    actually act on that difference instead of always losing to a fixed
    ~1.6 tax regardless of what the traffic is doing. `0.228 / 1.6 ≈
    0.143`. The 90th-percentile threshold is itself a judgment call, not
    a uniquely correct answer -- p75 (0.033, more reactive) and p95
    (0.397, more conservative) were both measured and are both on record
    in PROGRESS.md if this value needs revisiting; p90 was chosen as
    the conventional "meaningfully large, not noise" cutoff rather than
    picked to make any specific benchmark outcome look better -- this
    value was fixed *before* the post-recalibration gate comparison was
    ever re-run. See PROGRESS.md's "Recalibrating λ_s from the corridor's
    own measured pressure-gap distribution" section for the full
    derivation and the re-run results, including if this made things
    worse -- reported either way."""
    startup_lost_s: float = 2.0
    """Not in §3.9's table by name -- `L_i = yellow_s + all_red_s +
    start-up lost time` [§3.1's notation table] needs a start-up-lost
    component `yellow_s`/`all_red_s` (both on `Tier0Config` already)
    don't carry. 2.0s is a conventional value for the "first vehicle
    reaction" portion of lost time this build hasn't measured per
    junction."""
    hysteresis_frac: float = 0.05
    k: int = 2
    t_dec_s: float = 1.0
    enable_blocking: bool = True
    """Not a §3.9 tunable -- an ablation switch for the M4 gate's own
    required experiment (build guide §7: "with and without the theta_m
    blocking term ... under a downstream bottleneck"). `False` zeroes out
    `_block_pressure` entirely, leaving Terms 1/3/6 exactly as if Term 2
    didn't exist, so the same `propose()` codepath serves both arms of
    the ablation rather than a second hand-maintained copy of the
    pressure function that could quietly drift from the real one. Always
    `True` outside that one experiment -- production CA-MP always gates."""


def select_mode(ctx: JunctionContext, movements: frozenset[str]) -> str:
    """§3.8's degradation ladder, the confidence-threshold part of it
    (`c_i = min_l c_l`). A movement absent from `ctx.confidence` is fully
    confident by convention (see `JunctionContext`'s own docstring) --
    correct for this build, where every movement's state is SUMO ground
    truth. Returns one of "camp_full" / "camp_blended" /
    "profile_actuated" -- the ladder's lower rungs (fixed-time, local
    plan, failsafe) are the arbitration ladder's own job [ARCH §2.2
    rungs 1/5], not this function's."""
    if not movements:
        return "camp_full"
    c_i = min(ctx.confidence.get(m, 1.0) for m in movements)
    if c_i >= _CONFIDENCE_FULL_THRESHOLD:
        return "camp_full"
    if c_i >= _CONFIDENCE_BLENDED_THRESHOLD:
        return "camp_blended"
    return "profile_actuated"


def _all_movements(cfg: Tier0Config) -> frozenset[str]:
    if not cfg.phases:
        return frozenset()
    return frozenset().union(*(phase.green_movements for phase in cfg.phases.values()))


def _flow_pressure(cfg: Tier0Config, ctx: JunctionContext, phase_id: str) -> float:
    total = 0.0
    for m in cfg.phases[phase_id].green_movements:
        total += cfg.sat_flow_pcu_s.get(m, 0.0) * ctx.queue_pcu.get(m, 0.0)
    return total


def _block_pressure(
    camp_cfg: CampConfig, cfg: Tier0Config, ctx: JunctionContext, phase_id: str
) -> float:
    total = 0.0
    for m in cfg.phases[phase_id].green_movements:
        occupancy = ctx.receiving_occupancy.get(m, 0.0)
        theta = min(camp_cfg.theta_max, 1.0 / max(camp_cfg.eps, 1.0 - occupancy))
        total += cfg.sat_flow_pcu_s.get(m, 0.0) * ctx.queue_pcu.get(m, 0.0) * theta
    return total


def _fairness(camp_cfg: CampConfig, cfg: Tier0Config, ctx: JunctionContext, phase_id: str) -> float:
    total = 0.0
    for m in cfg.phases[phase_id].green_movements:
        if ctx.queue_pcu.get(m, 0.0) <= 0.0:
            continue
        wait_ratio = (
            min(ctx.wait_times_s.get(m, 0.0) / cfg.max_wait_s, 1.0)
            if cfg.max_wait_s > 0
            else 0.0
        )
        total += cfg.sat_flow_pcu_s.get(m, 0.0) * (wait_ratio**camp_cfg.gamma)
    return camp_cfg.lambda_f * total


def _switch(camp_cfg: CampConfig, cfg: Tier0Config, current: str, phase_id: str) -> float:
    """§3.4 Term 6, `S(p)` -- fixed post-diagnostic (see `m4_camp_diagnostics.py`
    and PROGRESS.md's "Root cause confirmed" section). The original
    implementation returned a bare `lost_time_s / t_dec_s` -- real seconds,
    un-scaled by `sat_flow_pcu_s` -- while every *other* term in `pressure()`
    (`_flow_pressure`, `_block_pressure`, `_fairness`) is a `sat_flow_pcu_s`-
    weighted quantity. That made `S(p)` the only term on a different numeric
    scale from the rest of 𝒫(p), and at this corridor's real (placeholder
    0.5 pcu/s) saturation flow and light/medium-demand queue sizes, the
    unscaled constant (~9.86) came out 22-61x the typical flow pressure it
    was being subtracted from -- confirmed by `m4_camp_diagnostics.py`:
    100% of phase changes at every demand level were `max_green_s` timeouts,
    never a genuine pressure comparison, because the current phase's own
    (switch-cost-free) pressure was the outright max on every single tick.

    The fix: price the lost green time the same way `_flow_pressure` prices
    a real queue. `sat_flow_pcu_s[m] * (lost_time_s / t_dec_s)` is a
    phantom "queue" of the vehicles movement `m` could have discharged
    during the lost time (units: pcu/s * s = pcu, same as `queue_pcu`);
    weighting that phantom queue by `sat_flow_pcu_s[m]` again -- exactly
    the way `_flow_pressure` turns a real `queue_pcu[m]` into a pressure
    term -- brings `S(p)` onto the same `sat_flow^2`-ish scale as Term 1
    instead of a bare seconds count. `t_dec_s` keeps its existing role
    (§3.9's tunable) inside that phantom-queue computation rather than
    being dropped.

    Deliberately the *mean* over `phase_id`'s green movements, not the sum
    `_flow_pressure` itself uses. First cut of this fix summed (matching
    `_flow_pressure` literally), and re-running `m4_camp_diagnostics.py`
    against the real corridor exposed why that was wrong: with a uniform
    corridor-wide `sat_flow_pcu_s`, summing makes `S(p)` scale with how
    many green movements `phase_id` happens to bundle, so multi-movement
    phases got penalized more than single-movement ones purely for their
    ring geometry, with no basis in real switching cost (the yellow/all-red/
    startup clearance interval doesn't get longer because more movements
    share the next phase). That skew biased CA-MP away from switching into
    multi-movement phases specifically, and materialized as new
    `failsafe_interlock_rejected` events (I5, max-wait) on the real
    corridor that the unfixed build never produced -- the safety net caught
    every one (0 unsafe plans ever reached the simulated cabinet), but a
    fix that makes the safety net fire *more* than the pre-fix build is a
    real regression worth fixing at the source, not something to leave for
    the interlock layer to keep absorbing. The mean keeps `S(p)` on the
    correct sat_flow-weighted scale (fixing the diagnosed bug) without
    making it depend on `phase_id`'s own movement count (avoiding the new
    one). Re-run of `m4_camp_diagnostics.py` after this correction: see
    PROGRESS.md's "Root cause confirmed" section for the before/after
    numbers.

    This is a deviation from the guide's literal `λ_s · lost_time_s /
    t_dec_s` shape (which has no `sat_flow_pcu_s` factor) -- flagged here
    exactly as Term 2's ambiguity is flagged in the module docstring,
    rather than silently changed. It was necessary because the guide's
    default `t_dec_s=1.0` implicitly assumes a pressure scale the guide's
    own generic worked example lives at, not this corridor's actual
    measured queue/sat_flow scale -- and no single constant `t_dec_s`
    override could fix that across all three demand levels at once,
    because the mismatch itself grows and shrinks with `sat_flow_pcu_s`,
    the same quantity every other term already scales by. When `sat_flow_
    pcu_s[m] == 1.0` (every existing unit test's default) and `phase_id`
    has a single green movement (also true of every existing unit test),
    this reduces to exactly the old formula, so it changes no previously-
    asserted numeric result written against that default.
    """
    if phase_id == current:
        return 0.0
    lost_time_s = (cfg.yellow_s + cfg.all_red_s + camp_cfg.startup_lost_s) / camp_cfg.t_dec_s
    movements = cfg.phases[phase_id].green_movements
    if not movements:
        return 0.0
    mean_sat_flow = sum(cfg.sat_flow_pcu_s.get(m, 0.0) for m in movements) / len(movements)
    return camp_cfg.lambda_s * mean_sat_flow * (mean_sat_flow * lost_time_s)


def pressure(
    camp_cfg: CampConfig, cfg: Tier0Config, ctx: JunctionContext, phase_id: str
) -> float:
    """𝒫(p), M4's four terms only -- see module docstring for exactly
    which terms and why. `camp_cfg.enable_blocking=False` (the M4 gate's
    own required ablation arm) drops Term 2 entirely, leaving pressure
    driven by flow/fairness/switching alone -- the same codepath as the
    enabled arm otherwise, so the two ablation runs can never drift apart
    from anything but that one term."""
    block = _block_pressure(camp_cfg, cfg, ctx, phase_id) if camp_cfg.enable_blocking else 0.0
    return (
        _flow_pressure(cfg, ctx, phase_id)
        - block
        + _fairness(camp_cfg, cfg, ctx, phase_id)
        - _switch(camp_cfg, cfg, ctx.current_phase_id, phase_id)
    )


def _ring_candidates(ring_order: tuple[str, ...], current: str, k: int) -> list[str]:
    """The next `k` ring positions after `current`, wrapping -- §3.7's
    limited lookahead, not a free choice over every phase. A single-phase
    ring (or `current` not found in it) has nothing to advance to."""
    n = len(ring_order)
    if n < 2:
        return []
    try:
        idx = ring_order.index(current)
    except ValueError:
        idx = -1
    span = min(k, n - 1)
    return [ring_order[(idx + offset) % n] for offset in range(1, span + 1)]


def _skippable(cfg: Tier0Config, ctx: JunctionContext, phase_id: str) -> bool:
    """§3.7: `skip p if q_p == 0 AND no ped call on p AND w_p < W_max -
    margin`. This build has no pedestrian-call model (the real corridor's
    extracted phases carry no pedestrian demand signal -- see
    `extract_tier0_config.py`), so a pedestrian phase is never skipped
    here rather than guessing at a call it has no way to observe."""
    phase = cfg.phases[phase_id]
    if phase.is_pedestrian:
        return False
    q = sum(ctx.queue_pcu.get(m, 0.0) for m in phase.green_movements)
    if q > 0:
        return False
    w = max((ctx.wait_times_s.get(m, 0.0) for m in phase.green_movements), default=0.0)
    return w < cfg.max_wait_s - _SKIP_WAIT_MARGIN_S


def _critical_phases(
    cfg: Tier0Config, ctx: JunctionContext, live_phases: list[str]
) -> list[str]:
    """Phases serving a movement within `_SKIP_WAIT_MARGIN_S` of I5's
    `max_wait_s` bound, with real demand -- most-urgent-first (smallest
    margin to the bound). Exists because `pressure()` alone cannot be
    trusted to reach a starved movement in time: confirmed on the real
    corridor once real per-lane saturation-flow calibration (see
    `measure_saturation_flow.py`, PROGRESS.md's "Real saturation-flow
    calibration" section) let a run last long enough to exercise it for
    the first time. The mechanism, worth restating here since it's the
    reason this function exists at all: at zero receiving-link occupancy
    (this module's own documented zero-occupancy cancellation of
    `P_flow`/`P_block`), a phase's pressure reduces to fairness minus
    switching cost. Fairness's own ceiling for a movement is bounded by
    `camp_cfg.lambda_f * sat_flow_pcu_s[m]` (capped at `wait_ratio == 1.0`
    -- it cannot grow any further once a movement has already waited the
    full `max_wait_s`), but `_switch`'s fix prices switching cost from
    that *same* `sat_flow_pcu_s` scale, and for a multi-movement phase at
    this corridor's real measured saturation flows that switching cost
    routinely comes out several times larger than fairness's ceiling --
    meaning a starved movement's own phase can be *structurally* incapable
    of ever outranking a phase that costs less to switch into, including
    one with no real demand of its own, no matter how long the wait grows.
    That is a gap in `pressure()`'s own design, not a tuning problem this
    function's threshold papers over -- it exists specifically so no
    single tick's ranking decision is trusted past the point where I5
    would otherwise be forced to reject the plan outright."""
    urgency: list[tuple[float, str]] = []
    for p in live_phases:
        margins = [
            cfg.max_wait_s - ctx.wait_times_s.get(m, 0.0)
            for m in cfg.phases[p].green_movements
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
    cfg: Tier0Config, ctx: JunctionContext, current: str, min_g: float, tick_s: float
) -> PlanStep:
    """Identical shape to semi_actuated's/coordinated_actuated's own --
    see semi_actuated.py's docstring for why this is duplicated rather
    than imported."""
    if current in ctx.faulted_phases:
        green_s = 0.0
    else:
        green_s = max(tick_s, min_g - ctx.current_phase_elapsed_s)
    return PlanStep(
        phase_id=current, green_s=green_s, yellow_s=cfg.yellow_s, all_red_s=cfg.all_red_s
    )


def _allocate_green(
    cfg: Tier0Config, phase_id: str, pressures: dict[str, float], nominal_cycle_s: float
) -> float:
    """§3.7: `g = clamp(min_green, T_cycle_nominal * P(next)/ΣP, max_green)`.
    `ΣP` can be zero or negative (pressure terms are signed) -- when it
    is, there's no meaningful proportional signal to allocate from, so
    this falls back to the phase's own `min_green_s` rather than dividing
    by a non-positive number."""
    min_g = cfg.min_green_s.get(phase_id, 0.0)
    max_g = cfg.max_green_s.get(phase_id, min_g)
    total_pressure = sum(pressures.values())
    if total_pressure <= 0:
        return min_g
    proportional = nominal_cycle_s * (pressures[phase_id] / total_pressure)
    return max(min_g, min(max_g, proportional))


def propose(
    cfg: Tier0Config,
    ctx: JunctionContext,
    *,
    camp_cfg: CampConfig | None = None,
    nominal_cycle_s: float = 60.0,
    tick_s: float = 1.0,
) -> SignalPlan:
    """One controller tick's CA-MP proposal [§3.7's `DECIDE`].
    `nominal_cycle_s` is this junction's own nominal cycle length (in
    practice, `webster.compute_timing`'s own tuned cycle for this
    junction -- ties the green-duration heuristic back to the same
    measured-flow-based tuning M3 already computed, rather than a second
    invented constant) -- purely a duration-allocation input, not a hard
    cycle CA-MP is bound to the way `coordinated_actuated` is."""
    camp_cfg = camp_cfg or CampConfig()
    current = ctx.current_phase_id
    elapsed = ctx.current_phase_elapsed_s
    current_is_faulted = current in ctx.faulted_phases

    mode = select_mode(ctx, _all_movements(cfg))
    if mode != "camp_full":
        return fixed_time.propose(cfg, ctx)

    live_phases = [p for p in cfg.ring_order if p not in ctx.faulted_phases]
    if not live_phases:
        return SignalPlan(intersection_id=cfg.intersection_id, steps=(), source="camp")

    pressures = {p: pressure(camp_cfg, cfg, ctx, p) for p in live_phases}
    min_g = cfg.min_green_s.get(current, 0.0)
    max_g = cfg.max_green_s.get(current, min_g)

    # 1. Extend?
    if not current_is_faulted:
        if elapsed < min_g:
            return SignalPlan(
                intersection_id=cfg.intersection_id,
                steps=(PlanStep(phase_id=current, green_s=tick_s),),
                source="camp",
            )

    # Starvation override -- see _critical_phases' own docstring for the
    # full mechanism. Checked here, before the ordinary pressure-based
    # extend decision below, not only inside the advance branch further
    # down: pressure() can otherwise judge `current` (even a completely
    # idle phase) the outright best candidate and "extend" it indefinitely,
    # in which case the advance branch is never reached at all -- this is
    # exactly the failure mode PROGRESS.md's calibration finding traced.
    # Only reachable once current's own min-green floor (I3) is already
    # satisfied (the branch above returns unconditionally before this
    # point), so this can never cut a phase short of its safety floor.
    critical = _critical_phases(cfg, ctx, live_phases)
    if critical and current not in critical:
        next_phase = critical[0]
        green_s = _allocate_green(cfg, next_phase, pressures, nominal_cycle_s)
        return SignalPlan(
            intersection_id=cfg.intersection_id,
            steps=(
                _exit_step(cfg, ctx, current, min_g, tick_s),
                PlanStep(phase_id=next_phase, green_s=green_s),
            ),
            source="camp",
        )

    if not current_is_faulted:
        if elapsed < max_g:
            best_pressure = max(pressures.values())
            # §3.9: "5% of max 𝒫" -- scaled by abs() rather than
            # best_pressure directly, since pressure is signed (the block
            # and switch terms subtract) and a literal `best_pressure -
            # frac*best_pressure` would shrink the tolerance band exactly
            # when best_pressure is negative, the opposite of a sane
            # hysteresis margin. abs() keeps the band's width tied to the
            # magnitude of the pressures in play regardless of sign.
            # `current` is guaranteed to be in `pressures` here: this whole
            # branch is inside `if not current_is_faulted`, and `pressures`
            # is keyed by every non-faulted ring phase.
            if pressures[current] >= best_pressure - camp_cfg.hysteresis_frac * abs(best_pressure):
                return SignalPlan(
                    intersection_id=cfg.intersection_id,
                    steps=(PlanStep(phase_id=current, green_s=tick_s),),
                    source="camp",
                )

    # 2. Advance around the ring, skipping empty non-starved phases.
    ring_candidates = _ring_candidates(cfg.ring_order, current, camp_cfg.k)
    candidates = [p for p in ring_candidates if p not in ctx.faulted_phases]
    if not candidates:
        candidates = live_phases
    filtered = [p for p in candidates if not _skippable(cfg, ctx, p)]
    if filtered:
        candidates = filtered

    next_phase = max(candidates, key=lambda p: pressures[p])
    green_s = _allocate_green(cfg, next_phase, pressures, nominal_cycle_s)

    return SignalPlan(
        intersection_id=cfg.intersection_id,
        steps=(
            _exit_step(cfg, ctx, current, min_g, tick_s),
            PlanStep(phase_id=next_phase, green_s=green_s),
        ),
        source="camp",
    )

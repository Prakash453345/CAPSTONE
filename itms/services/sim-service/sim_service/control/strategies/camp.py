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
    lambda_s: float = 1.0
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
    if phase_id == current:
        return 0.0
    lost_time_s = cfg.yellow_s + cfg.all_red_s + camp_cfg.startup_lost_s
    return camp_cfg.lambda_s * (lost_time_s / camp_cfg.t_dec_s)


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

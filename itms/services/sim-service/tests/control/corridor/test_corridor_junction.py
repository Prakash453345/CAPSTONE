"""Green Corridor Engine -- per-junction state machine and safety.

Organised by what each group of tests is *for*, because most of them
correspond to a specific numbered hazard from the M7 edge-case catalogue
and lose their point if that link is dropped.

1. **The invariant the whole design rests on**: no plan the engine
   proposes is ever rejected by `interlocks.check`. Rejection commands
   all-red, so a rejected preemption strands the emergency vehicle at a
   dark intersection -- the opposite of the request. Property-tested over
   the legal input domain rather than by example, because "never" is the
   claim.
2. **Structural properties** that make whole hazard classes unreachable
   rather than handled: the clean all-red break (A1/A2), clearance
   intervals never shortened (A7), no permissive preempt path (A5/D3).
3. **Bounded behaviour**: every way a dwell can end, each fired
   deliberately (E7/E9/E10/F9/H1).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.corridor import (
    Confirmation,
    DeferReason,
    JunctionPreemption,
    PreemptionClass,
    PreemptState,
    ReleaseReason,
    Reservation,
    protected_phase_for,
    transfer_time,
)
from sim_service.control.corridor.junction import PLAN_SOURCE, max_wait_headroom_s
from sim_service.control.safety import interlocks


def _config(
    n_phases: int = 2,
    *,
    min_green_s: float = 10.0,
    max_wait_s: float = 120.0,
    yellow_s: float = 6.0,
    all_red_s: float = 2.0,
    max_preempt_s_per_hour: float = 300.0,
    permissive: bool = False,
    ped_phase: str | None = None,
) -> Tier0Config:
    phase_ids = [f"P{i}" for i in range(n_phases)]
    movements = [f"m{i}" for i in range(n_phases)]
    phases = {}
    for pid, mv in zip(phase_ids, movements, strict=True):
        protected = frozenset() if (permissive and pid == "P1") else frozenset({mv})
        phases[pid] = Phase(
            pid,
            frozenset({mv}),
            is_pedestrian=(pid == ped_phase),
            protected_movements=protected,
        )
    conflicts = {mv: frozenset(o for o in movements if o != mv) for mv in movements}
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=tuple(phase_ids),
        conflict_matrix=conflicts,
        min_green_s=dict.fromkeys(phase_ids, min_green_s),
        max_green_s=dict.fromkeys(phase_ids, 90.0),
        yellow_s=yellow_s,
        all_red_s=all_red_s,
        max_wait_s=max_wait_s,
        max_preempt_s_per_hour=max_preempt_s_per_hour,
        sat_flow_pcu_s=dict.fromkeys(movements, 0.5),
        ped_walk_s={ped_phase: 7.0} if ped_phase else {},
        ped_clearance_s={ped_phase: 12.0} if ped_phase else {},
    )


def _ctx(cfg: Tier0Config, **kwargs) -> JunctionContext:
    base = dict(
        intersection_id=cfg.intersection_id,
        current_phase_id="P0",
        current_phase_elapsed_s=20.0,
    )
    base.update(kwargs)
    return JunctionContext(**base)


def _armed(cfg: Tier0Config, target: str = "P1", *, now_s: float = 100.0) -> JunctionPreemption:
    jp = JunctionPreemption(cfg.intersection_id)
    jp.grant(
        Reservation(
            vehicle_id="EV1",
            junction_id=cfg.intersection_id,
            priority=PreemptionClass.FIRE,
            movement="m1",
            granted_at_s=now_s,
            expires_at_s=now_s + 40.0,
        ),
        target,
        now_s,
    )
    return jp


_PROPOSE = dict(tick_s=1.0, dwell_commit_s=12.0, headroom_margin_s=20.0)


# ---------------------------------------------------------------------
# 1. The invariant: a proposed preemption plan is never rejected.
# ---------------------------------------------------------------------


@settings(max_examples=2000, deadline=None)
@given(
    n_phases=st.integers(min_value=2, max_value=4),
    elapsed=st.floats(min_value=0.0, max_value=60.0),
    min_green=st.floats(min_value=1.0, max_value=25.0),
    max_wait=st.floats(min_value=30.0, max_value=400.0),
    waits=st.lists(st.floats(min_value=0.0, max_value=400.0), min_size=0, max_size=4),
    used_budget=st.floats(min_value=0.0, max_value=400.0),
    ped_elapsed=st.floats(min_value=0.0, max_value=30.0),
    with_ped=st.booleans(),
)
def test_a_proposed_preemption_is_never_rejected_by_the_interlocks(
    n_phases, elapsed, min_green, max_wait, waits, used_budget, ped_elapsed, with_ped
):
    """The load-bearing property of the whole design.

    `arbiter.tick` answers a failing `interlocks.check` by commanding
    all-red. For a fixed-time plan that is correct -- nothing sits below
    it. For a preemption plan it is the worst available outcome: the
    emergency vehicle arrives at a junction in solid all-red, with the
    cross street stopped too, and the adaptive controller that could have
    run the junction perfectly well never gets asked.

    So `junction.py` computes every rejection reachable from its own
    proposals -- remaining minimum green (I3), a pedestrian phase
    mid-interval (I4), a starved cross movement at its bound (I5), the
    preemption-hour budget -- and holds or releases instead of proposing
    something that would bounce. This property is that claim, over the
    input domain rather than at a chosen point.

    Generated deliberately hostile: budgets already spent, movements
    already past their maximum wait, pedestrian phases part-way through
    their clearance, minimum greens longer than the elapsed time."""
    cfg = _config(
        n_phases,
        min_green_s=min_green,
        max_wait_s=max_wait,
        ped_phase="P0" if with_ped else None,
    )
    movements = [f"m{i}" for i in range(n_phases)]
    ctx = _ctx(
        cfg,
        current_phase_elapsed_s=elapsed,
        wait_times_s=dict(zip(movements, waits, strict=False)),
        has_demand=dict.fromkeys(movements, True),
        preempt_seconds_last_hour=used_budget,
        ped_phase_in_progress="P0" if with_ped else None,
        ped_phase_elapsed_s=ped_elapsed,
    )
    jp = _armed(cfg)
    plan = jp.propose(cfg, ctx, 100.0, **_PROPOSE)
    if plan is None:
        return
    assert plan.source == PLAN_SOURCE
    assert interlocks.check(plan, ctx, cfg) == []


# ---------------------------------------------------------------------
# 2. Structural properties.
# ---------------------------------------------------------------------


def test_entry_plan_carries_full_clearance_intervals():
    """A7: shortening yellow or red clearance to reduce right-of-way
    transfer time is a real and documented temptation -- it is exactly
    what a designer reaches for when transfer time has to fit inside a
    railroad's 20-second minimum warning. MUTCD forbids it without
    qualification, on entry and on exit.

    Here it is not merely forbidden, it is unavailable: the entry plan
    carries `cfg.yellow_s` and `cfg.all_red_s` verbatim, and
    `interlocks.clearance_intervals_present` would reject anything less
    between conflicting phases."""
    cfg = _config(min_green_s=10.0, yellow_s=6.0, all_red_s=2.0)
    ctx = _ctx(cfg, current_phase_elapsed_s=20.0)
    plan = _armed(cfg).propose(cfg, ctx, 100.0, **_PROPOSE)
    assert plan is not None and len(plan.steps) == 2
    assert plan.steps[0].yellow_s == cfg.yellow_s
    assert plan.steps[0].all_red_s == cfg.all_red_s
    assert interlocks.clearance_intervals_present(plan, cfg) == []


def test_no_movement_is_carried_across_any_transition():
    """A1/A2, the yellow trap -- the highest-severity hazard in the
    catalogue -- shown unreachable at every one of this corridor's real
    junctions rather than argued.

    The trap needs one direction's through movement held green while
    another terminates, so a waiting left-turner reads his own yellow as
    everyone's yellow and turns across traffic that still has green.
    WisDOT's fix is a clean all-red break with nothing carried across.
    `TraCICabinet` builds every phase's state from that phase's movements
    alone and shows all other indices red, and sequences a full all-red
    between them, so the break is unconditional.

    Checked against the corridor's own extracted configs, not synthetic
    ones: the claim is about this network's geometry."""
    import sys  # noqa: I001 -- order below is load-bearing, see comment
    from pathlib import Path

    root = Path(__file__).resolve().parents[5]
    net = root / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
    if not net.exists():  # pragma: no cover - network artefact absent
        return
    # `extract_tier0_config` lives in the scenario directory and is only
    # importable after the path insert above, so this import cannot be
    # hoisted or sorted above it -- exactly the trap that stopped
    # `m7_corridor_benchmark.py` from starting when a sort moved
    # `link_lanes` ahead of the module that put its directory on the path.
    sys.path.insert(0, str(net.parent))
    from extract_tier0_config import load_configs  # noqa: E402, I001

    from sim_service.signal_controller.traci_cabinet import TraCICabinet

    configs = load_configs(str(net))
    assert configs, "corridor configs failed to load"
    for cfg in configs.values():
        width = max(
            max((int(m.removeprefix("L")) for m in p.green_movements), default=-1)
            for p in cfg.phases.values()
        ) + 1
        cab = TraCICabinet(cfg.intersection_id, cfg.phases, state_len=width)
        for outgoing in cfg.ring_order:
            yellow = cab.yellow_state_for(outgoing)
            assert "G" not in yellow and "g" not in yellow, (
                f"{cfg.intersection_id}: leaving {outgoing} still shows a green "
                f"somewhere -- that is the yellow trap"
            )
            assert set(cab.all_red_state()) == {"r"}


def test_a_permissive_only_movement_is_never_preempted_for():
    """A5/D3. Four of this corridor's seven junctions serve some movements
    permissively -- SUMO's 'g', where the driver must yield -- and every
    one of those conflicts with a protected movement in its own phase.

    Preempting onto such a path would pair a green the driver must yield
    on with a confirmation indication asserting the junction is theirs.
    That is worse than no preemption at all, so it is refused and
    counted rather than served."""
    cfg = _config(permissive=True)
    assert protected_phase_for(cfg, "m0") == "P0"
    assert protected_phase_for(cfg, "m1") is None


def test_pedestrian_clearance_is_never_truncated_for_a_preemption():
    """B1/B2. MUTCD 11th Ed. §4F.18 *permits* omitting both the walk and
    the pedestrian change interval under preemption, and NCHRP Synthesis
    507 found 75% of agencies routinely truncate. This build declines the
    permission, which costs it nothing because interlock I4 already
    refuses to truncate a pedestrian phase for any requester "including
    preemption" -- the choice was made in M2 and is inherited.

    What is new is that the deferral is deliberate rather than
    incidental: the engine holds the pedestrian phase and counts the
    deferral, instead of proposing a switch and being rejected into
    all-red with pedestrians in the crosswalk."""
    cfg = _config(ped_phase="P0")
    ctx = _ctx(
        cfg,
        current_phase_elapsed_s=30.0,
        ped_phase_in_progress="P0",
        ped_phase_elapsed_s=4.0,
    )
    jp = _armed(cfg)
    plan = jp.propose(cfg, ctx, 100.0, **_PROPOSE)
    assert plan is not None
    assert plan.steps[0].phase_id == "P0", "must hold the pedestrian phase, not leave it"
    assert jp.last_defer is DeferReason.PEDESTRIAN
    assert interlocks.pedestrian_clearance_respected(plan, ctx, cfg) == []


def test_transfer_time_decomposes_and_takes_the_max_not_the_sum():
    """A pedestrian phase's clearance and its vehicular minimum green run
    concurrently. Summing them overstates the transfer time, and an
    overstated transfer time is not the conservative error it sounds
    like: it makes the engine trigger earlier and hold longer, spending
    cross-street service on margin that does not exist."""
    cfg = _config(min_green_s=10.0, ped_phase="P0", yellow_s=6.0, all_red_s=2.0)
    ctx = _ctx(
        cfg,
        current_phase_elapsed_s=4.0,
        ped_phase_in_progress="P0",
        ped_phase_elapsed_s=4.0,
    )
    t = transfer_time(cfg, ctx, "P1")
    assert t.remaining_min_green_s == 6.0
    assert t.remaining_ped_s == 15.0  # 7 walk + 12 clearance - 4 elapsed
    assert t.total_s == 15.0 + 6.0 + 2.0
    assert t.blocked


def test_transfer_time_is_zero_when_already_showing_the_target():
    cfg = _config()
    assert transfer_time(cfg, _ctx(cfg), "P0").total_s == 0.0


# ---------------------------------------------------------------------
# 3. Bounded behaviour: every release path fires.
# ---------------------------------------------------------------------


def test_entry_holds_the_current_phase_until_min_green_is_served():
    """E1, made explicit rather than surprising. Right-of-way transfer
    time is not a constant -- it depends on where in the cycle the call
    landed -- and the part that has not elapsed yet is a legal floor, not
    a delay to engineer away. The engine holds the current phase and the
    confirmation indication flashes."""
    cfg = _config(min_green_s=10.0)
    jp = _armed(cfg)
    ctx = _ctx(cfg, current_phase_elapsed_s=3.0)
    plan = jp.propose(cfg, ctx, 100.0, **_PROPOSE)
    assert plan is not None and len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P0"
    assert jp.state is PreemptState.ENTRY_HOLD
    assert jp.last_defer is DeferReason.MIN_GREEN
    assert jp.confirmation(cfg, ctx) is Confirmation.FLASHING

    ctx = _ctx(cfg, current_phase_elapsed_s=11.0)
    plan = jp.propose(cfg, ctx, 101.0, **_PROPOSE)
    assert plan is not None and len(plan.steps) == 2
    assert jp.state is PreemptState.ENTRY_CLEAR


def test_dwell_holds_and_shows_a_solid_confirmation():
    cfg = _config()
    jp = _armed(cfg)
    ctx = _ctx(cfg, current_phase_id="P1", current_phase_elapsed_s=2.0)
    plan = jp.propose(cfg, ctx, 100.0, **_PROPOSE)
    assert plan is not None and len(plan.steps) == 1
    assert plan.steps[0].phase_id == "P1"
    assert jp.state is PreemptState.DWELL
    assert jp.confirmation(cfg, ctx) is Confirmation.SOLID


def test_max_dwell_bounds_an_indefinite_hold():
    """E7/F9. FHWA on the vehicle side: an emergency vehicle stopped near
    an intersection with a running emitter "will hold the signal in the
    preemption phase indefinitely, causing significant traffic problems".
    Fairfax County and Plano each built custom emitter power-interrupt
    hardware because nothing downstream of the emitter bounded it. Here
    the bound is a required field of the reservation, so it cannot be
    left unconfigured."""
    cfg = _config()
    jp = _armed(cfg, now_s=100.0)  # expires at 140
    ctx = _ctx(cfg, current_phase_id="P1")
    assert jp.propose(cfg, ctx, 139.0, **_PROPOSE) is not None
    assert jp.propose(cfg, ctx, 141.0, **_PROPOSE) is None
    assert jp.releases[ReleaseReason.MAX_DWELL] == 1
    assert jp.reservation is None


def test_the_preemption_hour_budget_releases_rather_than_being_rejected():
    """H1's capacity cap, and the reason it is enforced twice.

    `interlocks.preempt_budget_ok` is the authority and still runs. But a
    rejection at that point commands all-red, so the engine checks the
    same arithmetic first and *releases* -- ending in a normal transition
    instead of a failsafe. The catalogue's requirement is that a denied
    emergency request is never silent; it is counted here, and the
    benchmark reports the count."""
    cfg = _config(max_preempt_s_per_hour=50.0)
    jp = _armed(cfg)
    ctx = _ctx(cfg, current_phase_id="P1", preempt_seconds_last_hour=49.5)
    assert jp.propose(cfg, ctx, 100.0, **_PROPOSE) is None
    assert jp.releases[ReleaseReason.BUDGET] == 1


def test_max_wait_headroom_releases_before_i5_can_reject():
    """The release with no counterpart in the EVP literature, which says
    more about the literature than about the hazard.

    This build has a hard per-movement maximum-wait interlock, so an
    unbounded preemption hold does not degrade the cross street
    gradually -- it hits a wall and the junction fails safe into all-red
    with the emergency vehicle still approaching. Releasing while enough
    headroom remains to complete a transition is what keeps the wall
    unreachable."""
    cfg = _config(max_wait_s=120.0)
    jp = _armed(cfg)
    ctx = _ctx(
        cfg,
        current_phase_id="P1",
        wait_times_s={"m0": 105.0},
        has_demand={"m0": True},
    )
    assert max_wait_headroom_s(cfg, ctx, "P1") == 15.0
    assert jp.propose(cfg, ctx, 100.0, **_PROPOSE) is None
    assert jp.releases[ReleaseReason.MAX_WAIT_HEADROOM] == 1


def test_headroom_ignores_movements_the_preemption_itself_serves():
    """A movement about to be given a green is not being starved by the
    preemption that is giving it."""
    cfg = _config(max_wait_s=120.0)
    ctx = _ctx(cfg, wait_times_s={"m1": 119.0}, has_demand={"m1": True})
    assert max_wait_headroom_s(cfg, ctx, "P1") == float("inf")


def test_a_faulted_target_phase_is_declined_not_proposed():
    """I6: a faulted phase cannot be commanded, and no version of this
    request can be served at this junction. Declining lets the ordinary
    controller keep running the other phases."""
    cfg = _config()
    jp = _armed(cfg)
    ctx = _ctx(cfg, faulted_phases=frozenset({"P1"}))
    assert jp.propose(cfg, ctx, 100.0, **_PROPOSE) is None
    assert jp.last_defer is DeferReason.FAULTED_PHASE


def test_superseding_a_reservation_counts_the_displaced_one():
    """D4. NEMA TS2 supports preemptor linking but, as the catalogue
    records, "does not explicitly detail mid-sequence preemption
    replacement scenarios" -- under-specified in the standard means it
    must be specified here. The displaced reservation ends cleanly and is
    counted, and the replacement re-enters at ENTRY so it passes through
    the same full clearance as any other transition."""
    cfg = _config()
    jp = _armed(cfg)
    jp.grant(
        Reservation(
            vehicle_id="EV2",
            junction_id="J",
            priority=PreemptionClass.RAIL,
            movement="m1",
            granted_at_s=105.0,
            expires_at_s=145.0,
        ),
        "P1",
        105.0,
    )
    assert jp.releases[ReleaseReason.SUPERSEDED] == 1
    assert jp.state is PreemptState.ENTRY_HOLD
    assert jp.reservation is not None and jp.reservation.vehicle_id == "EV2"


def test_no_reservation_means_no_opinion():
    """Most ticks. A corridor engine that always had something to say
    would be a strategy, and would have to be ranked against A-CA-MP
    rather than sitting above it."""
    cfg = _config()
    assert JunctionPreemption("J").propose(cfg, _ctx(cfg), 100.0, **_PROPOSE) is None
    assert JunctionPreemption("J").confirmation(cfg, _ctx(cfg)) is Confirmation.NONE

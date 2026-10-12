"""Head-of-line blocking (`strategies/hol.py`, `hol_camp.py`): a turner
waiting in the junction blocks its lane; the controller prices the lane as
blocked and can stop the stream the turner is waiting for (a *variant* of
the phase).

The junction used here: four single-lane approaches n, s, e, w, three
movements each (left, through, right). P0 serves n and s together, P1 e and
w; the right turns (L2, L5, L8, L11) are permissive and conflict with the
opposite approach's through movement."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from itms_domain import JunctionContext, Phase, PlanStep, SignalPlan, Tier0Config
from itms_domain.paths import DATA_DIR
from itms_domain.signal import BLOCKER_UNKNOWN
from sim_service.control.safety import interlocks
from sim_service.control.strategies import acamp, hol
from sim_service.control.strategies.hol_camp import HolAwareCamp, HolConfig
from sim_service.signal_controller.traci_cabinet import TraCICabinet

_APPROACH = {"n": (0, 1, 2), "s": (3, 4, 5), "e": (6, 7, 8), "w": (9, 10, 11)}
LANE_OF = {f"L{i}": f"{a}_0" for a, idx in _APPROACH.items() for i in idx}
_NS = [f"L{i}" for i in range(6)]
_EW = [f"L{i}" for i in range(6, 12)]


def _config() -> Tier0Config:
    conflicts: dict[str, set[str]] = {m: set() for m in LANE_OF}
    for a in _NS:                       # everything north-south crosses everything east-west
        for b in _EW:
            conflicts[a].add(b)
            conflicts[b].add(a)
    for turn, through in (("L2", "L4"), ("L5", "L1"), ("L8", "L10"), ("L11", "L7")):
        conflicts[turn].add(through)    # a right turn crosses the oncoming through
        conflicts[through].add(turn)
    phases = {
        "P0": Phase("P0", frozenset(_NS), protected_movements=frozenset(_NS) - {"L2", "L5"}),
        "P1": Phase("P1", frozenset(_EW), protected_movements=frozenset(_EW) - {"L8", "L11"}),
    }
    return Tier0Config(
        intersection_id="J", phases=phases, ring_order=("P0", "P1"),
        conflict_matrix={m: frozenset(c) for m, c in conflicts.items()},
        min_green_s={"P0": 5.0, "P1": 5.0}, max_green_s={"P0": 40.0, "P1": 40.0},
        yellow_s=3.0, all_red_s=2.0, max_wait_s=300.0,
        sat_flow_pcu_s=dict.fromkeys(LANE_OF, 0.5),
    )


def _with_variants() -> Tier0Config:
    cfg, base_of = hol.with_split_variants(_config(), LANE_OF)
    assert base_of == {"P0@0": "P0", "P0@1": "P0", "P1@0": "P1", "P1@1": "P1"}
    return cfg


def _controller(cfg: Tier0Config, **kw) -> HolAwareCamp:
    """Variants are candidates on the first blocked tick unless a test asks
    for the blockage to last (the deployed default does)."""
    kw.setdefault("hol", HolConfig(min_blocked_changes=0.0))
    return HolAwareCamp(acamp.AcampConfig(), lane_of=LANE_OF, base_of=cfg.alternates, **kw)


def _queues(n=0.0, s=0.0, e=0.0, w=0.0) -> dict[str, float]:
    per = {"n": n, "s": s, "e": e, "w": w}
    return {f"L{i}": per[a] for a, idx in _APPROACH.items() for i in idx}


# ---- the static parts ----------------------------------------------------------------


def test_a_variant_is_its_phase_without_the_stream_the_turn_yields_to() -> None:
    cfg = _with_variants()
    base, north = cfg.phases["P0"], cfg.phases["P0@0"]
    # north's across turn L2 yields to south's through L4: that is what is stopped
    assert base.green_movements - north.green_movements == frozenset({"L4"})
    # everything else is shown exactly as the base phase shows it: north's turn
    # still permissive, south's kerb turn still protected, south's across turn
    # still permissive
    assert north.protected_movements == base.protected_movements - {"L4"}
    assert cfg.ring_order == ("P0", "P1")                         # variants are not in the ring
    assert cfg.min_green_s["P0@0"] == cfg.min_green_s["P0"]
    assert cfg.validate() == []
    assert hol.own_movements(cfg, LANE_OF, "P0@0", "P0") == frozenset({"L0", "L1", "L2"})
    assert hol.own_movements(cfg, LANE_OF, "P0@1", "P0") == frozenset({"L3", "L4", "L5"})


def test_no_variant_where_nothing_yields_or_someone_walks() -> None:
    cfg = _config()
    alone = replace(cfg, phases={"P0": Phase("P0", frozenset({"L0", "L1", "L2"})),
                                 "P1": cfg.phases["P1"]})
    variants, _ = hol.split_variants(alone, LANE_OF)
    assert not any(v.startswith("P0@") for v in variants)        # one approach: nothing to stop
    unopposed = replace(cfg, conflict_matrix={
        m: frozenset(c for c in foes if not ({m, c} <= set(_NS)))
        for m, foes in cfg.conflict_matrix.items()})
    variants, _ = hol.split_variants(unopposed, LANE_OF)
    assert not any(v.startswith("P0@") for v in variants)        # n and s never conflict
    all_protected = replace(cfg, phases={**cfg.phases, "P0": Phase("P0", frozenset(_NS))})
    variants, _ = hol.split_variants(all_protected, LANE_OF)
    assert not any(v.startswith("P0@") for v in variants)        # no movement of P0 yields
    # a phase that also shows a crossing (a movement with no approach lane): its
    # clearance is not a vehicle's, so the phase is left alone
    walk = replace(cfg, phases={**cfg.phases, "P0": Phase(
        "P0", frozenset(_NS) | {"L12"}, protected_movements=cfg.phases["P0"].protected_movements)})
    variants, _ = hol.split_variants(walk, LANE_OF)
    assert not any(v.startswith("P0@") for v in variants)


def test_an_alternate_that_adds_a_green_or_stops_a_yielding_turn_is_rejected() -> None:
    """What makes a variant as safe as its base phase is checked where the
    configuration is loaded, not left to whoever builds variants."""
    cfg = _with_variants()
    north = cfg.phases["P0@0"]
    # the first design: this approach alone, its turn promoted to protected
    promoted = Phase("P0@0", frozenset({"L0", "L1", "L2"}))
    bad = replace(cfg, phases={**cfg.phases, "P0@0": promoted})
    assert any("differently" in p for p in bad.validate())
    assert any("stops a permissive" in p for p in bad.validate())   # south's turn L5: the trap
    # the second: south's turn kept permissive, north's turn protected against it
    half = Phase("P0@0", north.green_movements - {"L3"},
                 protected_movements=frozenset({"L0", "L1", "L2"}))
    assert any("differently" in p
               for p in replace(cfg, phases={**cfg.phases, "P0@0": half}).validate())


def test_the_safety_kernel_accepts_an_alternate_and_nothing_else_outside_the_ring() -> None:
    cfg = _with_variants()
    ctx = JunctionContext("J", "P0@0", 6.0)
    assert interlocks.check(SignalPlan("J", (PlanStep("P0@0", 1.0),)), ctx, cfg) == []
    ghost = replace(cfg, phases={**cfg.phases, "X": Phase("X", frozenset({"L0"}))},
                    min_green_s={**cfg.min_green_s, "X": 5.0})
    rules = [v.rule for v in interlocks.check(
        SignalPlan("J", (PlanStep("X", 1.0),)), JunctionContext("J", "X", 6.0), ghost)]
    assert "RING_INTEGRITY" in rules
    wider = replace(cfg, alternates={**cfg.alternates, "P1": "P0"})
    assert any("serves movements" in p for p in wider.validate())


def test_internal_lanes_are_attributed_to_their_signal_link() -> None:
    root = ET.fromstring("""<net>
        <connection from="n" to="x" fromLane="0" toLane="0" via=":J_2_0" tl="J" linkIndex="2"/>
        <connection from=":J_2" to="x" fromLane="0" toLane="0" via=":J_9_0"/>
        <connection from=":J_9" to="x" fromLane="0" toLane="0"/>
        <connection from="n" to="y" fromLane="0" toLane="0" via=":J_1_0" tl="J" linkIndex="1"/>
    </net>""")
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".net.xml", delete=False) as f:
        f.write(ET.tostring(root, encoding="unicode"))
    # the turn's waiting position (:J_9_0, past its internal junction) is still link 2
    assert hol.internal_links(f.name) == {"J": {":J_2_0": "L2", ":J_9_0": "L2", ":J_1_0": "L1"}}


def test_only_the_change_into_a_variant_keeps_its_greens() -> None:
    cfg = _with_variants()
    cab = TraCICabinet("J", cfg.phases, 12)
    # P0 -> its north variant: south's through gets its yellow and red, and
    # nothing else changes -- not north's greens, not south's yielding turn
    assert cab.can_carry("P0", "P0@0")
    assert cab.carried_clearance_states("P0", "P0@0") == ("GGgGygrrrrrr", "GGgGrgrrrrrr")
    # back, or across to the other variant, something starts: south's through
    # against north's turners in mid-flow. That takes an all-red.
    assert not cab.can_carry("P0@0", "P0") and not cab.can_carry("P0@0", "P0@1")
    # a phase that stopped a yielding turn while other greens ran on would be
    # the yellow trap (the first design's north-alone phase), and one that
    # turned a yielding green into a protected one adds a green of its own
    old = {**cfg.phases, "X": Phase("X", frozenset({"L0", "L1", "L2"})),
           "Y": Phase("Y", cfg.phases["P0@0"].green_movements,
                      protected_movements=frozenset({"L0", "L1", "L2", "L3"}))}
    cab = TraCICabinet("J", old, 12)
    assert not cab.can_carry("P0", "X") and not cab.can_carry("P0", "Y")
    # and between two unrelated phases nothing is carried
    assert not cab.can_carry("P0", "P1")


# ---- the controller ------------------------------------------------------------------


_q = st.floats(min_value=0.0, max_value=30.0, allow_nan=False)


@settings(max_examples=150, deadline=None)
@given(n=_q, s=_q, e=_q, w=_q, elapsed=st.floats(min_value=0.0, max_value=60.0),
       current=st.sampled_from(["P0", "P1"]))
def test_with_nothing_blocked_every_decision_is_the_parent_controllers(
        n, s, e, w, elapsed, current) -> None:
    cfg = _with_variants()
    ctx = JunctionContext("J", current, elapsed, queue_pcu=_queues(n, s, e, w))
    mine = _controller(cfg, nominal_cycle_s=60.0)(cfg, ctx)
    parent = acamp.AdaptiveCamp(acamp.AcampConfig(), nominal_cycle_s=60.0)(cfg, ctx)
    assert mine == parent


def test_a_blocked_lane_is_not_priced_as_draining() -> None:
    cfg = _with_variants()
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}       # north's turner waits in the box
    ctx = JunctionContext("J", "P0", 2.0, queue_pcu=_queues(n=20.0, s=2.0),
                          blocked_by=blocked)
    c = _controller(cfg, nominal_cycle_s=60.0)
    c(cfg, ctx)
    free = acamp.pressure(cfg, replace(ctx, blocked_by={}), acamp.AcampConfig(), "P0")
    assert c._raw["P0"] < free                             # noqa: SLF001
    # only south's 3 x 0.5 x 2 PCU is left; with south's through stopped, north's
    # 30 drains (south's kerb turn keeps its green but shares its lane with the
    # stopped through, so nothing is counted for it)
    assert c._raw["P0"] == 3.0 and c._raw["P0@0"] == 30.0  # noqa: SLF001
    # with no oncoming traffic the turner is not opposed, and the lane drains
    c(cfg, replace(ctx, queue_pcu=_queues(n=20.0)))
    assert c._raw["P0"] == 30.0                            # noqa: SLF001


def test_a_blocked_approach_is_served_alone_once_minimum_green_has_run() -> None:
    cfg = _with_variants()
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}
    ctx = JunctionContext("J", "P0", 2.0, queue_pcu=_queues(n=20.0, s=2.0), blocked_by=blocked)
    c = _controller(cfg, nominal_cycle_s=60.0)
    early = c(cfg, ctx)
    assert [s.phase_id for s in early.steps] == ["P0"]                 # inside min green: hold
    plan = c(cfg, replace(ctx, current_phase_elapsed_s=8.0))
    assert [s.phase_id for s in plan.steps] == ["P0", "P0@0"]
    assert plan.steps[0].yellow_s == cfg.yellow_s and plan.steps[0].all_red_s == cfg.all_red_s
    assert interlocks.check(plan, replace(ctx, current_phase_elapsed_s=8.0), cfg) == []
    # the pricing-only arm never leaves the base phase for a variant
    price = HolAwareCamp(acamp.AcampConfig(), lane_of=LANE_OF, base_of=cfg.alternates,
                         hol=HolConfig(use_variants=False), nominal_cycle_s=60.0)
    assert all("@" not in s.phase_id
               for s in price(cfg, replace(ctx, current_phase_elapsed_s=8.0)).steps)


def test_a_variant_is_left_when_the_other_approach_needs_the_green() -> None:
    cfg = _with_variants()
    ctx = JunctionContext("J", "P0@0", 8.0, queue_pcu=_queues(n=0.0, s=15.0))
    plan = _controller(cfg, nominal_cycle_s=60.0)(cfg, ctx)
    assert [s.phase_id for s in plan.steps] == ["P0@0", "P0"]         # back to both approaches
    assert interlocks.check(plan, ctx, cfg) == []


@settings(max_examples=200, deadline=None)
@given(n=_q, s=_q, e=_q, w=_q, elapsed=st.floats(min_value=0.0, max_value=60.0),
       current=st.sampled_from(["P0", "P1", "P0@0", "P0@1", "P1@0", "P1@1"]),
       blocked=st.lists(st.sampled_from(["n", "s", "e", "w"]), unique=True, max_size=4))
def test_every_plan_passes_the_interlocks(n, s, e, w, elapsed, current, blocked) -> None:
    cfg = _with_variants()
    turn = {"n": "L2", "s": "L5", "e": "L8", "w": "L11"}
    blocked_by = {f"L{i}": turn[a] for a in blocked for i in _APPROACH[a]}
    ctx = JunctionContext("J", current, elapsed, queue_pcu=_queues(n, s, e, w),
                          blocked_by=blocked_by)
    plan = _controller(cfg, nominal_cycle_s=60.0)(cfg, ctx)
    assert plan.steps and plan.steps[0].phase_id == current
    assert interlocks.check(plan, ctx, cfg) == []


# ---- what the base phase's other approach is owed while a variant runs -----------------


def test_a_variant_gives_way_before_the_other_approach_reaches_its_maximum_wait() -> None:
    cfg = _with_variants()
    south = dict.fromkeys(("L3", "L4", "L5"), True)
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}
    # north alone is still the better realisation by pressure (north 20, south 1) ...
    ctx = JunctionContext("J", "P0@0", 8.0, queue_pcu=_queues(n=20.0, s=1.0),
                          has_demand=south, blocked_by=blocked,
                          wait_times_s=dict.fromkeys(south, 200.0))
    c = _controller(cfg, nominal_cycle_s=60.0)
    assert [s.phase_id for s in c(cfg, ctx).steps] == ["P0@0"]
    # ... until south is within the parent's starvation margin of its maximum wait
    late = replace(ctx, wait_times_s=dict.fromkeys(south, cfg.max_wait_s - 10.0))
    plan = c(cfg, late)
    assert [s.phase_id for s in plan.steps] == ["P0@0", "P0"]
    assert c.stats["hol_family_starving"] == 1
    # inside the variant's minimum green it holds; the interlocks agree with both
    early = replace(late, current_phase_elapsed_s=2.0)
    assert [s.phase_id for s in c(cfg, early).steps] == ["P0@0"]
    assert interlocks.check(plan, late, cfg) == []


def test_the_ring_does_not_leave_a_family_whose_other_approach_had_no_green() -> None:
    cfg = _with_variants()
    # the ring arrived at P0 as "north alone"; east-west now outweighs it
    ctx = JunctionContext("J", "P0@0", 30.0, queue_pcu=_queues(s=1.0, e=30.0, w=30.0))
    c = _controller(cfg, nominal_cycle_s=60.0)
    parent = acamp.AdaptiveCamp(acamp.AcampConfig(), nominal_cycle_s=60.0)
    leaving = parent(cfg, replace(ctx, current_phase_id="P0"))
    assert [s.phase_id for s in leaving.steps][:2] == ["P0", "P1"]    # the parent would go
    plan = c(cfg, ctx)
    assert [s.phase_id for s in plan.steps] == ["P0@0", "P0"]         # south first
    assert c.stats["hol_family_owed"] == 1
    assert interlocks.check(plan, ctx, cfg) == []
    # had P0 itself run on this visit, south was served and the ring is free to go
    c2 = _controller(cfg, nominal_cycle_s=60.0)
    c2(cfg, JunctionContext("J", "P0", 6.0, queue_pcu=_queues(n=5.0, s=5.0)))
    assert [s.phase_id for s in c2(cfg, ctx).steps][:2] == ["P0@0", "P1"]
    assert c2.stats["hol_family_owed"] == 0


def test_a_variant_does_not_start_when_the_other_approach_could_not_wait_through_it() -> None:
    cfg = _with_variants()
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}
    south = dict.fromkeys(("L3", "L4", "L5"), True)
    ctx = JunctionContext("J", "P0", 8.0, queue_pcu=_queues(n=20.0, s=2.0), blocked_by=blocked,
                          has_demand=south)
    c = _controller(cfg, nominal_cycle_s=60.0)
    assert [s.phase_id for s in c(cfg, ctx).steps] == ["P0", "P0@0"]
    # margin 15 s + minimum green 5 s + change interval 5 s before the maximum wait
    tight = replace(ctx, wait_times_s=dict.fromkeys(south, cfg.max_wait_s - 24.0))
    assert [s.phase_id for s in c(cfg, tight).steps] == ["P0"]


def test_a_blockage_must_outlast_a_change_interval_when_asked_to() -> None:
    cfg = _with_variants()
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}
    ctx = JunctionContext("J", "P0", 8.0, queue_pcu=_queues(n=20.0, s=2.0), blocked_by=blocked)
    assert HolConfig().min_blocked_changes == 1.0                      # the default
    c = _controller(cfg, hol=HolConfig(), nominal_cycle_s=60.0)
    need = int(cfg.yellow_s + cfg.all_red_s)                           # 5 ticks of 1 s
    for _ in range(need - 1):
        assert [s.phase_id for s in c(cfg, ctx).steps] == ["P0"]
    assert [s.phase_id for s in c(cfg, ctx).steps] == ["P0", "P0@0"]
    clear = replace(ctx, blocked_by={})
    # a camera losing the vehicle for a second or two does not start the count again ...
    for _ in range(2):
        c(cfg, clear)
    assert [s.phase_id for s in c(cfg, ctx).steps] == ["P0", "P0@0"]
    # ... a blockage that has cleared does
    for _ in range(3):
        c(cfg, clear)
    assert [s.phase_id for s in c(cfg, ctx).steps] == ["P0"]


def test_a_blocker_whose_movement_the_camera_cannot_tell_is_taken_to_be_yielding() -> None:
    cfg = _with_variants()
    known = {m: "L2" for m in ("L0", "L1", "L2")}
    unknown = dict.fromkeys(("L0", "L1", "L2"), BLOCKER_UNKNOWN)
    ctx = JunctionContext("J", "P0", 8.0, queue_pcu=_queues(n=20.0, s=2.0))
    a, b = (_controller(cfg, nominal_cycle_s=60.0) for _ in range(2))
    assert a(cfg, replace(ctx, blocked_by=known)) == b(cfg, replace(ctx, blocked_by=unknown))
    assert a._raw == b._raw == {"P0": 3.0, "P0@0": 30.0, "P1": 0.0}    # noqa: SLF001
    # with nobody oncoming, nothing on the lane has anything to yield to
    b(cfg, replace(ctx, queue_pcu=_queues(n=20.0), blocked_by=unknown))
    assert b._raw["P0"] == 30.0                                        # noqa: SLF001


def test_an_approach_is_served_alone_only_when_none_of_its_lanes_is_discharging() -> None:
    """Two lanes on the north approach: the left turn has its own (L0 on
    n_1), through and right turn share n_0, which a turner blocks."""
    cfg = _with_variants()
    two_lanes = {**LANE_OF, "L0": "n_1"}
    blocked = {"L1": "L2", "L2": "L2"}
    ctx = JunctionContext("J", "P0", 8.0, queue_pcu=_queues(n=20.0, s=2.0), blocked_by=blocked)

    def plan(hol_cfg: HolConfig, c: JunctionContext) -> list[str]:
        ctl = HolAwareCamp(acamp.AcampConfig(), lane_of=two_lanes, base_of=cfg.alternates,
                           hol=hol_cfg, nominal_cycle_s=60.0)
        return [s.phase_id for s in ctl(cfg, c).steps]

    whole = HolConfig(min_blocked_changes=0.0)
    assert whole.whole_approach
    # the left-turn lane has a queue and is not blocked: the approach is still moving
    assert plan(whole, ctx) == ["P0"]
    # the first version went by the blocked lane alone
    assert plan(HolConfig(min_blocked_changes=0.0, whole_approach=False), ctx) == ["P0", "P0@0"]
    # with nothing waiting in the open lane, the whole approach is stalled
    empty_left = replace(ctx, queue_pcu={**ctx.queue_pcu, "L0": 0.0})
    assert plan(whole, empty_left) == ["P0", "P0@0"]


def test_variants_are_made_only_for_single_lane_approaches_unless_asked() -> None:
    cfg = _config()
    two_lanes = {**LANE_OF, "L0": "n_1"}                      # north has a second lane
    variants, base_of = hol.split_variants(cfg, two_lanes)
    assert base_of == {"P0@1": "P0", "P1@0": "P1", "P1@1": "P1"}     # south, east, west
    assert "P0@0" in hol.split_variants(cfg, two_lanes, single_lane_only=False)[0]


@settings(max_examples=100, deadline=None)
@given(n=_q, s=_q, e=_q, w=_q, elapsed=st.floats(min_value=0.0, max_value=60.0),
       current=st.sampled_from(["P0", "P1"]),
       blocked=st.lists(st.sampled_from(["n", "s", "e", "w"]), unique=True, max_size=4))
def test_where_no_approach_has_a_variant_a_blockage_changes_nothing(
        n, s, e, w, elapsed, current, blocked) -> None:
    """A junction of multi-lane approaches: there is nothing the controller
    could do about a blocked lane, so it is the parent, whatever is blocked."""
    lanes = {m: f"{lane}{'' if int(m[1:]) % 3 else 'x'}" for m, lane in LANE_OF.items()}
    cfg, base_of = hol.with_split_variants(_config(), lanes)
    assert base_of == {} and cfg == _config()
    turn = {"n": "L2", "s": "L5", "e": "L8", "w": "L11"}
    blocked_by = {f"L{i}": turn[a] for a in blocked for i in _APPROACH[a]}
    ctx = JunctionContext("J", current, elapsed, queue_pcu=_queues(n, s, e, w),
                          blocked_by=blocked_by)
    mine = HolAwareCamp(acamp.AcampConfig(), lane_of=lanes, base_of=base_of,
                        nominal_cycle_s=60.0)(cfg, ctx)
    assert mine == acamp.AdaptiveCamp(acamp.AcampConfig(), nominal_cycle_s=60.0)(cfg, ctx)


# ---- revision 2 (after the code review of 2026-10-04) ----------------------------------


def test_a_visit_that_used_a_variant_is_held_to_twice_the_base_phases_maximum_green() -> None:
    cfg = _with_variants()
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}
    ctx = JunctionContext("J", "P0@0", 8.0, queue_pcu=_queues(n=20.0, e=4.0, w=4.0),
                          blocked_by=blocked)

    def at(sim_time: float, visit_started: float) -> tuple[list[str], HolAwareCamp]:
        c = _controller(cfg, nominal_cycle_s=60.0)
        c.set_sim_time(visit_started)
        c(cfg, JunctionContext("J", "P0", 0.0, queue_pcu=ctx.queue_pcu))   # the ring arrives
        c.set_sim_time(sim_time)
        return [s.phase_id for s in c(cfg, ctx).steps], c

    # 8 s into the variant, 60 s into the visit: under 2 x 40 s, the queue keeps the green
    steps, _ = at(60.0, 0.0)
    assert steps == ["P0@0"]
    # 85 s into the visit: the parent is told the ceiling has passed and moves on
    steps, c = at(85.0, 0.0)
    assert steps[:2] == ["P0@0", "P1"] and c.stats["hol_family_budget_ticks"] == 1
    # the same moment in a visit that began 8 s ago: nothing to enforce yet
    steps, c = at(85.0, 77.0)
    assert steps == ["P0@0"] and c.stats["hol_family_budget_ticks"] == 0


def test_a_variant_whose_own_approach_is_empty_gives_the_green_back() -> None:
    cfg = _with_variants()
    # every receiving lane queued, so every pressure is negative and the
    # empty approach's is the *least* negative: comparing pressures alone
    # would hold it (the first version did, to the maximum green)
    ctx = JunctionContext("J", "P0@0", 8.0, queue_pcu=_queues(s=5.0),
                          receiving_queue_pcu=dict.fromkeys(LANE_OF, 6.0))
    c = _controller(cfg, nominal_cycle_s=60.0)
    plan = c(cfg, ctx)
    assert [s.phase_id for s in plan.steps] == ["P0@0", "P0"]
    assert c.stats["hol_variant_idle_exit"] == 1
    assert interlocks.check(plan, ctx, cfg) == []


def test_the_owed_approach_does_not_delay_a_phase_that_cannot_wait() -> None:
    cfg = _with_variants()
    queues = _queues(s=1.0, e=30.0, w=30.0)
    ctx = JunctionContext("J", "P0@0", 30.0, queue_pcu=queues)
    c = _controller(cfg, nominal_cycle_s=60.0)
    assert [s.phase_id for s in c(cfg, ctx).steps] == ["P0@0", "P0"]     # south is owed
    # an east movement 20 s from its maximum wait: a change, P0's minimum
    # green and another change (15 s) plus the margin would overrun it
    east = dict.fromkeys(("L6", "L7", "L8"), True)
    urgent = replace(ctx, has_demand=east,
                     wait_times_s=dict.fromkeys(east, cfg.max_wait_s - 20.0))
    c2 = _controller(cfg, nominal_cycle_s=60.0)
    assert [s.phase_id for s in c2(cfg, urgent).steps][:2] == ["P0@0", "P1"]
    assert c2.stats["hol_family_owed"] == 0


def test_a_blockage_seen_under_a_red_is_not_acted_on() -> None:
    """A turner left in the box when its green ended, with a vehicle stopped
    behind it at the red, is waiting for the signal. Only a lane blocked
    under its own green is held up by the turner."""
    cfg = _with_variants()
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}
    ctx = JunctionContext("J", "P1", 30.0, queue_pcu=_queues(n=20.0, s=2.0), blocked_by=blocked)
    c = _controller(cfg, nominal_cycle_s=60.0)
    parent = acamp.AdaptiveCamp(acamp.AcampConfig(), nominal_cycle_s=60.0)
    for _ in range(8):
        assert c(cfg, ctx) == parent(cfg, replace(ctx, blocked_by={}))
    assert c.stats["hol_blocked_ticks"] == 0
    # the same goes for south's lane while north's variant has south's through stopped
    south = {m: "L5" for m in ("L3", "L4", "L5")}
    c = _controller(cfg, nominal_cycle_s=60.0)
    c(cfg, JunctionContext("J", "P0@0", 3.0, queue_pcu=_queues(n=20.0, s=9.0), blocked_by=south))
    assert c.stats["hol_blocked_ticks"] == 0


def test_no_variant_is_built_where_the_ring_already_has_that_signal_state() -> None:
    cfg = _config()
    twin = hol.split_variants(cfg, LANE_OF)[0]["P0@0"]
    lead = replace(cfg, phases={**cfg.phases, "P2": replace(twin, id="P2")},
                   ring_order=("P2", "P0", "P1"),
                   min_green_s={**cfg.min_green_s, "P2": 5.0},
                   max_green_s={**cfg.max_green_s, "P2": 40.0})
    variants, base_of = hol.split_variants(lead, LANE_OF)
    assert "P0@0" not in variants and base_of["P0@1"] == "P0"


# ---- on real junctions ---------------------------------------------------------------


def _real_networks():
    root = DATA_DIR
    nets = [root / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"]
    nets += sorted((root / "scenarios" / "generated").glob("*/*.net.xml"))
    return [n for n in nets if n.exists()]


@pytest.mark.parametrize("net", _real_networks(), ids=lambda n: n.parent.name)
def test_every_variant_of_a_real_junction_is_as_safe_as_its_base_phase(net) -> None:
    """On the corridor and every generated scenario present: a variant
    shows each movement as its base phase does or not at all, stops no
    permissive movement, so the change from a ring phase to its own variant
    can keep the continuing greens without a yellow trap (every other change
    is an ordinary all-red break) -- for single-lane variants and for the
    multi-lane ones the ablation arms build."""
    sys.path.insert(0, str(net.parents[2] / "networks" / "vijayawada"))
    from extract_tier0_config import load_configs  # noqa: PLC0415
    from link_lanes import link_to_lane_map  # noqa: PLC0415

    lanes = link_to_lane_map(str(net))
    for tls, cfg in load_configs(net).items():
        before = set(cfg.validate())
        for single in (True, False):
            with_v, base_of = hol.with_split_variants(cfg, lanes.get(tls, {}),
                                                      single_lane_only=single)
            assert set(with_v.validate()) <= before, tls
            if not base_of:
                continue
            n_links = 1 + max(int(m[1:]) for p in with_v.phases.values()
                              for m in p.green_movements)
            cab = TraCICabinet(tls, with_v.phases, n_links)
            for v, b in base_of.items():
                variant, base = with_v.phases[v], with_v.phases[b]
                stopped = base.green_movements - variant.green_movements
                assert stopped and stopped <= base.protected_movements, (tls, v)
                assert variant.protected_movements == base.protected_movements - stopped
                # no crossing in a phase that has variants (this lane map
                # gives a crossing its walking area, a ":" lane)
                assert not any(lanes[tls].get(m, ":").startswith(":")
                               for m in base.green_movements), (tls, b)
                # the way in keeps its greens and stops exactly the stopped
                # streams; the way out, and across to another variant, starts
                # something and is an ordinary change
                assert cab.can_carry(b, v) and not cab.can_carry(v, b), (tls, v)
                yellow, _ = cab.carried_clearance_states(b, v)
                assert {f"L{i}" for i, c in enumerate(yellow) if c == "y"} == stopped
                for w in (x for x, bb in base_of.items() if bb == b and x != v):
                    assert not cab.can_carry(v, w), (tls, v, w)


def test_a_change_inside_the_family_waits_when_another_phase_could_not() -> None:
    cfg = _with_variants()
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}
    ctx = JunctionContext("J", "P0", 8.0, queue_pcu=_queues(n=20.0, s=2.0), blocked_by=blocked)
    assert [s.phase_id for s in _controller(cfg, nominal_cycle_s=60.0)(cfg, ctx).steps] == [
        "P0", "P0@0"]
    # east is 28 s from its maximum wait: the variant would put a change, its
    # minimum green and another change (15 s) in front of east's turn, inside
    # the 15 s the parent keeps in hand
    east = dict.fromkeys(("L6", "L7", "L8"), True)
    tight = replace(ctx, has_demand=east, wait_times_s=dict.fromkeys(east, cfg.max_wait_s - 28.0))
    plan = _controller(cfg, nominal_cycle_s=60.0)(cfg, tight)
    assert "P0@0" not in [s.phase_id for s in plan.steps]


def test_a_plan_made_on_the_visits_clock_still_respects_the_running_phases_minimum_green() -> None:
    """The parent may be told more has elapsed than the running variant's
    own green (the visit budget); when its plan leaves, the variant's own
    minimum green decides how soon -- for the fixed-time fallback too."""
    cfg = _with_variants()
    c = _controller(cfg, nominal_cycle_s=60.0)
    ctx = JunctionContext("J", "P0@0", 2.0)
    for source in ("acamp", "fixed_time"):
        parent = SignalPlan("J", (PlanStep("P0", 1.0, yellow_s=3.0, all_red_s=2.0),
                                  PlanStep("P1", 5.0)), source=source)
        plan = c._leaving(cfg, ctx, parent, "P0", "P0@0", 5.0,  # noqa: SLF001
                          realise=source == "acamp")
        assert [(s.phase_id, s.green_s) for s in plan.steps] == [("P0@0", 3.0), ("P1", 5.0)]
        assert interlocks.check(plan, ctx, cfg) == []


# ---- what the kernel and the configuration check enforce -------------------------------


def test_the_kernel_refuses_a_plan_into_an_alternate_that_is_not_its_phase_made_smaller() -> None:
    cfg = _with_variants()
    ctx = JunctionContext("J", "P0", 8.0)

    def into(alt: Phase, **extra) -> list[str]:
        bad = replace(cfg, phases={**cfg.phases, "P0@0": alt}, **extra)
        plan = SignalPlan("J", (PlanStep("P0", 1.0, yellow_s=3.0, all_red_s=2.0),
                                PlanStep("P0@0", 5.0)))
        return [v.rule for v in interlocks.check(plan, ctx, bad)]

    good = cfg.phases["P0@0"]
    assert into(good) == []
    # the first design (one approach alone, all protected; the other's yielding
    # turn stopped) and the second (own turn promoted against a kept one)
    assert "RING_INTEGRITY" in into(Phase("P0@0", frozenset({"L0", "L1", "L2"})))
    assert "RING_INTEGRITY" in into(Phase("P0@0", good.green_movements,
                                          protected_movements=good.protected_movements | {"L2"}))
    # an alternate that stops nothing reads back as its base phase
    assert "RING_INTEGRITY" in into(replace(cfg.phases["P0"], id="P0@0"))
    # one with no minimum green of its own could be left after no time at all
    assert "RING_INTEGRITY" in into(good, min_green_s={"P0": 5.0, "P1": 5.0})
    assert any("minimum green" in p for p in replace(
        cfg, min_green_s={"P0": 5.0, "P1": 5.0}).alternate_problems("P0@0"))
    # and with no all-red, what it stopped would restart into a junction not yet empty
    assert any("all-red" in p for p in replace(cfg, all_red_s=0.0).alternate_problems())
    assert cfg.alternate_problems() == []


def test_crossings_are_taken_from_the_network_and_keep_a_phase_free_of_variants(tmp_path) -> None:
    net = tmp_path / "x.net.xml"
    net.write_text("""<net>
        <connection from="n" to="x" fromLane="0" toLane="0" tl="J" linkIndex="1"/>
        <connection from=":J_c0" to=":J_w1" fromLane="0" toLane="0" tl="J" linkIndex="1"/>
        <connection from=":J_c1" to=":J_w2" fromLane="0" toLane="0" tl="J" linkIndex="12"
                    linkIndex2="13"/>
        <connection from=":J_2" to="x" fromLane="0" toLane="0"/>
    </net>""")
    # link 1 carries a vehicle connection *and* a crossing: a lane map alone shows the lane
    assert hol.pedestrian_links(net) == {"J": frozenset({"L1", "L12", "L13"})}
    cfg = _config()
    assert any(v.startswith("P0@") for v in hol.split_variants(cfg, LANE_OF)[0])
    variants, _ = hol.split_variants(cfg, LANE_OF, pedestrian={"L1"})
    assert not any(v.startswith("P0@") for v in variants)
    assert any(v.startswith("P1@") for v in variants)


# ---- what counts as a blockage, and what a visit has room for --------------------------


def test_only_a_vehicle_waiting_on_a_yielding_movement_counts_as_blocking() -> None:
    """A through vehicle stuck in the box behind a full exit holds the lane
    up too, but no change of phase at this junction helps it."""
    cfg = _with_variants()
    ctx = JunctionContext("J", "P0", 8.0, queue_pcu=_queues(n=20.0, s=2.0))
    c = _controller(cfg, nominal_cycle_s=60.0)
    stuck = {m: "L1" for m in ("L0", "L1", "L2")}            # the through, protected in P0
    assert [s.phase_id for s in c(cfg, replace(ctx, blocked_by=stuck)).steps] == ["P0"]
    assert c.stats["hol_blocked_ticks"] == 0
    turner = {m: "L2" for m in ("L0", "L1", "L2")}           # the across turn, yielding
    assert [s.phase_id for s in c(cfg, replace(ctx, blocked_by=turner)).steps] == ["P0", "P0@0"]


def test_a_change_inside_the_family_needs_room_in_the_visits_budget() -> None:
    cfg = _with_variants()                                   # maximum green 40 s: budget 80 s
    blocked = {m: "L2" for m in ("L0", "L1", "L2")}
    ctx = JunctionContext("J", "P0", 30.0, queue_pcu=_queues(n=20.0, s=2.0), blocked_by=blocked)

    def at(visit_s: float) -> tuple[list[str], int]:
        c = _controller(cfg, nominal_cycle_s=60.0)
        c.set_sim_time(0.0)
        c(cfg, JunctionContext("J", "P0", 0.0, queue_pcu=ctx.queue_pcu))     # the ring arrives
        c._visit_used_variant = True                         # noqa: SLF001 -- it has been round once
        c.set_sim_time(visit_s)
        plan = c(cfg, ctx)
        return [s.phase_id for s in plan.steps], c.stats["hol_no_room"]

    assert at(60.0) == (["P0", "P0@0"], 0)        # 60 + 5 s change + 5 s minimum green fit in 80
    assert at(72.0) == (["P0"], 1)                # 72 + 5 + 5 do not


def test_a_variant_gives_way_when_another_phase_is_running_out_of_time() -> None:
    cfg = _with_variants()
    east = dict.fromkeys(("L6", "L7", "L8"), True)
    ctx = JunctionContext("J", "P0@0", 8.0, queue_pcu=_queues(n=20.0, e=4.0, w=4.0),
                          has_demand=east)
    c = _controller(cfg, nominal_cycle_s=60.0)
    assert [s.phase_id for s in c(cfg, ctx).steps] == ["P0@0"]
    # east 18 s from its maximum wait: the parent's own margin (15 s) plus the
    # change interval still to come (5 s) is more than that
    late = replace(ctx, wait_times_s=dict.fromkeys(east, cfg.max_wait_s - 18.0))
    plan = c(cfg, late)
    assert [s.phase_id for s in plan.steps][:2] == ["P0@0", "P1"]
    assert c.stats["hol_variant_cut_short"] == 1

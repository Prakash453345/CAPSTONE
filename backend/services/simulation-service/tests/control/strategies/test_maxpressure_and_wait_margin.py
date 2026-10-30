"""Paper-A additions (2026-10-28): the plain max-pressure baseline and the
junction-sized I5 urgency margin in CC-A-CAMP."""

from __future__ import annotations

from dataclasses import replace

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies import acamp
from sim_service.control.strategies.maxpressure import MaxPressure


def _cfg(all_red: float = 2.0, yellow: float = 3.0, min_g: float = 7.0) -> Tier0Config:
    ids, ms = ["P0", "P1", "P2"], ["m0", "m1", "m2"]
    return Tier0Config(
        intersection_id="J",
        phases={p: Phase(p, frozenset({m})) for p, m in zip(ids, ms, strict=True)},
        ring_order=tuple(ids),
        conflict_matrix={m: frozenset(o for o in ms if o != m) for m in ms},
        min_green_s=dict.fromkeys(ids, min_g),
        max_green_s=dict.fromkeys(ids, 20.0),
        yellow_s=yellow,
        all_red_s=all_red,
        max_wait_s=120.0,
        sat_flow_pcu_s=dict.fromkeys(ms, 1.0),
    )


def _ctx(q=None, rq=None, waits=None, demand=None, elapsed=20.0, cur="P0"):
    return JunctionContext(
        intersection_id="J", current_phase_id=cur, current_phase_elapsed_s=elapsed,
        queue_pcu=q or {}, receiving_queue_pcu=rq or {}, wait_times_s=waits or {},
        has_demand=demand or {},
    )


def test_margin_is_never_below_the_old_15_s():
    assert acamp._wait_margin_s(_cfg(all_red=0.0, yellow=2.0, min_g=3.0)) == 15.0


def test_margin_covers_change_min_green_change_with_ite_all_red():
    # 3.5 s yellow, 3.5 s all-red, 7 s minimum green, three phases: the current
    # phase's min green and change, then the other critical phase's, then ours
    cfg = _cfg(all_red=3.5, yellow=3.5, min_g=7.0)
    assert acamp._wait_margin_s(cfg) == 2 * (7.0 + 7.0) + 1.0


def test_maxpressure_holds_for_its_slot():
    mp = MaxPressure(slot_s=10.0)
    plan = mp(_cfg(), _ctx(q={"m1": 50.0}, elapsed=8.0))
    assert [s.phase_id for s in plan.steps] == ["P0"]


def test_maxpressure_picks_the_largest_upstream_minus_downstream_queue():
    mp = MaxPressure()
    # m1 has the biggest queue but its exit is full; m2 wins
    plan = mp(_cfg(), _ctx(q={"m0": 1.0, "m1": 9.0, "m2": 6.0}, rq={"m1": 8.0}))
    assert plan.steps[-1].phase_id == "P2"
    assert not interlocks.check(plan, _ctx(q={"m2": 6.0}), _cfg())


def test_maxpressure_serves_a_movement_near_its_wait_bound_first():
    cfg, mp = _cfg(), MaxPressure()
    near = cfg.max_wait_s - acamp._wait_margin_s(cfg) + 1.0
    ctx = _ctx(q={"m1": 9.0}, waits={"m2": near}, demand={"m2": True})
    assert mp(cfg, ctx).steps[-1].phase_id == "P2"
    assert mp.stats["i5_guard"] == 1


def test_maxpressure_keeps_current_on_a_tie():
    cfg = replace(_cfg())
    plan = MaxPressure()(cfg, _ctx(q={"m0": 3.0, "m1": 3.0}))
    assert [s.phase_id for s in plan.steps] == ["P0"]

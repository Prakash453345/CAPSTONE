"""`AcampConfig.rest_in_green`: at its green ceiling a phase stays green while
no other phase has anything to serve.

Without it the ceiling always ends the green, and at light demand the ring
then moves to an empty phase and pays a change interval for nothing (the
Amaravati plan grid, light demand: 69 % of all phase changes were forced by
the ceiling). The rule may only ever hold a green when nobody is waiting.
"""

from __future__ import annotations

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies import acamp


def _ring_config(n_phases: int = 3) -> Tier0Config:
    phase_ids = [f"P{i}" for i in range(n_phases)]
    movements = [f"m{i}" for i in range(n_phases)]
    phases = {p: Phase(p, frozenset({m})) for p, m in zip(phase_ids, movements, strict=True)}
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=tuple(phase_ids),
        conflict_matrix={m: frozenset(o for o in movements if o != m) for m in movements},
        min_green_s=dict.fromkeys(phase_ids, 10.0),
        max_green_s=dict.fromkeys(phase_ids, 20.0),
        yellow_s=3.0,
        all_red_s=2.0,
        sat_flow_pcu_s=dict.fromkeys(movements, 1.0),
    )


def _ctx(queues: dict[str, float], *, elapsed: float = 20.0, waits=None, approaching=None):
    return JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=elapsed,
        queue_pcu=queues,
        wait_times_s=waits or {},
        approaching_pcu=approaching or {},
    )


def _controller(**kw) -> acamp.AdaptiveCamp:
    c = acamp.AdaptiveCamp(acamp.AcampConfig(**kw))
    c.set_sim_time(0.0)
    return c


def test_off_by_default_the_ceiling_ends_the_green_even_with_nobody_waiting():
    cfg, c = _ring_config(), _controller()
    assert not acamp.AcampConfig().rest_in_green
    plan = c(cfg, _ctx({"m0": 5.0}))
    assert plan.steps[-1].phase_id != "P0"
    assert c.stats["switch_max_green"] == 1 and c.stats["rest_in_green"] == 0


def test_at_the_ceiling_the_green_is_held_while_no_other_phase_has_anything_to_serve():
    cfg, c = _ring_config(), _controller(rest_in_green=True)
    for elapsed in (20.0, 45.0, 300.0):
        ctx = _ctx({"m0": 5.0}, elapsed=elapsed)
        plan = c(cfg, ctx)
        assert [s.phase_id for s in plan.steps] == ["P0"]
        assert not interlocks.check(plan, ctx, cfg)
    assert c.stats["rest_in_green"] == 3 and c.stats["switch_max_green"] == 0


def test_a_queue_on_another_phase_ends_the_rest_at_once():
    cfg, c = _ring_config(), _controller(rest_in_green=True)
    plan = c(cfg, _ctx({"m0": 50.0, "m2": 1.0}))
    assert plan.steps[-1].phase_id == "P2"
    assert c.stats["rest_in_green"] == 0 and c.stats["switch_max_green"] == 1


def test_traffic_approaching_another_phase_ends_the_rest():
    cfg, c = _ring_config(), _controller(rest_in_green=True)
    plan = c(cfg, _ctx({"m0": 50.0}, approaching={"m1": 2.0}))
    assert plan.steps[-1].phase_id != "P0" and c.stats["rest_in_green"] == 0


def test_a_wait_near_its_bound_on_an_empty_phase_ends_the_rest():
    cfg, c = _ring_config(), _controller(rest_in_green=True)
    near = cfg.max_wait_s - acamp._SKIP_WAIT_MARGIN_S + 1.0  # noqa: SLF001
    plan = c(cfg, _ctx({"m0": 50.0}, waits={"m1": near}))
    assert plan.steps[-1].phase_id != "P0" and c.stats["rest_in_green"] == 0


def test_a_pedestrian_phase_is_never_rested_past():
    cfg = _ring_config()
    phases = dict(cfg.phases)
    phases["P2"] = Phase("P2", phases["P2"].green_movements, is_pedestrian=True)
    from dataclasses import replace

    cfg = replace(cfg, phases=phases)
    c = _controller(rest_in_green=True)
    plan = c(cfg, _ctx({"m0": 5.0}))
    assert plan.steps[-1].phase_id != "P0" and c.stats["rest_in_green"] == 0


def test_below_the_ceiling_nothing_changes():
    cfg = _ring_config()
    a, b = _controller(), _controller(rest_in_green=True)
    for queues in ({"m0": 5.0}, {"m0": 5.0, "m1": 9.0}, {}):
        ctx = _ctx(queues, elapsed=12.0)
        assert a(cfg, ctx) == b(cfg, ctx)


def test_rest_needs_free_exit_ends_the_rest_while_a_give_way_waits_past_the_exit():
    cfg = _ring_config()
    ctx_waiting = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=20.0,
        queue_pcu={"m0": 5.0}, yield_waiting_pcu={"m0": 1.0},
    )
    c = _controller(rest_in_green=True, rest_needs_free_exit=True)
    plan = c(cfg, ctx_waiting)
    assert plan.steps[-1].phase_id != "P0"
    assert c.stats["rest_exit_wanted"] == 1 and c.stats["rest_in_green"] == 0
    # nobody waiting past the exit: the rest goes on
    c = _controller(rest_in_green=True, rest_needs_free_exit=True)
    assert [s.phase_id for s in c(cfg, _ctx({"m0": 5.0})).steps] == ["P0"]
    # a give-way waiting past another phase's exit does not matter
    other = JunctionContext(
        intersection_id="J", current_phase_id="P0", current_phase_elapsed_s=20.0,
        queue_pcu={"m0": 5.0}, yield_waiting_pcu={"m1": 3.0},
    )
    c = _controller(rest_in_green=True, rest_needs_free_exit=True)
    assert [s.phase_id for s in c(cfg, other).steps] == ["P0"]

"""Behaviour tests for A-CA-MP's gap-out rule (`AcampConfig.gap_out_grace_s`).

Unit-level, no SUMO: the rule is a function of the context the runner hands the
strategy, and the plan it returns has to pass the same interlocks as every
other switch."""

from __future__ import annotations

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.safety import interlocks
from sim_service.control.strategies.acamp import AcampConfig, AdaptiveCamp


def _cfg() -> Tier0Config:
    phases = {
        "P0": Phase("P0", frozenset({"L0"})),
        "P1": Phase("P1", frozenset({"L1"})),
    }
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=("P0", "P1"),
        conflict_matrix={"L0": frozenset({"L1"}), "L1": frozenset({"L0"})},
        min_green_s={"P0": 7.0, "P1": 7.0},
        max_green_s={"P0": 40.0, "P1": 40.0},
        yellow_s=3.5,
        all_red_s=2.0,
        max_wait_s=120.0,
        sat_flow_pcu_s={"L0": 0.5, "L1": 0.5},
    )


def _ctx(elapsed: float, *, own_queue: float, other_queue: float) -> JunctionContext:
    return JunctionContext(
        intersection_id="J",
        current_phase_id="P0",
        current_phase_elapsed_s=elapsed,
        has_demand={"L0": own_queue > 0, "L1": other_queue > 0},
        wait_times_s={"L0": 0.0, "L1": 5.0},
        queue_pcu={"L0": own_queue, "L1": other_queue},
        approaching_pcu={"L0": 0.0, "L1": 0.0},
        receiving_occupancy={},
        receiving_queue_pcu={},
    )


def _drive(controller: AdaptiveCamp, cfg: Tier0Config, seconds: int, **kw):
    """Tick with the phase held until it proposes a transition, or `seconds`
    ticks pass. Stops at the first transition because this fixture keeps
    feeding the same phase as current -- the real runner would move on."""
    plan = None
    for i in range(seconds):
        plan = controller(cfg, _ctx(float(i), **kw))
        if len(plan.steps) == 2:
            return plan
    return plan


def test_an_empty_phase_yields_once_the_grace_period_passes():
    cfg = _cfg()
    c = AdaptiveCamp(AcampConfig(gap_out_grace_s=3.0), nominal_cycle_s=60.0)
    plan = _drive(c, cfg, 14, own_queue=0.0, other_queue=4.0)
    assert len(plan.steps) == 2 and plan.steps[1].phase_id == "P1"
    assert c.stats["switch_gap_out"] == 1


def test_it_never_cuts_minimum_green():
    cfg = _cfg()
    c = AdaptiveCamp(AcampConfig(gap_out_grace_s=0.0), nominal_cycle_s=60.0)
    for i in range(7):  # min green is 7 s
        plan = c(cfg, _ctx(float(i), own_queue=0.0, other_queue=4.0))
        assert len(plan.steps) == 1, f"switched at elapsed={i}, inside minimum green"
    assert c.stats["switch_gap_out"] == 0


def test_a_phase_with_its_own_demand_is_never_gapped_out():
    cfg = _cfg()
    c = AdaptiveCamp(AcampConfig(gap_out_grace_s=3.0), nominal_cycle_s=60.0)
    _drive(c, cfg, 20, own_queue=2.0, other_queue=4.0)
    assert c.stats["switch_gap_out"] == 0


def test_demand_arriving_inside_the_grace_period_resets_the_clock():
    cfg = _cfg()
    c = AdaptiveCamp(AcampConfig(gap_out_grace_s=3.0), nominal_cycle_s=60.0)
    for i in range(10):
        c(cfg, _ctx(float(i), own_queue=0.0, other_queue=4.0) if i < 9
          else _ctx(float(i), own_queue=1.0, other_queue=4.0))
    assert c._empty_for_s == 0.0


def test_no_yield_when_nothing_else_is_waiting():
    cfg = _cfg()
    c = AdaptiveCamp(AcampConfig(gap_out_grace_s=3.0), nominal_cycle_s=60.0)
    _drive(c, cfg, 20, own_queue=0.0, other_queue=0.0)
    assert c.stats["switch_gap_out"] == 0


def test_a_negative_grace_disables_the_rule():
    cfg = _cfg()
    c = AdaptiveCamp(AcampConfig(gap_out_grace_s=-1.0), nominal_cycle_s=60.0)
    _drive(c, cfg, 20, own_queue=0.0, other_queue=4.0)
    assert c.stats["switch_gap_out"] == 0


def test_the_plan_it_proposes_passes_every_interlock():
    cfg = _cfg()
    c = AdaptiveCamp(AcampConfig(gap_out_grace_s=3.0), nominal_cycle_s=60.0)
    ctx = None
    plan = None
    for i in range(14):
        ctx = _ctx(float(i), own_queue=0.0, other_queue=4.0)
        plan = c(cfg, ctx)
        if len(plan.steps) == 2:
            break
    assert len(plan.steps) == 2
    assert interlocks.check(plan, ctx, cfg) == []

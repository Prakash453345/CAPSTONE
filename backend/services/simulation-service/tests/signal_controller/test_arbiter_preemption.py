"""Rung 3 of the arbitration ladder: corridor preemption. The arbiter is
still the only thing that commands a cabinet; a preemption plan is checked
by the same interlocks as any strategy plan, and a rejected one falls
through to the strategy rather than forcing all-red.
"""

from __future__ import annotations

from itms_domain import JunctionContext, Phase, PlanStep, SignalPlan, Tier0Config
from sim_service.signal_controller import arbiter
from sim_service.signal_controller.cabinet import FakeCabinet


def _cfg() -> Tier0Config:
    return Tier0Config(
        intersection_id="J",
        phases={
            "NS": Phase("NS", frozenset({"N", "S"})),
            "EW": Phase("EW", frozenset({"E", "W"})),
        },
        ring_order=("NS", "EW"),
        conflict_matrix={
            "N": frozenset({"E", "W"}), "S": frozenset({"E", "W"}),
            "E": frozenset({"N", "S"}), "W": frozenset({"N", "S"}),
        },
        min_green_s={"NS": 10.0, "EW": 10.0},
        max_green_s={"NS": 60.0, "EW": 60.0},
        yellow_s=3.0,
        all_red_s=2.0,
        max_wait_s=600.0,
        max_preempt_s_per_hour=300.0,
    )


def _hold_ew(cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan | None:
    """A preemption source that always wants EW held."""
    if ctx.current_phase_id == "EW":
        return SignalPlan("J", (PlanStep("EW", green_s=1.0),), source="corridor_preemption")
    return SignalPlan(
        "J",
        (
            PlanStep("NS", green_s=max(0.0, 10.0 - ctx.current_phase_elapsed_s),
                     yellow_s=cfg.yellow_s, all_red_s=cfg.all_red_s),
            PlanStep("EW", green_s=10.0),
        ),
        source="corridor_preemption",
    )


def test_preemption_commands_the_ev_phase_when_it_is_safe():
    cfg = _cfg()
    ctx = JunctionContext("J", "EW", 12.0)   # EW already live and past min-green
    cabinet = FakeCabinet()
    cabinet.command("EW")

    decision = arbiter.tick(cfg, ctx, cabinet, preempt=_hold_ew)

    assert decision.mode == "corridor_preemption"
    assert decision.plan is not None and decision.plan.steps[0].phase_id == "EW"
    assert decision.plan.source == "corridor_preemption"
    assert cabinet.read_state().phase_id == "EW"


def test_preemption_switch_from_a_settled_phase_clears_properly():
    cfg = _cfg()
    ctx = JunctionContext("J", "NS", 15.0)   # NS live, min-green served
    cabinet = FakeCabinet()
    cabinet.command("NS")

    decision = arbiter.tick(cfg, ctx, cabinet, preempt=_hold_ew)

    assert decision.mode == "corridor_preemption"
    assert [s.phase_id for s in decision.plan.steps] == ["NS", "EW"]
    assert decision.plan.steps[0].yellow_s == cfg.yellow_s


def test_a_min_green_truncating_preemption_is_rejected_and_the_strategy_runs():
    cfg = _cfg()
    ctx = JunctionContext("J", "NS", 2.0)    # only 2 s into NS's 10 s min-green

    def truncating(cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        return SignalPlan(
            "J",
            (
                PlanStep("NS", green_s=0.0, yellow_s=cfg.yellow_s, all_red_s=cfg.all_red_s),
                PlanStep("EW", green_s=10.0),
            ),
            source="corridor_preemption",
        )

    cabinet = FakeCabinet()
    cabinet.command("NS")
    decision = arbiter.tick(cfg, ctx, cabinet, preempt=truncating)

    # not commanded as a preemption -- fell through to the fixed-time strategy
    assert decision.mode == "fixed_time"
    assert any("corridor_preemption_rejected" in n for n in decision.notes)
    assert any("I3" in n for n in decision.notes)
    # and the junction is NOT in all-red -- the strategy kept it on NS
    assert cabinet.read_state().phase_id == "NS"


def test_no_preemption_request_leaves_the_ladder_unchanged():
    cfg = _cfg()
    ctx = JunctionContext("J", "NS", 0.0)
    cabinet = FakeCabinet()

    baseline = arbiter.tick(cfg, ctx, cabinet)
    cabinet2 = FakeCabinet()
    with_none = arbiter.tick(cfg, ctx, cabinet2, preempt=lambda c, x: None)

    assert baseline.mode == with_none.mode == "fixed_time"
    assert with_none.notes == ()

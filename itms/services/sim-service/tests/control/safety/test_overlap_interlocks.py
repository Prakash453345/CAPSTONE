"""An overlap (`Phase.overlap_movements`) is not owned by its phase but is
shown with it, so the interlocks treat it as green: I1 checks it against the
phase's movements, and a change out of the phase clears it."""

from __future__ import annotations

from dataclasses import replace

from itms_domain import SignalPlan, Tier0Config
from itms_domain.signal import Phase, PlanStep
from sim_service.control.safety.interlocks import (
    clearance_intervals_present,
    no_conflicting_greens,
)


def _cfg(overlap: frozenset[str]) -> Tier0Config:
    phases = {"P1": Phase("P1", frozenset({"L0"})),
              "P2": Phase("P2", frozenset({"L2"}), overlap_movements=overlap)}
    return Tier0Config(
        intersection_id="J", phases=phases, ring_order=("P1", "P2"),
        conflict_matrix={"L0": frozenset({"L2", "L1"}), "L1": frozenset({"L0", "L2"}),
                         "L2": frozenset({"L0", "L1"})},
        min_green_s={"P1": 7.0, "P2": 7.0}, max_green_s={"P1": 40.0, "P2": 40.0},
        yellow_s=3.0, all_red_s=2.0)


def test_i1_checks_an_overlap_against_the_phase_it_is_shown_with() -> None:
    plan = SignalPlan(intersection_id="J", steps=(PlanStep(phase_id="P2", green_s=10.0),))
    assert no_conflicting_greens(plan, _cfg(frozenset())) == []
    assert [v.rule for v in no_conflicting_greens(plan, _cfg(frozenset({"L1"})))] == ["I1"]


def test_a_change_away_from_a_shown_overlap_needs_the_full_clearance() -> None:
    cfg = replace(_cfg(frozenset()), phases={
        "P1": Phase("P1", frozenset({"L3"})),
        "P2": Phase("P2", frozenset({"L2"}), overlap_movements=frozenset({"L1"}))})
    rushed = SignalPlan(intersection_id="J", steps=(
        PlanStep(phase_id="P2", green_s=10.0, yellow_s=0.0, all_red_s=0.0),
        PlanStep(phase_id="P1", green_s=10.0)))
    cfg = replace(cfg, conflict_matrix={**cfg.conflict_matrix, "L3": frozenset({"L1"}),
                                        "L1": frozenset({"L0", "L2", "L3"})})
    assert [v.rule for v in clearance_intervals_present(rushed, cfg)] == ["I2"]

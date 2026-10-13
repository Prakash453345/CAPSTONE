"""Unit tests for `webster.compute_timing`'s pure math -- deliberately
against small, hand-checkable synthetic flows rather than the real
Vijayawada data, so each assertion's expected number can be verified by
hand against Webster's formula, not just re-derived by the same code under
test."""

from __future__ import annotations

import math

from itms_domain import Phase, Tier0Config
from sim_service.control.strategies import webster


def _two_phase_config(min_green_s: float = 5.0, max_green_s: float = 120.0) -> Tier0Config:
    phases = {
        "P0": Phase("P0", frozenset({"L0"})),
        "P1": Phase("P1", frozenset({"L1"})),
    }
    return Tier0Config(
        intersection_id="J",
        phases=phases,
        ring_order=("P0", "P1"),
        conflict_matrix={"L0": frozenset({"L1"}), "L1": frozenset({"L0"})},
        min_green_s={"P0": min_green_s, "P1": min_green_s},
        max_green_s={"P0": max_green_s, "P1": max_green_s},
        yellow_s=3.0,
        all_red_s=2.0,
    )


def test_zero_flow_splits_the_cycle_evenly():
    cfg = _two_phase_config()
    timing = webster.compute_timing(cfg, {})
    assert timing.degree_of_saturation == 0.0
    # No demand data anywhere -- both phases get the same share of whatever
    # green pool the (near-minimum) cycle produces.
    assert timing.green_s["P0"] == timing.green_s["P1"]
    assert timing.cycle_s >= webster._MIN_CYCLE_S


def test_proportional_split_matches_hand_computed_webster():
    cfg = _two_phase_config(min_green_s=1.0, max_green_s=1000.0)
    # y0 = 950/1900 = 0.5, y1 = 190/1900 = 0.1 -> Y = 0.6
    flows = {"L0": 950.0, "L1": 190.0}
    timing = webster.compute_timing(cfg, flows)

    assert math.isclose(timing.critical_flow_ratios["P0"], 0.5, rel_tol=1e-9)
    assert math.isclose(timing.critical_flow_ratios["P1"], 0.1, rel_tol=1e-9)
    assert math.isclose(timing.degree_of_saturation, 0.6, rel_tol=1e-9)

    total_lost_time_s = 2 * webster._LOST_TIME_PER_PHASE_S  # 8.0
    expected_cycle = (1.5 * total_lost_time_s + webster._STARTUP_CLEARANCE_S) / (1 - 0.6)
    expected_cycle = max(webster._MIN_CYCLE_S, min(webster._MAX_CYCLE_S, expected_cycle))
    assert math.isclose(timing.cycle_s, expected_cycle, rel_tol=1e-9)

    pool = timing.cycle_s - total_lost_time_s
    expected_g0 = (0.5 / 0.6) * pool
    expected_g1 = (0.1 / 0.6) * pool
    assert math.isclose(timing.green_s["P0"], expected_g0, rel_tol=1e-9)
    assert math.isclose(timing.green_s["P1"], expected_g1, rel_tol=1e-9)
    # P0 (the heavier movement) gets more green than P1.
    assert timing.green_s["P0"] > timing.green_s["P1"]


def test_oversaturated_junction_reports_true_y_but_clamps_the_formula():
    cfg = _two_phase_config(min_green_s=1.0, max_green_s=1000.0)
    # y0 = y1 = 1900/1900 = 1.0 each -> Y = 2.0, way past saturation.
    flows = {"L0": 1900.0, "L1": 1900.0}
    timing = webster.compute_timing(cfg, flows)

    assert math.isclose(timing.degree_of_saturation, 2.0, rel_tol=1e-9)
    # The formula's input Y is clamped, so the cycle is finite and capped.
    assert timing.cycle_s <= webster._MAX_CYCLE_S
    assert timing.cycle_s > 0
    # Equal demand on both phases -> equal green split regardless of the
    # clamp (the clamp affects cycle length, not the proportional split).
    assert math.isclose(timing.green_s["P0"], timing.green_s["P1"], rel_tol=1e-9)


def test_green_never_goes_below_min_green_even_with_zero_measured_demand():
    # A phase nobody uses (flow=0) must still get at least its own
    # min_green -- Webster's proportional share can round to less than
    # that, and the Tier-0 config's own floor wins.
    cfg = _two_phase_config(min_green_s=15.0, max_green_s=200.0)
    flows = {"L0": 1800.0, "L1": 0.0}
    timing = webster.compute_timing(cfg, flows)
    assert timing.green_s["P1"] >= 15.0


def test_green_never_exceeds_max_green_even_with_dominant_demand():
    cfg = _two_phase_config(min_green_s=1.0, max_green_s=20.0)
    flows = {"L0": 1850.0, "L1": 5.0}
    timing = webster.compute_timing(cfg, flows)
    assert timing.green_s["P0"] <= 20.0


def test_fixed_cycle_s_overrides_the_optimum_cycle_formula():
    cfg = _two_phase_config(min_green_s=1.0, max_green_s=1000.0)
    flows = {"L0": 950.0, "L1": 190.0}  # same case as the hand-computed test above
    timing = webster.compute_timing(cfg, flows, fixed_cycle_s=100.0)
    assert timing.cycle_s == 100.0
    # Split still proportional to the same 0.5/0.1 flow ratios, just within
    # the externally-fixed 100s pool instead of the formula's own optimum.
    total_lost_time_s = 2 * webster._LOST_TIME_PER_PHASE_S
    pool = 100.0 - total_lost_time_s
    assert math.isclose(timing.green_s["P0"], (0.5 / 0.6) * pool, rel_tol=1e-9)
    # degree_of_saturation is still this junction's own true measured value,
    # unaffected by which cycle length the split was computed against.
    assert math.isclose(timing.degree_of_saturation, 0.6, rel_tol=1e-9)


def test_fixed_cycle_s_still_respects_min_and_max_green():
    cfg = _two_phase_config(min_green_s=15.0, max_green_s=20.0)
    flows = {"L0": 1800.0, "L1": 0.0}
    timing = webster.compute_timing(cfg, flows, fixed_cycle_s=40.0)
    assert timing.green_s["P1"] >= 15.0
    assert timing.green_s["P0"] <= 20.0


def test_empty_ring_returns_degenerate_zero_timing():
    cfg = Tier0Config(
        intersection_id="J",
        phases={},
        ring_order=(),
        conflict_matrix={},
        min_green_s={},
        max_green_s={},
        yellow_s=3.0,
        all_red_s=2.0,
    )
    timing = webster.compute_timing(cfg, {})
    assert timing.cycle_s == 0.0
    assert timing.green_s == {}

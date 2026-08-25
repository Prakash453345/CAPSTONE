"""Unit tests for the bench report's CI math -- hand-checkable against a
known dataset (values 1..10 have a textbook mean/stdev) so the t-critical
lookup and the CI formula are each independently verifiable."""

from __future__ import annotations

import math

from sim_service.control import bench_stats


def test_t_critical_matches_known_table_values():
    assert bench_stats.t_critical_95(9) == 2.262  # the gate's own N=10 -> df=9
    assert bench_stats.t_critical_95(1) == 12.706


def test_t_critical_falls_back_to_normal_approx_beyond_the_table():
    assert bench_stats.t_critical_95(31) == 1.96
    assert bench_stats.t_critical_95(1000) == 1.96


def test_t_critical_rejects_nonpositive_df():
    try:
        bench_stats.t_critical_95(0)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for df < 1")


def test_confidence_interval_matches_hand_computed_values():
    # 1..10: mean=5.5, sample stdev=sqrt(82.5/9)=3.0276503..., n=10 -> df=9
    values = list(range(1, 11))
    ci = bench_stats.confidence_interval_95(values)
    assert math.isclose(ci.mean, 5.5, rel_tol=1e-9)
    expected_stdev = math.sqrt(sum((v - 5.5) ** 2 for v in values) / 9)
    expected_half_width = 2.262 * (expected_stdev / math.sqrt(10))
    assert math.isclose(ci.half_width_95, expected_half_width, rel_tol=1e-6)
    assert ci.n == 10


def test_confidence_interval_on_a_single_value_has_zero_width_not_an_error():
    ci = bench_stats.confidence_interval_95([42.0])
    assert ci.mean == 42.0
    assert ci.half_width_95 == 0.0
    assert ci.n == 1


def test_confidence_interval_on_empty_input_is_zero():
    ci = bench_stats.confidence_interval_95([])
    assert ci.mean == 0.0
    assert ci.half_width_95 == 0.0
    assert ci.n == 0


def test_confidence_interval_on_identical_values_has_zero_width():
    ci = bench_stats.confidence_interval_95([7.0] * 10)
    assert ci.mean == 7.0
    assert ci.half_width_95 == 0.0


def test_str_flags_missing_ci_for_n_below_two():
    ci = bench_stats.confidence_interval_95([3.0])
    assert "no CI" in str(ci)
    ci2 = bench_stats.confidence_interval_95([3.0, 4.0])
    assert "±" in str(ci2)

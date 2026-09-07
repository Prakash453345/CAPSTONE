"""`ConformalCalibrator` -- the plan section 10 alert threshold.

The load-bearing test is `test_empirical_false_alarm_rate_is_bounded_by_alpha`:
calibrate on held-out normal scores, then the alert rate on a *fresh* normal
sample must sit at or below alpha (within sampling error). Everything else
checks the adaptive machinery around that guarantee.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from sim_service.control.anomaly.calibration import (
    ConformalCalibrator,
    ConformalConfig,
    _weighted_conformal_quantile,
)


def _normal_scores(n: int, *, loc: float = 0.0, scale: float = 1.0, seed: int = 0):
    return np.random.default_rng(seed).normal(loc, scale, n).tolist()


# ---- the guarantee -------------------------------------------------


def test_empirical_false_alarm_rate_is_bounded_by_alpha():
    cal = ConformalCalibrator(ConformalConfig(alpha=0.05, min_points=200))
    cal.fit(_normal_scores(8000, seed=1))
    fresh = np.array(_normal_scores(20000, seed=2))
    fpr = float(np.mean(fresh > cal.tau))
    assert fpr <= 0.05 + 0.01          # bounded by alpha, small sampling slack
    assert fpr >= 0.05 - 0.02          # and not absurdly conservative


def test_tau_is_infinite_until_min_points_seen():
    cal = ConformalCalibrator(ConformalConfig(alpha=0.1, min_points=500))
    assert cal.tau == math.inf
    assert not cal.is_alert(1e9)
    for s in _normal_scores(499, seed=0):
        cal.observe_normal(s)
    assert cal.tau == math.inf
    cal.observe_normal(0.0)
    assert math.isfinite(cal.tau)


def test_is_alert_splits_on_tau():
    cal = ConformalCalibrator(ConformalConfig(alpha=0.05, min_points=100))
    cal.fit(_normal_scores(5000, seed=3))
    t = cal.tau
    assert cal.is_alert(t + 1.0)
    assert not cal.is_alert(t - 1.0)


# ---- the feedback loop ------------------------------------------


def test_operator_rejections_raise_tau():
    cal = ConformalCalibrator(ConformalConfig(alpha=0.05, window=50_000, min_points=100))
    cal.fit(_normal_scores(10000, seed=4))
    tau_before = cal.tau
    borderline = tau_before + 0.5
    assert cal.is_alert(borderline)

    # the operator keeps rejecting candidates that scored around `borderline`
    for _ in range(400):
        cal.observe_rejected([borderline + 0.1, borderline - 0.1, borderline])
    assert cal.tau > tau_before
    assert not cal.is_alert(borderline)          # the detector stopped over-firing here
    assert cal.report()["rejected_points_absorbed"] == 1200


# ---- adaptivity ------------------------------------------------


def test_sliding_window_tracks_a_distribution_shift():
    cal = ConformalCalibrator(ConformalConfig(alpha=0.1, window=4000, min_points=200))
    cal.fit(_normal_scores(4000, loc=0.0, seed=5))
    tau_low = cal.tau
    for s in _normal_scores(4000, loc=10.0, seed=6):   # demand regime shifts up
        cal.observe_normal(s)
    tau_high = cal.tau
    assert tau_high > tau_low + 5.0                    # old points fully evicted


def test_recency_weighting_pulls_tau_toward_recent_points():
    old = _normal_scores(3000, loc=0.0, seed=7)
    new = _normal_scores(3000, loc=6.0, seed=8)
    unweighted = ConformalCalibrator(ConformalConfig(alpha=0.1, window=10000,
                                                     decay=1.0, min_points=100))
    weighted = ConformalCalibrator(ConformalConfig(alpha=0.1, window=10000,
                                                   decay=0.999, min_points=100))
    for c in (unweighted, weighted):
        c.fit(old + new)
    assert weighted.tau > unweighted.tau              # recent (higher) points weigh more


# ---- exactness / plumbing -------------------------------------


def test_equal_weight_quantile_matches_the_classic_order_statistic():
    rng = np.random.default_rng(0)
    v = rng.normal(size=1000)
    w = np.ones(1000)
    alpha = 0.1
    tau = _weighted_conformal_quantile(v, w, alpha)
    k = math.ceil((len(v) + 1) * (1 - alpha))          # 1-indexed order statistic
    expected = np.sort(v)[k - 1]
    assert tau == pytest.approx(expected)


def test_report_has_the_expected_keys():
    cal = ConformalCalibrator(ConformalConfig(alpha=0.05, min_points=50))
    cal.fit(_normal_scores(1000, seed=9))
    r = cal.report()
    assert set(r) == {
        "alpha", "tau", "n_points", "window", "decay",
        "rejected_points_absorbed", "empirical_fpr_on_window",
    }
    assert r["empirical_fpr_on_window"] <= 0.08


def test_save_and_load_roundtrip(tmp_path):
    cal = ConformalCalibrator(ConformalConfig(alpha=0.03, window=5000, decay=0.9995,
                                              min_points=100))
    cal.fit(_normal_scores(3000, seed=11))
    cal.observe_rejected([5.0, 6.0])
    p = tmp_path / "conformal.json"
    cal.save(p)
    back = ConformalCalibrator.load(p)
    assert back.tau == pytest.approx(cal.tau)
    assert back.cfg.decay == 0.9995
    assert back.report()["rejected_points_absorbed"] == 2


@pytest.mark.parametrize("bad", [
    {"alpha": 0.0}, {"alpha": 1.0}, {"alpha": -0.1},
    {"decay": 0.0}, {"decay": 1.5}, {"window": 0},
])
def test_config_rejects_bad_values(bad):
    with pytest.raises(ValueError):
        ConformalConfig(**bad)

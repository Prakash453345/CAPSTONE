"""`control/online_calibration.py` -- learning from prediction error.

The properties worth pinning are mostly about *not* learning the wrong
thing. An estimator that happily consumes every green would be easy to
write and would degrade the controller, so most of these tests are about
what it refuses.
"""

from __future__ import annotations

import json

from sim_service.control.online_calibration import OnlineCalibration


def _cal(**kw) -> OnlineCalibration:
    return OnlineCalibration(**kw)


def test_unsaturated_greens_are_refused():
    """The identification problem, and the single most important
    behaviour here. A green whose queue cleared measures how much traffic
    there was, not how fast the approach can serve it. Consuming those
    observations would drag every estimate downward at exactly the
    movements that are keeping up -- learning that looks like learning and
    is worse than none."""
    cal = _cal()
    for _ in range(50):
        residual = cal.observe_green(
            "J",
            "m0",
            baseline_sat_flow=0.4,
            discharged_pcu=20.0,
            effective_green_s=20.0,
            queue_remained=False,
        )
        assert residual is None
    assert cal.sat_flow_for("J", 0.4, "m0") == 0.4
    assert cal.models["J\x1fm0"].rejected_unsaturated == 50


def test_tiny_and_short_observations_are_refused():
    """Two vehicles crossing says more about those drivers than about a
    saturation rate, and a green shorter than the start-up wave measures
    lost time rather than capacity."""
    cal = _cal()
    assert (
        cal.observe_green(
            "J",
            "m0",
            baseline_sat_flow=0.4,
            discharged_pcu=1.0,
            effective_green_s=20.0,
            queue_remained=True,
        )
        is None
    )
    assert cal.models["J\x1fm0"].rejected_too_small == 1
    assert (
        cal.observe_green(
            "J",
            "m0",
            baseline_sat_flow=0.4,
            discharged_pcu=20.0,
            effective_green_s=2.0,
            queue_remained=True,
        )
        is None
    )
    assert cal.models["J\x1fm0"].rejected_too_short == 1
    assert cal.models["J\x1fm0"].saturated_samples == 0


def test_it_converges_toward_the_true_rate():
    """Given saturated observations at a consistent real rate, the
    estimate should move from the (wrong) baseline toward it."""
    cal = _cal(alpha=0.2)
    true_rate = 0.30
    for _ in range(60):
        cal.observe_green(
            "J",
            "m0",
            baseline_sat_flow=0.5,
            discharged_pcu=true_rate * 20.0,
            effective_green_s=20.0,
            queue_remained=True,
        )
    assert abs(cal.sat_flow_for("J", 0.5, "m0") - true_rate) < 0.02


def test_the_five_placeholder_movements_are_exactly_the_case_this_helps():
    """Five of this corridor's 73 movements never got an offline reading
    and sit on a 0.5 placeholder against a measured corridor mean of
    0.400. Operational observation is the only thing that can correct
    them, and the band is wide enough to let it."""
    cal = _cal(alpha=0.2)
    for _ in range(60):
        cal.observe_green(
            "J",
            "L4",
            baseline_sat_flow=0.5,
            discharged_pcu=0.32 * 20.0,
            effective_green_s=20.0,
            queue_remained=True,
        )
    learned = cal.sat_flow_for("J", 0.5, "L4")
    assert 0.30 < learned < 0.36, learned
    assert learned < 0.5 * 2.0 and learned > 0.5 * 0.5  # inside the band, not clamped by it


def test_the_band_clamps_an_implausible_estimate():
    """A movement whose observations demand 5x its measured saturation
    flow has an observation problem, not a capacity discovery. The band
    turns that into a visible clamp rather than a silent corruption of
    the term that multiplies the whole pressure function."""
    cal = _cal(alpha=0.5)
    for _ in range(100):
        cal.observe_green(
            "J",
            "m0",
            baseline_sat_flow=0.4,
            discharged_pcu=2.0 * 20.0,
            effective_green_s=20.0,
            queue_remained=True,
        )
    assert cal.sat_flow_for("J", 0.4, "m0") == 0.4 * cal.max_factor
    assert cal.report()["at_upper_bound"] == 1


def test_an_unobserved_movement_behaves_exactly_as_before():
    """Falling back to the config value rather than to a corridor mean is
    what makes this additive: a movement nothing has been learned about
    must behave identically to how it did before this module existed."""
    cal = _cal()
    assert cal.sat_flow_for("J", 0.4321, "never-seen") == 0.4321
    assert cal.arrival_reliability_for("J", "never-seen") == 1.0


def test_arrival_reliability_learns_the_shortfall():
    """`approaching_pcu` assumes counted vehicles keep coming. Where they
    turn off or get held up, the anticipation term was overstating that
    movement's claim on green, and the learned ratio is the correction."""
    cal = _cal(arrival_alpha=0.2)
    for _ in range(80):
        cal.observe_arrivals("J", "m0", baseline_sat_flow=0.4, predicted_pcu=10.0, arrived_pcu=7.0)
    assert abs(cal.arrival_reliability_for("J", "m0") - 0.7) < 0.02


def test_arrival_reliability_never_exceeds_one():
    """More traffic arriving than was predicted means the prediction
    missed some, not that the predictor is more than perfectly reliable.
    A ratio above 1.0 would inflate `approaching_pcu` above what was
    actually observed on the lane."""
    cal = _cal(arrival_alpha=0.5)
    for _ in range(50):
        cal.observe_arrivals("J", "m0", baseline_sat_flow=0.4, predicted_pcu=5.0, arrived_pcu=50.0)
    assert cal.arrival_reliability_for("J", "m0") <= 1.0


def test_report_separates_rejection_causes():
    """The aggregate count cannot distinguish "this approach is never busy
    enough to measure" from "the thresholds are wrong" -- the first is a
    fact about the corridor and the second is a bug."""
    cal = _cal()
    cal.observe_green(
        "J",
        "a",
        baseline_sat_flow=0.4,
        discharged_pcu=20.0,
        effective_green_s=20.0,
        queue_remained=False,
    )
    cal.observe_green(
        "J",
        "b",
        baseline_sat_flow=0.4,
        discharged_pcu=0.5,
        effective_green_s=20.0,
        queue_remained=True,
    )
    cal.observe_green(
        "J",
        "c",
        baseline_sat_flow=0.4,
        discharged_pcu=20.0,
        effective_green_s=1.0,
        queue_remained=True,
    )
    r = cal.report()
    assert r["rejected_unsaturated"] == 1
    assert r["rejected_too_small"] == 1
    assert r["rejected_too_short"] == 1


def test_save_load_round_trip(tmp_path):
    cal = _cal(alpha=0.15)
    for _ in range(30):
        cal.observe_green(
            "J",
            "m0",
            baseline_sat_flow=0.4,
            discharged_pcu=6.0,
            effective_green_s=20.0,
            queue_remained=True,
        )
        cal.observe_arrivals("J", "m0", baseline_sat_flow=0.4, predicted_pcu=8.0, arrived_pcu=6.0)
    path = tmp_path / "cal.json"
    cal.save(path)
    assert not list(path.parent.glob("*.tmp"))
    json.loads(path.read_text())

    back = OnlineCalibration.load(path)
    assert back.alpha == 0.15
    assert back.sat_flow_for("J", 0.4, "m0") == cal.sat_flow_for("J", 0.4, "m0")
    assert back.arrival_reliability_for("J", "m0") == cal.arrival_reliability_for("J", "m0")


def test_cold_start_load_is_not_an_error(tmp_path):
    cal = OnlineCalibration.load(tmp_path / "absent.json")
    assert cal.report()["movements_learned"] == 0
    assert cal.sat_flow_for("J", 0.4, "m0") == 0.4


def test_overrides_cover_every_configured_movement():
    """The mapping handed to the strategy must be total over the config,
    or a movement would silently drop out of the pressure function."""
    cal = _cal()
    for _ in range(30):
        cal.observe_green(
            "J",
            "m1",
            baseline_sat_flow=0.4,
            discharged_pcu=6.0,
            effective_green_s=20.0,
            queue_remained=True,
        )
    config = {"m0": 0.4, "m1": 0.4, "m2": 0.35}
    out = cal.sat_flow_overrides("J", config)
    assert set(out) == set(config)
    assert out["m0"] == 0.4 and out["m2"] == 0.35  # untouched
    assert out["m1"] != 0.4  # learned

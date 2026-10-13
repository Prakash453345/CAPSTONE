"""Queue past the view, counted at both ends (`vision_service.state.gap_count`)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from itms_geo.coverage import LaneCoverage
from vision_service.state.gap_count import EdgeGap, GapConfig, build_gaps, update_gap

L = 600.0
CFG = GapConfig()


def _cov(lane: str, runs: list[tuple[float, float]]) -> LaneCoverage:
    s = np.arange(0.0, L + 1e-9, 2.0)
    covered = np.zeros(len(s), bool)
    for a, b in runs:
        covered |= (s >= a) & (s <= b)
    return LaneCoverage(lane, L, s, covered, np.where(covered, 0.1, np.inf))


def _network(lanes=("e_0", "e_1")):
    return SimpleNamespace(lanes={ln: SimpleNamespace(edge_id="e", length=L, speed=13.9)
                                  for ln in lanes})


def _gap(lanes=("e_0",)) -> EdgeGap:
    return EdgeGap(edge_id="e", lanes=lanes, s_a=50.0, end_a=100.0, s_b=550.0, cam_a="up",
                   cam_b="near", near_start={ln: 500.0 for ln in lanes},
                   unseen_m={ln: 400.0 for ln in lanes}, lag_s=3.6, free_s=28.8)


def _tr(cam: str, tid: int, s: float, *, stopped: bool = False, pcu: float = 1.0):
    return SimpleNamespace(camera_id=cam, track_id=tid, s=s, stopped=stopped, pcu=pcu)


def test_the_count_lines_sit_in_both_views_with_the_unseen_stretch_between() -> None:
    net = _network()
    covs = {"up": {ln: _cov(ln, [(0, 98)]) for ln in net.lanes},
            "near": {ln: _cov(ln, [(502, 600)]) for ln in net.lanes}}
    gaps = build_gaps(net, covs, ["e_0"], CFG)
    g = gaps["e"]
    assert (g.cam_a, g.cam_b) == ("up", "near")
    assert 0 < g.s_a < g.end_a <= 98 and 502 < g.s_b < 600
    assert g.lanes == ("e_0", "e_1") and all(v > 350 for v in g.unseen_m.values())
    # no upstream view: an entry, its inflow modelled
    assert build_gaps(net, {"near": covs["near"]}, ["e_0"], CFG)["e"].modelled
    # filmed nearly end to end: nothing out of view worth counting
    close = {"up": {ln: _cov(ln, [(0, 480)]) for ln in net.lanes}, "near": covs["near"]}
    assert build_gaps(net, close, ["e_0"], CFG) == {}


def _queue_at_far_end(tid0: int = 1000) -> list:
    """Stopped vehicles standing across line B (a queue that may run past the view)."""
    return [_tr("near", tid0 + k, 542.0 + 4.0 * k, stopped=True) for k in range(5)]


def test_vehicles_that_went_in_and_never_came_out_are_queued_out_of_view() -> None:
    g = _gap()
    t = 0.0
    update_gap(g, t, {"e_0": _queue_at_far_end()}, CFG)   # anchors: nothing hidden yet
    for k in range(40):                                    # 40 cars drive past line A
        t += 1.0
        update_gap(g, t, {"e_0": [_tr("up", k, 40.0)] + _queue_at_far_end()}, CFG)
        t += 1.0
        update_gap(g, t, {"e_0": [_tr("up", k, 60.0)] + _queue_at_far_end()}, CFG)
    for _ in range(60):                                    # ... and none reaches line B
        t += 1.0
        update_gap(g, t, {"e_0": _queue_at_far_end()}, CFG)
    assert g.in_pcu == 40 and g.out_pcu == 0
    # the five standing in view were there when the count was anchored; all 40
    # newcomers are behind them, out of sight
    assert g.hidden == 40
    # only the excess over report_above_pcu reaches the lane estimate
    assert g.share(t, CFG) == {"e_0": pytest.approx(40.0 - CFG.report_above_pcu)}


def test_a_track_jittering_across_a_line_counts_once() -> None:
    g = _gap()
    update_gap(g, 0.0, {"e_0": _queue_at_far_end()}, CFG)
    for k, s in enumerate([548.0, 551.0, 549.5, 552.0, 549.0, 553.0]):
        update_gap(g, 1.0 + k, {"e_0": [_tr("near", 7, s, stopped=True)] + _queue_at_far_end()},
                   CFG)
    assert g.out_pcu == 1


def test_an_empty_far_end_proves_nothing_is_hidden_and_resets_the_count() -> None:
    g = _gap()
    t = 0.0
    update_gap(g, t, {"e_0": _queue_at_far_end()}, CFG)
    for k in range(20):
        t += 1.0
        update_gap(g, t, {"e_0": [_tr("up", k, 40.0)] + _queue_at_far_end()}, CFG)
        t += 1.0
        update_gap(g, t, {"e_0": [_tr("up", k, 60.0)] + _queue_at_far_end()}, CFG)
    for _ in range(40):
        t += 1.0
        update_gap(g, t, {"e_0": _queue_at_far_end()}, CFG)
    assert g.hidden > 0
    # the queue has gone (a drift of 15 missed exits would otherwise stay forever)
    for _ in range(int(CFG.clear_s) + 1):
        t += 1.0
        update_gap(g, t, {"e_0": []}, CFG)
    assert g.hidden == 0 and g.share(t, CFG) == {}


def test_hidden_queue_goes_only_to_lanes_whose_far_end_queues_and_is_capped() -> None:
    g = _gap(("e_0", "e_1"))
    t = 0.0
    q = {"e_0": _queue_at_far_end(), "e_1": [_tr("near", 900, 530.0)]}   # e_1: moving only
    update_gap(g, t, q, CFG)
    for k in range(300):
        t += 1.0
        update_gap(g, t, {**q, "e_0": [_tr("up", k, 40.0)] + q["e_0"]}, CFG)
        t += 1.0
        update_gap(g, t, {**q, "e_0": [_tr("up", k, 60.0)] + q["e_0"]}, CFG)
    share = g.share(t, CFG)
    assert set(share) == {"e_0"}
    assert share["e_0"] == CFG.jam_pcu_per_m * g.unseen_m["e_0"]   # 300 in, 80 fit


def test_the_estimator_adds_the_counted_queue_to_the_lane(network, rig, links) -> None:
    from vision_service.state import EstimatorConfig, LinkStateEstimator

    # the synthetic corridor has one camera: its approach is an entry, and an
    # empty road hides nothing
    est = LinkStateEstimator(rig, links[0], links[1], EstimatorConfig())
    assert set(est.gaps) == {"in"} and est.gaps["in"].modelled
    for t in range(5):
        est.update(float(t), [])
    assert est.lanes["in_0"].hidden_pcu == 0.0
    assert LinkStateEstimator(rig, links[0], links[1],
                              EstimatorConfig(gap_counting=False)).gaps == {}


def _entry() -> EdgeGap:
    return EdgeGap(edge_id="e", lanes=("e_0",), s_a=0.0, end_a=0.0, s_b=550.0, cam_a=None,
                   cam_b="near", near_start={"e_0": 500.0}, unseen_m={"e_0": 500.0},
                   lag_s=0.0, free_s=36.0)


def test_an_entry_nobody_films_upstream_learns_its_arrivals_while_nothing_queues() -> None:
    net = _network(("e_0",))
    covs = {"near": {"e_0": _cov("e_0", [(502, 600)])}}
    g = build_gaps(net, covs, ["e_0"], CFG)["e"]
    assert g.modelled and g.unseen_m["e_0"] > 450
    g = _entry()
    t, k = 0.0, 0
    for _ in range(1200):                  # free flow: one car across B every 10 s
        t += 1.0
        cars = []
        if int(t) % 10 in (0, 1):
            cars = [_tr("near", k, 545.0 if int(t) % 10 == 0 else 556.0)]
            if int(t) % 10 == 1:
                k += 1
        update_gap(g, t, {"e_0": cars}, CFG)
    assert 0.07 < g.rate < 0.11 and g.hidden == 0.0
    # a queue stands across B and nothing leaves: arrivals pile up out of view
    rate = g.rate
    for _ in range(300):
        t += 1.0
        update_gap(g, t, {"e_0": _queue_at_far_end()}, CFG)
    assert g.rate == rate                  # not learned while queued
    # about 300 s of arrivals, less what may still be driving to the queue
    assert 300 * rate - rate * g.free_s - 1e-6 <= g.hidden <= 300 * rate + 1e-6
    assert g.share(t, CFG)["e_0"] == pytest.approx(g.hidden - CFG.report_above_pcu)

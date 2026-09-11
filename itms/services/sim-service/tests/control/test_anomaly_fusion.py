"""`FusionLayer`, `CandidateRaiser`, `neighbour_mean_scores`."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from sim_service.control.anomaly.fusion import (  # noqa: E402
    FUSION_FEATURES,
    N_FUSION_FEATURES,
    CandidateRaiser,
    FusionConfig,
    FusionLayer,
    RaiserConfig,
    neighbour_mean_scores,
)

_GS = FUSION_FEATURES.index("graph_score")
_VIS = FUSION_FEATURES.index("vision_score")


def _feat(graph_score=0.0, persistence=0.0, neighbour_mean=0.0, is_green=0.0, vision_score=0.0):
    row = np.zeros(N_FUSION_FEATURES)
    row[_GS] = graph_score
    row[FUSION_FEATURES.index("persistence")] = persistence
    row[FUSION_FEATURES.index("neighbour_mean")] = neighbour_mean
    row[FUSION_FEATURES.index("is_green")] = is_green
    row[_VIS] = vision_score
    return row


# ---- monotone mode ---------------------------------------------


def test_monotone_probability_is_half_at_tau_and_monotone_around_it():
    fl = FusionLayer(FusionConfig(mode="monotone", gain=1.5))
    tau = 2.0
    assert fl.probability(_feat(graph_score=tau), tau) == pytest.approx(0.5)
    assert fl.probability(_feat(graph_score=tau + 1.0), tau) > 0.5
    assert fl.probability(_feat(graph_score=tau - 1.0), tau) < 0.5


def test_monotone_is_graph_only_when_vision_absent_and_rises_with_vision():
    fl = FusionLayer(FusionConfig(mode="monotone"))
    tau = 1.0
    no_vision = fl.probability(_feat(graph_score=1.2, vision_score=0.0), tau)
    with_vision = fl.probability(_feat(graph_score=1.2, vision_score=0.8), tau)
    assert with_vision > no_vision


def test_probability_broadcasts_over_a_matrix_of_nodes():
    fl = FusionLayer()
    feats = np.stack([_feat(graph_score=g) for g in (-2.0, 0.0, 3.0)])
    p = fl.probability(feats, tau=0.0)
    assert p.shape == (3,)
    assert p[0] < p[1] < p[2]


def test_probability_rejects_wrong_feature_width():
    fl = FusionLayer()
    with pytest.raises(ValueError):
        fl.probability(np.zeros((4, N_FUSION_FEATURES - 1)), tau=0.0)


def test_fit_is_rejected_in_monotone_mode():
    fl = FusionLayer(FusionConfig(mode="monotone"))
    with pytest.raises(RuntimeError):
        fl.fit(np.zeros((2, N_FUSION_FEATURES)), [0, 1], tau=0.0)


# ---- logistic mode ------------------------------------------


def _labelled_dataset(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < 0.15).astype(int)
    X = np.zeros((n, N_FUSION_FEATURES))
    for i in range(n):
        if y[i]:
            X[i] = _feat(graph_score=rng.normal(4.0, 1.0),
                         persistence=rng.uniform(0.4, 1.0),
                         neighbour_mean=rng.normal(2.0, 1.0),
                         is_green=float(rng.random() < 0.7))
        else:
            X[i] = _feat(graph_score=rng.normal(0.0, 1.0),
                         persistence=rng.uniform(0.0, 0.2),
                         neighbour_mean=rng.normal(0.0, 1.0),
                         is_green=float(rng.random() < 0.5))
    return X, y


def test_logistic_fusion_learns_a_usable_boundary():
    fl = FusionLayer(FusionConfig(mode="logistic", epochs=600))
    X, y = _labelled_dataset()
    stats = fl.fit(X, y, tau=1.0)
    assert stats["recall"] > 0.8
    assert stats["precision"] > 0.7
    # graph_score should carry a clearly positive weight
    assert stats["weights"]["graph_score"] > 0.3


def test_logistic_predict_proba_increases_with_graph_score():
    fl = FusionLayer(FusionConfig(mode="logistic", epochs=400))
    X, y = _labelled_dataset(seed=3)
    fl.fit(X, y, tau=1.0)
    lo = fl.probability(_feat(graph_score=0.0), tau=1.0)
    hi = fl.probability(_feat(graph_score=6.0), tau=1.0)
    assert hi > lo
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0


def test_logistic_fusion_roundtrips_through_json(tmp_path):
    fl = FusionLayer(FusionConfig(mode="logistic", epochs=200))
    X, y = _labelled_dataset(seed=5)
    fl.fit(X, y, tau=1.0)
    probe = np.stack([_feat(graph_score=g, persistence=0.5) for g in (-1.0, 2.0, 5.0)])
    before = fl.probability(probe, tau=1.0)

    p = tmp_path / "fusion.json"
    fl.save(p)
    back = FusionLayer.load(p)
    assert np.allclose(back.probability(probe, tau=1.0), before, atol=1e-9)


# ---- CandidateRaiser -------------------------------------


def test_raiser_needs_k_consecutive_ticks_over_threshold():
    r = CandidateRaiser(n_nodes=3, cfg=RaiserConfig(persistence_ticks=4, cooldown_ticks=100))
    prob = [0.9, 0.1, 0.1]
    gs = [5.0, 0.0, 0.0]
    for tick in range(1, 4):
        assert r.update(tick, prob, gs) == []          # 3 ticks -- not enough
    raised = r.update(4, prob, gs)                      # 4th consecutive -> fire
    assert len(raised) == 1
    assert raised[0].node_index == 0
    assert raised[0].first_over_tick == 1
    assert raised[0].graph_score == 5.0


def test_raiser_interruption_resets_the_streak():
    r = CandidateRaiser(n_nodes=1, cfg=RaiserConfig(persistence_ticks=3))
    r.update(1, [0.9], [4.0])
    r.update(2, [0.9], [4.0])
    r.update(3, [0.2], [0.0])          # dropped back under -> streak resets
    assert r.update(4, [0.9], [4.0]) == []
    assert r.update(5, [0.9], [4.0]) == []
    assert len(r.update(6, [0.9], [4.0])) == 1


def test_raiser_cooldown_suppresses_a_second_candidate_on_the_same_link():
    r = CandidateRaiser(n_nodes=1, cfg=RaiserConfig(persistence_ticks=2, cooldown_ticks=50,
                                                    clear_ticks=999))
    assert r.update(1, [0.9], [4.0]) == []
    assert len(r.update(2, [0.9], [4.0])) == 1          # 2nd consecutive tick -> fires
    for t in range(3, 45):
        assert r.update(t, [0.9], [4.0]) == []          # still in cooldown (until tick 52)


def test_raiser_recovery_clears_cooldown_early():
    r = CandidateRaiser(n_nodes=1, cfg=RaiserConfig(persistence_ticks=2, cooldown_ticks=500,
                                                    clear_ticks=5))
    r.update(1, [0.9], [4.0])
    assert len(r.update(2, [0.9], [4.0])) == 1          # fires at t=2, cooldown to 502
    for t in range(3, 12):
        r.update(t, [0.1], [0.0])                       # >= clear_ticks quiet -> cooldown lifted
    r.update(12, [0.9], [4.0])
    assert len(r.update(13, [0.9], [4.0])) == 1         # can fire again well before tick 502


def test_raiser_tracks_nodes_independently():
    r = CandidateRaiser(n_nodes=2, cfg=RaiserConfig(persistence_ticks=2, cooldown_ticks=100))
    r.update(1, [0.9, 0.1], [4.0, 0.0])
    raised = r.update(2, [0.9, 0.9], [4.0, 3.0])
    assert {c.node_index for c in raised} == {0}        # node 1 only has 1 tick so far
    raised2 = r.update(3, [0.1, 0.9], [0.0, 3.0])
    assert {c.node_index for c in raised2} == {1}


# ---- neighbour_mean_scores ------------------------------


def test_neighbour_mean_excludes_self():
    adj = [[0, 1, 2], [0, 1], [2]]  # adjacency_lists style (self included)
    gs = [10.0, 2.0, 4.0]
    nm = neighbour_mean_scores(gs, adj)
    assert nm[0] == pytest.approx((2.0 + 4.0) / 2)
    assert nm[1] == pytest.approx(10.0)
    assert nm[2] == pytest.approx(4.0)  # isolated -> its own score

"""`STGraphAutoencoder` / `GraphAnomalyDetector` / `EWMALinkDetector`.

Uses tiny synthetic "normal" traffic (smooth per-node sinusoids + noise) so
the model trains in a couple of seconds on CPU. The load-bearing test is
`test_detector_flags_the_node_with_an_injected_spike` -- after fitting on
normal data only, a window with a spike on one node must score that node far
above the rest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import numpy as np

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from sim_service.control.anomaly.detector import (  # noqa: E402
    ErrorNormalizer,
    EWMALinkDetector,
    GraphAnomalyDetector,
    ModelConfig,
    STGraphAutoencoder,
    TemporalConvNet,
    WindowBuffer,
)
from sim_service.control.anomaly.graph_features import (  # noqa: E402
    N_FEATURES,
    AnomalyGraph,
    FeatureNormalizer,
)

torch.manual_seed(0)
np.random.seed(0)

_N = 6


def _ring_graph(n: int = _N) -> AnomalyGraph:
    """A little directed ring with self loops -- enough topology for the GAT
    to have neighbours to attend to."""
    edges = [(i, (i + 1) % n) for i in range(n)] + [(i, i) for i in range(n)]
    etypes = ["downstream"] * n + ["self"] * n
    return AnomalyGraph(
        node_ids=tuple(f"J::L{i}" for i in range(n)),
        tls_of=("J",) * n,
        link_of=tuple(f"L{i}" for i in range(n)),
        approach_lane_of=tuple(f"lane_{i}" for i in range(n)),
        receiving_lane_of=(None,) * n,
        edge_index=tuple(edges),
        edge_type=tuple(etypes),
    )


def _tiny_cfg(n: int = _N) -> ModelConfig:
    return ModelConfig(
        n_nodes=n, window=6, d_model=8, n_heads=2,
        tcn_kernel=2, tcn_dilations=(1, 2), d_bottleneck=4, dropout=0.0,
    )


def _normal_run(t: int, n: int = _N, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    tt = np.arange(t)
    run = np.zeros((t, n, N_FEATURES), dtype=np.float32)
    for i in range(n):
        base = 0.5 + 0.4 * np.sin(2 * np.pi * (tt / 40.0) + i)
        for f in range(N_FEATURES):
            run[:, i, f] = base + 0.02 * rng.standard_normal(t)
    return run


# ---- model plumbing -------------------------------------------------


def test_forward_produces_the_expected_shapes():
    cfg = _tiny_cfg()
    model = STGraphAutoencoder(cfg)
    ei = GraphAnomalyDetector._build_edge_index(_ring_graph())
    x = torch.randn(3, cfg.window, _N, N_FEATURES)
    x_recon, x_next, z = model(x, ei)
    assert x_recon.shape == (3, cfg.window, _N, N_FEATURES)
    assert x_next.shape == (3, _N, N_FEATURES)
    assert z.shape == (3, _N, cfg.d_bottleneck)


def test_losses_returns_scalar_and_per_node_error():
    cfg = _tiny_cfg()
    model = STGraphAutoencoder(cfg)
    ei = GraphAnomalyDetector._build_edge_index(_ring_graph())
    x = torch.randn(4, cfg.window, _N, N_FEATURES)
    y = torch.randn(4, _N, N_FEATURES)
    loss, per_node = model.losses(x, y, ei)
    assert loss.ndim == 0
    assert per_node.shape == (4, _N)
    assert not per_node.requires_grad


def test_temporal_conv_is_causal():
    tcn = TemporalConvNet(channels=4, kernel=2, dilations=(1, 2), dropout=0.0)
    tcn.eval()
    x = torch.randn(2, 4, 10)
    y1 = tcn(x)
    x2 = x.clone()
    x2[..., 7:] += 5.0  # perturb only the last 3 timesteps
    y2 = tcn(x2)
    # outputs at t < 7 must be unchanged
    assert torch.allclose(y1[..., :7], y2[..., :7], atol=1e-5)
    assert not torch.allclose(y1[..., 7:], y2[..., 7:], atol=1e-5)


# ---- training + detection --------------------------------------


@pytest.fixture(scope="module")
def fitted_detector():
    graph = _ring_graph()
    cfg = _tiny_cfg()
    train_runs = [_normal_run(240, seed=s) for s in (1, 2, 3)]
    val_runs = [_normal_run(160, seed=s) for s in (10, 11)]
    fn = FeatureNormalizer.fit([r.reshape(-1, N_FEATURES).tolist() for r in train_runs])
    det = GraphAnomalyDetector(graph, cfg, fn)
    report = det.fit(train_runs, val_runs, epochs=25, lr=3e-3, batch_size=32, patience=8)
    return det, report


def test_training_reduces_validation_loss(fitted_detector):
    _, report = fitted_detector
    assert report.val_loss[-1] < report.val_loss[0] * 0.7
    assert report.best_val_loss <= min(report.val_loss)


def test_error_normalizer_is_fitted_during_training(fitted_detector):
    det, _ = fitted_detector
    assert det.error_normalizer is not None
    assert len(det.error_normalizer.mean) == _N


def test_score_on_normal_data_is_near_zero(fitted_detector):
    det, _ = fitted_detector
    run = _normal_run(120, seed=99)
    window = run[-det.cfg.window :]
    scores = det.score(window)
    assert len(scores) == _N
    assert max(abs(s) for s in scores) < 6.0  # normal traffic stays in-distribution


def test_detector_flags_the_node_with_an_injected_spike(fitted_detector):
    det, _ = fitted_detector
    run = _normal_run(120, seed=7)
    window = run[-det.cfg.window :].copy()
    target = 2
    window[-3:, target, :] += 4.0  # a sustained anomaly on one node's features
    scores = det.score(window)
    others = [s for i, s in enumerate(scores) if i != target]
    assert scores[target] > max(others) + 2.0
    assert scores[target] > 3.0


def test_detector_version_is_stable_and_weight_dependent(fitted_detector):
    det, _ = fitted_detector
    v1 = det.detector_version
    assert v1 == det.detector_version
    assert v1.startswith("graph-ae@")
    with torch.no_grad():
        next(iter(det.model.parameters())).add_(1.0)
    assert det.detector_version != v1


def test_save_and_load_roundtrip_preserves_scores(fitted_detector, tmp_path):
    det, _ = fitted_detector
    run = _normal_run(80, seed=5)
    window = run[-det.cfg.window :].copy()
    window[-2:, 4, :] += 3.0
    before = det.score(window)

    det.save(tmp_path / "m6")
    reloaded = GraphAnomalyDetector.load(tmp_path / "m6", _ring_graph())
    after = reloaded.score(window)
    assert np.allclose(before, after, atol=1e-4)


def test_load_rejects_a_topology_mismatch(fitted_detector, tmp_path):
    det, _ = fitted_detector
    det.save(tmp_path / "m6b")
    wrong = _ring_graph(n=_N + 1)
    with pytest.raises(ValueError):
        GraphAnomalyDetector.load(tmp_path / "m6b", wrong)


# ---- ErrorNormalizer / WindowBuffer -------------------------


def test_error_normalizer_zscores_and_roundtrips():
    errs = np.abs(np.random.default_rng(0).standard_normal((200, 4))) + 0.1
    norm = ErrorNormalizer.fit(errs)
    z = norm.z(norm.mean)
    assert all(abs(v) < 1e-9 for v in z)
    back = ErrorNormalizer.from_json(norm.to_json())
    assert back.mean == norm.mean and back.std == norm.std


def test_error_normalizer_rejects_bad_shape():
    with pytest.raises(ValueError):
        ErrorNormalizer.fit(np.zeros((0, 4)))


def test_window_buffer_fills_and_emits_a_stacked_array():
    buf = WindowBuffer(window=4, n_nodes=_N)
    assert not buf.ready
    for _ in range(3):
        buf.push(np.zeros((_N, N_FEATURES)))
    assert not buf.ready
    buf.push(np.ones((_N, N_FEATURES)))
    assert buf.ready
    arr = buf.array()
    assert arr.shape == (4, _N, N_FEATURES)
    assert (arr[-1] == 1.0).all()
    # ring drops the oldest
    buf.push(np.full((_N, N_FEATURES), 2.0))
    assert (buf.array()[-1] == 2.0).all()
    assert buf.array().shape == (4, _N, N_FEATURES)


def test_window_buffer_rejects_a_wrong_shaped_frame():
    buf = WindowBuffer(window=3, n_nodes=_N)
    with pytest.raises(ValueError):
        buf.push(np.zeros((_N + 1, N_FEATURES)))


# ---- EWMA baseline -------------------------------------------


def test_ewma_baseline_is_silent_during_warmup_then_flags_a_spike():
    det = EWMALinkDetector(n_nodes=_N, alpha=0.05, warmup=30)
    rng = np.random.default_rng(0)
    for _ in range(30):
        frame = 0.3 + 0.02 * rng.standard_normal((_N, N_FEATURES))
        assert det.score(frame[None]) == [0.0] * _N

    calm = 0.3 + 0.02 * rng.standard_normal((_N, N_FEATURES))
    for _ in range(20):
        det.score(calm[None])

    spike = (0.3 + 0.02 * rng.standard_normal((_N, N_FEATURES))).astype(float)
    spike[3, 0] += 3.0        # queue_pcu spike on node 3
    scores = det.score(spike[None])
    assert scores[3] > 5.0
    assert scores[3] > max(s for i, s in enumerate(scores) if i != 3)


def test_ewma_baseline_saves_and_loads(tmp_path):
    det = EWMALinkDetector(n_nodes=_N, alpha=0.03, warmup=10)
    rng = np.random.default_rng(1)
    for _ in range(25):
        det.score((0.4 + 0.05 * rng.standard_normal((_N, N_FEATURES)))[None])
    det.save(tmp_path / "base")
    back = EWMALinkDetector.load(tmp_path / "base")
    assert back.alpha == 0.03
    probe = np.full((_N, N_FEATURES), 0.4)
    assert np.allclose(back.score(probe[None]), det.score(probe[None]), atol=1e-9)

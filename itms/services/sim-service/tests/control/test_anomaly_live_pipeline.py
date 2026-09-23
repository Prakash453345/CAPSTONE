"""`LiveIncidentDetector`'s full pipeline, with a real (tiny, briefly-fitted)
detector -- needs the optional `[anomaly]` extra, same as
`test_anomaly_detector.py`. Not an accuracy test (that's
`scripts/m6_incident_injection_gate.py`'s job on the real corridor); this
only proves the wiring end to end: a sustained spike on one node's features
must turn into a published `IncidentCandidate` event with the right fields.
See `test_anomaly_live.py` for the always-on graceful-degradation tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import numpy as np

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from itms_common.events import decode_envelope  # noqa: E402
from sim_service.control.anomaly.detector import (  # noqa: E402
    GraphAnomalyDetector,
    ModelConfig,
)
from sim_service.control.anomaly.graph_features import (  # noqa: E402
    N_FEATURES,
    AnomalyGraph,
    FeatureNormalizer,
)
from sim_service.control.anomaly.live import LiveIncidentDetector  # noqa: E402

torch.manual_seed(0)
np.random.seed(0)

_N = 5


class _FakeBus:
    def __init__(self):
        self.published: list[tuple[str, bytes]] = []

    def publish(self, topic: str, raw: bytes) -> str:
        self.published.append((topic, raw))
        return f"id-{len(self.published)}"


def _ring_graph(n: int = _N) -> AnomalyGraph:
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
        n_nodes=n, window=4, d_model=8, n_heads=2,
        tcn_kernel=2, tcn_dilations=(1, 2), d_bottleneck=4, dropout=0.0,
    )


def _normal_run(t: int, n: int = _N, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    tt = np.arange(t)
    run = np.zeros((t, n, N_FEATURES), dtype=np.float32)
    for i in range(n):
        base = 0.5 + 0.3 * np.sin(2 * np.pi * (tt / 30.0) + i)
        for f in range(N_FEATURES):
            run[:, i, f] = base + 0.02 * rng.standard_normal(t)
    return run


@pytest.fixture(scope="module")
def artifacts_dir(tmp_path_factory):
    """A tiny, briefly-fitted detector saved under detector/, plus a handful
    of held-out normal feature runs under features/val/ -- exactly the
    layout scripts/m6_record_features.py + scripts/m6_train_detector.py
    produce, minus the real corridor's size and training budget."""
    art = tmp_path_factory.mktemp("m6_artifacts")
    graph = _ring_graph()
    cfg = _tiny_cfg()

    train_runs = [_normal_run(150, seed=s) for s in (1, 2, 3)]
    val_runs = [_normal_run(150, seed=s) for s in (10, 11)]
    fn = FeatureNormalizer.fit([r.reshape(-1, N_FEATURES).tolist() for r in train_runs])
    det = GraphAnomalyDetector(graph, cfg, fn)
    det.fit(train_runs, val_runs, epochs=15, lr=3e-3, batch_size=32, patience=8)
    det.save(art / "detector")

    val_dir = art / "features" / "val"
    val_dir.mkdir(parents=True)
    for i, seed in enumerate((20, 21, 22, 23)):
        np.save(val_dir / f"medium_seed{i}.npy", _normal_run(300, seed=seed))

    return art, graph


def test_live_detector_loads_when_artifacts_exist(artifacts_dir):
    art, graph = artifacts_dir
    live = LiveIncidentDetector(graph, _FakeBus(), artifacts_dir=art, alpha=0.2)
    assert live.available is True, live.unavailable_reason
    assert live.conformal is not None
    stats = live.stats()
    assert stats["available"] == 1.0


def test_sustained_spike_raises_and_publishes_a_candidate(artifacts_dir):
    from sim_service.control.anomaly.fusion import RaiserConfig

    art, graph = artifacts_dir
    bus = _FakeBus()
    live = LiveIncidentDetector(
        graph, bus, artifacts_dir=art, alpha=0.2,
        raiser_cfg=RaiserConfig(persistence_ticks=3, cooldown_ticks=1000, clear_ticks=5),
    )
    assert live.available is True, live.unavailable_reason

    target = 2
    step = 0
    # fill the window buffer on normal traffic first
    for frame in _normal_run(live.detector.cfg.window, seed=99):
        live.on_tick(step, float(step), frame.tolist())
        step += 1
    # then hold a large, sustained spike on one node's features
    for _ in range(10):
        frame = _normal_run(1, seed=99)[0]
        frame[target, :] += 6.0
        live.on_tick(step, float(step), frame.tolist())
        step += 1

    # Which exact node ends up flagged is model-dependent noise on a tiny,
    # briefly-fitted network (a spike propagates through the graph message
    # passing to the spiked node's neighbours too -- see the module
    # docstring's "a real incident lifts a node's neighbours too") --
    # this is a wiring test, not an accuracy test, so it checks the
    # candidate is well-formed and self-consistent rather than pinned to
    # `target` specifically.
    assert live.candidates_raised >= 1
    assert bus.published, "expected at least one published event"
    topic, raw = bus.published[0]
    assert topic == "incident.candidate"
    envelope = decode_envelope(raw)
    assert envelope["event_type"] == "IncidentCandidate"
    payload = envelope["payload"]
    node = graph.index_of(payload["intersection_id"], payload["link_id"])
    assert 0 <= node < graph.num_nodes
    assert payload["fused_probability"] >= 0.5
    assert payload["graph_score"] > payload["threshold_tau"]
    assert payload["detector_version"].startswith("graph-ae@")
    assert "/conformal@" in payload["detector_version"]

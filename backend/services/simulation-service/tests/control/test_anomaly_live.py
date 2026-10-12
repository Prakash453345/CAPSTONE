"""`LiveIncidentDetector`'s graceful-degradation contract -- no numpy/torch
needed, so this runs under plain `make test`/`test-fast` (unlike the model
itself). See `test_anomaly_live_pipeline.py` for the full, [anomaly]-extra
pipeline test that actually raises and publishes a candidate.
"""

from __future__ import annotations

from sim_service.control.anomaly.graph_features import N_FEATURES, AnomalyGraph
from sim_service.control.anomaly.live import LiveIncidentDetector

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


def test_unavailable_when_no_model_is_present(tmp_path):
    """Whatever the reason -- extra not installed, or (when it is) no
    detector/ dir or no val features under an empty artifacts_dir -- the
    detector must come up disabled rather than raise, with a human-readable
    explanation."""
    graph = _ring_graph()
    bus = _FakeBus()
    live = LiveIncidentDetector(graph, bus, artifacts_dir=tmp_path)
    assert live.available is False
    assert live.unavailable_reason  # non-empty, explains why


def test_on_tick_is_a_safe_no_op_when_unavailable(tmp_path):
    graph = _ring_graph()
    bus = _FakeBus()
    live = LiveIncidentDetector(graph, bus, artifacts_dir=tmp_path)
    for step in range(20):
        live.on_tick(step, float(step), [[0.0] * N_FEATURES for _ in range(_N)])
    assert live.ticks_scored == 0
    assert live.candidates_raised == 0
    assert bus.published == []


def test_stats_reports_unavailable(tmp_path):
    graph = _ring_graph()
    live = LiveIncidentDetector(graph, _FakeBus(), artifacts_dir=tmp_path)
    stats = live.stats()
    assert stats["available"] == 0.0
    assert stats["candidates_raised"] == 0.0

"""Shared harness for the M6 incident-injection gate: "run one scenario with
a detector live and incidents injected, then score detections against the
exact ground-truth windows." One definition, so the gate and any diagnostic
script agree on it (same discipline as scripts/m5_harness.py).

Seed discipline: the incident schedule seed and the SUMO traffic seed are the
same number, so an arm's runs are reproducible and comparable across arms.
The detector was trained on the disjoint TRAIN band (see m6_record_features).

Not a pytest target -- real SUMO, and needs the `[anomaly]` extra.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import numpy as np
from sim_service.control.anomaly.calibration import ConformalCalibrator
from sim_service.control.anomaly.detector import (
    EWMALinkDetector,
    GraphAnomalyDetector,
    WindowBuffer,
)
from sim_service.control.anomaly.fusion import (
    CandidateRaiser,
    FusionLayer,
    RaiserConfig,
    neighbour_mean_scores,
)
from sim_service.control.anomaly.graph_features import N_FEATURES, AnomalyGraph
from sim_service.control.anomaly.injector import IncidentInjector, random_schedule
from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import webster
from sim_service.signal_controller.queue_state import load_vtype_pcu

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402

_NET = _ROOT / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_DEMAND = _ROOT / "scenarios" / "demand" / "vijayawada"
_ART = _ROOT / "scripts" / "results" / "m6_artifacts"

EVAL_SEEDS = list(range(1, 11))
MAX_STEPS = 6000
N_INCIDENTS = 6
LATENCY_GRACE_S = 45         # a detection this long after a window closes still counts
GATE_RECALL = 0.90
GATE_LATENCY_S = 30.0


@dataclass
class RunResult:
    arm: str
    level: str
    seed: int
    n_nodes: int = 1
    n_incidents: int = 0
    detected: int = 0
    latencies_s: list[float] = field(default_factory=list)
    localized: int = 0
    false_alarms: int = 0          # raised candidates not tied to an injected window
    raw_over_threshold: int = 0    # per (node, tick) fused_probability >= 0.5 crossings
    ticks_scored: int = 0
    candidates: int = 0

    @property
    def recall(self) -> float:
        return self.detected / self.n_incidents if self.n_incidents else 0.0

    @property
    def mean_latency_s(self) -> float:
        return float(np.mean(self.latencies_s)) if self.latencies_s else float("nan")

    @property
    def raw_fpr(self) -> float:
        """Per (node, tick) crossing rate -- the quantity conformal bounds at
        alpha (plan 11, "empirical false-positive rate on that set")."""
        denom = self.ticks_scored * self.n_nodes
        return self.raw_over_threshold / denom if denom else 0.0

    @property
    def candidate_fpr(self) -> float:
        """Fraction of scored ticks that produced a spurious candidate -- the
        operational false-alarm load an operator actually sees."""
        return self.false_alarms / self.ticks_scored if self.ticks_scored else 0.0


def _scenario_paths(level: str) -> tuple[Path, Path]:
    suffix = "" if level == "medium" else f"_{level}"
    return (_DEMAND / f"vijayawada_corridor{suffix}.sumocfg",
            _DEMAND / f"vijayawada_corridor{suffix}.rou.xml")


def _webster_strategy(configs, flows):
    return {
        tls: partial(webster.propose, timing=webster.compute_timing(cfg, flows.get(tls, {})))
        for tls, cfg in configs.items()
    }


class _Scorer:
    """Consumes the per-tick feature matrix, runs detector -> fusion -> raiser,
    and records every raised candidate as `(node_index, sim_tick, graph_score)`."""

    def __init__(self, arm, graph, detector, fusion, conformal, raiser_cfg):
        self.arm = arm
        self.graph = graph
        self.detector = detector
        self.fusion = fusion
        self.conformal = conformal
        self.adj = graph.adjacency_lists()
        self.window = getattr(detector, "warmup_windows", 1)
        self.buf = WindowBuffer(self.window, graph.num_nodes)
        self.raiser = CandidateRaiser(graph.num_nodes, cfg=raiser_cfg)
        self.raised: list[tuple[int, int, float]] = []
        self.ticks_scored = 0
        self.raw_over = 0

    def on_tick(self, step: int, _sim_time: float, matrix: list[list[float]]) -> None:
        self.buf.push(matrix)
        if not self.buf.ready:
            return
        win = self.buf.array()
        gs = self.detector.score(win)                      # per-node graph_score
        tau = self.conformal.tau
        nb = neighbour_mean_scores(gs, self.adj)
        last = win[-1]
        feats = np.zeros((self.graph.num_nodes, 5))
        feats[:, 0] = gs
        feats[:, 2] = nb
        feats[:, 3] = last[:, 6]                           # is_green feature index
        fused = self.fusion.probability(feats, tau)
        self.ticks_scored += 1
        self.raw_over += int((fused >= 0.5).sum())
        for c in self.raiser.update(step, fused.tolist(), list(gs)):
            self.raised.append((c.node_index, c.sim_tick, c.graph_score))


def run_incident_scenario(
    arm: str,
    level: str,
    seed: int,
    *,
    graph: AnomalyGraph,
    detector,
    fusion: FusionLayer,
    conformal: ConformalCalibrator,
    raiser_cfg: RaiserConfig,
    inject: bool = True,
) -> RunResult:
    sumocfg, route = _scenario_paths(level)
    configs = load_configs(_NET)
    flows = compute_link_flows(_NET, route)
    vtype_pcu = load_vtype_pcu(route)
    link_lanes = link_to_lane_map(_NET)
    receiving_lanes = link_to_receiving_lane_map(_NET)

    injector = None
    if inject:
        lanes = sorted({ln for links in link_lanes.values() for ln in links.values()})
        schedule = random_schedule(
            lanes, seed=seed, n_incidents=N_INCIDENTS, run_ticks=MAX_STEPS,
            warmup_ticks=400, cooldown_ticks=300, min_gap_ticks=200,
        )
        injector = IncidentInjector(schedule, link_lanes=link_lanes)

    scorer = _Scorer(arm, graph, detector, fusion, conformal, raiser_cfg)
    run_controlled_scenario(
        str(sumocfg), configs,
        strategy=_webster_strategy(configs, flows),
        seed=seed, link_lanes=link_lanes, receiving_lanes=receiving_lanes,
        vtype_pcu=vtype_pcu, max_steps=MAX_STEPS,
        incident_injector=injector,
        anomaly_graph=graph, anomaly_feature_sink=scorer.on_tick,
    )

    res = RunResult(
        arm=arm, level=level, seed=seed, n_nodes=graph.num_nodes,
        ticks_scored=scorer.ticks_scored, candidates=len(scorer.raised),
        raw_over_threshold=scorer.raw_over,
    )
    if not inject:
        res.false_alarms = len(scorer.raised)
        return res

    assert injector is not None
    windows = injector.realised_windows()
    res.n_incidents = len(windows)
    link_index = {}
    for i in range(graph.num_nodes):
        link_index.setdefault((graph.tls_of[i], graph.link_of[i]), i)

    matched_candidate_ids: set[int] = set()
    for w in windows:
        target_nodes = {
            link_index[(w.intersection_id, lk)]
            for lk in w.link_ids
            if (w.intersection_id, lk) in link_index
        }
        end = (w.end_tick or MAX_STEPS) + LATENCY_GRACE_S
        best: tuple[float, int] | None = None
        for cid, (node, tick, _score) in enumerate(scorer.raised):
            if w.actual_start_tick <= tick <= end and node in target_nodes:
                lat = tick - w.actual_start_tick
                if best is None or lat < best[0]:
                    best = (lat, cid)
        if best is not None:
            res.detected += 1
            res.localized += 1
            res.latencies_s.append(float(best[0]))
            matched_candidate_ids.add(best[1])

    # any raised candidate not tied to an injected window is a false alarm
    for cid, (_node, tick, _score) in enumerate(scorer.raised):
        if cid in matched_candidate_ids:
            continue
        inside_any = any(
            w.actual_start_tick <= tick <= (w.end_tick or MAX_STEPS) + LATENCY_GRACE_S
            for w in windows
        )
        if not inside_any:
            res.false_alarms += 1
    return res


def load_detector(arm: str, graph: AnomalyGraph):
    if arm == "ewma":
        return EWMALinkDetector(graph.num_nodes)
    return GraphAnomalyDetector.load(_ART / "detector", graph)


def calibrate_from_val_features(arm: str, graph: AnomalyGraph, detector, alpha: float):
    """Fit the conformal threshold on the recorded VAL normal-traffic feature
    runs -- every (tick, node) score, scored by this arm's detector. The
    gate's own injected runs are never used for calibration.

    The calibration window is sized to hold the whole VAL set so tau is the
    quantile of the full held-out normal distribution, not a recent tail."""
    from sim_service.control.anomaly.calibration import ConformalConfig

    val_dir = _ART / "features" / "val"
    window = getattr(detector, "warmup_windows", 1)
    scores: list[float] = []
    for p in sorted(val_dir.glob("*.npy")):
        run = np.load(p).astype(np.float32)
        if run.shape[1:] != (graph.num_nodes, N_FEATURES):
            continue
        buf = WindowBuffer(window, graph.num_nodes)
        for frame in run:
            buf.push(frame)
            if buf.ready:
                scores.extend(detector.score(buf.array()))
    cal = ConformalCalibrator(
        ConformalConfig(alpha=alpha, min_points=200, window=max(20_000, len(scores)))
    )
    cal.fit(scores)
    return cal

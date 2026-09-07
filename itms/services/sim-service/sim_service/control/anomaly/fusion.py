"""The interpretable fusion layer and the candidate-raising policy -- plan
sections 5 and 9.

`FusionLayer` turns the graph detector's per-node `graph_score` (and, from
M8, a vision-rule score) plus a few engineered context signals into one
`fused_probability` in [0, 1]. Deliberately shallow -- a monotone squashing
by default, or a small numpy logistic regression when incident-labelled data
exists -- because a deep fusion net would break the platform's audit
principle (plan 9: "a deep fusion net would break the project's own audit
principle"). It degrades exactly to graph-only when `vision_score` is absent.

`CandidateRaiser` is the "detect -> candidate" gate that sits on top: a node
must stay above the conformal threshold for K consecutive ticks before a
candidate is raised (plan 5, "holds a live lane past threshold"), with a
per-link cooldown so one incident produces one candidate, not a stream.

numpy only -- no torch.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# The engineered signals the fusion layer reads, in order. Append-only.
FUSION_FEATURES: tuple[str, ...] = (
    "graph_score",       # z-scored per-node reconstruction error from the detector
    "persistence",       # fraction of the last K ticks this node was above threshold
    "neighbour_mean",    # mean graph_score over this node's graph neighbours
    "is_green",          # 1.0 if the link's movement is green -- a green-phase stop
                         # is the real signal, a red-phase queue is lawful (pillar 4.3)
    "vision_score",      # deterministic vision-rule score; 0.0 until M8
)
N_FUSION_FEATURES = len(FUSION_FEATURES)


@dataclass
class FusionConfig:
    mode: str = "monotone"        # "monotone" | "logistic"
    gain: float = 1.4             # monotone: slope of the sigmoid in graph_score units
    vision_weight: float = 2.0    # monotone: how much a vision score adds pre-sigmoid
    l2: float = 1e-3              # logistic: ridge penalty
    lr: float = 0.1              # logistic: gradient-descent step
    epochs: int = 400            # logistic: gradient-descent iterations

    def __post_init__(self) -> None:
        if self.mode not in ("monotone", "logistic"):
            raise ValueError(f"unknown fusion mode {self.mode!r}")


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))


class FusionLayer:
    """`probability(features, tau)` maps an `[..., N_FUSION_FEATURES]` array to
    `fused_probability` in [0, 1].

    In `monotone` mode (the default, no training): `sigmoid(gain * (graph_score
    - tau) + vision_weight * vision_score)`. So with no vision the alert rule
    `fused_probability >= 0.5` is exactly `graph_score >= tau` -- the conformal
    threshold is the decision boundary, and fusion adds nothing spurious.

    In `logistic` mode: a plain logistic regression over all FUSION_FEATURES,
    fitted on injector-labelled windows (the gate provides them, with the
    train/eval seed split kept). `tau` still centres the graph_score feature so
    the fitted model and the conformal layer stay aligned.
    """

    def __init__(self, cfg: FusionConfig | None = None):
        self.cfg = cfg or FusionConfig()
        self.weights: np.ndarray | None = None   # [N_FUSION_FEATURES]
        self.bias: float = 0.0
        self._feat_mean: np.ndarray | None = None
        self._feat_std: np.ndarray | None = None

    # ---- inference --------------------------------------------------

    def probability(self, features: np.ndarray, tau: float) -> np.ndarray:
        f = np.asarray(features, dtype=np.float64)
        if f.shape[-1] != N_FUSION_FEATURES:
            raise ValueError(f"features last dim {f.shape[-1]} != {N_FUSION_FEATURES}")
        gs = f[..., 0] - (tau if math.isfinite(tau) else 0.0)  # centre graph_score on tau
        vis = f[..., FUSION_FEATURES.index("vision_score")]

        if self.cfg.mode == "monotone" or self.weights is None:
            z = self.cfg.gain * gs + self.cfg.vision_weight * vis
            return _sigmoid(z)

        centred = f.copy()
        centred[..., 0] = gs
        std = (centred - self._feat_mean) / self._feat_std
        return _sigmoid(std @ self.weights + self.bias)

    # ---- training (logistic mode) ------------------------------

    def fit(self, features: np.ndarray, labels: Sequence[int], tau: float) -> dict:
        """Fit the logistic regression. `features`: `[S, N_FUSION_FEATURES]`,
        `labels`: 1 inside an injected-incident window, else 0. `tau` centres
        the graph_score column exactly as inference does."""
        if self.cfg.mode != "logistic":
            raise RuntimeError("fit() is only valid in logistic mode")
        x = np.asarray(features, dtype=np.float64).copy()
        y = np.asarray(labels, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != N_FUSION_FEATURES or x.shape[0] != y.shape[0]:
            raise ValueError("features must be [S, N_FUSION_FEATURES] aligned with labels")
        x[:, 0] = x[:, 0] - (tau if math.isfinite(tau) else 0.0)

        self._feat_mean = x.mean(axis=0)
        self._feat_std = np.maximum(1e-9, x.std(axis=0))
        xs = (x - self._feat_mean) / self._feat_std

        w = np.zeros(N_FUSION_FEATURES)
        b = 0.0
        n = len(y)
        pos = max(1.0, y.sum())
        neg = max(1.0, n - y.sum())
        sw = np.where(y > 0.5, n / (2 * pos), n / (2 * neg))  # balance rare positives
        for _ in range(self.cfg.epochs):
            p = _sigmoid(xs @ w + b)
            g = (p - y) * sw
            gw = xs.T @ g / n + self.cfg.l2 * w
            gb = g.mean()
            w -= self.cfg.lr * gw
            b -= self.cfg.lr * gb
        self.weights = w
        self.bias = float(b)

        p = self.probability(np.asarray(features, dtype=np.float64), tau)
        pred = (p >= 0.5).astype(int)
        tp = int(((pred == 1) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        return {
            "n": n,
            "positives": int(y.sum()),
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "weights": dict(zip(FUSION_FEATURES, w.tolist(), strict=True)),
            "bias": self.bias,
        }

    # ---- persistence ---------------------------------------

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(
                {
                    "cfg": vars(self.cfg),
                    "feature_names": list(FUSION_FEATURES),
                    "weights": None if self.weights is None else self.weights.tolist(),
                    "bias": self.bias,
                    "feat_mean": None if self._feat_mean is None else self._feat_mean.tolist(),
                    "feat_std": None if self._feat_std is None else self._feat_std.tolist(),
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, path: str | Path) -> FusionLayer:
        raw = json.loads(Path(path).read_text())
        if raw.get("feature_names") != list(FUSION_FEATURES):
            raise ValueError("fusion layer fitted against a different FUSION_FEATURES")
        obj = cls(FusionConfig(**raw["cfg"]))
        obj.weights = None if raw["weights"] is None else np.asarray(raw["weights"])
        obj.bias = raw["bias"]
        obj._feat_mean = None if raw["feat_mean"] is None else np.asarray(raw["feat_mean"])
        obj._feat_std = None if raw["feat_std"] is None else np.asarray(raw["feat_std"])
        return obj


# ---------------------------------------------------------------------------
# candidate-raising policy
# ---------------------------------------------------------------------------


@dataclass
class RaiserConfig:
    persistence_ticks: int = 5     # consecutive ticks over tau before a candidate
    cooldown_ticks: int = 240      # after raising on a link, silence it this long
    clear_ticks: int = 10          # consecutive ticks back under tau to end the cooldown early


@dataclass
class RaisedCandidate:
    node_index: int
    sim_tick: int
    first_over_tick: int
    fused_probability: float
    graph_score: float


@dataclass
class CandidateRaiser:
    """Per-node state machine: NORMAL -> (K consecutive ticks over tau) ->
    RAISED (emits one candidate) -> COOLDOWN -> NORMAL. One candidate per
    incident, not one per tick."""

    n_nodes: int
    cfg: RaiserConfig = field(default_factory=RaiserConfig)
    _over: np.ndarray = field(init=False)
    _under: np.ndarray = field(init=False)
    _cooldown_until: np.ndarray = field(init=False)
    _first_over: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self._over = np.zeros(self.n_nodes, dtype=np.int64)
        self._under = np.zeros(self.n_nodes, dtype=np.int64)
        self._cooldown_until = np.full(self.n_nodes, -1, dtype=np.int64)
        self._first_over = np.full(self.n_nodes, -1, dtype=np.int64)

    def update(
        self,
        sim_tick: int,
        fused_probability: Sequence[float],
        graph_score: Sequence[float],
        *,
        prob_threshold: float = 0.5,
    ) -> list[RaisedCandidate]:
        """Feed one tick. Returns the candidates that became RAISED this tick
        (usually none). `prob_threshold` is the fused-probability cutoff --
        0.5 in monotone mode is exactly `graph_score >= tau`."""
        p = np.asarray(fused_probability, dtype=np.float64)
        gs = np.asarray(graph_score, dtype=np.float64)
        over = p >= prob_threshold

        self._over = np.where(over, self._over + 1, 0)
        self._under = np.where(over, 0, self._under + 1)
        self._first_over = np.where(
            (self._over == 1), sim_tick, self._first_over
        )

        # release cooldown early if the link has been quiet long enough
        recovered = self._under >= self.cfg.clear_ticks
        self._cooldown_until = np.where(recovered, -1, self._cooldown_until)

        in_cooldown = sim_tick < self._cooldown_until
        fires = (self._over >= self.cfg.persistence_ticks) & ~in_cooldown

        raised: list[RaisedCandidate] = []
        for i in np.nonzero(fires)[0]:
            raised.append(
                RaisedCandidate(
                    node_index=int(i),
                    sim_tick=sim_tick,
                    first_over_tick=int(self._first_over[i]),
                    fused_probability=float(p[i]),
                    graph_score=float(gs[i]),
                )
            )
            self._cooldown_until[i] = sim_tick + self.cfg.cooldown_ticks
            self._over[i] = 0
        return raised


def neighbour_mean_scores(
    graph_score: Sequence[float], adjacency: Sequence[Sequence[int]]
) -> list[float]:
    """Mean `graph_score` over each node's graph neighbours (self excluded).
    `adjacency[i]` is the list of source indices with an edge into `i`, from
    `AnomalyGraph.adjacency_lists()`. A real incident lifts a node's
    neighbours too; a lone-node detector glitch does not."""
    gs = np.asarray(graph_score, dtype=np.float64)
    out: list[float] = []
    for i, srcs in enumerate(adjacency):
        nb = [s for s in srcs if s != i]
        out.append(float(gs[nb].mean()) if nb else float(gs[i]))
    return out

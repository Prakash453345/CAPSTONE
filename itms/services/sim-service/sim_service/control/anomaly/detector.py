"""The pattern / graph anomaly detector -- plan section 6.1 and the model
table in section 9.

`STGraphAutoencoder` is a spatiotemporal graph autoencoder: GATv2 spatial
attention over the corridor graph, interleaved with a dilated causal temporal
convolution (a "mirror TCN" -- the decoder undoes the encoder's compression
step for step), trained unsupervised to reconstruct a window of normal
per-link features and to forecast the next tick. At inference the per-node
reconstruction+forecast error, z-scored against that node's own error
distribution on normal traffic, is `graph_score` -- localized to one link,
which is what later lets it line up with a camera.

`GraphAnomalyDetector` wraps the model with the two normalizers, training,
scoring, and save/load. `EWMALinkDetector` is the deliberately-simple baseline
the gate makes the graph model beat (plan 6.1: "prove the GNN actually
helps"): a per-link EWMA / z-score with no graph structure at all, same
`score(window)` interface.

torch + numpy live here and nowhere else in the control tree -- install with
`pip install -e 'services/sim-service[anomaly]'`. `graph_features.py` and
`injector.py` stay dependency-free so the SUMO tick loop pays nothing for
them.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch import nn

from sim_service.control.anomaly.graph_features import (
    N_FEATURES,
    AnomalyGraph,
    FeatureNormalizer,
)

# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------


@dataclass
class ModelConfig:
    n_nodes: int
    n_features: int = N_FEATURES
    window: int = 10          # ticks of history the encoder sees
    d_model: int = 32
    n_heads: int = 4
    tcn_kernel: int = 3
    tcn_dilations: tuple[int, ...] = (1, 2, 4)
    d_bottleneck: int = 16
    forecast_weight: float = 0.5   # lambda on the one-step-ahead term
    dropout: float = 0.05


class GATv2Layer(nn.Module):
    """Edge-sparse GATv2 (Brody et al. 2022). Messages and attention logits
    are formed only for the edges that exist (~940 for this corridor, vs an
    N*N=5329 dense tensor), gathered/scattered by index -- so it stays cheap
    on CPU here and scales to a city-size graph without an N*N blow-up.
    No torch_geometric dependency; the scatter is plain `index_add_`.

    `edge_index` is `[2, E]` long: row 0 = source node j, row 1 = target node
    i (message flows j -> i). Self-loops must already be present as edges."""

    def __init__(self, d_in: int, d_out: int, n_heads: int, dropout: float):
        super().__init__()
        assert d_out % n_heads == 0
        self.n_heads = n_heads
        self.d_head = d_out // n_heads
        self.lin_l = nn.Linear(d_in, d_out)   # target i
        self.lin_r = nn.Linear(d_in, d_out)   # source j
        self.att = nn.Parameter(torch.empty(n_heads, self.d_head))
        self.leaky = nn.LeakyReLU(0.2)
        self.drop = nn.Dropout(dropout)
        self.proj = nn.Linear(d_out, d_out)
        self.norm = nn.LayerNorm(d_out)
        nn.init.xavier_uniform_(self.att)

    def forward(self, h: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        # h: [B, N, d_in]
        b, n, _ = h.shape
        src, dst = edge_index[0], edge_index[1]                    # [E], [E]
        e = src.numel()
        hl = self.lin_l(h).view(b, n, self.n_heads, self.d_head)
        hr = self.lin_r(h).view(b, n, self.n_heads, self.d_head)

        m_src = hr[:, src]                                         # [B, E, H, d_head]
        m_dst = hl[:, dst]
        logits = (self.leaky(m_src + m_dst) * self.att).sum(-1)    # [B, E, H]

        # softmax over the incoming edges of each target node
        logits = logits - logits.amax(dim=1, keepdim=True)         # stability
        ex = logits.exp()
        denom = h.new_zeros(b, n, self.n_heads).index_add_(
            1, dst, ex
        )[:, dst]                                                  # [B, E, H]
        alpha = self.drop(ex / (denom + 1e-16))

        msg = (alpha.unsqueeze(-1) * m_src).reshape(b, e, -1)      # [B, E, d_out]
        agg = h.new_zeros(b, n, self.n_heads * self.d_head).index_add_(1, dst, msg)
        return self.norm(self.proj(agg) + self.lin_l(h))


class TemporalConvNet(nn.Module):
    """Stack of causal dilated 1-D convs applied per node along time. Causal =
    left-padded then right-trimmed, so a tick is never reconstructed using its
    own future."""

    def __init__(self, channels: int, kernel: int, dilations: Sequence[int], dropout: float):
        super().__init__()
        self.convs = nn.ModuleList(
            nn.Conv1d(channels, channels, kernel, dilation=d) for d in dilations
        )
        # LayerNorm over the channel dim only -- an activation norm over the
        # time axis (BatchNorm1d / GroupNorm) would fold a later tick's
        # statistics into an earlier tick's output and break causality.
        self.norms = nn.ModuleList(nn.LayerNorm(channels) for _ in dilations)
        self.drop = nn.Dropout(dropout)
        self.kernel = kernel
        self.dilations = list(dilations)
        self.act = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [BN, C, T]
        for conv, norm, d in zip(self.convs, self.norms, self.dilations, strict=True):
            y = torch.nn.functional.pad(x, ((self.kernel - 1) * d, 0))  # causal left pad
            y = conv(y)
            y = norm(y.transpose(1, 2)).transpose(1, 2)  # [BN,C,T]->[BN,T,C]->back
            y = self.drop(self.act(y))
            x = x + y
        return x


class STGraphAutoencoder(nn.Module):
    """Encoder: a causal temporal conv extracts each link's recent dynamics,
    then ONE GATv2 pass mixes the corridor neighbourhood on the temporally-
    encoded state, then a linear bottleneck. Decoder mirrors it (graph pass,
    then a temporal conv expands the bottleneck back over the window).

    The spatial op runs at batch `B` on the last-timestep representation --
    not at `B*T` on every frame -- which is what keeps it CPU-trainable in
    minutes (T-then-S ordering, as in STGCN's sandwich): the temporal conv
    has already carried the history each node needs before neighbours are
    mixed in."""

    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg
        d = cfg.d_model
        self.in_proj = nn.Linear(cfg.n_features, d)
        self.enc_tcn = TemporalConvNet(d, cfg.tcn_kernel, cfg.tcn_dilations, cfg.dropout)
        self.enc_gat = GATv2Layer(d, d, cfg.n_heads, cfg.dropout)
        self.to_bottleneck = nn.Linear(d, cfg.d_bottleneck)

        self.from_bottleneck = nn.Linear(cfg.d_bottleneck, d)
        self.dec_gat = GATv2Layer(d, d, cfg.n_heads, cfg.dropout)
        self.dec_tcn = TemporalConvNet(d, cfg.tcn_kernel, cfg.tcn_dilations, cfg.dropout)
        self.recon_head = nn.Linear(d, cfg.n_features)
        self.forecast_head = nn.Linear(cfg.d_bottleneck, cfg.n_features)

    def _temporal(self, tcn: TemporalConvNet, h: torch.Tensor) -> torch.Tensor:
        b, t, n, d = h.shape
        y = h.permute(0, 2, 3, 1).reshape(b * n, d, t)
        y = tcn(y)
        return y.reshape(b, n, d, t).permute(0, 3, 1, 2)

    def forward(
        self, x: torch.Tensor, edge_index: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        # x: [B, T, N, F]
        b, t, n, _ = x.shape
        h = self.in_proj(x)                                   # [B, T, N, d]
        h = self._temporal(self.enc_tcn, h)                   # causal, per node
        h = self.enc_gat(h[:, -1], edge_index)               # [B, N, d] -- batch B
        z = self.to_bottleneck(h)                            # [B, N, d_bottle]

        g = self.dec_gat(self.from_bottleneck(z), edge_index)  # [B, N, d]
        g = g.unsqueeze(1).expand(b, t, n, self.cfg.d_model)
        g = self._temporal(self.dec_tcn, g)                   # [B, T, N, d]
        x_recon = self.recon_head(g)                          # [B, T, N, F]
        x_next = self.forecast_head(z)                        # [B, N, F]
        return x_recon, x_next, z

    def losses(
        self,
        x: torch.Tensor,
        x_next_true: torch.Tensor,
        edge_index: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Returns `(scalar_loss, per_node_error [B, N])`. per_node_error is
        the mean squared error over the window and features plus the weighted
        forecast error -- the same quantity `score` z-scores."""
        x_recon, x_next, _ = self.forward(x, edge_index)
        recon_se = (x_recon - x).pow(2).mean(dim=(1, 3))       # [B, N]
        fcast_se = (x_next - x_next_true).pow(2).mean(dim=2)   # [B, N]
        per_node = recon_se + self.cfg.forecast_weight * fcast_se
        return per_node.mean(), per_node.detach()


# ---------------------------------------------------------------------------
# error normalizer -- turns raw per-node error into graph_score
# ---------------------------------------------------------------------------


@dataclass
class ErrorNormalizer:
    """Per-node mean/std of the model's reconstruction error on *normal*
    traffic. `graph_score[n] = (error[n] - mean[n]) / std[n]` -- so a score of
    3 means "this link's error is 3 sigma above what this link normally
    produces", localized and comparable across links of very different
    baseline behaviour."""

    mean: list[float]
    std: list[float]

    @classmethod
    def fit(cls, errors: Sequence[Sequence[float]]) -> ErrorNormalizer:
        a = np.asarray(errors, dtype=np.float64)          # [samples, N]
        if a.ndim != 2 or a.shape[0] == 0:
            raise ValueError("errors must be [samples, n_nodes] with samples > 0")
        mean = a.mean(axis=0)
        std = np.sqrt(np.maximum(1e-12, a.var(axis=0)))
        return cls(mean=mean.tolist(), std=std.tolist())

    def z(self, error: Sequence[float]) -> list[float]:
        return [
            (float(e) - m) / s for e, m, s in zip(error, self.mean, self.std, strict=True)
        ]

    def to_json(self) -> dict:
        return {"mean": self.mean, "std": self.std}

    @classmethod
    def from_json(cls, d: dict) -> ErrorNormalizer:
        return cls(mean=list(d["mean"]), std=list(d["std"]))


# ---------------------------------------------------------------------------
# windowing
# ---------------------------------------------------------------------------


class WindowBuffer:
    """Fixed-length ring of the most recent `window` feature frames. Live
    inference pushes one `[N, F]` frame per tick and, once full, hands the
    detector a `[window, N, F]` array."""

    def __init__(self, window: int, n_nodes: int):
        self._window = window
        self._n = n_nodes
        self._frames: deque[np.ndarray] = deque(maxlen=window)

    def push(self, frame: Sequence[Sequence[float]]) -> None:
        arr = np.asarray(frame, dtype=np.float32)
        if arr.shape != (self._n, N_FEATURES):
            raise ValueError(f"frame shape {arr.shape} != {(self._n, N_FEATURES)}")
        self._frames.append(arr)

    @property
    def ready(self) -> bool:
        return len(self._frames) == self._window

    def array(self) -> np.ndarray:
        if not self.ready:
            raise RuntimeError("window not full yet")
        return np.stack(self._frames, axis=0)  # [window, N, F]


# ---------------------------------------------------------------------------
# graph detector
# ---------------------------------------------------------------------------


@dataclass
class TrainReport:
    epochs_run: int
    best_val_loss: float
    train_loss: list[float] = field(default_factory=list)
    val_loss: list[float] = field(default_factory=list)


class GraphAnomalyDetector:
    """The trained graph detector: model + feature normalizer + error
    normalizer + topology, with training and scoring."""

    def __init__(
        self,
        graph: AnomalyGraph,
        cfg: ModelConfig,
        feature_normalizer: FeatureNormalizer,
        *,
        device: str = "cpu",
    ):
        if cfg.n_nodes != graph.num_nodes:
            raise ValueError(f"cfg.n_nodes {cfg.n_nodes} != graph {graph.num_nodes}")
        self.graph = graph
        self.cfg = cfg
        self.feature_normalizer = feature_normalizer
        self.error_normalizer: ErrorNormalizer | None = None
        self.device = torch.device(device)
        self.model = STGraphAutoencoder(cfg).to(self.device)
        self._edge_index = self._build_edge_index(graph).to(self.device)

    # ---- topology --------------------------------------------------------

    @staticmethod
    def _build_edge_index(graph: AnomalyGraph) -> torch.Tensor:
        """`[2, E]` long: row 0 = source, row 1 = target. Self-loops are added
        if the graph did not already carry them, so every node always attends
        to itself."""
        pairs = set(graph.edge_index) | {(i, i) for i in range(graph.num_nodes)}
        src = [s for s, _ in sorted(pairs)]
        dst = [d for _, d in sorted(pairs)]
        return torch.tensor([src, dst], dtype=torch.long)

    # ---- data prep -----------------------------------------------------

    def _windows_from_run(self, run: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """`run`: [T, N, F] of one normal scenario. Returns
        `(X [S, W, N, F], Y [S, N, F])` -- every length-W window and the frame
        immediately after it."""
        w = self.cfg.window
        run = self.feature_normalizer_transform(run)
        t = run.shape[0]
        if t <= w:
            return (
                np.empty((0, w, self.cfg.n_nodes, N_FEATURES), np.float32),
                np.empty((0, self.cfg.n_nodes, N_FEATURES), np.float32),
            )
        idx = np.arange(t - w)
        X = np.stack([run[i : i + w] for i in idx]).astype(np.float32)
        Y = run[w : w + len(idx)].astype(np.float32)
        return X, Y

    def feature_normalizer_transform(self, run: np.ndarray) -> np.ndarray:
        flat = [self.feature_normalizer.transform_row(row) for row in run.reshape(-1, N_FEATURES)]
        return np.asarray(flat, dtype=np.float32).reshape(run.shape)

    # ---- training ----------------------------------------------------

    def fit(
        self,
        train_runs: Sequence[np.ndarray],
        val_runs: Sequence[np.ndarray],
        *,
        epochs: int = 40,
        lr: float = 1e-3,
        batch_size: int = 64,
        weight_decay: float = 1e-5,
        patience: int = 6,
        seed: int = 0,
        log=lambda msg: None,
    ) -> TrainReport:
        torch.manual_seed(seed)
        Xtr, Ytr = _cat([self._windows_from_run(r) for r in train_runs])
        Xva, Yva = _cat([self._windows_from_run(r) for r in val_runs])
        if len(Xtr) == 0 or len(Xva) == 0:
            raise ValueError("not enough frames to form a single training/val window")
        log(f"train windows={len(Xtr)}  val windows={len(Xva)}")

        Xtr_t = torch.from_numpy(Xtr)
        Ytr_t = torch.from_numpy(Ytr)
        Xva_t = torch.from_numpy(Xva).to(self.device)
        Yva_t = torch.from_numpy(Yva).to(self.device)

        opt = torch.optim.Adam(self.model.parameters(), lr=lr, weight_decay=weight_decay)
        report = TrainReport(epochs_run=0, best_val_loss=math.inf)
        best_state = None
        bad = 0
        n = len(Xtr_t)

        for epoch in range(1, epochs + 1):
            self.model.train()
            perm = torch.randperm(n)
            running = 0.0
            for s in range(0, n, batch_size):
                b = perm[s : s + batch_size]
                xb = Xtr_t[b].to(self.device)
                yb = Ytr_t[b].to(self.device)
                opt.zero_grad()
                loss, _ = self.model.losses(xb, yb, self._edge_index)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 5.0)
                opt.step()
                running += loss.item() * len(b)
            train_loss = running / n

            self.model.eval()
            with torch.no_grad():
                val_loss = self.model.losses(Xva_t, Yva_t, self._edge_index)[0].item()
            report.train_loss.append(train_loss)
            report.val_loss.append(val_loss)
            report.epochs_run = epoch
            log(f"epoch {epoch:3d}  train {train_loss:.5f}  val {val_loss:.5f}")

            if val_loss < report.best_val_loss - 1e-6:
                report.best_val_loss = val_loss
                best_state = {
                    k: v.detach().cpu().clone() for k, v in self.model.state_dict().items()
                }
                bad = 0
            else:
                bad += 1
                if bad >= patience:
                    log(f"early stop at epoch {epoch}")
                    break

        if best_state is not None:
            self.model.load_state_dict(best_state)
        self._fit_error_normalizer(val_runs, log)
        return report

    def _inference_error(self, x_norm: torch.Tensor) -> torch.Tensor:
        """Per-node error usable without the true next frame: reconstruction
        error over the window, plus the disagreement between the model's
        one-step forecast and its own reconstruction of the last observed
        tick. On normal traffic the model is trained to make both small; an
        anomaly inflates at least one. `x_norm`: [B, W, N, F] normalized.
        Returns [B, N]. Both `fit` and `score` go through here, so the error
        normalizer is fitted on exactly the quantity `score` z-scores."""
        x_recon, x_next, _ = self.model(x_norm, self._edge_index)
        recon_se = (x_recon - x_norm).pow(2).mean(dim=(1, 3))       # [B, N]
        fcast_se = (x_next - x_recon[:, -1]).pow(2).mean(dim=2)     # [B, N]
        return recon_se + self.cfg.forecast_weight * fcast_se

    def _fit_error_normalizer(self, val_runs: Sequence[np.ndarray], log) -> None:
        self.model.eval()
        errs: list[np.ndarray] = []
        with torch.no_grad():
            for run in val_runs:
                X, _ = self._windows_from_run(run)
                if len(X) == 0:
                    continue
                xb = torch.from_numpy(X).to(self.device)
                errs.append(self._inference_error(xb).cpu().numpy())
        if not errs:
            raise ValueError("no val windows to fit the error normalizer on")
        self.error_normalizer = ErrorNormalizer.fit(np.concatenate(errs, axis=0))
        log(f"error normalizer fitted on {sum(len(e) for e in errs)} normal windows")

    # ---- scoring ---------------------------------------------------

    def score(self, window: np.ndarray) -> list[float]:
        """`window`: [W, N, F] raw (un-normalized) features, most recent last.
        Returns `graph_score` per node, node order == graph.node_ids."""
        if self.error_normalizer is None:
            raise RuntimeError("detector not fitted (no error normalizer)")
        w = self.cfg.window
        if window.shape != (w, self.cfg.n_nodes, N_FEATURES):
            raise ValueError(f"window {window.shape} != {(w, self.cfg.n_nodes, N_FEATURES)}")
        norm = self.feature_normalizer_transform(window.astype(np.float32))
        x = torch.from_numpy(norm[None]).to(self.device)          # [1, W, N, F]
        self.model.eval()
        with torch.no_grad():
            per_node = self._inference_error(x)[0].cpu().numpy()
        return self.error_normalizer.z(per_node.tolist())

    @property
    def warmup_windows(self) -> int:
        return self.cfg.window

    @property
    def detector_version(self) -> str:
        h = hashlib.sha256()
        for v in self.model.state_dict().values():
            h.update(v.detach().cpu().numpy().tobytes())
        h.update(json.dumps(asdict(self.cfg), sort_keys=True).encode())
        return f"graph-ae@{h.hexdigest()[:8]}"

    # ---- persistence ---------------------------------------------

    def save(self, dirpath: str | Path) -> None:
        d = Path(dirpath)
        d.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), d / "model.pt")
        (d / "config.json").write_text(json.dumps(asdict(self.cfg), indent=2))
        (d / "feature_normalizer.json").write_text(
            json.dumps(
                {
                    "mean": self.feature_normalizer.mean,
                    "std": self.feature_normalizer.std,
                    "passthrough": list(self.feature_normalizer.passthrough),
                },
                indent=2,
            )
        )
        if self.error_normalizer is not None:
            (d / "error_normalizer.json").write_text(
                json.dumps(self.error_normalizer.to_json(), indent=2)
            )
        (d / "graph.json").write_text(
            json.dumps({"node_ids": list(self.graph.node_ids)}, indent=2)
        )
        (d / "version.txt").write_text(self.detector_version)

    @classmethod
    def load(
        cls, dirpath: str | Path, graph: AnomalyGraph, *, device: str = "cpu"
    ) -> GraphAnomalyDetector:
        d = Path(dirpath)
        cfg = ModelConfig(**json.loads((d / "config.json").read_text()))
        cfg.tcn_dilations = tuple(cfg.tcn_dilations)
        saved_nodes = json.loads((d / "graph.json").read_text())["node_ids"]
        if saved_nodes != list(graph.node_ids):
            raise ValueError("saved detector topology does not match the given graph -- retrain")
        fn_raw = json.loads((d / "feature_normalizer.json").read_text())
        fn = FeatureNormalizer(
            mean=fn_raw["mean"], std=fn_raw["std"], passthrough=tuple(fn_raw["passthrough"])
        )
        det = cls(graph, cfg, fn, device=device)
        det.model.load_state_dict(torch.load(d / "model.pt", map_location=device))
        err_path = d / "error_normalizer.json"
        if err_path.exists():
            det.error_normalizer = ErrorNormalizer.from_json(json.loads(err_path.read_text()))
        return det


def _cat(pairs: Sequence[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    xs = [x for x, _ in pairs if len(x)]
    ys = [y for _, y in pairs if len(y)]
    if not xs:
        return (
            np.empty((0, 0, 0, 0), np.float32),
            np.empty((0, 0, 0), np.float32),
        )
    return np.concatenate(xs, axis=0), np.concatenate(ys, axis=0)


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------


class EWMALinkDetector:
    """Per-link EWMA + EWM-variance z-score, no graph, no learning beyond the
    running moments -- the baseline plan 6.1 requires the graph model to beat.
    Consumes the same `queue_pcu` / `halting_frac` a per-sensor threshold
    would, and scores a node by the larger of the two z-scores (a jam shows in
    both; either alone is enough to flag).

    `score(window)` is causal and stateful: it reads the last frame, returns
    the z-scores against the current EWMA, then folds that frame in. Feed it
    every tick, exactly like the graph detector.
    """

    _QUEUE_IDX = 0        # FEATURE_NAMES.index("queue_pcu")
    _HALT_IDX = 4         # FEATURE_NAMES.index("halting_frac")

    def __init__(self, n_nodes: int, *, alpha: float = 0.02, warmup: int = 120):
        self.n_nodes = n_nodes
        self.alpha = alpha
        self.warmup = warmup
        self._count = 0
        self._mean = np.zeros((n_nodes, 2), dtype=np.float64)
        self._var = np.ones((n_nodes, 2), dtype=np.float64)

    def _obs(self, frame: np.ndarray) -> np.ndarray:
        return np.stack([frame[:, self._QUEUE_IDX], frame[:, self._HALT_IDX]], axis=1)

    def score(self, window: np.ndarray) -> list[float]:
        frame = np.asarray(window[-1], dtype=np.float64)
        x = self._obs(frame)                                   # [N, 2]
        z = (x - self._mean) / np.sqrt(self._var + 1e-9)
        # update (EWMA of mean and of squared deviation)
        a = self.alpha
        diff = x - self._mean
        self._mean += a * diff
        self._var = (1 - a) * (self._var + a * diff * diff)
        self._count += 1
        if self._count <= self.warmup:
            return [0.0] * self.n_nodes
        return np.maximum(z[:, 0], z[:, 1]).tolist()

    @property
    def warmup_windows(self) -> int:
        return 1

    @property
    def detector_version(self) -> str:
        return f"ewma-baseline@a{self.alpha}"

    def save(self, dirpath: str | Path) -> None:
        d = Path(dirpath)
        d.mkdir(parents=True, exist_ok=True)
        (d / "ewma_baseline.json").write_text(
            json.dumps(
                {
                    "n_nodes": self.n_nodes,
                    "alpha": self.alpha,
                    "warmup": self.warmup,
                    "count": self._count,
                    "mean": self._mean.tolist(),
                    "var": self._var.tolist(),
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, dirpath: str | Path) -> EWMALinkDetector:
        raw = json.loads((Path(dirpath) / "ewma_baseline.json").read_text())
        det = cls(raw["n_nodes"], alpha=raw["alpha"], warmup=raw["warmup"])
        det._count = raw["count"]
        det._mean = np.asarray(raw["mean"], dtype=np.float64)
        det._var = np.asarray(raw["var"], dtype=np.float64)
        return det

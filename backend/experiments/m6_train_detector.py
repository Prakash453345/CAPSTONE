"""Train the M6 spatiotemporal graph autoencoder on the recorded normal-
traffic feature stream, and save the detector (weights + feature normalizer +
error normalizer + topology) for the injection gate and the live pipeline.

Run `scripts/m6_record_features.py` first. Not a pytest target -- needs the
`[anomaly]` extra and a few minutes of CPU.

Usage:
    python scripts/m6_train_detector.py
    python scripts/m6_train_detector.py --epochs 60 --window 16
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sim_service.control.anomaly.detector import GraphAnomalyDetector, ModelConfig
from sim_service.control.anomaly.graph_features import (
    N_FEATURES,
    AnomalyGraph,
    FeatureNormalizer,
)

_ROOT = Path(__file__).resolve().parent.parent
_NET = _ROOT / "data" / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_ART = _ROOT / "experiments" / "results" / "m6_artifacts"
_FEATURES = _ART / "features"
_DETECTOR = _ART / "detector"


def _load_runs(sub: str) -> list[np.ndarray]:
    d = _FEATURES / sub
    runs = [np.load(p) for p in sorted(d.glob("*.npy"))]
    if not runs:
        raise SystemExit(
            f"no feature files in {d} -- run scripts/m6_record_features.py first"
        )
    return runs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--d-model", type=int, default=32)
    ap.add_argument("--bottleneck", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default=str(_DETECTOR))
    args = ap.parse_args()

    graph = AnomalyGraph.from_network(_NET)
    train_runs = _load_runs("train")
    val_runs = _load_runs("val")
    for r in (*train_runs, *val_runs):
        if r.shape[1:] != (graph.num_nodes, N_FEATURES):
            raise SystemExit(
                f"feature file shape {r.shape} != (*, {graph.num_nodes}, {N_FEATURES}) "
                "-- re-record after any graph/feature change"
            )
    print(
        f"graph {graph.num_nodes} nodes | train runs {len(train_runs)} "
        f"({sum(len(r) for r in train_runs)} ticks) | val runs {len(val_runs)}"
    )

    fn = FeatureNormalizer.fit([r.reshape(-1, N_FEATURES).tolist() for r in train_runs])
    cfg = ModelConfig(
        n_nodes=graph.num_nodes,
        window=args.window,
        d_model=args.d_model,
        d_bottleneck=args.bottleneck,
    )
    det = GraphAnomalyDetector(graph, cfg, fn, device=args.device)
    n_params = sum(p.numel() for p in det.model.parameters())
    print(f"model parameters: {n_params:,}\n")

    report = det.fit(
        train_runs,
        val_runs,
        epochs=args.epochs,
        lr=args.lr,
        batch_size=args.batch_size,
        patience=args.patience,
        log=lambda m: print(m, flush=True),
    )

    out = Path(args.out)
    det.save(out)
    (out / "train_report.json").write_text(
        json.dumps(
            {
                "epochs_run": report.epochs_run,
                "best_val_loss": report.best_val_loss,
                "train_loss": report.train_loss,
                "val_loss": report.val_loss,
                "n_params": n_params,
                "config": vars(cfg),
            },
            indent=2,
            default=list,
        )
    )
    print(
        f"\nsaved detector -> {out}"
        f"\n  version        {det.detector_version}"
        f"\n  best val loss  {report.best_val_loss:.5f}"
        f"\n  epochs run     {report.epochs_run}"
    )


if __name__ == "__main__":
    main()

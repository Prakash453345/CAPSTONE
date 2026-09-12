"""Train the M6 spatiotemporal graph anomaly detector.

Usage:
    python scripts/train_anomaly_detector.py \\
        --data-dir data/m6/normal \\
        --graph scenarios/networks/vijayawada/adjacency.json \\
        --output-dir models --epochs 50

Steps:
  1. Load graph from adjacency JSON
  2. Load normal-traffic Parquet files
  3. Split train/val (80/20)
  4. Train GAT+GRU autoencoder (MSE reconstruction)
  5. Save model, scaler, conformal calibrator
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import torch

from itms_anomaly.dataset import TrafficDataset, FeatureScaler
from itms_anomaly.graph import build_graph_from_json
from itms_anomaly.model import SpatioTemporalGAE
from itms_anomaly.train import train_model
from itms_anomaly.conformal import ConformalCalibrator
from itms_anomaly.detector import AnomalyDetector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s train-anomaly %(message)s",
)
log = logging.getLogger("train-anomaly")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train M6 anomaly detector")
    parser.add_argument(
        "--data-dir", required=True, help="Directory with normal Parquet files"
    )
    parser.add_argument(
        "--graph", required=True, help="Path to adjacency JSON"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Output directory for model files"
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--window-size", type=int, default=10)
    parser.add_argument("--alpha", type=float, default=0.05, help="Conformal α")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load graph
    log.info("loading graph from %s", args.graph)
    edge_index, node_index = build_graph_from_json(args.graph)
    num_nodes = len(node_index)
    log.info("graph: %d nodes, %d edges", num_nodes, edge_index.shape[1])

    # 2. Load data
    parquet_files = sorted(data_dir.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"no Parquet files found in {data_dir}")
    log.info("found %d Parquet files", len(parquet_files))

    dataset = TrafficDataset(
        parquet_paths=[str(p) for p in parquet_files],
        node_index=node_index,
        window_size=args.window_size,
    )
    log.info("dataset: %d windows", len(dataset))

    # 3. Split train/val
    train_size = int(0.8 * len(dataset))
    val_size = len(dataset) - train_size
    train_ds, val_ds = torch.utils.data.random_split(
        dataset, [train_size, val_size]
    )
    log.info("train: %d, val: %d", len(train_ds), len(val_ds))

    # Save scaler
    scaler_path = output_dir / "scaler.json"
    dataset.scaler.save(str(scaler_path))
    log.info("scaler saved to %s", scaler_path)

    # 4. Create and train model
    model = SpatioTemporalGAE(in_features=6)
    param_count = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log.info("model: %d parameters", param_count)

    history = train_model(
        model=model,
        dataset=train_ds,
        edge_index=edge_index,
        epochs=args.epochs,
        lr=args.lr,
        batch_size=args.batch_size,
    )

    # 5. Save model
    model_path = output_dir / "anomaly_detector.pt"
    torch.save(model.state_dict(), model_path)
    log.info("model saved to %s", model_path)

    # 6. Conformal calibration on validation set
    log.info("running conformal calibration on validation set")
    detector = AnomalyDetector(
        model=model,
        edge_index=edge_index,
        node_index=node_index,
        scaler=dataset.scaler,
        window_size=args.window_size,
    )

    # Score all validation windows
    all_scores = []
    model.eval()
    with torch.no_grad():
        for i in range(len(val_ds)):
            window = val_ds[i]  # [T, N, F]
            x = window.unsqueeze(0)  # [1, T, N, F]
            recon = model(x, edge_index)
            mse = torch.mean((x - recon) ** 2, dim=-1)  # [1, T, N]
            # Take last timestep, all nodes
            scores = mse[0, -1, :].numpy()
            all_scores.extend(scores.tolist())

    calibrator = ConformalCalibrator(alpha=args.alpha)
    tau = calibrator.fit(all_scores)

    conformal_path = output_dir / "conformal.json"
    calibrator.save(str(conformal_path))

    # Summary
    best_train = min(history.get("train_losses", [float("inf")]))
    best_val = min(history.get("val_losses", [float("inf")]))
    log.info("=== Training Summary ===")
    log.info("  Parameters:        %d", param_count)
    log.info("  Best train loss:   %.6f", best_train)
    log.info("  Best val loss:     %.6f", best_val)
    log.info("  Conformal α:       %.3f", args.alpha)
    log.info("  Conformal τ:       %.6f", tau)
    log.info("  Calibration points:%d", len(all_scores))


if __name__ == "__main__":
    main()

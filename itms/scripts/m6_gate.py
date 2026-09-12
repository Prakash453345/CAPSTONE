"""M6 Gate: end-to-end evaluation of the incident detection pipeline.

Usage:
    python scripts/m6_gate.py \\
        --data-dir data/m6 \\
        --model models/anomaly_detector.pt \\
        --graph scenarios/networks/vijayawada/adjacency.json \\
        --scaler models/scaler.json \\
        --conformal models/conformal.json

Gate criteria (from M6 planning document §11):
  - Recall >= 90% on injected incidents at all demand levels
  - Mean detection latency < 30 seconds at all demand levels
  - Empirical false-alarm rate <= 2x conformal target alpha
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from itms_anomaly.graph import build_graph_from_json
from itms_anomaly.model import SpatioTemporalGAE
from itms_anomaly.dataset import FeatureScaler, TrafficDataset
from itms_anomaly.detector import AnomalyDetector
from itms_anomaly.baseline import EWMABaseline
from itms_anomaly.conformal import ConformalCalibrator

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s m6-gate %(message)s"
)
log = logging.getLogger("m6-gate")

DEMAND_LEVELS = ["light", "medium", "heavy"]
FEATURE_COLS = [
    "queue_pcu", "receiving_occupancy", "mean_speed_mps",
    "occupancy", "wait_time_s", "vehicle_count",
]


def _load_run_data(parquet_path: str, node_index: dict[str, int]):
    """Load a Parquet file and reshape into per-tick feature dicts."""
    df = pd.read_parquet(parquet_path)
    ticks = sorted(df["tick"].unique())
    result = []
    for tick in ticks:
        tick_df = df[df["tick"] == tick]
        features = {}
        for _, row in tick_df.iterrows():
            edge_id = row["edge_id"]
            if edge_id in node_index:
                features[edge_id] = {
                    col: float(row.get(col, 0.0)) for col in FEATURE_COLS
                }
        result.append((tick, features))
    return result


def _evaluate_detector(
    detector_name: str,
    run_data: list[tuple[int, dict]],
    ground_truth: list[dict],
    score_fn,
    threshold: float,
    update_fn,
):
    """Run a detector on one run's data and compute metrics."""
    detections = []  # (tick, edge_id, score)

    for tick, features in run_data:
        update_fn(features)
        scores = score_fn()
        for edge_id, score in scores.items():
            if score > threshold:
                detections.append((tick, edge_id, score))

    # Match detections to ground truth injections
    detected_incidents = set()
    detection_latencies = []
    localization_correct = 0
    true_positives = 0

    for gt in ground_truth:
        gt_edge = gt["edge_id"]
        gt_start = gt["start_tick"]
        gt_end = gt["end_tick"]
        gt_idx = id(gt)

        for tick, edge_id, _ in detections:
            if gt_start <= tick <= gt_end:
                if gt_idx not in detected_incidents:
                    detected_incidents.add(gt_idx)
                    detection_latencies.append(tick - gt_start)
                    if edge_id == gt_edge:
                        localization_correct += 1
                    true_positives += 1
                break

    # False positives: detections outside any injection window
    false_positives = 0
    for tick, edge_id, _ in detections:
        in_window = any(
            gt["start_tick"] <= tick <= gt["end_tick"]
            for gt in ground_truth
        )
        if not in_window:
            false_positives += 1

    total_incidents = len(ground_truth)
    recall = len(detected_incidents) / total_incidents if total_incidents > 0 else 0.0
    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    mean_latency = np.mean(detection_latencies) if detection_latencies else float("nan")
    loc_acc = (
        localization_correct / len(detected_incidents)
        if detected_incidents
        else 0.0
    )

    return {
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "mean_latency_s": float(mean_latency),
        "localization_accuracy": loc_acc,
        "total_incidents": total_incidents,
        "detected": len(detected_incidents),
        "false_positives": false_positives,
    }


def _evaluate_false_alarms(
    run_data: list[tuple[int, dict]],
    score_fn,
    threshold: float,
    update_fn,
):
    """Count false alarms on a pure-normal run."""
    total_ticks = 0
    alarm_ticks = 0

    for tick, features in run_data:
        update_fn(features)
        scores = score_fn()
        total_ticks += 1
        if any(s > threshold for s in scores.values()):
            alarm_ticks += 1

    rate = alarm_ticks / total_ticks if total_ticks > 0 else 0.0
    return {"alarm_ticks": alarm_ticks, "total_ticks": total_ticks, "rate": rate}


def _print_row(label: str, values: dict[str, float], fmt: str = ".1%"):
    cols = [f"{values.get(d, 0):{fmt}}" for d in DEMAND_LEVELS]
    print(f"  {label:<22s} {cols[0]:>10s} {cols[1]:>10s} {cols[2]:>10s}")


def main() -> None:
    parser = argparse.ArgumentParser(description="M6 Gate: Incident Detection")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--scaler", required=True)
    parser.add_argument("--conformal", required=True)
    parser.add_argument("--alpha", type=float, default=0.05)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    # Load model and tools
    edge_index, node_index = build_graph_from_json(args.graph)
    scaler = FeatureScaler.load(args.scaler)
    calibrator = ConformalCalibrator.load(args.conformal)

    model = SpatioTemporalGAE(in_features=6)
    model.load_state_dict(
        torch.load(args.model, map_location="cpu", weights_only=True)
    )
    model.eval()

    gnn_results: dict[str, dict] = {}
    ewma_results: dict[str, dict] = {}
    gnn_fa: dict[str, dict] = {}
    ewma_fa: dict[str, dict] = {}

    for demand in DEMAND_LEVELS:
        log.info("evaluating demand=%s", demand)

        # Incident runs
        incident_dir = data_dir / "incident"
        incident_files = sorted(incident_dir.glob(f"{demand}_*.parquet"))
        label_files = sorted(incident_dir.glob(f"{demand}_*_labels.json"))

        demand_gnn_metrics = []
        demand_ewma_metrics = []

        for pf, lf in zip(incident_files, label_files):
            with open(lf) as f:
                ground_truth = json.load(f)

            run_data = _load_run_data(str(pf), node_index)

            # GNN detector
            detector = AnomalyDetector(
                model=model, edge_index=edge_index,
                node_index=node_index, scaler=scaler,
            )
            m = _evaluate_detector(
                "GNN", run_data, ground_truth,
                detector.score, calibrator.threshold,
                detector.update,
            )
            demand_gnn_metrics.append(m)

            # EWMA baseline
            baseline = EWMABaseline()
            m = _evaluate_detector(
                "EWMA", run_data, ground_truth,
                baseline.score, 3.0,
                baseline.update,
            )
            demand_ewma_metrics.append(m)

        # Average metrics across runs
        def avg_metrics(metrics_list):
            if not metrics_list:
                return {k: 0.0 for k in [
                    "recall", "precision", "f1",
                    "mean_latency_s", "localization_accuracy",
                ]}
            return {
                k: float(np.mean([m[k] for m in metrics_list]))
                for k in ["recall", "precision", "f1",
                           "mean_latency_s", "localization_accuracy"]
            }

        gnn_results[demand] = avg_metrics(demand_gnn_metrics)
        ewma_results[demand] = avg_metrics(demand_ewma_metrics)

        # False-alarm runs (normal data)
        normal_dir = data_dir / "normal"
        normal_files = sorted(normal_dir.glob(f"{demand}_*.parquet"))

        gnn_fa_rates = []
        ewma_fa_rates = []
        for nf in normal_files:
            run_data = _load_run_data(str(nf), node_index)

            det = AnomalyDetector(
                model=model, edge_index=edge_index,
                node_index=node_index, scaler=scaler,
            )
            fa = _evaluate_false_alarms(
                run_data, det.score, calibrator.threshold, det.update
            )
            gnn_fa_rates.append(fa["rate"])

            bl = EWMABaseline()
            fa = _evaluate_false_alarms(
                run_data, bl.score, 3.0, bl.update
            )
            ewma_fa_rates.append(fa["rate"])

        gnn_fa[demand] = {"rate": float(np.mean(gnn_fa_rates)) if gnn_fa_rates else 0.0}
        ewma_fa[demand] = {"rate": float(np.mean(ewma_fa_rates)) if ewma_fa_rates else 0.0}

    # Print gate table
    print()
    print("=" * 65)
    print("  M6 Gate: Incident Detection")
    print("=" * 65)

    print("\n  Graph Anomaly Detector (GAT+GRU):")
    print(f"  {'':22s} {'Light':>10s} {'Medium':>10s} {'Heavy':>10s}    Gate")
    _print_row("Recall", {d: gnn_results[d]["recall"] for d in DEMAND_LEVELS})
    print(f"{'':26s}{'':>10s}{'':>10s}{'':>10s}    >= 90%")
    _print_row("Precision", {d: gnn_results[d]["precision"] for d in DEMAND_LEVELS})
    _print_row("F1", {d: gnn_results[d]["f1"] for d in DEMAND_LEVELS})

    lat_cols = [f"{gnn_results[d]['mean_latency_s']:.1f}" for d in DEMAND_LEVELS]
    print(f"  {'Det. latency (s)':<22s} {lat_cols[0]:>10s} {lat_cols[1]:>10s} {lat_cols[2]:>10s}    < 30s")

    fa_cols = [f"{gnn_fa[d]['rate']:.2%}" for d in DEMAND_LEVELS]
    print(f"  {'False-alarm rate':<22s} {fa_cols[0]:>10s} {fa_cols[1]:>10s} {fa_cols[2]:>10s}    <= {2*args.alpha:.0%}")

    _print_row("Localization acc.", {d: gnn_results[d]["localization_accuracy"] for d in DEMAND_LEVELS})

    print("\n  EWMA Baseline (no graph):")
    print(f"  {'':22s} {'Light':>10s} {'Medium':>10s} {'Heavy':>10s}")
    _print_row("Recall", {d: ewma_results[d]["recall"] for d in DEMAND_LEVELS})
    _print_row("Precision", {d: ewma_results[d]["precision"] for d in DEMAND_LEVELS})
    _print_row("F1", {d: ewma_results[d]["f1"] for d in DEMAND_LEVELS})

    lat_cols = [f"{ewma_results[d]['mean_latency_s']:.1f}" for d in DEMAND_LEVELS]
    print(f"  {'Det. latency (s)':<22s} {lat_cols[0]:>10s} {lat_cols[1]:>10s} {lat_cols[2]:>10s}")

    fa_cols = [f"{ewma_fa[d]['rate']:.2%}" for d in DEMAND_LEVELS]
    print(f"  {'False-alarm rate':<22s} {fa_cols[0]:>10s} {fa_cols[1]:>10s} {fa_cols[2]:>10s}")

    print("\n  GNN vs EWMA:")
    for d in DEMAND_LEVELS:
        f1_diff = gnn_results[d]["f1"] - ewma_results[d]["f1"]
        lat_diff = ewma_results[d]["mean_latency_s"] - gnn_results[d]["mean_latency_s"]
        print(f"    {d:8s}  F1: {f1_diff:+.1%}   Latency: {lat_diff:+.1f}s")

    # Gate pass/fail
    print("\n  Gate criteria:")
    recalls = [gnn_results[d]["recall"] for d in DEMAND_LEVELS]
    latencies = [gnn_results[d]["mean_latency_s"] for d in DEMAND_LEVELS]
    fa_rates = [gnn_fa[d]["rate"] for d in DEMAND_LEVELS]

    recall_pass = all(r >= 0.9 for r in recalls)
    latency_pass = all(l < 30 for l in latencies)
    fa_pass = all(r <= 2 * args.alpha for r in fa_rates)

    status = lambda ok: "[PASS]" if ok else "[FAIL]"
    print(f"    {status(recall_pass)} Recall >= 90% at all demand levels")
    print(f"    {status(latency_pass)} Detection latency < 30s at all demand levels")
    print(f"    {status(fa_pass)} False-alarm rate <= 2x alpha at all demand levels")
    print()

    # Save results JSON
    results_dir = Path("scripts/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "gnn": {d: {**gnn_results[d], "false_alarm_rate": gnn_fa[d]["rate"]} for d in DEMAND_LEVELS},
        "ewma": {d: {**ewma_results[d], "false_alarm_rate": ewma_fa[d]["rate"]} for d in DEMAND_LEVELS},
        "gate": {
            "recall_pass": recall_pass,
            "latency_pass": latency_pass,
            "false_alarm_pass": fa_pass,
            "alpha": args.alpha,
        },
    }
    with open(results_dir / "m6_gate_results.json", "w") as f:
        json.dump(results, f, indent=2)
    log.info("results saved to scripts/results/m6_gate_results.json")


if __name__ == "__main__":
    main()

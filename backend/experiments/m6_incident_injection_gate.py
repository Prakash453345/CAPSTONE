"""M6 gate [plan section 11]. For each arm x demand level x seed: inject
known incidents, run the detector live, and score detections against the
exact ground-truth tick windows.

Gate criterion (plan 11, graph-only mode):
    recall >= 90%, mean detection latency < 30 s, empirical false-alarm rate
    within 2x the conformal target alpha, at light / medium / heavy demand.

The `graph` arm is the trained spatiotemporal autoencoder; the `ewma` arm is
the per-link EWMA/z-score baseline it must beat (plan 6.1).

Prereqs: `scripts/m6_record_features.py` then `scripts/m6_train_detector.py`.
Not a pytest target.

Usage:
    python scripts/m6_incident_injection_gate.py
    python scripts/m6_incident_injection_gate.py --arms graph --levels light --seeds 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m6_harness as H  # noqa: E402
from sim_service.control.anomaly.fusion import RaiserConfig  # noqa: E402
from sim_service.control.anomaly.graph_features import AnomalyGraph  # noqa: E402

_OUT = Path(__file__).resolve().parent / "results" / "m6_incident_injection_gate.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="graph,ewma")
    ap.add_argument("--levels", default="light,medium,heavy")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--persistence", type=int, default=5)
    args = ap.parse_args()

    arms = [a for a in args.arms.split(",") if a]
    levels = [x for x in args.levels.split(",") if x]
    seeds = H.EVAL_SEEDS[: args.seeds]
    raiser_cfg = RaiserConfig(persistence_ticks=args.persistence)

    graph = AnomalyGraph.from_network(H._NET)
    print(f"graph {graph.num_nodes} nodes | arms {arms} | levels {levels} | "
          f"seeds {seeds} | alpha {args.alpha}\n")

    rows: list[dict] = []
    for arm in arms:
        detector = H.load_detector(arm, graph)
        from sim_service.control.anomaly.fusion import FusionLayer

        fusion = FusionLayer()  # monotone: fused >= 0.5  <=>  graph_score >= tau
        print(f"[{arm}] calibrating conformal threshold on VAL normal features...", flush=True)
        conformal = H.calibrate_from_val_features(arm, graph, detector, args.alpha)
        print(f"[{arm}] tau = {conformal.tau:.3f}  ({conformal.n_points} calib points)\n",
              flush=True)

        for level in levels:
            for seed in seeds:
                t0 = time.time()
                res = H.run_incident_scenario(
                    arm, level, seed, graph=graph, detector=detector, fusion=fusion,
                    conformal=conformal, raiser_cfg=raiser_cfg, inject=True,
                )
                normal = H.run_incident_scenario(
                    arm, level, seed, graph=graph, detector=detector, fusion=fusion,
                    conformal=conformal, raiser_cfg=raiser_cfg, inject=False,
                )
                row = {
                    "arm": arm, "level": level, "seed": seed,
                    "n_incidents": res.n_incidents, "detected": res.detected,
                    "recall": round(res.recall, 3),
                    "mean_latency_s": round(res.mean_latency_s, 1),
                    "localized": res.localized,
                    "raw_fpr_normal": round(normal.raw_fpr, 5),
                    "candidate_fpr_normal": round(normal.candidate_fpr, 5),
                    "raw_over_normal": normal.raw_over_threshold,
                    "false_alarms_normal": normal.false_alarms,
                    "node_ticks_normal": normal.ticks_scored * normal.n_nodes,
                    "ticks_scored_normal": normal.ticks_scored,
                    "wall_s": round(time.time() - t0, 1),
                }
                rows.append(row)
                print(
                    f"[{arm:5s} {level:6s} seed {seed:2d}] "
                    f"recall {row['recall']:.2f} ({res.detected}/{res.n_incidents})  "
                    f"lat {row['mean_latency_s']:>5}s  "
                    f"raw_fpr {row['raw_fpr_normal']:.4f}  "
                    f"cand_fpr {row['candidate_fpr_normal']:.4f}  ({row['wall_s']:.0f}s)",
                    flush=True,
                )

    _OUT.write_text(json.dumps(rows, indent=2))
    _summarize(rows, args.alpha)
    print(f"\nwrote {_OUT}")


def _summarize(rows: list[dict], alpha: float) -> None:
    print("\n" + "=" * 88)
    print(f"{'arm':6s} {'level':7s} {'recall':>8s} {'mean_lat_s':>11s} {'raw_fpr':>9s} "
          f"{'cand_fpr':>9s} {'2*alpha':>9s} {'verdict':>9s}")
    print("-" * 88)
    arms = sorted({r["arm"] for r in rows})
    order = {"light": 0, "medium": 1, "heavy": 2}
    levels = sorted({r["level"] for r in rows}, key=lambda x: order.get(x, 9))
    for arm in arms:
        for level in levels:
            sub = [r for r in rows if r["arm"] == arm and r["level"] == level]
            if not sub:
                continue
            det = sum(r["detected"] for r in sub)
            inc = sum(r["n_incidents"] for r in sub)
            recall = det / inc if inc else 0.0
            lats = [r["mean_latency_s"] for r in sub if r["mean_latency_s"] == r["mean_latency_s"]]
            mean_lat = sum(lats) / len(lats) if lats else float("nan")
            raw_over = sum(r["raw_over_normal"] for r in sub)
            node_ticks = sum(r["node_ticks_normal"] for r in sub)
            raw_fpr = raw_over / node_ticks if node_ticks else 0.0
            cand = sum(r["false_alarms_normal"] for r in sub)
            ticks = sum(r["ticks_scored_normal"] for r in sub)
            cand_fpr = cand / ticks if ticks else 0.0
            ok = (
                recall >= H.GATE_RECALL
                and mean_lat < H.GATE_LATENCY_S
                and raw_fpr <= 2 * alpha
            )
            print(f"{arm:6s} {level:7s} {recall:>8.2f} {mean_lat:>11.1f} {raw_fpr:>9.4f} "
                  f"{cand_fpr:>9.4f} {2 * alpha:>9.3f} {'PASS' if ok else 'FAIL':>9s}")
    print("=" * 88)
    print(f"gate: recall >= {H.GATE_RECALL:.0%}, mean latency < {H.GATE_LATENCY_S:.0f}s, "
          f"raw_fpr <= {2 * alpha:.3f}  (plan section 11, graph-only mode)")
    print("raw_fpr = per (node,tick) threshold crossings / node-ticks  (what conformal bounds)")
    print("cand_fpr = ticks with a spurious raised candidate / ticks   (operator-visible load)")


if __name__ == "__main__":
    main()

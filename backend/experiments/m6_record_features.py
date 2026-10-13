"""Record the per-link anomaly feature stream on NORMAL traffic -- the
training and calibration data for the M6 graph detector (plan 6.1: "trains on
the project's own simulated traffic", no external dataset, no incident labels).

One `[T, N, F]` float32 array per (demand level x seed), written to
`scripts/results/m6_artifacts/features/{level}_seed{seed}.npy`. The controller
is the tuned Webster baseline -- deterministic, demand-aware, no learning
state -- so "normal" here means the corridor running its established baseline
plan with no incident injected. Seeds follow the same TRAIN/EVAL split the
M5 harness uses, so nothing the detector trains on is ever scored on.

Not part of the pytest suite -- shells out to real SUMO. Needs the `[anomaly]`
extra (numpy).

Usage:
    python scripts/m6_record_features.py                 # all levels, train+val seeds
    python scripts/m6_record_features.py --levels light --seeds 3
"""

from __future__ import annotations

import argparse
import sys
from functools import partial
from pathlib import Path

import numpy as np
from sim_service.control.anomaly.graph_features import AnomalyGraph
from sim_service.control.runner import run_controlled_scenario
from sim_service.control.strategies import webster
from sim_service.signal_controller.queue_state import load_vtype_pcu

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "data" / "scenarios" / "networks" / "vijayawada"))
from extract_tier0_config import load_configs  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402

_NET = _ROOT / "data" / "scenarios" / "networks" / "vijayawada" / "vijayawada_corridor.net.xml"
_DEMAND = _ROOT / "data" / "scenarios" / "demand" / "vijayawada"
_OUT = _ROOT / "experiments" / "results" / "m6_artifacts" / "features"

# Same discipline as scripts/m5_harness.py: train on one disjoint seed band,
# evaluate on another. The detector never sees an EVAL seed.
TRAIN_SEEDS = list(range(101, 111))
VAL_SEEDS = list(range(1, 11))
MAX_STEPS = 6000


def _demand_paths(level: str) -> tuple[Path, Path]:
    suffix = "" if level == "medium" else f"_{level}"
    return (
        _DEMAND / f"vijayawada_corridor{suffix}.sumocfg",
        _DEMAND / f"vijayawada_corridor{suffix}.rou.xml",
    )


def record_one(level: str, seed: int, graph: AnomalyGraph, out_dir: Path) -> Path:
    sumocfg, route = _demand_paths(level)
    configs = load_configs(_NET)
    flows = compute_link_flows(_NET, route)
    vtype_pcu = load_vtype_pcu(route)
    link_lanes = link_to_lane_map(_NET)
    receiving_lanes = link_to_receiving_lane_map(_NET)

    strategy = {
        tls_id: partial(
            webster.propose,
            timing=webster.compute_timing(cfg, flows.get(tls_id, {})),
        )
        for tls_id, cfg in configs.items()
    }

    frames: list[list[list[float]]] = []
    run_controlled_scenario(
        str(sumocfg),
        configs,
        strategy=strategy,
        seed=seed,
        link_lanes=link_lanes,
        receiving_lanes=receiving_lanes,
        vtype_pcu=vtype_pcu,
        max_steps=MAX_STEPS,
        anomaly_graph=graph,
        anomaly_feature_sink=lambda _step, _t, matrix: frames.append(matrix),
    )

    arr = np.asarray(frames, dtype=np.float32)  # [T, N, F]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{level}_seed{seed}.npy"
    np.save(path, arr)
    print(f"  {level:6s} seed {seed:3d}  ->  {arr.shape}  {path.name}", flush=True)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="light,medium,heavy")
    ap.add_argument("--seeds", type=int, default=0,
                    help="cap seeds per band (0 = all: 10 train + 10 val)")
    ap.add_argument("--out", default=str(_OUT))
    args = ap.parse_args()

    levels = [x for x in args.levels.split(",") if x]
    train = TRAIN_SEEDS[: args.seeds] if args.seeds else TRAIN_SEEDS
    val = VAL_SEEDS[: args.seeds] if args.seeds else VAL_SEEDS
    out_dir = Path(args.out)

    graph = AnomalyGraph.from_network(_NET)
    print(f"graph: {graph.num_nodes} nodes, {graph.num_edges} edges")
    print(f"recording {len(levels)} levels x ({len(train)} train + {len(val)} val) seeds\n")

    for level in levels:
        for seed in train:
            record_one(level, seed, graph, out_dir / "train")
        for seed in val:
            record_one(level, seed, graph, out_dir / "val")

    print(f"\ndone -- features under {out_dir}")


if __name__ == "__main__":
    main()

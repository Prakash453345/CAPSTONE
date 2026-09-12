import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path

import pandas as pd

try:
    import traci
except ImportError:
    pass

from scripts.build_graph import build_graph
from scripts.incident_injector import IncidentInjector


def _resolve_sumo_binary():
    explicit = os.environ.get("SUMO_BINARY")
    if explicit:
        return explicit
    found = shutil.which("sumo")
    if found:
        return found
    candidate = Path(sys.executable).parent / "sumo"
    if candidate.exists():
        return str(candidate)
    if os.name == "nt":
        candidate_exe = Path(sys.executable).parent / "sumo.exe"
        if candidate_exe.exists():
            return str(candidate_exe)
    raise RuntimeError("could not find 'sumo' binary")


def get_sumocfg_path(demand: str) -> str:
    base = Path("scenarios/demand/vijayawada")
    if demand == "medium":
        return str(base / "vijayawada_corridor.sumocfg")
    else:
        return str(base / f"vijayawada_corridor_{demand}.sumocfg")


def run_simulation(
    sumo_binary: str,
    sumocfg_path: str,
    seed: int,
    output_parquet: str,
    adjacency_list: dict,
    nodes: list,
    incident_injector: IncidentInjector = None,
    output_labels: str = None
):
    cmd = [
        sumo_binary,
        "-c", sumocfg_path,
        "--seed", str(seed),
        "--step-length", "1",
        "--no-step-log", "true",
        "--time-to-teleport", "-1"
    ]
    
    traci.start(cmd)
    
    sim_duration = 1800
    if incident_injector:
        incident_injector.plan_injections(sim_duration=sim_duration)
        
    records = []
    
    for tick in range(sim_duration):
        traci.simulationStep()
        
        if incident_injector:
            incident_injector.apply_tick(tick)
            
        occupancies = {}
        for edge in nodes:
            occupancies[edge] = traci.edge.getLastStepOccupancy(edge) / 100.0
            
        for edge in nodes:
            occ = occupancies[edge]
            downstream = adjacency_list.get(edge, [])
            if downstream:
                recv_occ = sum(occupancies[d] for d in downstream) / len(downstream)
            else:
                recv_occ = 0.0
                
            queue_pcu = float(traci.edge.getLastStepHaltingNumber(edge))
            mean_speed_mps = traci.edge.getLastStepMeanSpeed(edge)
            vehicle_count = float(traci.edge.getLastStepVehicleNumber(edge))
            wait_time_s = traci.edge.getWaitingTime(edge)
            
            records.append({
                "tick": tick,
                "edge_id": edge,
                "queue_pcu": queue_pcu,
                "receiving_occupancy": recv_occ,
                "mean_speed_mps": mean_speed_mps,
                "occupancy": occ,
                "wait_time_s": wait_time_s,
                "vehicle_count": vehicle_count
            })
            
    traci.close()
    
    df = pd.DataFrame(records)
    Path(output_parquet).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_parquet, index=False)
    
    if incident_injector and output_labels:
        Path(output_labels).parent.mkdir(parents=True, exist_ok=True)
        with open(output_labels, "w") as f:
            json.dump(incident_injector.ground_truth, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, default="data/m6")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--demand-levels", type=str, default="light,medium,heavy")
    args = parser.parse_args()

    # Pre-build graph
    net_path = "scenarios/networks/vijayawada/vijayawada_corridor.net.xml"
    adj_out = os.path.join(args.output_dir, "adjacency.json")
    build_graph(net_path, adj_out, "vijayawada_corridor", False)
    
    with open(adj_out, "r") as f:
        graph_data = json.load(f)
        
    adjacency_list = graph_data["adjacency_list"]
    nodes = graph_data["nodes"]

    sumo_binary = _resolve_sumo_binary()
    demands = args.demand_levels.split(",")

    for demand in demands:
        sumocfg_path = get_sumocfg_path(demand.strip())
        for seed in range(args.seeds):
            print(f"Running {demand} seed {seed} (normal)...")
            normal_out = os.path.join(args.output_dir, "normal", f"{demand}_{seed}.parquet")
            run_simulation(
                sumo_binary, sumocfg_path, seed, normal_out, adjacency_list, nodes,
                incident_injector=None
            )
            
            print(f"Running {demand} seed {seed} (incident)...")
            incident_out = os.path.join(args.output_dir, "incident", f"{demand}_{seed}.parquet")
            labels_out = os.path.join(args.output_dir, "incident", f"{demand}_{seed}_labels.json")
            
            injector = IncidentInjector(net_path, random.Random(seed))
            run_simulation(
                sumo_binary, sumocfg_path, seed, incident_out, adjacency_list, nodes,
                incident_injector=injector, output_labels=labels_out
            )

if __name__ == "__main__":
    main()

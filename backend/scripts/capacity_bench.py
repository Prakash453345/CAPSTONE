#!/usr/bin/env python3
"""Capacity benchmark: how many junctions / vehicles can this machine simulate?

Builds square signalised grids (N x N junctions) with netgenerate, loads them
with random demand, and runs SUMO under TraCI with a per-step controller-style
workload (reads halting counts on every controlled lane of every junction each
step, which is what a pressure-based controller does). For each size it reports
the real-time factor (RTF = simulated seconds / wall seconds; >1 means faster
than real time), peak and mean vehicles on the road, ms per step, and peak SUMO
memory. It stops growing the grid once RTF drops below --stop-rtf.

Run natively on the Mac, from backend/, with the project venv:
    source .venv/bin/activate
    python scripts/capacity_bench.py            # default sweep
    python scripts/capacity_bench.py --quick    # a few minutes instead of ~20
Tips: plug in power, close other apps, stop the Docker stack. The results are
also written to scripts/capacity_bench_results.json.

Reads/writes only temp files plus that one JSON; touches nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _sysctl(name: str) -> str:
    try:
        return subprocess.check_output(["sysctl", "-n", name], text=True).strip()
    except Exception:
        return "?"


def machine_info() -> dict:
    mem = _sysctl("hw.memsize")
    return {
        "chip": _sysctl("machdep.cpu.brand_string"),
        "ram_gb": round(int(mem) / 2**30, 1) if mem.isdigit() else None,
        "cpu_count": os.cpu_count(),
        "os": platform.platform(),
        "python": platform.python_version(),
    }


def sumo_tools_dir() -> Path:
    try:
        import sumo  # eclipse-sumo wheel

        return Path(sumo.SUMO_HOME) / "tools"
    except Exception:
        home = os.environ.get("SUMO_HOME")
        if not home:
            sys.exit("Cannot find SUMO. Activate the project venv (eclipse-sumo) or set SUMO_HOME.")
        return Path(home) / "tools"


def child_rss_mb() -> float:
    # macOS reports ru_maxrss in bytes, Linux in KiB.
    r = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return r / 2**20 if sys.platform == "darwin" else r / 1024


def run_one(n: int, rate: int, duration: int, control: bool, work: Path, tools: Path) -> dict:
    import sumolib
    import traci

    net = work / f"g{n}.net.xml"
    rou = work / f"g{n}_{rate}.rou.xml"
    trips = work / f"g{n}_{rate}.trips.xml"
    env = dict(os.environ, SUMO_HOME=str(tools.parent))

    subprocess.run(
        [
            sumolib.checkBinary("netgenerate"), "--grid", "--grid.number", str(n),
            "--grid.length", "150", "--default.lanenumber", "2",
            "--default-junction-type", "traffic_light", "--no-turnarounds", "true",
            "-o", str(net), "--no-warnings", "true",
        ],
        check=True, capture_output=True, env=env,
    )
    period = 3600.0 / (rate * n * n)
    subprocess.run(
        [
            sys.executable, str(tools / "randomTrips.py"), "-n", str(net),
            "-o", str(trips), "-r", str(rou), "-b", "0", "-e", str(duration),
            "-p", f"{period:.6f}", "--seed", "1",
        ],
        check=True, capture_output=True, env=env,
    )

    traci.start(
        [
            sumolib.checkBinary("sumo"), "-n", str(net), "-r", str(rou),
            "--no-step-log", "true", "--no-warnings", "true",
            "--time-to-teleport", "300", "--seed", "1", "--step-length", "1",
        ]
    )
    tls_ids = traci.trafficlight.getIDList()
    lanes = {t: sorted(set(traci.trafficlight.getControlledLanes(t))) for t in tls_ids}
    peak = total = 0
    t0 = time.perf_counter()
    for _ in range(duration):
        traci.simulationStep()
        count = traci.vehicle.getIDCount()
        peak = max(peak, count)
        total += count
        if control:
            for t in tls_ids:
                _ = sum(traci.lane.getLastStepHaltingNumber(ln) for ln in lanes[t])
                _ = traci.trafficlight.getPhase(t)
    wall = time.perf_counter() - t0
    traci.close()
    return {
        "junctions": len(tls_ids),
        "grid": f"{n}x{n}",
        "rate_per_junction_hour": rate,
        "peak_vehicles": peak,
        "mean_vehicles": round(total / duration),
        "wall_s": round(wall, 1),
        "rtf": round(duration / wall, 2),
        "ms_per_step": round(1000 * wall / duration, 1),
        "peak_sumo_rss_mb": round(child_rss_mb()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grids", default="3,5,8,12,16,24,32", help="grid sides N (N*N junctions), ascending")
    ap.add_argument("--rates", default="300,800,1500", help="veh/h inserted per junction (light,medium,heavy)")
    ap.add_argument("--duration", type=int, default=600, help="simulated seconds per run")
    ap.add_argument("--stop-rtf", type=float, default=1.0, help="stop growing a load level below this RTF")
    ap.add_argument("--no-control", action="store_true", help="skip the per-step TraCI controller workload")
    ap.add_argument("--quick", action="store_true", help="fewer sizes, 300 s runs")
    a = ap.parse_args()
    if a.quick:
        a.grids, a.rates, a.duration = "3,6,10,16", "300,1000", 300

    tools = sumo_tools_dir()
    info = machine_info()
    print("Machine:", json.dumps(info))
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for rate in (int(r) for r in a.rates.split(",")):
            print(f"\n== load: {rate} veh/h per junction ==")
            print(f"{'grid':>6} {'junc':>5} {'peak veh':>9} {'mean veh':>9} {'RTF':>7} {'ms/step':>8} {'RSS MB':>7}")
            for n in (int(g) for g in a.grids.split(",")):
                try:
                    r = run_one(n, rate, a.duration, not a.no_control, work, tools)
                except Exception as e:  # keep going, record the failure
                    print(f"{n}x{n}: failed: {e}")
                    break
                rows.append(r)
                print(
                    f"{r['grid']:>6} {r['junctions']:>5} {r['peak_vehicles']:>9} {r['mean_vehicles']:>9} "
                    f"{r['rtf']:>7} {r['ms_per_step']:>8} {r['peak_sumo_rss_mb']:>7}"
                )
                if r["rtf"] < a.stop_rtf:
                    print(f"  RTF below {a.stop_rtf}: stopping this load level.")
                    break
    out = Path(__file__).with_name("capacity_bench_results.json")
    out.write_text(json.dumps({"machine": info, "duration_s": a.duration, "rows": rows}, indent=2))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()

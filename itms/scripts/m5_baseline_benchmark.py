"""Frozen M5 traffic-coordination benchmark -- a reproducible baseline to
compare future code changes against.

Runs three arms, fresh, on the same held-out EVAL_SEEDS and demand levels:

    webster   tuned fixed-time baseline
    ceiling   A-CA-MP + 1.25x per-phase Webster ceiling, supervisor OFF
    ccacamp   same ceiling, cycle supervisor ON  (the current M5 controller)

Unlike m5_ccacamp_gate.py this re-runs Webster instead of reading it from an
older artifact, so every number in the output comes from one code version
and one SUMO build.

Usage:
    python scripts/m5_baseline_benchmark.py --out results/my_run.json
    python scripts/compare_m5_baseline.py BASELINE.json NEW.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from m5_ccacamp_gate import _ARMS, CEILING_FACTOR, paired  # noqa: E402
from m5_cycle_ceiling_probe import configs_with_ceiling  # noqa: E402

ARMS = ("webster", "ceiling", "ccacamp")
METRICS = ("person_delay_s", "stops_per_vehicle", "person_throughput_per_hour")


def _job(args) -> dict:
    arm, level, seed = args
    t0 = time.time()
    tdir = Path(f"/tmp/m5_baseline_tripinfo/{arm}")
    if arm == "webster":
        rec = H.run_one("webster", level, seed, tripinfo_dir=tdir)
    else:
        rec = H.run_one(
            "acamp", level, seed, tripinfo_dir=tdir, acamp_cfg=_ARMS[arm],
            record_memory=False,
            inputs=configs_with_ceiling(H.scenario_inputs(level), CEILING_FACTOR),
        )
    rec["arm"] = arm
    rec["wall_s"] = round(time.time() - t0, 1)
    return rec


def summarize(records: list[dict]) -> dict:
    out: dict = {}
    levels = [lv for lv in ("light", "medium", "heavy")
              if any(r["demand_level"] == lv for r in records)]
    for level in levels:
        by = {a: {r["seed"]: r for r in records
                  if r["arm"] == a and r["demand_level"] == level} for a in ARMS}
        lv: dict = {"arms": {}, "paired": {}}
        for a, runs in by.items():
            if not runs:
                continue
            v = list(runs.values())
            lv["arms"][a] = {
                "n": len(v),
                "person_delay_s": st.fmean(r["person_delay_s"] for r in v),
                "p95_wait_s": st.fmean(r["wait_time_s"]["p95_s"] for r in v),
                "max_wait_s": st.fmean(r["wait_time_s"]["max_s"] for r in v),
                "stops_per_vehicle": st.fmean(r["stops_per_vehicle"] for r in v),
                "person_throughput_per_hour":
                    st.fmean(r["person_throughput_per_hour"] for r in v),
                "interlock_violations": sum(r["interlock_violations"] for r in v),
            }
        for base in ("webster", "ceiling"):
            for key in METRICS[:2]:
                if by[base] and by["ccacamp"]:
                    lv["paired"][f"ccacamp_vs_{base}:{key}"] = paired(
                        by[base], by["ccacamp"], key)
        out[level] = lv
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="light,medium,heavy")
    ap.add_argument("--seeds", type=int, default=len(H.EVAL_SEEDS))
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    levels = [x for x in args.levels.split(",") if x]
    seeds = H.EVAL_SEEDS[: args.seeds]
    jobs = [(a, lv, s) for lv in levels for a in ARMS for s in seeds]
    print(f"{len(jobs)} runs: arms {ARMS} x levels {levels} x seeds {seeds}", flush=True)

    t0 = time.time()
    records: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for rec in pool.map(_job, jobs):
            records.append(rec)
            print(f"[{len(records)}/{len(jobs)}] {rec['arm']:8s} {rec['demand_level']:6s} "
                  f"seed={rec['seed']:2d} delay={rec['person_delay_s']:>12,.0f} "
                  f"stops={rec['stops_per_vehicle']:.2f} viol={rec['interlock_violations']} "
                  f"({rec['wall_s']:.0f}s)", flush=True)

    from importlib.metadata import version  # noqa: PLC0415
    payload = {
        "meta": {
            "created_unix": int(time.time()),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "sumo_version": version("eclipse-sumo"),
            "ceiling_factor": CEILING_FACTOR,
            "seeds": seeds, "levels": levels, "arms": list(ARMS),
            "wall_min": round((time.time() - t0) / 60, 1),
        },
        "summary": summarize(records),
        "records": records,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=1, default=str))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

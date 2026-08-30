"""Does the demand memory actually earn its place? The experiment that
answers it, and the reason it has to exist.

**The problem this addresses.** M5's gate runs on SUMO ground truth, so
`JunctionContext.confidence` is empty at every movement, `select_mode`
returns "camp_full" on every tick, and the memory-blending rung never
executes -- the gate's own `decision_stats` report `blended: 0`. A
milestone that shipped a demand profile and then measured it in a regime
where it is dormant would be claiming credit for dead code. That is
exactly the failure mode `camp.py` avoided by refusing to half-implement
"camp_blended" against data that did not exist; the same standard applies
now that the data does.

**What is simulated, precisely.** M8's vision pipeline is what would ever
produce `confidence < 1.0` for a real movement: a camera with rain on the
lens, a night scene, an occluded approach. This script injects a fixed
confidence at every movement to stand in for that, and compares two arms
that are identical except for whether a historical profile is available
to fall back on:

    memory ON  -- degraded live state blended toward this junction's own
                  historical profile for this time of day
    memory OFF -- degraded live state used as-is

Both arms are A-CA-MP with identical parameters, so the difference is
attributable to the memory and nothing else.

**Why a wrapper rather than a `run_controlled_scenario` parameter.**
Sensor degradation is an experimental *treatment*, not a production
feature -- no real deployment wants a knob that makes its cameras worse.
Injecting it by wrapping the strategy keeps it entirely inside this
script, where a reader can see the whole manipulation in one place, and
leaves the runner with no code path that exists only for an experiment.

**What this cannot show.** A fixed confidence across all movements and
all time is not what real sensor degradation looks like -- real failures
are bursty, spatially correlated, and correlated with exactly the
conditions (rain, dusk) that also change demand. This measures whether
the fallback mechanism works and helps, not how much it would help in a
real outage. Stated rather than left for a reader to assume.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from itms_domain import JunctionContext, SignalPlan, Tier0Config  # noqa: E402
from sim_service.control import bench_stats  # noqa: E402
from sim_service.control.memory import DemandMemory  # noqa: E402
from sim_service.control.strategies import acamp  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402

_RESULTS_PATH = Path(__file__).resolve().parent / "m5_sensor_degradation_results.json"


class DegradedSensor:
    """Stamps a fixed `confidence` on every movement before delegating.

    Forwards `set_sim_time` explicitly rather than via `__getattr__`,
    because `runner.py` detects a time-aware strategy with `hasattr`, and
    a `__getattr__`-based proxy would answer `hasattr` truthfully for
    every attribute name including ones the inner object lacks -- a
    proxy that lies about its interface is a bad thing to put underneath
    an experiment whose whole purpose is attributing a difference to one
    cause."""

    def __init__(self, inner: acamp.AdaptiveCamp, confidence: float):
        self.inner = inner
        self.confidence = confidence

    def set_sim_time(self, sim_time_s: float) -> None:
        self.inner.set_sim_time(sim_time_s)

    @property
    def stats(self) -> dict[str, int]:
        return self.inner.stats

    def __call__(self, cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        movements = frozenset().union(*(p.green_movements for p in cfg.phases.values()))
        return self.inner(cfg, replace(ctx, confidence=dict.fromkeys(movements, self.confidence)))


def _job(args) -> dict:
    arm, level, seed, confidence, cfg_path, mem_path = args
    acamp_cfg = load_config(cfg_path) if cfg_path else None
    memory = DemandMemory.load(mem_path) if (arm == "memory_on" and mem_path) else None

    inputs = H.scenario_inputs(level)
    configs, flows, _, _ = inputs
    inner = H.build_acamp(configs, flows, acamp_cfg=acamp_cfg, demand_memory=memory)
    strategy = {tls: DegradedSensor(ctrl, confidence) for tls, ctrl in inner.items()}

    # Bypass `H.run_one`'s own strategy construction -- this experiment
    # needs the wrapper in between, which is the one thing the shared
    # harness deliberately does not know about.
    original = H.CONTROLLERS["acamp"]
    H.CONTROLLERS["acamp"] = lambda *a, **k: strategy
    try:
        started = time.time()
        record = H.run_one(
            "acamp", level, seed, tripinfo_dir=Path("/tmp/m5_degr"), inputs=inputs
        )
    finally:
        H.CONTROLLERS["acamp"] = original
    record["arm"] = arm
    record["confidence"] = confidence
    record["wall_s"] = round(time.time() - started, 1)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory", default=str(H.ARTIFACT_DIR / "demand_memory.json"))
    parser.add_argument("--tuned-config", default=None)
    parser.add_argument("--confidence", type=float, default=0.6,
                        help="0.5..0.8 lands on the camp_blended rung")
    parser.add_argument("--levels", default="light,medium")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 2))
    args = parser.parse_args()

    levels = [x for x in args.levels.split(",") if x]
    seeds = H.EVAL_SEEDS[: args.seeds]
    jobs = [
        (arm, level, seed, args.confidence, args.tuned_config, args.memory)
        for level in levels
        for arm in ("memory_on", "memory_off")
        for seed in seeds
    ]
    print(f"sensor degradation: confidence={args.confidence} at every movement")
    print(f"{len(jobs)} runs, eval seeds {seeds}\n", flush=True)

    records = []
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for r in pool.map(_job, jobs):
            records.append(r)
            blended = r.get("decision_stats", {}).get("blended", 0)
            fallback = r.get("decision_stats", {}).get("fallback_fixed_time", 0)
            print(
                f"[{len(records)}/{len(jobs)}] {r['arm']:10s} {r['demand_level']:6s} "
                f"seed={r['seed']:2d} delay={r['person_delay_s']:>12,.0f} "
                f"viol={r['interlock_violations']:<4d} blended={blended:<6d} "
                f"fixedtime={fallback}",
                flush=True,
            )

    summary = {}
    for level in levels:
        summary[level] = {}
        for arm in ("memory_on", "memory_off"):
            rows = [r for r in records if r["demand_level"] == level and r["arm"] == arm]
            ci = bench_stats.confidence_interval_95([r["person_delay_s"] for r in rows])
            summary[level][arm] = {
                "person_delay_mean_s": ci.mean,
                "person_delay_ci95_half_s": ci.half_width_95,
                "interlock_violations_total": sum(r["interlock_violations"] for r in rows),
                "blended_ticks_total": sum(
                    r.get("decision_stats", {}).get("blended", 0) for r in rows
                ),
                "seeds": len(rows),
            }

    _RESULTS_PATH.write_text(
        json.dumps({"confidence": args.confidence, "summary": summary, "runs": records}, indent=2)
    )
    print("\n" + "=" * 72)
    for level in levels:
        on = summary[level]["memory_on"]
        off = summary[level]["memory_off"]
        delta = (off["person_delay_mean_s"] - on["person_delay_mean_s"]) / off["person_delay_mean_s"]
        print(
            f"{level:8s} memory ON {on['person_delay_mean_s']:>12,.0f} +/- "
            f"{on['person_delay_ci95_half_s']:>8,.0f}   OFF "
            f"{off['person_delay_mean_s']:>12,.0f} +/- {off['person_delay_ci95_half_s']:>8,.0f}"
            f"   delta {delta:+.1%}"
        )
    print(f"\nwrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()

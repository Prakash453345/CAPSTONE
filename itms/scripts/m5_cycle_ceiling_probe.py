"""Does bounding the cycle actually recover the loss? The cheap test.

`m5_medium_cycle_diagnostic.py` found a monotonic dose-response across
three demand levels: the further A-CA-MP's emergent cycle sits above
Webster's delay-minimising optimum, the worse it does.

    level    Webster optimum   A-CA-MP emergent   ratio    vs Webster
    light         40.0 s            70.8 s        1.77x     +43.4%
    medium        42.1 s            59.1 s        1.40x     +25.7%
    heavy        104.1 s            76.7 s        0.74x      -4.2%

That is a correlation over three points. Before building a cycle
supervisor to act on it, this tests the causal claim the cheap way --
with a parameter that already exists, is already enforced by the
interlocks, and requires no new code in the control path.

**Why `max_green_s` is the right instrument.** It is currently a flat
**90 s** for every phase of every junction: a safety constant, never
derived from demand. Against a mean green of ~26 s it essentially never
binds -- `switch_max_green` accounts for **0.3%** of ticks. So the
controller today has a cycle ceiling in name only.

Lowering it per phase to a multiple of *that phase's own Webster green*
is the crudest possible version of the proposed supervisor: a hard
ceiling, no intelligence, no choice of successor phase. If the crude
version recovers most of the loss, the intelligent version is justified.
If it recovers nothing, cycle length is not the mechanism and the
supervisor would not have helped either.

**Read the result asymmetrically.** This is a *strong confirm and a weak
reject*. A ceiling can only time a phase out; it cannot pick the best
safe competing phase, which is the half of the supervisor that does the
real work. A positive result is strong evidence for building it. A null
result rules out the crude mechanism, not the intelligent one.

**Heavy demand is the negative control**, and the prediction is specific:
a ceiling derived from Webster *cannot bind* at heavy, because Webster's
heavy cycle (104.1 s) is already longer than A-CA-MP's emergent one
(76.7 s). Heavy should come back unchanged. That matters beyond this
experiment: it demonstrates the ceiling is intrinsically **one-sided** --
it can shorten a cycle and never lengthen one -- which is the property
that stops a supervisor destroying the only demand level A-CA-MP wins at.

Nothing in `acamp.py` is edited. The ceiling is injected through the
`Tier0Config` the harness already passes to both the strategy and the
interlocks, so the thing measured is the shipped controller under a
different safety bound.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from itms_domain import Tier0Config  # noqa: E402
from sim_service.control.strategies import webster  # noqa: E402

ABSOLUTE_CEILING_S = 90.0
"""The shipped `max_green_s`. Kept as the upper clamp so no arm can ever
*raise* a ceiling above the value the safety configuration already
sanctions -- this probe only ever tightens."""


def webster_ceilings(
    cfg: Tier0Config, flows: dict, factor: float
) -> dict[str, float]:
    """Per-phase `max_green_s` at `factor` x that phase's Webster green.

    Clamped below by `min_green_s` (a ceiling under the floor is not a
    valid Tier-0 config, and `Tier0Config.validate` is entitled to reject
    it) and above by the shipped 90 s. At factor 1.0 a phase whose
    Webster green equals its minimum becomes effectively fixed -- that is
    a real consequence of the tightest arm, not a bug in it, and it is
    why the 1.25x arm exists alongside."""
    timing = webster.compute_timing(cfg, flows)
    greens = getattr(timing, "green_s", None) or {}
    out: dict[str, float] = {}
    for phase_id in cfg.ring_order:
        floor = cfg.min_green_s.get(phase_id, 0.0)
        target = greens.get(phase_id)
        if target is None:
            out[phase_id] = cfg.max_green_s.get(phase_id, ABSOLUTE_CEILING_S)
            continue
        out[phase_id] = min(ABSOLUTE_CEILING_S, max(floor, factor * target))
    return out


def configs_with_ceiling(inputs, factor: float | None):
    """`inputs` with every junction's `max_green_s` replaced. `factor`
    None means the shipped configuration, untouched."""
    configs, flows, vtype_pcu, paths = inputs
    if factor is None:
        return inputs
    tightened = {
        tls_id: replace(cfg, max_green_s=webster_ceilings(cfg, flows.get(tls_id, {}), factor))
        for tls_id, cfg in configs.items()
    }
    return tightened, flows, vtype_pcu, paths


_ARMS: dict[str, float | None] = {
    "shipped_90s": None,
    "ceiling_1.25x": 1.25,
    "ceiling_1.00x": 1.00,
}
"""Default arms: the confirmation experiment, run on `EVAL_SEEDS`.

`--factors` and `--seed-set train` switch this script into *selection*
mode, which is a different job with a different rule attached. The
confirmation above is leakage-free because both factors recover roughly
the same amount -- the finding is about the mechanism, not the number.
**Choosing between factors is not**, and must happen on `TRAIN_SEEDS`
before the chosen one is re-verified on the held-out set. Same discipline
`m5_protect_threshold_sweep.py` used, for the same reason."""


def _job(args) -> dict:
    arm, level, seed, factor = args
    inputs = configs_with_ceiling(H.scenario_inputs(level), factor)
    started = time.time()
    record = H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_ceiling_tripinfo"),
        record_memory=False,
        inputs=inputs,
    )
    record["arm"] = arm
    record["wall_s"] = round(time.time() - started, 1)
    return record


def emergent_cycle(record: dict, n_junctions: int, phases: float) -> float:
    s = record.get("decision_stats") or {}
    sw = (
        s.get("switch_pressure", 0)
        + s.get("switch_max_green", 0)
        + s.get("switch_starvation", 0)
    ) / n_junctions
    return ((s.get("ticks", 0) / n_junctions) / sw) * phases if sw else 0.0


_T_CRIT = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447,
           8: 2.365, 9: 2.306, 10: 2.262, 20: 2.093, 30: 2.045}


def _t(n: int) -> float:
    """Two-sided t(0.975) at df = n-1. Tabulated rather than assumed:
    the selection sweep runs 5 seeds, where the right value is 2.776 and
    the n=10 constant this function replaced (2.262) would have widened
    every interval's claim to significance by 20%."""
    return _T_CRIT.get(n, 2.045)


def paired(a: dict[int, dict], b: dict[int, dict], key: str) -> dict:
    seeds = sorted(set(a) & set(b))
    diffs = [b[s][key] - a[s][key] for s in seeds]
    mean = st.fmean(diffs)
    if len(diffs) < 2:
        return {"n": len(diffs), "mean": mean}
    half = _t(len(diffs)) * st.stdev(diffs) / len(diffs) ** 0.5
    base = st.fmean(a[s][key] for s in seeds)
    return {
        "n": len(diffs),
        "mean": mean,
        "pct": 100.0 * mean / base if base else None,
        "ci95": [mean - half, mean + half],
        "significant": (mean - half) * (mean + half) > 0,
        "n_better": sum(1 for d in diffs if d < 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", default="light,medium,heavy")
    parser.add_argument("--seeds", type=int, default=len(H.EVAL_SEEDS))
    parser.add_argument(
        "--seed-set", default="eval", choices=["eval", "train"],
        help="'train' switches to selection mode -- choosing a factor must "
             "never happen on the held-out evaluation seeds",
    )
    parser.add_argument(
        "--factors", default=None,
        help="comma-separated ceiling factors, e.g. '0.75,1.0,1.25,1.5,2.0'. "
             "Omit for the default confirmation arms.",
    )
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parent / "m5_artifacts" / "m5_cycle_ceiling_probe.json"
        ),
    )
    args = parser.parse_args()

    levels = [x for x in args.levels.split(",") if x]
    pool_seeds = H.TRAIN_SEEDS if args.seed_set == "train" else H.EVAL_SEEDS
    seeds = pool_seeds[: args.seeds]

    arms: dict[str, float | None] = dict(_ARMS)
    if args.factors:
        arms = {f"ceiling_{float(f):.2f}x": float(f) for f in args.factors.split(",") if f}
    jobs = [(arm, level, seed, arms[arm]) for level in levels for arm in arms for seed in seeds]
    mode = "SELECTION (training seeds)" if args.seed_set == "train" else "CONFIRMATION (held-out)"
    print(f"cycle-ceiling probe -- {mode}: {len(jobs)} runs "
          f"({len(arms)} arms x {len(levels)} levels x {len(seeds)} seeds)")
    print(f"{args.seed_set} seeds {seeds}")
    print(f"arms: {', '.join(f'{k}={v}' for k, v in arms.items())}\n", flush=True)

    records: list[dict] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for record in pool.map(_job, jobs):
            records.append(record)
            done = len(records)
            rate = (time.time() - started) / done
            print(
                f"[{done}/{len(jobs)}] {record['arm']:14s} {record['demand_level']:6s} "
                f"seed={record['seed']:3d}  delay={record['person_delay_s']:>12,.0f}  "
                f"viol={record['interlock_violations']:<3d} "
                f"({record['wall_s']:.0f}s, eta {rate * (len(jobs) - done) / 60:.0f}m)",
                flush=True,
            )

    # -- report ---------------------------------------------------------
    summary: dict = {}
    for level in levels:
        configs, flows, _v, _p = H.scenario_inputs(level)
        n_j = len(configs)
        phases = st.fmean(len(c.ring_order) for c in configs.values())
        wc = st.fmean(
            webster.compute_timing(c, flows.get(t, {})).cycle_s for t, c in configs.items()
        )
        by_arm = {
            arm: {r["seed"]: r for r in records if r["arm"] == arm and r["demand_level"] == level}
            for arm in arms
        }
        # The reference is the shipped arm when present, else the loosest
        # ceiling -- in selection mode there is no shipped arm to anchor to.
        reference = "shipped_90s" if "shipped_90s" in by_arm else max(
            arms, key=lambda a: arms[a] or 0.0
        )
        print(f"\n{'=' * 78}\n{level.upper()}   (Webster optimum cycle {wc:.1f}s)\n{'=' * 78}")
        print(f"{'arm':14s} {'delay':>12s} {'cycle':>8s} {'ratio':>7s} "
              f"{'stops':>7s} {'viol':>5s}  vs {reference}")
        level_summary = {}
        for arm in arms:
            runs = by_arm[arm]
            if not runs:
                continue
            delay = st.fmean(r["person_delay_s"] for r in runs.values())
            cyc = st.fmean(emergent_cycle(r, n_j, phases) for r in runs.values())
            stops = st.fmean(r["stops_per_vehicle"] for r in runs.values())
            viol = sum(r["interlock_violations"] for r in runs.values())
            cmp_txt = ""
            if arm != reference and by_arm.get(reference):
                c = paired(by_arm[reference], runs, "person_delay_s")
                ci = c.get("ci95")
                cmp_txt = (
                    f"{c['mean']:+,.0f} ({c.get('pct', 0):+.1f}%) "
                    + (f"[{ci[0]:+,.0f}, {ci[1]:+,.0f}] " if ci else "")
                    + ("SIG" if c.get("significant") else "n.s.")
                    + f" {c.get('n_better', 0)}/{c['n']} better"
                )
                level_summary[arm] = c
            print(f"{arm:14s} {delay:12,.0f} {cyc:7.1f}s {cyc / wc:6.2f}x "
                  f"{stops:7.2f} {viol:5d}  {cmp_txt}")
        summary[level] = {"webster_cycle_s": wc, "reference_arm": reference,
                          "paired_vs_reference": level_summary}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"records": records, "summary": summary}, indent=1, default=str)
    )
    print(f"\nwrote {args.out}   total wall {(time.time() - started) / 60:.0f} min")


if __name__ == "__main__":
    main()

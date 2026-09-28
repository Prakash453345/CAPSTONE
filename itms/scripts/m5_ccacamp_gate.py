"""CC-A-CAMP gate: does the supervisor earn its keep over a static ceiling?

The question has narrowed twice, and the narrowing is the point. It began
as "why does A-CA-MP lose to a 1958 fixed-time formula". Re-measurement
under the fixed cabinet showed the losses were real and larger than
recorded (+43.4% at light, +25.7% at medium). The diagnosis found an
emergent cycle nothing bounded, with delay tracking the ratio to
Webster's optimum monotonically across all three demand levels. A static
per-phase ceiling at 1.25x Webster's green then recovered the whole loss
and more -- A-CA-MP beats Webster at every demand level with no change to
the controller at all.

So the supervisor is no longer being asked to fix a broken controller. It
is being asked whether **online cyclical structure beats an offline
bound**, which is a much narrower claim and the only honest way to
justify the extra machinery.

Three arms, paired on the same held-out seeds:

    webster    the baseline, from the post-cabinet-fix gate
    ceiling    1.25x per-phase Webster ceiling, supervisor OFF
    ccacamp    the same ceiling, supervisor ON

`ceiling` is the arm that matters. Beating Webster is already done;
beating `ceiling` is what decides whether CC-A-CAMP is a contribution or
an ornament.

**Two things are being measured, and they are not the same thing.**

1. *Delay.* The prior is that the supervisor adds little here, because
   the ceiling already brought the cycle inside the envelope -- at 1.25x
   the measured ratios were 0.94x/0.85x/0.53x, all at or under Webster's
   optimum. A supervisor that fires rarely cannot move a mean much.

2. *Safety.* This is where it should pay. Heavy demand's
   `failsafe_interlock_rejected` events survive every ceiling factor
   tried (1, 3, 1, 2, 4 for factors 0.75x through 2.00x), because a bound
   on cycle *length* does not imply every phase is *served*.
   `m5_heavy_violation_diagnostic.py` traced every one of them to a
   single mechanism: a movement reaching its 452 s `max_wait_s` bound
   9.0 s into another phase's 10 s minimum green, where I3 forbids
   cutting the incumbent short and I5 must then reject the plan. Serving
   every phase inside a bounded cycle is what stops the wait getting
   there.

So a null result on delay with violations driven to zero is a *success*,
and reporting only the delay column would hide it. The MOE set follows
FHWA's adaptive-signal validation guidance, which cautions explicitly
against evaluating on average delay alone.

**The intervention rate is a headline number, not a diagnostic.** If the
supervisor fires on most phase ends then A-CA-MP has become Webster with
extra steps, the delay win belongs to the cycle reference rather than to
any real-time adaptation, and the honest conclusion is a different one
from the one the arm was built to support.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from m5_cycle_ceiling_probe import configs_with_ceiling, emergent_cycle  # noqa: E402
from sim_service.control.strategies import webster  # noqa: E402
from sim_service.control.strategies.acamp import AcampConfig  # noqa: E402

CEILING_FACTOR = 1.25
"""Chosen on `TRAIN_SEEDS`, where factors from 0.75x to 2.00x were
measured statistically indistinguishable, on the stated grounds that it
has a rationale expressible in one sentence ("Webster's green plus 25%
headroom"), ties for fewest heavy violations, and preserves more adaptive
range than the tighter factors. See PROGRESS.md -- the held-out numbers
confirm that choice rather than being its basis."""

_ARMS = {
    "ceiling": AcampConfig(cycle_supervisor=False),
    "ccacamp": AcampConfig(cycle_supervisor=True),
}

_T_CRIT = {3: 4.303, 5: 2.776, 10: 2.262, 20: 2.093, 30: 2.045}


def _t(n: int) -> float:
    return _T_CRIT.get(n, 2.045)


def _job(args) -> dict:
    arm, level, seed = args
    started = time.time()
    record = H.run_one(
        "acamp",
        level,
        seed,
        tripinfo_dir=Path("/tmp/m5_ccacamp_tripinfo"),
        acamp_cfg=_ARMS[arm],
        record_memory=False,
        inputs=configs_with_ceiling(H.scenario_inputs(level), CEILING_FACTOR),
    )
    record["arm"] = arm
    record["wall_s"] = round(time.time() - started, 1)
    return record


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


def _fmt(c: dict) -> str:
    ci = c.get("ci95")
    return (
        f"{c['mean']:+,.1f} ({c.get('pct', 0):+.1f}%) "
        + (f"[{ci[0]:+,.1f}, {ci[1]:+,.1f}] " if ci else "")
        + ("SIG " if c.get("significant") else "n.s.")
        + f" {c.get('n_better', 0)}/{c['n']}"
    )


def _webster_runs(level: str) -> dict[int, dict]:
    """Per-seed Webster from the post-cabinet-fix gates, so the baseline
    is the same measurement the rest of this work quotes rather than a
    fresh one that would differ by run-to-run noise alone."""
    out: dict[int, dict] = {}
    art = Path(__file__).resolve().parent / "m5_artifacts"
    for name in ("m5_gate_medium_postfix.json", "m5_gate_lightheavy_postfix.json"):
        path = art / name
        if not path.exists():
            continue
        for r in json.loads(path.read_text())["runs"]:
            if r["controller"] == "webster" and r["demand_level"] == level:
                out[r["seed"]] = r
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", default="light,medium,heavy")
    parser.add_argument("--seeds", type=int, default=len(H.EVAL_SEEDS))
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "m5_artifacts" / "m5_ccacamp_gate.json"),
    )
    args = parser.parse_args()

    levels = [x for x in args.levels.split(",") if x]
    seeds = H.EVAL_SEEDS[: args.seeds]
    jobs = [(arm, level, seed) for level in levels for arm in _ARMS for seed in seeds]
    print(f"CC-A-CAMP gate: {len(jobs)} runs "
          f"({len(_ARMS)} arms x {len(levels)} levels x {len(seeds)} seeds), "
          f"ceiling {CEILING_FACTOR}x")
    print(f"held-out eval seeds {seeds}\n", flush=True)

    records: list[dict] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for record in pool.map(_job, jobs):
            records.append(record)
            done = len(records)
            rate = (time.time() - started) / done
            s = record.get("decision_stats") or {}
            print(
                f"[{done}/{len(jobs)}] {record['arm']:8s} {record['demand_level']:6s} "
                f"seed={record['seed']:3d}  delay={record['person_delay_s']:>12,.0f}  "
                f"viol={record['interlock_violations']:<3d} "
                f"sup={s.get('switch_cycle_supervisor', 0):>4d} "
                f"({record['wall_s']:.0f}s, eta {rate * (len(jobs) - done) / 60:.0f}m)",
                flush=True,
            )

    summary: dict = {}
    for level in levels:
        configs, flows, _v, _p = H.scenario_inputs(level)
        n_j = len(configs)
        phases = st.fmean(len(c.ring_order) for c in configs.values())
        wc = st.fmean(
            webster.compute_timing(c, flows.get(t, {})).cycle_s for t, c in configs.items()
        )
        by = {
            a: {r["seed"]: r for r in records if r["arm"] == a and r["demand_level"] == level}
            for a in _ARMS
        }
        web = _webster_runs(level)

        print(f"\n{'=' * 92}\n{level.upper()}   (Webster optimum cycle {wc:.1f}s)\n{'=' * 92}")
        print(f"{'arm':9s} {'delay':>12s} {'p95 wait':>9s} {'max wait':>9s} "
              f"{'stops':>6s} {'cycle':>7s} {'viol':>5s} {'sup/switch':>11s}")
        for arm in ("webster", *_ARMS):
            runs = web if arm == "webster" else by[arm]
            if not runs:
                continue
            d = st.fmean(r["person_delay_s"] for r in runs.values())
            p95 = st.fmean(r["wait_time_s"]["p95_s"] for r in runs.values())
            mx = st.fmean(r["wait_time_s"]["max_s"] for r in runs.values())
            stops = st.fmean(r["stops_per_vehicle"] for r in runs.values())
            viol = sum(r["interlock_violations"] for r in runs.values())
            cyc = (
                st.fmean(emergent_cycle(r, n_j, phases) for r in runs.values())
                if arm != "webster" else wc
            )
            rate_txt = "-"
            if arm != "webster":
                sup = sum((r["decision_stats"] or {}).get("switch_cycle_supervisor", 0)
                          for r in runs.values())
                sw = sum(
                    sum((r["decision_stats"] or {}).get(k, 0)
                        for k in ("switch_pressure", "switch_max_green",
                                  "switch_starvation", "switch_cycle_supervisor"))
                    for r in runs.values()
                )
                rate_txt = f"{100 * sup / sw:.1f}%" if sw else "-"
            print(f"{arm:9s} {d:12,.0f} {p95:9.1f} {mx:9.1f} {stops:6.2f} "
                  f"{cyc:6.1f}s {viol:5d} {rate_txt:>11s}")

        level_summary = {}
        for base_name, base in (("webster", web), ("ceiling", by["ceiling"])):
            if not base:
                continue
            for key in ("person_delay_s", "stops_per_vehicle"):
                c = paired(base, by["ccacamp"], key)
                level_summary[f"ccacamp_vs_{base_name}:{key}"] = c
                print(f"  ccacamp vs {base_name:8s} {key:20s} {_fmt(c)}")
        summary[level] = level_summary

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"ceiling_factor": CEILING_FACTOR, "records": records, "summary": summary},
                   indent=1, default=str)
    )
    print(f"\nwrote {args.out}   total wall {(time.time() - started) / 60:.0f} min")


if __name__ == "__main__":
    main()

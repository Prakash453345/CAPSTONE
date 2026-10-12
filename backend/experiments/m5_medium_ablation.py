"""Why does A-CA-MP lose at medium demand, *after* the cabinet fix?

The question is new even though it sounds old. Medium demand has been an
open thread since M4, but every previous investigation ran against a
corridor whose `TraCICabinet` wrote `'G'` for nine movements the network
marks `'g'` -- removing the yield obligation, and with it handing those
movements capacity they were never entitled to. The fix is in; the
numbers were never re-taken. They have now been:

    medium, 10 EVAL_SEEDS, paired        person-delay vs Webster
    before the cabinet fix               +15.9%   (overlapping CIs, "a tie")
    after  the cabinet fix               +25.7%   [+33,819, +65,503], 10/10 seeds

So medium is not a tie and never was one -- the tie was an artefact of a
safety defect inflating the network's capacity. That reframes the
investigation: there is a real, consistent, 25% loss to explain, not a
coin-flip.

**The hypothesis this script tests.** The post-fix gate's own decision
counters show `extend_allocation_protected` firing **330 times per run**
at medium. That should be impossible on the record: `protect_allocated_
green` is gated on `congestion_weight >= 0.5`, and
`m5_congestion_profile.py` measured medium's busiest junction peaking at
only 0.339. The gate was tuned on heavy-demand data and medium was
verified never to reach it.

The cabinet fix is what changed. Removing nine movements' unearned
capacity lengthens the queues those movements feed, which raises the
smoothed load the congestion weight reads, which pushes medium over a
threshold it previously sat below. **A safety fix moved medium demand
into a regime whose mechanism was only ever verified at heavy demand.**

That matters because the mechanism was separately measured to be
*harmful* at medium when forced to fire: `m5_protect_threshold_sweep.py`
walked the threshold from 0.50 down to 0.10 and medium's delay got
monotonically worse at every step, three seeds out of three, as the
firing count rose from 223 to 445. Nobody acted on that, because at the
shipped 0.5 threshold medium never fired. It fires now.

So: run medium with the flag off, paired on the same seeds, and see.

Two arms only, one boolean between them, nothing tuned -- the same shape
`m5_protect_allocated_green_verify.py` used for the original heavy-demand
verification. `acamp.py` is not edited; the config is passed in, so the
thing measured is the thing that ships.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.control.strategies.acamp import AcampConfig  # noqa: E402

_T_CRIT = {3: 4.303, 5: 2.571, 10: 2.262, 20: 2.093, 30: 2.045}


def _t(n: int) -> float:
    """Two-sided t(0.975) at df = n-1, for the sample sizes this project
    actually uses. Falls back to the largest tabulated value rather than
    to 1.96, because using the normal quantile at n=10 is the mistake
    that turns an overlapping interval into a false positive."""
    return _T_CRIT.get(n, 2.045)


def run_arm(label: str, cfg: AcampConfig, level: str, seeds: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for seed in seeds:
        record = H.run_one(
            "acamp",
            level,
            seed,
            tripinfo_dir=Path("/tmp/m5_ablation_tripinfo"),
            acamp_cfg=cfg,
            demand_memory=None,
            record_memory=False,
        )
        out[seed] = record
        stats = record.get("decision_stats") or {}
        print(
            f"  {label:12s} seed={seed:3d}  delay={record['person_delay_s']:>11,.0f}  "
            f"stops={record['stops_per_vehicle']:.2f}  "
            f"protected={stats.get('extend_allocation_protected', 0):>6,d}  "
            f"switch_p={stats.get('switch_pressure', 0):>5,d}  "
            f"viol={record['interlock_violations']}",
            flush=True,
        )
    return out


def paired(a: dict[int, dict], b: dict[int, dict], key: str) -> dict:
    """`b - a` on the shared seeds. Paired because both arms ran the
    identical seed, so seed-to-seed variance -- which dominates this
    corridor -- cancels."""
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
        "n_worse": sum(1 for d in diffs if d > 0),
        "per_seed": {s: d for s, d in zip(seeds, diffs, strict=True)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", default="medium")
    parser.add_argument("--seeds", type=int, default=len(H.EVAL_SEEDS))
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parent / "m5_artifacts" / "m5_medium_ablation.json"
        ),
    )
    args = parser.parse_args()

    seeds = H.EVAL_SEEDS[: args.seeds]
    base = AcampConfig()
    arms = {
        "shipped": base,
        "no_protect": replace(base, protect_allocated_green=False),
    }
    print(f"medium ablation: {len(arms)} arms x {len(seeds)} seeds at {args.level} demand")
    print(f"eval seeds {seeds} (disjoint from TRAIN_SEEDS {H.TRAIN_SEEDS})\n", flush=True)

    results = {}
    for label, cfg in arms.items():
        print(f"{label}:", flush=True)
        results[label] = run_arm(label, cfg, args.level, seeds)

    print(f"\n{'=' * 74}")
    for key in ("person_delay_s", "stops_per_vehicle", "person_throughput_per_hour"):
        # Numeric run-level keys only. `wait_time_s` is a summary object
        # (p95/max), not a scalar, and feeding it to `fmean` is what the
        # first version of this loop did.
        if not isinstance(results["shipped"][seeds[0]].get(key), int | float):
            continue
        for label in arms:
            vals = [results[label][s][key] for s in seeds]
            print(f"{label:12s} {key:20s} {st.fmean(vals):12,.2f}")
        cmp = paired(results["shipped"], results["no_protect"], key)
        ci = cmp.get("ci95")
        print(
            f"  turning protection OFF: {cmp['mean']:+,.1f} "
            f"({cmp.get('pct', 0):+.1f}%)"
            + (f"  95% CI [{ci[0]:+,.1f}, {ci[1]:+,.1f}]" if ci else "")
            + f"  {'SIGNIFICANT' if cmp.get('significant') else 'not significant'}"
            + f"  ({cmp.get('n_worse', 0)}/{cmp['n']} seeds worse)\n"
        )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(
            {
                "level": args.level,
                "seeds": seeds,
                "runs": {k: {str(s): v for s, v in r.items()} for k, r in results.items()},
                "paired_no_protect_minus_shipped": {
                    key: paired(results["shipped"], results["no_protect"], key)
                    for key in ("person_delay_s", "stops_per_vehicle")
                    if isinstance(results["shipped"][seeds[0]].get(key), int | float)
                },
                "interlock_violations": {
                    label: {str(s): r[s]["interlock_violations"] for s in seeds}
                    for label, r in results.items()
                },
            },
            indent=1,
            default=str,
        )
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

"""Tables for the any-network gate: every scenario's closed-loop results, side
by side with the Vijayawada corridor's.

Each input is a `m8_closed_loop_gate.py` output run with `ITMS_SCENARIO`
pointing at a scenario from `scenarios/build_scenario.py`. Prints, per
scenario and demand level, Webster's and each other arm's mean person-delay,
the paired difference against Webster (and against perfect data for camera
arms), how many seeds were better, and interlock violations.

    python scripts/any_network_report.py results/generalize/*.json \\
        --scenario-dir scenarios/generated
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m5_ccacamp_gate import paired  # noqa: E402

LEVELS = ("light", "medium", "heavy")


def _fmt(c: dict) -> str:
    if not c or c.get("n", 0) < 2:
        return "--"
    sig = "**SIG**" if c["significant"] else "n.s."
    return f"{c['pct']:+.1f}% {sig} ({c['n_better']}/{c['n']})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--scenario-dir", default="scenarios/generated",
                    help="where each scenario's scenario.json is (for its description)")
    args = ap.parse_args()
    print("| scenario | junctions | phases | level | Webster | arm | mean | vs Webster "
          "| vs perfect data | violations |")
    print("|---|---:|---|---|---:|---|---:|---|---|---:|")
    for f in args.files:
        d = json.loads(Path(f).read_text())
        # the scenario each run was on (older files: the file name)
        name = next((r["scenario"] for r in d["records"] if r.get("scenario")), Path(f).stem)
        label = Path(f).stem
        man_p = Path(args.scenario_dir) / name / "scenario.json"
        man = json.loads(man_p.read_text()) if man_p.exists() else {}
        n_tls = man.get("signalised_junctions", "?")
        phases = sorted(set(man.get("phases_per_junction", [])))
        arms = [a for a in dict.fromkeys(r["arm"] for r in d["records"]) if a != "webster"]
        for level in LEVELS:
            by = {a: {r["seed"]: r for r in d["records"]
                      if r["arm"] == a and r["demand_level"] == level}
                  for a in ["webster", *arms]}
            if not by["webster"]:
                continue
            w = st.fmean(r["person_delay_s"] for r in by["webster"].values())
            for a in arms:
                runs = by[a]
                if not runs:
                    continue
                m = st.fmean(r["person_delay_s"] for r in runs.values())
                vt = _fmt(paired(by["truth"], runs, "person_delay_s")) \
                    if a != "truth" and by.get("truth") else ""
                viol = sum(r["interlock_violations"] for r in runs.values())
                print(f"| {label} | {n_tls} | {phases} | {level} | {w:,.0f} | {a} | {m:,.0f} "
                      f"| {_fmt(paired(by['webster'], runs, 'person_delay_s'))} | {vt} "
                      f"| {viol} |")


if __name__ == "__main__":
    main()

"""Tables for the counted-queue gate (M8 heavy-demand jam fix).

Reads a closed-loop gate output and prints, per demand level: every arm's
mean person-delay and worst run, the paired comparisons against ground truth
and Webster, each counting version against the camera system without
counting, the per-seed numbers, and the jam markers -- the longest wait any
vehicle had and how long the network took to empty. Seeds 1-5 are reported
apart from 6-10: seed 5 is the run the jam was traced on.

Arms: `...:nogap` is the camera system without counting (as it was before);
`...:count_v2` the second version, which reported every counted PCU; the
plain arm is the adopted version (only an edge's excess over 10 PCU).

    python scripts/m8_gap_report.py baselines/2026-09-29_m8_heavy_jam/closed_loop.json
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m5_ccacamp_gate import paired  # noqa: E402

GAP = "vision:itms6_640:failsafe"
V2 = "vision:itms6_640:failsafe:count_v2"
NOGAP = "vision:itms6_640:failsafe:nogap"
ALL_ARMS = ("webster", "truth", NOGAP, V2, GAP)
SHORT = {"webster": "Webster", "truth": "perfect data", NOGAP: "camera, no count (before)",
         V2: "camera, count v2", GAP: "camera, count (adopted)"}


def _pair(a: dict, b: dict, key: str) -> dict:
    return paired(a, b, key) if set(a) & set(b) else {}


def _fmt(c: dict) -> str:
    if not c or c.get("n", 0) < 2:
        return "--"
    sig = "**SIG**" if c["significant"] else "n.s."
    return f"{c['pct']:+.1f}% {sig} ({c['n_better']}/{c['n']} lower)"


def main() -> None:
    d = json.loads(Path(sys.argv[1]).read_text())
    recs = d["records"]
    for level in ("medium", "heavy"):
        by = {a: {r["seed"]: r for r in recs if r["arm"] == a and r["demand_level"] == level}
              for a in ALL_ARMS}
        if not by[GAP]:
            continue
        ARMS = tuple(a for a in ALL_ARMS if by[a])
        seeds_all = sorted({s for runs in by.values() for s in runs})
        print(f"\n## {level}\n")
        splits = [(f"seeds {seeds_all[0]}-{seeds_all[-1]}", seeds_all)]
        if seeds_all == list(range(1, 11)):
            splits += [("seeds 1-5", range(1, 6)), ("seeds 6-10", range(6, 11))]
        for label, seeds in splits:
            sub = {a: {s: r for s, r in runs.items() if s in seeds} for a, runs in by.items()}
            print(f"**{label}**\n")
            print("| arm | n | mean person-delay (s) | worst run | vs perfect data "
                  "| vs Webster | vs no count |")
            print("|---|---:|---:|---:|---|---|---|")
            for a in ARMS:
                runs = sub[a]
                if not runs:
                    continue
                v = [r["person_delay_s"] for r in runs.values()]
                vt = _fmt(_pair(sub["truth"], runs, "person_delay_s")) if a != "truth" else ""
                vw = _fmt(_pair(sub["webster"], runs, "person_delay_s")) \
                    if a != "webster" else ""
                vn = _fmt(_pair(sub[NOGAP], runs, "person_delay_s")) if a in (V2, GAP) else ""
                print(f"| {SHORT[a]} | {len(runs)} | {st.fmean(v):,.0f} | {max(v):,.0f} "
                      f"| {vt} | {vw} | {vn} |")
            print()
        print("| seed | " + " | ".join(SHORT[a] for a in ARMS) + " |")
        print("|---:|" + "---:|" * len(ARMS))
        for s in seeds_all:
            cells = []
            for a in ARMS:
                r = by[a].get(s)
                cells.append(f"{r['person_delay_s']:,.0f}" if r else "--")
            print(f"| {s} | " + " | ".join(cells) + " |")
        print("\njam markers (longest wait s / steps to empty the network):\n")
        print("| seed | " + " | ".join(SHORT[a] for a in ARMS) + " |")
        print("|---:|" + "---:|" * len(ARMS))
        for s in seeds_all:
            cells = []
            for a in ARMS:
                r = by[a].get(s)
                cells.append(f"{r['wait_time_s']['max_s']:,.0f} / {r['steps']:,}" if r else "--")
            print(f"| {s} | " + " | ".join(cells) + " |")
        viol = {a: sum(r["interlock_violations"] for r in by[a].values()) for a in ARMS}
        fb = {a: sum(r.get("decision_stats", {}).get("fallback_fixed_time", 0)
                     for r in by[a].values()) for a in ARMS}
        print(f"\ninterlock violations: {viol}; fixed-time fallback ticks: {fb}")


if __name__ == "__main__":
    main()

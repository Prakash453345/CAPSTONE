"""Print the M8 results as the markdown tables quoted in PROGRESS.md and the
baseline README, straight from the gate outputs -- so no number in the
write-up is hand-copied.

    python scripts/m8_report.py --closed-loop closed_loop.json \\
        --perception perception_gate.json --incidents incident_analysis.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _pct(c: dict | None) -> str:
    if not c:
        return "--"
    sig = "**SIG**" if c.get("significant") else "n.s."
    pct = c.get("pct")
    return f"{pct:+.1f}% {sig}, {c.get('n_better', 0)}/{c['n']} seeds lower" if pct is not None \
        else "--"


# Head-to-head comparisons the gate's own summary (which pairs every arm with
# Webster and with truth) does not make: what the confidence policy does,
# with and without a real camera failure.
EXTRA_PAIRS = [
    ("vision:finetuned_day:trust", "vision:finetuned_day:honest"),
    ("vision:finetuned_day:trust", "vision:finetuned_day:failsafe"),
    ("vision:finetuned_day:failsafe", "vision:finetuned_day:honest"),
    ("vision:coco_pretrained:failsafe", "vision:coco_pretrained:honest"),
    ("vision:finetuned_day:trust", "vision:finetuned_day:trust:outage"),
    ("vision:finetuned_day:trust:outage", "vision:finetuned_day:honest:outage"),
    ("vision:finetuned_day:trust:outage", "vision:finetuned_day:failsafe:outage"),
    ("vision:finetuned_day:honest:outage", "vision:finetuned_day:failsafe:outage"),
    ("vision:finetuned_day:trust", "vision:finetuned_day:trust:blind"),
    ("vision:finetuned_day:trust:blind", "vision:finetuned_day:failsafe:blind"),
    ("vision:finetuned_day:failsafe:blind:nocheck", "vision:finetuned_day:failsafe:blind"),
]


def closed_loop(path: str) -> str:
    d = json.loads(Path(path).read_text())
    out = []
    for level, lv in sorted(d["summary"].items(), key=lambda kv: ("light", "medium",
                                                                  "heavy").index(kv[0])):
        out.append(f"\n**{level}** (paired held-out seeds)\n")
        out.append("| arm | n | person-delay | p95 wait (s) | stops/veh | interlock viol. | "
                   "confidence fed (mean) | fixed-time fallback |")
        out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        order = ["webster", "truth", "vision:finetuned_day:trust", "vision:finetuned_day:failsafe",
                 "vision:finetuned_day:honest", "vision:coco_pretrained:failsafe",
                 "vision:coco_pretrained:honest"]
        for a in sorted(lv["arms"], key=lambda x: order.index(x) if x in order else 99):
            r = lv["arms"][a]
            conf = r.get("confidence_fed_mean")
            fb = r["fallback_fixed_time"] / r["ticks"] if r.get("ticks") else 0.0
            out.append(f"| `{a}` | {r['n']} | {r['person_delay_s']:,.0f} | {r['p95_wait_s']:.1f} "
                       f"| {r['stops_per_vehicle']:.2f} | {r['interlock_violations']} | "
                       f"{'--' if conf is None else f'{conf:.2f}'} | "
                       f"{'--' if a in ('webster', 'truth') else f'{100 * fb:.1f}% of ticks'} |")
        runs: dict[str, dict[int, dict]] = {}
        for r in d["records"]:
            if r["demand_level"] == level:
                runs.setdefault(r["arm"], {})[r["seed"]] = r
        head = [(a, b) for a, b in EXTRA_PAIRS if a in runs and b in runs]
        if head:
            from m5_ccacamp_gate import paired  # noqa: PLC0415

            out.append("\n| head to head (second vs first) | person-delay | stops/veh |")
            out.append("|---|---|---|")
            for a, b in head:
                out.append(f"| `{b}` vs `{a}` | {_pct(paired(runs[a], runs[b], 'person_delay_s'))}"
                           f" | {_pct(paired(runs[a], runs[b], 'stops_per_vehicle'))} |")
        pairs = lv.get("paired", {})
        if pairs:
            out.append("\n| comparison | person-delay | stops/veh |")
            out.append("|---|---|---|")
            names = sorted({k.split(":")[0] if not k.startswith("vision") else
                            k.rsplit(":", 1)[0] for k in pairs})
            for n in names:
                if n.startswith("webster_vs"):
                    continue  # the reverse of truth_vs_webster
                out.append(f"| `{n}` | {_pct(pairs.get(n + ':person_delay_s'))} | "
                           f"{_pct(pairs.get(n + ':stops_per_vehicle'))} |")
    return "\n".join(out)


def _f(x, fmt="{:.2f}") -> str:
    return "--" if x is None or (isinstance(x, float) and math.isnan(x)) else fmt.format(x)


def perception(path: str) -> str:
    d = json.loads(Path(path).read_text())
    runs = sorted(d["runs"], key=lambda r: (("light", "medium", "heavy").index(r["level"]),
                                            ["ideal", "finetuned_day", "coco_pretrained",
                                             "night_rain"].index(r["preset"])))
    out = ["| level | preset | queue PCU MAE / bias / corr | approaching MAE | "
           "recv. occupancy MAE | MOTA | IDF1 | det. recall car / 2W / auto | speed MAE (m/s) | "
           "lane acc. | confidence mean (<0.8) | queue truncated | candidates / h (no incident) |",
           "|---|---|---|---|---|---:|---:|---|---:|---:|---|---:|---:|"]
    for r in runs:
        s = r["summary"]
        q = s["links"]["queue_pcu"]
        ap = s["links"]["approaching_pcu"]
        ro = s["links"]["receiving_occupancy"]
        rc = s["detection"]["recall_by_class"]

        def rec(c: str, rc: dict = rc) -> str:
            v = rc.get(c)
            return _f(v[0]) if v else "--"

        hours = max(r["sim_hours"], 1e-9)
        out.append(
            f"| {r['level']} | `{r['preset']}` | {_f(q.get('mae'))} / "
            f"{_f(q.get('bias'), '{:+.2f}')} / {_f(q.get('corr'))} | {_f(ap.get('mae'))} | "
            f"{_f(ro.get('mae'), '{:.3f}')} | "
            f"{_f(s['tracking']['mota'])} | {_f(s['tracking']['idf1'])} | "
            f"{rec('car')} / {rec('motorcycle')} / {rec('auto_rickshaw')} | "
            f"{_f(s['ground']['speed_err_mps_mae'])} | {_f(s['ground']['lane_accuracy'])} | "
            f"{_f(s['confidence']['mean'])} ({_f(100 * s['confidence']['below_0.8'], '{:.0f}')}%)"
            f" | {_f(100 * s['truncated_lane_fraction'], '{:.1f}')}% | "
            f"{len(r['candidates']) / hours:.1f} |")
    return "\n".join(out)


def incidents(path: str) -> str:
    d = json.loads(Path(path).read_text())
    out = [f"False-alarm budget on TRAIN: {d['budget_false_alarms_per_h']} per simulated hour, "
           "whole corridor.\n",
           "| | incidents | in view | recall (all) | recall (in view) | mean latency (s) | "
           "false alarms / h | by rule |",
           "|---|---:|---:|---:|---:|---:|---:|---|"]
    for name in ("train", "eval", "eval_hand_set_default"):
        s = d[name]
        out.append(f"| {name.replace('_', ' ')} | {s['incidents']} | {s['in_view']} | "
                   f"{_f(s['recall_all'])} | {_f(s['recall_in_view'])} | "
                   f"{_f(s['mean_latency_s'], '{:.0f}')} | {_f(s['false_alarms_per_hour'])} | "
                   f"{s['false_alarms_by_rule'] or '--'} |")
    out.append("\nIn-view incidents by kind (eval): " + ", ".join(
        f"{k} {v['detected']}/{v['n']}" for k, v in d["eval"]["by_kind"].items()))
    out.append("\nChosen policy: rules " + ", ".join(d["chosen_policy"]["rules"]) +
               f"; persistence {d['chosen_policy']['persist_ticks']} ticks")
    out.append("\n| FA/h (train) | recall in view (train) | recall in view (eval) | "
               "FA/h (eval) | latency (eval, s) |")
    out.append("|---:|---:|---:|---:|---:|")
    for p in d["pareto_train_vs_eval"]:
        out.append(f"| {p['fa_per_h_train']:.2f} | {p['recall_in_view_train']:.2f} | "
                   f"{_f(p.get('recall_in_view_eval'))} | "
                   f"{_f(p.get('false_alarms_per_hour_eval'))} | "
                   f"{_f(p.get('mean_latency_s_eval'), '{:.0f}')} |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--closed-loop")
    ap.add_argument("--perception")
    ap.add_argument("--incidents")
    args = ap.parse_args()
    if args.closed_loop:
        print("## Closed loop\n" + closed_loop(args.closed_loop) + "\n")
    if args.perception:
        print("## Perception\n\n" + perception(args.perception) + "\n")
    if args.incidents:
        print("## Incidents\n\n" + incidents(args.incidents) + "\n")


if __name__ == "__main__":
    main()

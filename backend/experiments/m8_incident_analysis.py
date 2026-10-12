"""Choose the vision incident rules' operating point on TRAIN seeds, then
report it on EVAL seeds.

`m8_incident_gate.py` logs every rule hit at deliberately low thresholds
together with the measure behind it (seconds stopped, seconds of void ...).
That makes the operating thresholds a *post-hoc* choice, and this script
makes it honestly: the whole search happens on the training runs, and the
evaluation runs are scored exactly once, at the chosen policy -- the same
discipline as every other tuning step in this project (TRAIN seeds 101+,
held-out seeds 1-10).

The search. Every rule's candidates depend only on that rule's own
thresholds (and the shared persistence), a window counts as detected if any
rule's candidate matches it, and false alarms add up across rules. So each
rule is scored alone over its own grid, settings that another setting of
the same rule dominates (detects a superset of windows, no later, with no
more false alarms) are dropped, and only the survivors are combined. The
objective is recall on *in-view* incidents subject to a false-alarm budget
per simulated hour for the whole corridor; ties go to fewer false alarms,
then lower latency.

    python scripts/m8_incident_analysis.py train.json eval.json [--budget 1.0]
"""

from __future__ import annotations

import argparse
import gzip
import itertools
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m8_incident_gate import (  # noqa: E402
    DEFAULT_POLICY,
    LATENCY_GRACE_S,
    MAX_STEPS,
    candidates_under,
    summarise,
)

GRIDS: dict[str, dict[str, list]] = {
    "stuck_on_green": {"stuck_sibling_s": [10.0, 15.0, 20.0, 30.0],
                       "stuck_alone_s": [30.0, 45.0, 60.0, 90.0, 1e9]},
    "midblock_stop": {"midblock_s": [15.0, 20.0, 30.0, 45.0, 60.0],
                      "midblock_dwell_s": [60.0, 90.0, 120.0],
                      "midblock_impact_s": [10.0, 15.0, 20.0, 30.0]},
    "flow_void": {"void_s": [60.0, 90.0, 120.0], "void_min_swerves": [0, 2, 3, 5],
                  "void_min_share": [0.0, 0.2, 0.3, 0.5],
                  "void_min_from_stop_line_m": [0.0, 30.0, 60.0]},
    "collision_cue": {"collision_s": [5.0, 10.0, 20.0]},
    "wrong_way": {"wrong_way_s": [3.0, 5.0]},
}
PERSIST = [1, 3, 5]


def _load(path: str) -> list[dict]:
    """A gate output, plain or gzipped (the baseline stores the hit logs as
    `.json.gz`)."""
    raw = Path(path).read_bytes()
    if path.endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw)["runs"]


def _windows(runs: list[dict]) -> list[tuple[int, int, dict]]:
    return [(i, k, w) for i, r in enumerate(runs) for k, w in enumerate(r["windows"])]


def _rule_outcome(runs: list[dict], by_rule_hits: list[dict], rule: str, pol: dict) -> tuple[
    dict, int
]:
    """{(run, window): latency} and the false-alarm count for one rule."""
    det: dict[tuple[int, int], float] = {}
    fa = 0
    for i, r in enumerate(runs):
        cands = candidates_under(by_rule_hits[i].get(rule, []), {**pol, "rules": [rule]})
        wins = r["windows"]
        for c in cands:
            inside = False
            for k, w in enumerate(wins):
                end = (w["end"] or MAX_STEPS) + LATENCY_GRACE_S
                if w["start"] <= c["t"] <= end:
                    inside = True
                    targets = {(w["tls"], lk) for lk in w["links"]}
                    if any(tuple(lk) in targets for lk in c["links"]):
                        lat = c["t"] - w["start"]
                        if lat < det.get((i, k), 1e18):
                            det[(i, k)] = lat
            fa += not inside
    return det, fa


def _dominated(a: tuple[dict, int], b: tuple[dict, int]) -> bool:
    """Is `a` dominated by `b`?"""
    (da, fa), (db, fb) = a, b
    return fb <= fa and set(da) <= set(db) and all(db[k] <= da[k] for k in da) and \
        (fb < fa or set(db) != set(da) or any(db[k] < da[k] for k in da))


def _settings(rule: str) -> list[dict]:
    grid = GRIDS[rule]
    keys = list(grid)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*grid.values())]


def search(runs: list[dict], budget_per_h: float) -> tuple[dict, list[dict]]:
    hours = sum(r["sim_hours"] for r in runs)
    by_rule_hits = []
    for r in runs:
        d: dict = {}
        for h in r["hits"]:
            d.setdefault(h[1], []).append(h)
        by_rule_hits.append(d)
    inview = {(i, k) for i, k, w in _windows(runs) if w["covered"]}
    best, frontier = None, []
    for persist in PERSIST:
        per_rule: dict[str, list[tuple[dict | None, tuple[dict, int]]]] = {}
        for rule in GRIDS:
            opts = [(None, ({}, 0))]  # the rule switched off
            for s in _settings(rule):
                opts.append((s, _rule_outcome(runs, by_rule_hits, rule,
                                              {**DEFAULT_POLICY, **s, "persist_ticks": persist})))
            per_rule[rule] = [o for o in opts
                              if not any(_dominated(o[1], p[1]) for p in opts if p is not o)]
        for combo in itertools.product(*per_rule.values()):
            fa = sum(o[1][1] for o in combo)
            if fa / hours > budget_per_h * 4:  # far outside anything worth recording
                continue
            det: dict = {}
            for _, (d, _f) in combo:
                for k, v in d.items():
                    if v < det.get(k, 1e18):
                        det[k] = v
            hit = [k for k in det if k in inview]
            recall = len(hit) / len(inview) if inview else 0.0
            lat = st.fmean(det[k] for k in hit) if hit else 1e9
            pol = {**DEFAULT_POLICY, "persist_ticks": persist,
                   "rules": [rule for rule, (s, _) in zip(GRIDS, combo, strict=True)
                             if s is not None]}
            for s, _ in combo:
                if s:
                    pol.update(s)
            rec = {"policy": pol, "recall_in_view": recall, "fa_per_h": fa / hours,
                   "latency_s": lat}
            frontier.append(rec)
            key = (recall, -fa, -lat)
            if fa / hours <= budget_per_h and (best is None or key > best[0]):
                best = (key, rec)
    # Pareto frontier over (recall up, false alarms down)
    frontier.sort(key=lambda r: (r["fa_per_h"], -r["recall_in_view"], r["latency_s"]))
    pareto, top = [], -1.0
    for r in frontier:
        if r["recall_in_view"] > top:
            pareto.append(r)
            top = r["recall_in_view"]
    if best is None:
        raise SystemExit(f"no policy meets {budget_per_h} false alarms/h on the training runs")
    return best[1]["policy"], pareto


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("train")
    ap.add_argument("eval")
    ap.add_argument("--budget", type=float, default=1.0,
                    help="false alarms per simulated hour, whole corridor")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    train, evl = _load(args.train), _load(args.eval)
    policy, pareto = search(train, args.budget)
    report = {
        "budget_false_alarms_per_h": args.budget,
        "chosen_policy": policy,
        "train": summarise(train, policy),
        "eval": summarise(evl, policy),
        "eval_hand_set_default": summarise(evl, DEFAULT_POLICY),
        "pareto_train_vs_eval": [
            {"fa_per_h_train": round(p["fa_per_h"], 3),
             "recall_in_view_train": round(p["recall_in_view"], 3),
             **{f"{k}_eval": v for k, v in summarise(evl, p["policy"]).items()
                if k in ("recall_in_view", "false_alarms_per_hour", "mean_latency_s")}}
            for p in pareto],
    }
    text = json.dumps(report, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()

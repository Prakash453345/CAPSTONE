"""Blocked lanes: what the overview cameras report against what the simulator
knows, per approach lane and second.

CC-A-CAMP on perfect data drives the signals; the cameras only watch (the
scenario's `cameras_box.json`: approach cameras plus one overview camera per
junction, `scenarios/build_scenario.py --add-box-cameras`). Every second,
for every approach lane of every signalised junction:

    simulator  `QueueStateSampler._blocked_by` -- the front vehicle stopped
               with a stopped vehicle that left this lane inside the box,
               its tail within 3 m
    cameras    `LinkStateEstimator.blocked` -- the same thing from ground
               tracks of the overview camera

and the two are scored against each other to the second and within 2 s (a
tracker's stopped/moving state lags a simulator's by about a second each
way). Also reported: how long blockages last in each reading.

    ITMS_SCENARIO=scenarios/generated/narrow_lh python scripts/m8_blocked_lane_agreement.py \\
        --level medium --seed 101 --steps 900 --preset itms6_640 --out agreement.json
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_harness as M  # noqa: E402
from sim_service.control.strategies import hol  # noqa: E402
from sim_service.signal_controller.queue_state import QueueStateSampler  # noqa: E402
from vision_service.sim.closed_loop import VisionLoop  # noqa: E402


def _runs(v: list[int]) -> dict:
    v = sorted(v)
    if not v:
        return {"n": 0}
    return {"n": len(v), "median_s": st.median(v), "p90_s": v[int(0.9 * (len(v) - 1))],
            "share_lasting_5s_or_more": round(sum(x >= 5 for x in v) / len(v), 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="medium")
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--steps", type=int, default=900)
    ap.add_argument("--preset", default="itms6_640")
    ap.add_argument("--out")
    args = ap.parse_args()

    approach, receiving = M.link_maps()
    internal = hol.internal_links(M.H.NET_PATH)
    lane_links = {(t, ln): [k for k, v in m.items() if v == ln]
                  for t, m in approach.items() for ln in set(m.values())}
    samplers = {t: QueueStateSampler(approach[t], receiving.get(t, {}), {},
                                     internal_links=internal.get(t, {})) for t in approach}
    loop = VisionLoop(M.vision_factory(args.preset, args.seed, 5.0, box=True), approach.keys())
    n: collections.Counter = collections.Counter()
    series: dict = collections.defaultdict(lambda: ([], []))
    run_len = {"simulator": collections.defaultdict(int), "cameras": collections.defaultdict(int)}
    runs: dict[str, list[int]] = {"simulator": [], "cameras": []}

    def on_tick(step, t):
        cam = loop.ensure(t).estimator.blocked
        for tls in sorted(approach):
            truth = samplers[tls]._blocked_by()  # noqa: SLF001
            for (t2, ln), links in lane_links.items():
                if t2 != tls:
                    continue
                tr = any(k in truth for k in links)
                cm = any(k in cam.get(tls, {}) for k in links)
                n["both"] += tr and cm
                n["cameras_only"] += cm and not tr
                n["simulator_only"] += tr and not cm
                n["neither"] += not tr and not cm
                series[(tls, ln)][0].append(tr)
                series[(tls, ln)][1].append(cm)
                for name, flag in (("simulator", tr), ("cameras", cm)):
                    if flag:
                        run_len[name][(tls, ln)] += 1
                    elif run_len[name][(tls, ln)]:
                        runs[name].append(run_len[name][(tls, ln)])
                        run_len[name][(tls, ln)] = 0

    rec = M.run_scenario("ccacamp", args.level, args.seed, on_tick=on_tick,
                         max_steps=args.steps, tag="blocked_agreement")
    near: collections.Counter = collections.Counter()
    for tr, cm in series.values():
        for i in range(len(tr)):
            w = slice(max(0, i - 2), i + 3)
            if cm[i]:
                near["cameras"] += 1
                near["cameras_near_simulator"] += any(tr[w])
            if tr[i]:
                near["simulator"] += 1
                near["simulator_near_cameras"] += any(cm[w])
    out = {
        "scenario": M.H.SCENARIO_NAME, "level": args.level, "seed": args.seed,
        "preset": args.preset, "steps": rec["steps"], "lane_seconds": dict(n),
        "to_the_second": {
            "precision": round(n["both"] / max(1, n["both"] + n["cameras_only"]), 3),
            "recall": round(n["both"] / max(1, n["both"] + n["simulator_only"]), 3)},
        "within_2s": {
            "precision": round(near["cameras_near_simulator"] / max(1, near["cameras"]), 3),
            "recall": round(near["simulator_near_cameras"] / max(1, near["simulator"]), 3)},
        "blockage_length": {k: _runs(v) for k, v in runs.items()},
    }
    print(json.dumps(out, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

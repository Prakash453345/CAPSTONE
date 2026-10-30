"""Measure the calibration-drift monitor on TRAIN seeds (M8).

CC-A-CAMP on SUMO truth drives the traffic (so the cameras cannot change
it); the vision system films it, and every camera's `DriftMonitor` state is
recorded each tick. Four fault-free runs give the monitor's false alarms and
how close each camera comes to its thresholds; two runs knock one camera 3°
askew (SimCam's `bump` fault) at 1,200 s and give the time to flag it.

    python scripts/m8_drift_check.py --out drift_check.json
    python scripts/m8_drift_check.py --out drift_check.json --from-series drift_check.series.json

The first form runs the simulations and also writes `<out>.series.json`
(per camera, per tick: t, samples in window, heading error, off-lane rate,
drift flag); the second re-summarises a recorded series.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

BUMP_CAMERA = "cam_2833253632_343269496"
BUMP_T = 1200.0
BUMP_DEG = 3.0
BASELINE_T = 300.0  # the monitor learns its baseline over the first 300 s
JOBS = [  # preset, level, seed, steps, bump
    ("coco_pretrained", "medium", 101, 2400, False),
    ("coco_pretrained", "medium", 102, 2400, False),
    ("coco_pretrained", "heavy", 101, 3000, False),
    ("finetuned_day", "medium", 101, 2400, False),
    ("finetuned_day", "medium", 101, 2400, True),
    ("coco_pretrained", "medium", 101, 2400, True),
]


def _key(preset, level, seed, steps, bump) -> str:
    k = f"{preset}_{level}_{seed}_{steps}"
    return f"{k}_{BUMP_CAMERA}_{int(BUMP_T)}_{int(BUMP_DEG)}" if bump else k


def _record(job) -> dict:
    import m8_harness as M
    from vision_service.classes import ClassTable
    from vision_service.incidents import TraciSignalState
    from vision_service.pipeline import CameraFault
    from vision_service.simcam import TraciWorld

    preset, level, seed, steps, bump = job
    inputs = M.ccacamp_inputs(level)
    approach, _ = M.link_maps()
    make = M.vision_factory(preset, seed, 5.0)
    world, signal = TraciWorld(), TraciSignalState(approach.keys())
    st: dict = {"vs": None, "prev": None}
    series: dict[str, list] = {}

    def num(x: float, nd: int):
        return round(x, nd) if x == x else None  # NaN -> None

    def on_tick(step, t):
        snap = world.snapshot()
        if st["vs"] is None:
            dims = world.vtype_dimensions()
            vs = make(ClassTable.default().with_dimensions(dims) if dims else ClassTable.default())
            vs.incidents.signal = signal
            if bump:
                vs.inject_fault(BUMP_CAMERA, CameraFault("bump", BUMP_T, d_heading_deg=BUMP_DEG))
            st["vs"] = vs
        vs = st["vs"]
        signal.refresh(t)
        vs.step_world(st["prev"], snap)
        vs.tick(t)
        st["prev"] = snap
        for cid, p in vs.pipelines.items():
            d = p.health.drift
            series.setdefault(cid, []).append([
                t, len(d._samples), num(d.heading_err_deg, 3), num(d.offlane_rate, 4),
                int(d.drift)])

    M.run_scenario("ccacamp", level, seed, inputs=inputs, on_tick=on_tick, max_steps=steps,
                   tag="driftcheck")
    return {"preset": preset, "level": level, "seed": seed, "steps": steps,
            "bump": [BUMP_CAMERA, str(int(BUMP_T)), str(int(BUMP_DEG))] if bump else [],
            "series": series}


def summarise(run: dict) -> dict:
    """Per camera: its largest rise over its own baseline (the first window
    at or after `BASELINE_T`) while fault-free; alarms; and, for the bumped
    camera, the rises at the alarm and after it."""
    bump_cam = run["bump"][0] if run["bump"] else None
    bump_t = float(run["bump"][1]) if run["bump"] else float("inf")
    per_cam, alarms, bumped = {}, {}, None
    for cid, ser in run["series"].items():
        ok = [(t, h, o, dr) for t, _, h, o, dr in ser if h is not None and o is not None]
        base = next(((h, o) for t, h, o, _ in ok if t >= BASELINE_T), None)
        flagged = [t for t, *_, dr in ser if dr]
        if flagged:
            alarms[cid] = {"first_t": flagged[0], "ticks": len(flagged)}
        if base is None:
            continue
        clean = [(h - base[0], o - base[1]) for t, h, o, _ in ok
                 if t >= BASELINE_T and (cid != bump_cam or t < bump_t)]
        if clean:
            per_cam[cid] = {"heading_deg": round(max(c[0] for c in clean), 2),
                            "offlane": round(max(c[1] for c in clean), 3)}
        if cid == bump_cam:
            post = [(t, h - base[0], o - base[1], dr) for t, h, o, dr in ok if t >= bump_t]
            first = flagged[0] if flagged else None
            at = next((p for p in post if first is not None and p[0] >= first), None)
            windows = {}
            for lo in range(int(bump_t), int(post[-1][0]) + 1, 300) if post else ():
                w = [p for p in post if lo <= p[0] < lo + 300]
                if w:
                    windows[f"{lo}-{lo + 300}"] = {
                        "heading_rise_median": round(statistics.median(p[1] for p in w), 2),
                        "offlane_rise_median": round(statistics.median(p[2] for p in w), 3),
                        "offlane_rise_max": round(max(p[2] for p in w), 3),
                        "flagged_share": round(sum(p[3] for p in w) / len(w), 3)}
            bumped = {"camera": cid, "latency_s": None if first is None else first - bump_t,
                      "at_alarm": None if at is None else
                      {"heading_rise": round(at[1], 2), "offlane_rise": round(at[2], 3)},
                      "after_bump": windows}
    worst = max(per_cam.items(), key=lambda kv: kv[1]["offlane"], default=(None, None))
    return {"preset": run["preset"], "level": run["level"], "seed": run["seed"],
            "bump": run["bump"],
            "max_rise_fault_free": {
                "heading_deg": max((v["heading_deg"] for v in per_cam.values()), default=None),
                "offlane": max((v["offlane"] for v in per_cam.values()), default=None)},
            "closest_to_offlane_threshold": worst[0],
            "alarms": alarms, "bumped": bumped, "per_camera": per_cam}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from-series", help="re-summarise a recorded series instead of running")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()
    if args.from_series:
        runs = json.loads(Path(args.from_series).read_text())
    else:
        with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
            runs = list(pool.map(_record, JOBS))
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).with_suffix(".series.json").write_text(json.dumps(runs))
    out = {"note": ("Calibration-drift monitor, CC-A-CAMP on truth driving the traffic (TRAIN "
                    "seeds). Per camera: largest rise over its own baseline (the window at "
                    f"t={BASELINE_T:.0f} s) in heading error (deg) and off-lane rate while "
                    "fault-free; the monitor alarms above 6 deg or 0.2. Bump runs: a "
                    f"{BUMP_DEG:.0f}-degree heading bump on {BUMP_CAMERA} at {BUMP_T:.0f} s."),
           "runs": {_key(r["preset"], r["level"], r["seed"], r["steps"], bool(r["bump"])):
                    summarise(r) for r in runs}}
    Path(args.out).write_text(json.dumps(out, indent=1))
    for k, v in out["runs"].items():
        b = v["bumped"]
        print(k, v["max_rise_fault_free"], "closest:", v["closest_to_offlane_threshold"],
              "false alarms:", sorted(c for c in v["alarms"] if c != (b or {}).get("camera")),
              "bump latency:", b and b["latency_s"])


if __name__ == "__main__":
    main()

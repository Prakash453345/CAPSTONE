"""M8 perception gate: how far are the camera estimates from SUMO truth?

Runs the current M5 controller (CC-A-CAMP) on ground truth -- so the traffic
is the traffic the real system produces -- while the vision system films
the corridor through every camera in `cameras.json` via SimCam, and
`vision_service.eval.twin.TwinRecorder` scores every stage:

    detection   recall by class (against what could be seen), precision
    tracking    MOTA, IDF1, identity switches
    ground      position error, speed error, lane accuracy, stopped state
    links       the four controller quantities vs QueueStateSampler truth
    confidence  distribution of the estimator's own confidence
    incidents   candidates raised with no incident injected (false alarms)

Presets are the error models in `vision_service/simcam/errors.py`; `ideal`
isolates the geometry and tracking from detector error.

    python scripts/m8_perception_gate.py --out results/m8_perception_gate.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_harness as M  # noqa: E402
from sim_service.signal_controller.queue_state import QueueStateSampler  # noqa: E402
from vision_service.eval.twin import TwinRecorder  # noqa: E402
from vision_service.incidents import TraciSignalState  # noqa: E402
from vision_service.simcam import TraciWorld  # noqa: E402


def _job(args) -> dict:
    preset, level, seed, fps, max_steps = args
    t0 = time.time()
    inputs = M.ccacamp_inputs(level)
    _, _, vtype_pcu, _ = inputs
    approach, receiving = M.link_maps()
    make = M.vision_factory(preset, seed, fps)
    world = TraciWorld()
    signal = TraciSignalState(approach.keys())
    state: dict = {"vs": None, "prev": None, "rec": None, "vision_s": 0.0}

    def on_tick(step: int, t: float) -> None:
        a = time.time()
        snap = world.snapshot()
        if state["vs"] is None:
            from vision_service.classes import ClassTable  # noqa: PLC0415

            dims = world.vtype_dimensions()
            vs = make(ClassTable.default().with_dimensions(dims) if dims else ClassTable.default())
            vs.incidents.signal = signal
            samplers = {tls: QueueStateSampler(approach[tls], receiving[tls], vtype_pcu)
                        for tls in approach}
            rec = TwinRecorder(vs, samplers)
            rec.attach()
            state.update(vs=vs, rec=rec)
        vs, rec = state["vs"], state["rec"]
        signal.refresh(t)
        vs.step_world(state["prev"], snap)
        vs.tick(t, keep_tracks=True)
        rec.on_tick(t, snap)
        for c in vs.incidents.new_candidates:
            state.setdefault("candidates", []).append(
                {"rule": c.rule, "lane": c.lane_id, "t": c.raised_t, "evidence": c.evidence})
        state["prev"] = snap
        state["vision_s"] += time.time() - a

    run = M.run_scenario("ccacamp", level, seed, inputs=inputs, on_tick=on_tick,
                         max_steps=max_steps, tag=f"perc_{preset}")
    rec = state["rec"]
    return {
        "preset": preset,
        "level": level,
        "seed": seed,
        "fps": fps,
        "run": run,
        "summary": rec.summary(),
        "candidates": state.get("candidates", []),
        "sim_hours": (run["steps"] - rec.warmup_s) / 3600.0,
        "vision_s": round(state["vision_s"], 1),
        "wall_s": round(time.time() - t0, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", default="ideal,finetuned_day,coco_pretrained,night_rain")
    ap.add_argument("--levels", default="light,medium,heavy")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true",
                    help="keep the runs already in --out and run only the missing ones")
    args = ap.parse_args()

    presets = [p for p in args.presets.split(",") if p]
    levels = [lv for lv in args.levels.split(",") if lv]
    seeds = M.EVAL_SEEDS[: args.seeds]
    jobs = [(p, lv, s, args.fps, args.max_steps) for lv in levels for p in presets for s in seeds]
    out: list[dict] = M.previous_runs(args.out, "runs") if args.resume else []
    done = {(r["preset"], r["level"], r["seed"]) for r in out}
    jobs = [j for j in jobs if (j[0], j[1], j[2]) not in done]
    print(f"{len(jobs)} runs to do ({len(out)} kept): presets {presets} x levels {levels} x "
          f"seeds {seeds}", flush=True)
    t0 = time.time()
    total = len(jobs) + len(out)
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for r in pool.map(_job, jobs):
            out.append(r)
            lk = r["summary"]["links"]["queue_pcu"]
            tr = r["summary"]["tracking"]
            print(f"[{len(out)}/{total}] {r['preset']:16s} {r['level']:6s} seed={r['seed']} "
                  f"queue MAE={lk.get('mae', float('nan')):.2f} bias={lk.get('bias', 0):+.2f} "
                  f"corr={lk.get('corr', float('nan')):.2f}  MOTA={tr['mota']:.2f} "
                  f"IDF1={tr['idf1']:.2f}  cand={len(r['candidates'])}  ({r['wall_s']:.0f}s)",
                  flush=True)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(
                {"meta": {"fps": args.fps, "seeds": seeds, "presets": presets, "levels": levels,
                          "wall_min": round((time.time() - t0) / 60, 1)}, "runs": out},
                indent=1, default=str))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

"""Choose `BlindCameraCheck`'s `hold_s` and `gap_s` on TRAIN seeds (M8).

Runs CC-A-CAMP on the cameras (`failsafe`, cross-check *off*, so the check
cannot change the traffic it is measured on) and records, every controller
tick, each link's stop-bar loop (emulated from the snapshot SimCam films)
and whether the camera reports any vehicle on the link. The check is then
replayed offline for every setting in the grid:

- false alarms: a link on a working camera entering "blind" (fault-free
  runs, and the working cameras of the blind runs), per corridor-hour;
- detection: for each blinded link, seconds from the blindness to the first
  alarm -- and how many were never caught.

    python scripts/m8_blind_check_calibration.py --out results/m8_blind_check.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_harness as M  # noqa: E402
from itms_domain.camera import BlindCameraCheck  # noqa: E402
from m8_closed_loop_gate import OUTAGE_S, _outage_tls, _with_fault  # noqa: E402
from vision_service.sim.closed_loop import VisionLoop, VisionSensor  # noqa: E402

HOLDS = (5.0, 10.0, 15.0, 20.0, 30.0, 45.0)
GAPS = (5.0, 10.0, 20.0)


class _Recorder(VisionSensor):
    def __init__(self, *a, series: dict, **k):
        super().__init__(*a, blind_check=False, **k)
        self.series = series

    def __call__(self, cfg, ctx):
        system = self.loop.ensure(self._t)
        qs = system.estimator.queue_sample(self.tls_id)
        seen = qs["vehicles_seen"]
        for link, here in self.loop.stopbar(self.tls_id).items():
            row = self.series.setdefault(f"{self.tls_id}|{link}", [[], "", ""])
            row[0].append(self._t)
            row[1] += "1" if here else "0"
            row[2] += "1" if seen.get(link, 0.0) >= 1 else "0"
        return super().__call__(cfg, ctx)


def _job(args) -> dict:
    level, seed, preset, blind = args
    t0 = time.time()
    inputs = M.ccacamp_inputs(level)
    base = M.build_strategy("ccacamp", inputs)
    approach, _ = M.link_maps()
    factory = M.vision_factory(preset, seed, 5.0)
    if blind:
        factory = _with_fault(factory, "blind")
    loop = VisionLoop(factory, approach.keys())
    series: dict = {}
    strategy = {tls: _Recorder(ctrl, loop, tls, "failsafe", series=series)
                for tls, ctrl in base.items()}
    rec = M.run_scenario("ccacamp", level, seed, inputs=inputs, strategy=strategy,
                         tag=f"blindcal_{preset}_{int(blind)}")
    return {"level": level, "seed": seed, "preset": preset, "blind": blind,
            "blind_tls": _outage_tls() if blind else None, "window": list(OUTAGE_S),
            "series": series, "person_delay_s": rec["person_delay_s"],
            "wall_s": round(time.time() - t0)}


def replay(run: dict, hold: float, gap: float) -> tuple[int, float, list[float], int]:
    """(false-alarm onsets, hours, detection latencies, blinded links missed)."""
    start, end = run["window"]
    fa, lat, missed, hours = 0, [], 0, 0.0
    for key, (ts, occ, seen) in run["series"].items():
        tls, link = key.split("|")
        check = BlindCameraCheck(hold_s=hold, gap_s=gap)
        blind_here = run["blind_tls"] == tls
        was, first = False, None
        for t, o, s in zip(ts, occ, seen, strict=True):
            now = link in check.update(t, {link: o == "1"}, {link: 1.0 if s == "1" else 0.0})
            if now and not was:
                if blind_here and start <= t <= end:
                    first = t if first is None else first
                else:
                    fa += 1
            was = now
        if blind_here:
            if first is None:
                missed += 1
            else:
                lat.append(first - start)
        if ts:
            hours = max(hours, (ts[-1] - ts[0]) / 3600.0)
    return fa, hours, lat, missed


def score(runs: list[dict]) -> dict:
    out = {}
    for hold, gap in itertools.product(HOLDS, GAPS):
        fa = hours = missed = 0
        lat: list[float] = []
        for r in runs:
            f, h, la, m = replay(r, hold, gap)
            fa, hours, missed = fa + f, hours + h, missed + m
            lat += la
        lat.sort()
        out[f"hold{int(hold)}_gap{int(gap)}"] = {
            "hold_s": hold, "gap_s": gap, "false_alarms": fa,
            "false_alarms_per_hour_corridor": fa / max(hours, 1e-9),
            "blind_links_caught": len(lat), "blind_links_missed": missed,
            "median_latency_s": lat[len(lat) // 2] if lat else None,
            "max_latency_s": lat[-1] if lat else None}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()
    seeds = M.TRAIN_SEEDS[:2]
    jobs = [(lv, s, p, False) for lv in ("medium", "heavy")
            for p in ("finetuned_day", "coco_pretrained") for s in seeds]
    jobs += [("medium", s, "finetuned_day", True) for s in seeds]
    runs = []
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        for r in pool.map(_job, jobs):
            runs.append(r)
            print(f"[{len(runs)}/{len(jobs)}] {r['level']:6s} seed={r['seed']} {r['preset']:15s} "
                  f"blind={r['blind']} links={len(r['series'])} ({r['wall_s']}s)", flush=True)
    result = {"grid": score(runs), "runs_meta": [{k: v for k, v in r.items() if k != "series"}
                                                 for r in runs]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1))
    Path(args.out).with_suffix(".series.json").write_text(json.dumps(runs))
    for k, v in result["grid"].items():
        print(k, {x: v[x] for x in ("false_alarms_per_hour_corridor", "blind_links_caught",
                                    "blind_links_missed", "median_latency_s")})


if __name__ == "__main__":
    main()

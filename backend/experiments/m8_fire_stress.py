"""How the fire/smoke scorer behaves when the picture gets worse, and on real
traffic video. A diagnostic, not a gate: nothing here may be used to choose
a threshold or to train (the 250 Bengaluru frames are Step 2's B4 test set,
already scored once).

1. No-fire Bengaluru frames, degraded like `m8_detector_stress.py` does
   (darkening, noise, soft focus, JPEG, haze, headlight glare, rain): how
   many frames alarm, and the highest scores.
2. Short traffic clips (not Indian, no fire in them), scored once a second
   and run through `FireMonitor`: how many frames alarm, how many candidates
   a camera would have raised, and the time per frame.

    python scripts/m8_fire_stress.py --det <v4.pt> --cls <cls.onnx> \\
        --frames b4/test4 --clips a.mp4 b.avi --out fire_stress.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from m8_detector_stress import CONDITIONS  # noqa: E402
from vision_service.fire import FireMonitor  # noqa: E402
from vision_service.fire.detector import FireScorer  # noqa: E402


def frames_stress(scorer, folder: Path, only) -> dict:
    paths = sorted(folder.glob("*.jpg"))
    out = {}
    for name, fn in CONDITIONS.items():
        if only and name not in only:
            continue
        alarms, top = [], []
        for k, p in enumerate(paths):
            img = fn(cv2.imread(str(p)), np.random.default_rng(100003 + k))
            s = scorer.score(img)
            top.append(max(s.p_fire / scorer.thresholds[0], s.p_smoke / scorer.thresholds[1]))
            if s.alarm:
                alarms.append({"frame": p.name, "p_fire": round(s.p_fire, 3),
                               "p_smoke": round(s.p_smoke, 3)})
        out[name] = {"frames": len(paths), "alarms": len(alarms), "alarm_frames": alarms,
                     "max_score_over_threshold": round(max(top), 3)}
        print(f"{name:8s} alarms {len(alarms):3d} of {len(paths)}", flush=True)
    return out


def clip_stress(scorer, path: str) -> dict:
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(fps)))               # one frame per second of video
    mon = FireMonitor(Path(path).stem)
    scored = alarm_frames = 0
    times, ncand, cands = [], [], []
    for k in range(0, n, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, k)
        ok, frame = cap.read()
        if not ok:
            break
        t0 = time.perf_counter()
        s = scorer.score(frame)
        times.append(time.perf_counter() - t0)
        ncand.append(s.n_candidates)
        scored += 1
        alarm_frames += s.alarm
        t = k / fps
        mon.observe(t, s)
        new, _ = mon.drain()
        cands += [{"t": round(t, 1), "kind": c.kind} for c in new]
    cap.release()
    return {"seconds_of_video": round(n / fps, 1), "frames_scored": scored,
            "alarm_frames": alarm_frames, "candidates_raised": cands,
            "candidates_per_frame": {"mean": round(float(np.mean(ncand)), 2) if ncand else None,
                                     "max": int(max(ncand)) if ncand else None},
            "s_per_frame": {"median": round(float(np.median(times)), 3) if times else None,
                            "max": round(float(max(times)), 3) if times else None}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", required=True)
    ap.add_argument("--cls", required=True)
    ap.add_argument("--frames")
    ap.add_argument("--clips", nargs="*", default=[])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    scorer = FireScorer(a.det, a.cls)
    res: dict = {"detector": a.det, "classifier": a.cls, "thresholds": scorer.thresholds}
    if a.frames:
        res["frames"] = frames_stress(scorer, Path(a.frames), a.only)
        Path(a.out).write_text(json.dumps(res, indent=1))
    res["clips"] = {}
    for c in a.clips:
        res["clips"][Path(c).name] = r = clip_stress(scorer, c)
        print(Path(c).name, json.dumps(r), flush=True)
    Path(a.out).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

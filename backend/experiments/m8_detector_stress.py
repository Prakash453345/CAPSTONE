"""How much does the adopted vehicle detector lose when the picture gets worse?

A diagnostic, not a gate and not a tuning set: it re-scores the model on the
same 250 labelled UVH-26 frames after degrading each frame in a fixed,
seeded way, and prints what falls. Nothing here may be used to choose a
threshold or a training set (these 250 frames are the test frames).

The degradations are crude stand-ins for conditions the labelled frames
lack (they are almost all daylight): darkening, sensor noise, soft focus,
heavy JPEG, haze, headlight glare on a dark frame, rain streaks. A real
night camera is not a darkened day frame (infrared, auto-exposure, motion
blur), so a drop here says "this model is sensitive to X", and no drop does
not say "safe at night".

    python scripts/m8_detector_stress.py --data data/uvh26 \\
        --model data/models/itms_six_fp32_640.onnx --out stress.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from m8_detector_eval import evaluate, load_detector, load_truth  # noqa: E402


def _u8(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0, 255).astype(np.uint8)


def dusk(img, rng):
    return _u8(img.astype(np.float32) * 0.55)


def night(img, rng):
    x = (img.astype(np.float32) / 255.0) ** 2.0 * 0.5
    x = x + rng.normal(0, 0.015, x.shape).astype(np.float32)
    return _u8(x * 255)


def noise(img, rng):
    return _u8(img.astype(np.float32) + rng.normal(0, 12, img.shape).astype(np.float32))


def blur(img, rng):
    return cv2.GaussianBlur(img, (0, 0), 2.0)


def jpeg(img, rng):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 15])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def haze(img, rng):
    return _u8(img.astype(np.float32) * 0.6 + 200 * 0.4)


def glare(img, rng):
    base = night(img, rng).astype(np.float32)
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for _ in range(3):
        cx, cy = rng.uniform(0.1 * w, 0.9 * w), rng.uniform(0.45 * h, 0.9 * h)
        s = rng.uniform(25, 60)
        g = 255.0 * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * s * s)))
        base += g[..., None]
    return _u8(base)


def rain(img, rng):
    out = img.copy()
    h, w = img.shape[:2]
    layer = np.zeros_like(img)
    for _ in range(500):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        cv2.line(layer, (x, y), (x - 6, y + 22), (255, 255, 255), 1)
    out = cv2.addWeighted(out, 1.0, layer, 0.35, 0)
    return cv2.GaussianBlur(out, (0, 0), 0.8)


CONDITIONS = {"clean": lambda img, rng: img, "dusk": dusk, "night": night, "noise": noise,
              "blur": blur, "jpeg": jpeg, "haze": haze, "glare": glare, "rain": rain}


class Degraded:
    def __init__(self, inner, fn, seed: int = 0):
        self.inner, self.fn, self.seed, self.k = inner, fn, seed, 0
        self.class_map = inner.class_map
        self.name = "degraded"

    def detect(self, frame):
        rng = np.random.default_rng(self.seed * 100003 + self.k)
        self.k += 1
        return self.inner.detect(self.fn(frame, rng))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/uvh26")
    ap.add_argument("--model", required=True)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--op", type=float, default=0.5)
    ap.add_argument("--floor", type=float, default=0.05)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    data = Path(a.data)
    images, truth, _ = load_truth(data)
    det, _, backend = load_detector(a.model, a.floor, a.imgsz)
    out = {"model": a.model, "backend": backend, "imgsz": a.imgsz, "op": a.op, "conditions": {}}
    print(f"{'condition':8s} recall  precision  FP/img  mAP50  PCU bias")
    for name, fn in CONDITIONS.items():
        if a.only and name not in a.only:
            continue
        s = evaluate(Degraded(det, fn), images, truth, data, a.op, a.limit)
        keep = {k: s[k] for k in ("map50", "vehicle_recall", "vehicle_precision",
                                  "false_pos_per_image", "pcu_per_image", "recall_by_size",
                                  "per_class") if k in s}
        out["conditions"][name] = keep
        print(f"{name:8s} {s['vehicle_recall']:.3f}   {s['vehicle_precision']:.3f}      "
              f"{s['false_pos_per_image']:.2f}    {s['map50']:.3f}  "
              f"{s['pcu_per_image']['bias']:+.2f}", flush=True)
        Path(a.out).write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()

"""False alarms of the fire and smoke detector on Indian traffic frames (M8).

The Colab notebook (`notebooks/m8_fire_smoke.ipynb`) chooses the alarm
threshold on its validation split and scores D-Fire's test split. What it
cannot score is how often the detector cries fire on the kind of frame a
junction camera sends. Orange autos, red buses, brake lights, sodium lamps
and dust are what fool a fire detector on Indian roads.

This scores that on the 250 Bengaluru CCTV test frames of the vehicle work
(`data/uvh26/val_sample`). None of them shows a fire, and none was used to
train or tune the fire model: the notebook's Bengaluru negatives come from
the vehicle notebook's training and hold-out frames, which exclude these
frames and their cameras. A frame alarms when its highest fire or smoke
score reaches the notebook's threshold. The bar was set before the run: at
most 1 % of frames.

    python scripts/m8_fire_eval.py --model data/fire/itms_fire_640.onnx \\
        --report data/fire/fire_report.json --frames data/uvh26/val_sample \\
        --out fire_false_alarms.json
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
import time
from pathlib import Path

import cv2
import numpy as np
from vision_service.detect.yolo import letterbox

FA_BAR = 0.01


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="itms_fire_<size>.onnx")
    ap.add_argument("--report", help="fire_report.json (the threshold chosen on validation)")
    ap.add_argument("--thresh", type=float, help="override the report's threshold")
    ap.add_argument("--frames", default="data/uvh26/val_sample")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument(
        "--sheet", help="draw the highest-scoring frames here (.jpg), for review by eye"
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import onnxruntime as ort  # noqa: PLC0415

    if args.thresh is not None:
        t, source = args.thresh, "command line"
    else:
        rep = json.loads(Path(args.report).read_text())
        t, source = rep["threshold"]["t"], f"{args.report}: {rep['threshold']['chosen_on']}"
    sess = ort.InferenceSession(args.model, providers=["CPUExecutionProvider"])
    meta = sess.get_modelmeta().custom_metadata_map
    names = ast.literal_eval(meta["names"]) if "names" in meta else {0: "fire", 1: "smoke"}
    names = [names[k] for k in sorted(names)]
    assert sorted(names) == ["fire", "smoke"], names
    inp = sess.get_inputs()[0].name
    frames = sorted(
        p for p in Path(args.frames).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")
    )
    assert frames, f"no frames in {args.frames}"
    rows, times = [], []
    for i, p in enumerate(frames):
        img = cv2.imread(str(p))
        if img is None:
            raise SystemExit(f"{p} does not open")
        x, r, (left, top) = letterbox(img, args.imgsz, rect=True, stride=32)
        x = np.ascontiguousarray(x[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        t0 = time.perf_counter()
        y = sess.run(None, {inp: x})[0][0]  # (4 + 2, N)
        if i >= 3:  # the first runs warm up
            times.append((time.perf_counter() - t0) * 1000)
        cls = y[4 : 4 + len(names)]
        best = int(np.argmax(cls.max(0)))
        k = int(np.argmax(cls[:, best]))
        cx, cy, w, h = (float(v) for v in y[:4, best])
        box = [
            (cx - w / 2 - left) / r,
            (cy - h / 2 - top) / r,
            (cx + w / 2 - left) / r,
            (cy + h / 2 - top) / r,
        ]
        rows.append(
            {
                "frame": p.name,
                **{n: float(cls[j].max()) for j, n in enumerate(names)},
                "top_class": names[k],
                "top_box": [round(v, 1) for v in box],
            }
        )
    top = np.array([max(r["fire"], r["smoke"]) for r in rows])
    alarms = [r for r, s in zip(rows, top, strict=True) if s >= t]
    out = {
        "model": args.model,
        "threshold": t,
        "threshold_from": source,
        "frames": len(rows),
        "alarms": len(alarms),
        "alarm_share": len(alarms) / len(rows),
        "bar_max_share": FA_BAR,
        "passes": len(alarms) / len(rows) <= FA_BAR,
        "score_quantiles": {q: round(float(np.quantile(top, q)), 4) for q in (0.5, 0.9, 0.99, 1.0)},
        "cpu_ms_per_frame_median": round(statistics.median(times), 1) if times else None,
        "alarm_frames": sorted(alarms, key=lambda r: -max(r["fire"], r["smoke"])),
        "highest_scoring": sorted(rows, key=lambda r: -max(r["fire"], r["smoke"]))[:12],
    }
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"threshold {t} ({source})")
    print(
        f"{len(alarms)} of {len(rows)} frames alarm ({100 * out['alarm_share']:.1f} %; bar <= "
        f"{100 * FA_BAR:.0f} %): {'passes' if out['passes'] else 'FAILS'}"
    )
    print(
        "highest scores:",
        [
            (r["frame"], r["top_class"], round(max(r["fire"], r["smoke"]), 3))
            for r in out["highest_scoring"][:5]
        ],
    )
    print("CPU per frame (median):", out["cpu_ms_per_frame_median"], "ms")
    if args.sheet:
        tiles = []
        for r in out["highest_scoring"][:8]:
            img = cv2.imread(str(Path(args.frames) / r["frame"]))
            x1, y1, x2, y2 = (int(v) for v in r["top_box"])
            col = (0, 128, 255) if r["top_class"] == "fire" else (200, 200, 200)
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 4)
            cv2.putText(
                img,
                f"{r['top_class']} {max(r['fire'], r['smoke']):.2f}",
                (x1, max(30, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                col,
                3,
            )
            tiles.append(cv2.resize(img, (480, 270)))
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[i : i + 4]) for i in range(0, len(tiles), 4)])
        cv2.imwrite(args.sheet, grid, [cv2.IMWRITE_JPEG_QUALITY, 85])


if __name__ == "__main__":
    main()

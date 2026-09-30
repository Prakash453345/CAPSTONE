"""Compare detectors on labelled Indian CCTV images (M8).

Runs each model through the pipeline's own adapter (`UltralyticsDetector`,
so the class mapping the live system uses is what gets scored) over the
UVH-26 validation sample that `scripts/m8_fetch_uvh26_sample.py`
downloads, and scores it with `vision_service.eval.detection`: AP50 per
class, and -- at ByteTrack's high-score line, what tracks are built from --
recall, precision, confusions, false positives, recall by box size, the
per-image PCU count error, and CPU time per image.

    python scripts/m8_detector_eval.py --data data/uvh26 \\
        --model stock=yolo11s.pt --model uvh26=data/uvh26/UVH-26-MV-YOLOv11-S.pt \\
        --imgsz 640 --out results/m8_detector_eval.json

`--clips a.mp4 b.avi` also counts, per model, the vehicle boxes found on
evenly spaced frames of unlabelled video (no accuracy there -- a check that
a model finds vehicles at all on a view it was not trained on).

Needs `pip install -e 'services/vision-service[yolo]'`, or only
`onnxruntime opencv-python-headless` for `.onnx` models (export with
`yolo export model=<file>.pt format=onnx dynamic=True`).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from collections import Counter
from pathlib import Path

import numpy as np
from vision_service.classes import VClass, vclass_from_name
from vision_service.eval.detection import DetectionEval

WARMUP = 3


def load_truth(data: Path) -> tuple[list[dict], dict[int, list[tuple[list[float], VClass | None]]],
                                    dict[int, str]]:
    coco = json.loads((data / "val_sample.json").read_text())
    cat = {c["id"]: c["name"] for c in coco["categories"]}
    boxes: dict[int, list] = {im["id"]: [] for im in coco["images"]}
    for a in coco["annotations"]:
        x, y, w, h = a["bbox"]
        boxes[a["image_id"]].append(([x, y, x + w, y + h], vclass_from_name(cat[a["category_id"]])))
    return coco["images"], boxes, cat


def evaluate(det, images, truth, data: Path, op: float, limit: int | None) -> dict:
    import cv2  # noqa: PLC0415

    ev = DetectionEval(op_thresh=op)
    times = []
    for i, im in enumerate(images[:limit] if limit else images):
        frame = cv2.imread(str(data / "val_sample" / im["file_name"]))
        if frame is None:
            raise SystemExit(f"cannot read {im['file_name']}")
        t0 = time.perf_counter()
        dets = [d for d in det.detect(frame) if d.vclass is not VClass.PERSON]
        if i >= WARMUP:
            times.append(time.perf_counter() - t0)
        gt = truth[im["id"]]
        ev.add([b for b, _ in gt], [c for _, c in gt], [d.box for d in dets],
               [d.score for d in dets], [d.vclass for d in dets], image=im["file_name"])
    s = ev.summary()
    s["per_image"] = ev.per_image          # for scripts/m8_detector_compare.py
    s["per_box"] = ev.per_box              # for scripts/m8_simcam_calibrate.py
    s["cpu_ms_per_image"] = {"median": 1000 * statistics.median(times) if times else None,
                             "mean": 1000 * statistics.mean(times) if times else None,
                             "n": len(times)}
    return s


def clip_counts(det, path: str, frames: int, op: float) -> dict:
    import cv2  # noqa: PLC0415

    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    idx = sorted({int(round(k)) for k in np.linspace(0, max(n - 1, 0), frames)})
    per_class: Counter = Counter()
    with_vehicle = 0
    for k in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, k)
        ok, frame = cap.read()
        if not ok:
            continue
        found = [d for d in det.detect(frame) if d.score >= op and d.vclass is not VClass.PERSON]
        per_class.update(d.vclass.value for d in found)
        with_vehicle += bool(found)
    cap.release()
    return {"frames": len(idx), "frames_with_a_vehicle_box": with_vehicle,
            "vehicle_boxes": sum(per_class.values()), "by_class": dict(per_class.most_common())}


def load_detector(weights: str, floor: float, imgsz: int):
    """`(detector, {id: name}, backend)`: a `.onnx` file runs on ONNX
    Runtime (no torch; `OnnxDetector` matches Ultralytics box for box on a
    dynamic-shape export), anything else on Ultralytics."""
    if weights.endswith(".onnx"):
        import ast  # noqa: PLC0415

        from vision_service.detect.yolo import OnnxDetector  # noqa: PLC0415

        det = OnnxDetector(weights, conf=floor, imgsz=imgsz,
                           providers=["CPUExecutionProvider"])
        meta = det.session.get_modelmeta().custom_metadata_map
        names = ast.literal_eval(meta["names"]) if "names" in meta else {}
        return det, dict(names) if isinstance(names, dict) else dict(enumerate(names)), \
            f"onnxruntime {__import__('onnxruntime').__version__}"
    import torch  # noqa: PLC0415
    from vision_service.detect.yolo import UltralyticsDetector  # noqa: PLC0415

    torch.set_num_threads(os.cpu_count() or 1)
    det = UltralyticsDetector(weights, conf=floor, imgsz=imgsz, device="cpu")
    names = det.model.names
    return det, names if isinstance(names, dict) else dict(enumerate(names)), \
        f"torch {torch.__version__}, {torch.get_num_threads()} threads"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/uvh26")
    ap.add_argument("--model", action="append", required=True, help="name=weights (repeat)")
    ap.add_argument("--imgsz", type=int, nargs="+", default=[640])
    ap.add_argument("--op", type=float, default=0.5, help="operating threshold (ByteTrack high)")
    ap.add_argument("--floor", type=float, default=0.05, help="lowest score kept, for AP")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--clips", nargs="*", default=[])
    ap.add_argument("--clip-frames", type=int, default=75)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = Path(args.data)
    images, truth, cats = load_truth(data)
    result: dict = {
        "meta": {"data": str(data), "images": len(images[:args.limit] if args.limit else images),
                 "categories": {n: (vclass_from_name(n).value if vclass_from_name(n) else None)
                                for n in cats.values()},
                 "op_thresh": args.op, "score_floor": args.floor,
                 "cpu": platform.processor() or platform.machine(), "cpus": os.cpu_count()},
        "models": {}, "clips": {}}
    for spec in args.model:
        name, weights = spec.split("=", 1)
        for imgsz in args.imgsz:
            key = f"{name}@{imgsz}"
            det, names, backend = load_detector(weights, args.floor, imgsz)
            print(f"{key} ({backend}): {len(names)} classes", flush=True)
            s = evaluate(det, images, truth, data, args.op, args.limit)
            s["weights"] = weights
            s["backend"] = backend
            s["imgsz"] = imgsz
            s["class_map"] = {str(n): (det.class_map[i].value if i in det.class_map else None)
                              for i, n in sorted(names.items())
                              if len(names) <= 20 or i in det.class_map}
            result["models"][key] = s
            print(f"  mAP50 {s['map50']:.3f}  vehicle recall {s['vehicle_recall']:.3f}  "
                  f"precision {s['vehicle_precision']:.3f}  FP/img {s['false_pos_per_image']:.2f}  "
                  f"PCU bias {s['pcu_per_image']['bias']:+.2f}  "
                  f"{s['cpu_ms_per_image']['median']:.0f} ms/img", flush=True)
            for clip in args.clips:
                c = clip_counts(det, clip, args.clip_frames, args.op)
                result["clips"].setdefault(Path(clip).name, {})[key] = c
                print(f"  {Path(clip).name}: {c['vehicle_boxes']} boxes, "
                      f"{c['frames_with_a_vehicle_box']}/{c['frames']} frames", flush=True)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()

"""Diagnostic: how much do repaired BatchNorm statistics change a detector?

IISc's released model has non-finite BatchNorm statistics, and the version 1
fine-tunes have theirs clipped to 65,504 by half-precision saves. This
re-estimates them in full precision and scores the result, three ways:

- rect:     letterboxed frames as the detectors see them at inference;
- square:   frames padded to a square;
- pipeline: Ultralytics' own training pipeline with the model's own
            augmentation settings (what notebook version 2 does, on
            training images).

**Calibration uses the even-indexed test frames (images only, no labels) and
scoring the odd-indexed ones**, so the two never overlap. But they come from
the same cameras, so this is a diagnostic to choose a method, not a result:
the Colab notebook repairs on training images and the full 250 frames judge
it. JPEG copies of the frames, 640 px input, the tracker's 0.5 line.

    python bn_split.py --frames tjpg --labels data/uvh26/val_sample.json \\
        --iisc UVH-26-MV-YOLOv11-S.pt --ft6 itms_six_640.pt --out bn_split.json
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time

import cv2
import numpy as np
import torch
from vision_service.classes import VClass, vclass_from_name
from vision_service.detect.yolo import UltralyticsDetector, batchnorm_health, letterbox
from vision_service.eval.detection import DetectionEval, paired_bootstrap

AUG_KEYS = (
    "mosaic",
    "mixup",
    "cutmix",
    "copy_paste",
    "degrees",
    "translate",
    "scale",
    "shear",
    "perspective",
    "flipud",
    "fliplr",
    "hsv_h",
    "hsv_s",
    "hsv_v",
    "bgr",
)


def raw(det: UltralyticsDetector) -> UltralyticsDetector:
    """Run every model through the raw head (a 6-class model would otherwise go through
    Ultralytics' predictor, which fuses BatchNorm away before we can touch it)."""
    det._raw = True
    det._net = det.model.model.float().eval()
    det._stride = int(max(det._net.stride))
    return det


def _reset(net: torch.nn.Module) -> list:
    bns = [m for m in net.modules() if isinstance(m, torch.nn.BatchNorm2d)]
    for m in bns:
        m.reset_running_stats()
        m.momentum = None
    net.train()
    return bns


def _done(net: torch.nn.Module, bns: list) -> None:
    net.eval()
    for m in bns:
        m.momentum = 0.03


def recal_letterbox(det: UltralyticsDetector, frames: list[np.ndarray], rect: bool) -> None:
    net = det._net
    bns = _reset(net)
    xs = [letterbox(f, 640, rect=rect, stride=32)[0] for f in frames]
    groups: dict = {}
    for x in xs:
        groups.setdefault(x.shape, []).append(x)
    with torch.no_grad():
        for g in groups.values():
            for i in range(0, len(g), 8):
                b = np.stack([x[:, :, ::-1].transpose(2, 0, 1) for x in g[i : i + 8]])
                net(torch.from_numpy(np.ascontiguousarray(b, dtype=np.float32) / 255.0))
    _done(net, bns)


def recal_pipeline(det: UltralyticsDetector, data_yaml: str, train_args: dict) -> None:
    from ultralytics.cfg import get_cfg  # noqa: PLC0415
    from ultralytics.data import build_dataloader, build_yolo_dataset  # noqa: PLC0415
    from ultralytics.data.utils import check_det_dataset  # noqa: PLC0415
    from ultralytics.utils.torch_utils import init_seeds  # noqa: PLC0415

    init_seeds(26, deterministic=True)
    aug = {k: train_args[k] for k in AUG_KEYS if k in train_args}
    cfg = get_cfg(overrides={**aug, "imgsz": 640, "rect": False, "cache": False, "seed": 26})
    data = check_det_dataset(data_yaml)
    dl = build_dataloader(
        build_yolo_dataset(cfg, data["train"], 8, data, mode="train", stride=32),
        8,
        0,
        shuffle=True,
        rank=-1,
    )
    net = det._net
    bns = _reset(net)
    with torch.no_grad():
        for b in dl:
            net(b["img"].float() / 255)
    _done(net, bns)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True, help="the 250 test frames (stem.jpg or stem.png)")
    ap.add_argument("--labels", required=True, help="val_sample.json")
    ap.add_argument("--iisc", required=True)
    ap.add_argument("--ft6", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    torch.set_num_threads(4)
    coco = json.load(open(args.labels))
    cat = {c["id"]: c["name"] for c in coco["categories"]}
    id2n = {im["id"]: im["file_name"] for im in coco["images"]}
    gt: dict = {n: [] for n in id2n.values()}
    for a in coco["annotations"]:
        x, y, w, h = a["bbox"]
        gt[id2n[a["image_id"]]].append(
            ([x, y, x + w, y + h], vclass_from_name(cat[a["category_id"]]))
        )
    names = sorted(gt)
    calib, score = names[0::2], names[1::2]

    def path(n: str) -> str:
        stem = os.path.splitext(n)[0]
        return next(
            p
            for p in (f"{args.frames}/{stem}.jpg", f"{args.frames}/{stem}.png")
            if os.path.exists(p)
        )

    frames = {n: cv2.imread(path(n)) for n in names}
    # the calibration half as a one-class YOLO dataset, for the training pipeline
    tmp = tempfile.mkdtemp(prefix="bncal_")
    for sub in ("images/train", "labels/train"):
        os.makedirs(f"{tmp}/{sub}")
    for n in calib:
        stem = os.path.splitext(n)[0]
        os.symlink(
            os.path.abspath(path(n)), f"{tmp}/images/train/{stem}{os.path.splitext(path(n))[1]}"
        )
        H, W = frames[n].shape[:2]
        with open(f"{tmp}/labels/train/{stem}.txt", "w") as f:
            for (x1, y1, x2, y2), _ in gt[n]:
                f.write(
                    f"0 {(x1 + x2) / 2 / W:.6f} {(y1 + y2) / 2 / H:.6f} "
                    f"{(x2 - x1) / W:.6f} {(y2 - y1) / H:.6f}\n"
                )
    yaml = f"{tmp}/d.yaml"
    open(yaml, "w").write(f"path: {tmp}\ntrain: images/train\nval: images/train\nnames:\n  0: v\n")

    def run(det: UltralyticsDetector) -> DetectionEval:
        ev = DetectionEval()
        for n in score:
            d = [x for x in det.detect(frames[n]) if x.vclass is not VClass.PERSON]
            ev.add(
                [b for b, _ in gt[n]],
                [c for _, c in gt[n]],
                [x.box for x in d],
                [x.score for x in d],
                [x.vclass for x in d],
                image=n,
            )
        return ev

    arms, health = {}, {}
    for model, weights in (("iisc", args.iisc), ("ft6", args.ft6)):
        train_args = torch.load(weights, map_location="cpu", weights_only=False)["train_args"]
        for how in ("as_delivered", "rect", "square", "pipeline"):
            t = time.time()
            det = raw(UltralyticsDetector(weights, conf=0.05, imgsz=640, device="cpu"))
            if how in ("rect", "square"):
                recal_letterbox(det, [frames[n] for n in calib], rect=how == "rect")
            elif how == "pipeline":
                recal_pipeline(det, yaml, train_args)
            key = f"{model}_{how}"
            health[key] = batchnorm_health(det._net)
            arms[key] = run(det)
            s = arms[key].summary()
            print(
                f"{key:18s} recall {s['vehicle_recall']:.3f}  "
                f"precision {s['vehicle_precision']:.3f}  "
                f"false/img {s['false_pos_per_image']:.3f}  mAP50 {s['map50']:.3f}  "
                f"PCU MAE {s['pcu_per_image']['mae']:.3f}  bias {s['pcu_per_image']['bias']:+.3f}  "
                f"{health[key]}  {time.time() - t:.0f} s",
                flush=True,
            )
    pairs = [("iisc_as_delivered", f"iisc_{h}") for h in ("rect", "square", "pipeline")]
    pairs += [("ft6_as_delivered", f"ft6_{h}") for h in ("rect", "square", "pipeline")]
    pairs += [
        ("iisc_as_delivered", "ft6_as_delivered"),
        ("iisc_as_delivered", "ft6_pipeline"),
        ("iisc_pipeline", "ft6_pipeline"),
    ]
    paired = {}
    for a, b in pairs:
        paired[f"{a} -> {b}"] = cmp = paired_bootstrap(
            arms[a].per_image, arms[b].per_image, n=10000
        )
        print(f"{a} -> {b}")
        for k, r in cmp.items():
            print(
                f"    {k:22s} {r['a']:.3f} -> {r['b']:.3f}  {r['diff']:+.3f} "
                f"[{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}]{' *' if r['excludes_zero'] else ''}"
            )
    summ = {
        k: {
            x: v
            for x, v in ev.summary().items()
            if x
            in (
                "vehicle_recall",
                "correct_type_recall",
                "vehicle_precision",
                "false_pos_per_image",
                "map50",
                "pcu_per_image",
                "images",
                "vehicles",
            )
        }
        for k, ev in arms.items()
    }
    json.dump(
        {
            "calibration_frames": calib,
            "scored_frames": score,
            "input_px": 640,
            "op_thresh": 0.5,
            "batchnorm_health": health,
            "summary": summ,
            "paired": paired,
        },
        open(args.out, "w"),
        indent=1,
        default=str,
    )


if __name__ == "__main__":
    main()

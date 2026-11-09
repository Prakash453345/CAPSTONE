"""Fit SimCam detector-error presets from the full UVH-26 validation detections (M8).

Same maximum-likelihood fit as `m8_simcam_calibrate.py`, but the per-box records come from the
saved full-val detections (`m8_detector_fullval.py` runs) instead of a 250-frame still test, at the
score line each model was adopted at (`m8_detector_matched.py`). Frames: the 4,797 UNTOUCHED ones
(a fit is not tuning, but this keeps the DEV frames out of anything reported).

    python m8_simcam_fit_fullval.py --labels UVH-26-MV-Val.json --old250 val_sample.json \
        --fresh250 fresh_names.json --run <score dir>/run --model m_coco=0.60 --out fit.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from m8_detector_fullval import load_dets
import numpy as np
import m8_simcam_calibrate as cal
from m8_simcam_calibrate import confusion, fit
from vision_service.classes import VClass, vclass_from_name
from vision_service.eval.detection import DetectionEval


CAP = 1500   # boxes per class used in the fit (seeded subsample); a full 60k-box grid search takes hours


def cap_boxes(per_box: list, seed: int = 0) -> list:
    rng = np.random.default_rng(seed)
    out = []
    for c in sorted({b[0] for b in per_box}):
        rows = [b for b in per_box if b[0] == c]
        if len(rows) > CAP:
            rows = [rows[i] for i in sorted(rng.choice(len(rows), CAP, replace=False))]
        out += rows
    return out


def main() -> None:
    cal.H50_GRID = np.arange(5.0, 400.0 + 1e-9, 1.0)   # 1 px steps (calibrate uses 0.25)
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--old250", required=True)
    ap.add_argument("--fresh250", required=True)
    ap.add_argument("--run", action="append", required=True)
    ap.add_argument("--model", action="append", required=True, help="name=score_line")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    dets = {}
    for r in a.run:
        dets.update(load_dets(Path(r))[1])
    coco = json.loads(Path(a.labels).read_text())
    cat = {c["id"]: c["name"] for c in coco["categories"]}
    id2n = {i["id"]: i["file_name"] for i in coco["images"]}
    truth = {n: ([], []) for n in id2n.values()}
    for an in coco["annotations"]:
        x, y, w, h = an["bbox"]
        n = id2n[an["image_id"]]
        truth[n][0].append([x, y, x + w, y + h])
        truth[n][1].append(vclass_from_name(cat[an["category_id"]]))
    old = {i["file_name"] for i in json.loads(Path(a.old250).read_text())["images"]}
    fresh = {str(x) for x in json.loads(Path(a.fresh250).read_text())}
    classes = list(VClass)
    out = {}
    for spec in a.model:
        m, thr = spec.split("=")
        d = dets[f"{m}_6"]
        names = sorted(set(d) - old - fresh)
        ev = DetectionEval(op_thresh=float(thr))
        for n in names:
            b, s, c = d[n]
            ev.add(truth[n][0], truth[n][1], b, s, [classes[i] for i in c], image=n)
        summ = ev.summary()
        f = fit(cap_boxes(ev.per_box))
        f["confusion"] = confusion(summ["per_class"])
        f["source"] = {"model": m, "op_thresh": float(thr), "frames": len(names),
                       "frames_set": "UNTOUCHED", "boxes": len(ev.per_box), "fit_boxes_cap_per_class": CAP}
        out[m] = f
        print(m, "frames", len(names), "boxes", len(ev.per_box))
        print("  base_recall", f["base_recall"])
        print("  size_h50", f["size_h50_by_class"], "pooled", f["size_h50_px"])
        print("  confusion", f["confusion"])
    Path(a.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

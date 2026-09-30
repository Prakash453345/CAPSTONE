"""Score a tracker against annotated real video in MOTChallenge format -- how
the digital twin's assumed error presets get replaced by measured ones.

MOTChallenge text format, one box per line:

    frame, id, x, y, w, h, conf, class, visibility

(`x, y` top-left, pixels; `class` and `visibility` optional). Ground truth
rows with `conf == 0` are "ignore" regions and are skipped, as the benchmark
does. BMD-45, UA-DETRAC and most Indian traffic datasets either ship this
format or convert to it in a few lines.

    python -m vision_service.eval.mot gt.txt pred.txt

prints MOTA, IDF1, recall, precision and identity switches.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from vision_service.eval.metrics import ClearMot


def load_mot(path: str | Path, *, is_gt: bool = False) -> dict[int, list[tuple[int, np.ndarray]]]:
    """`{frame: [(id, box_xyxy), ...]}`."""
    frames: dict[int, list[tuple[int, np.ndarray]]] = defaultdict(list)
    for line in Path(path).read_text().splitlines():
        parts = [p.strip() for p in line.replace(";", ",").split(",") if p.strip()]
        if len(parts) < 6:
            continue
        f, i = int(float(parts[0])), int(float(parts[1]))
        x, y, w, h = (float(v) for v in parts[2:6])
        if is_gt and len(parts) >= 7 and float(parts[6]) == 0:
            continue
        frames[f].append((i, np.array([x, y, x + w, y + h])))
    return frames


def evaluate(gt_path: str | Path, pred_path: str | Path, iou: float = 0.5) -> dict:
    gt = load_mot(gt_path, is_gt=True)
    pred = load_mot(pred_path)
    acc = ClearMot(iou_thresh=iou)
    for f in sorted(set(gt) | set(pred)):
        g = gt.get(f, [])
        p = pred.get(f, [])
        acc.update(
            [i for i, _ in p],
            np.array([b for _, b in p]).reshape(-1, 4),
            [i for i, _ in g],
            np.array([b for _, b in g]).reshape(-1, 4),
        )
    out = acc.summary()
    out["frames"] = len(set(gt) | set(pred))
    return out


def write_mot(path: str | Path, rows: list[tuple[int, int, np.ndarray, float]]) -> None:
    """`rows`: `(frame, track_id, box_xyxy, score)` -> MOTChallenge text."""
    lines = []
    for f, i, b, s in rows:
        x1, y1, x2, y2 = (float(v) for v in b)
        lines.append(f"{f},{i},{x1:.2f},{y1:.2f},{x2 - x1:.2f},{y2 - y1:.2f},{s:.3f},-1,-1")
    Path(path).write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("gt")
    ap.add_argument("pred")
    ap.add_argument("--iou", type=float, default=0.5)
    args = ap.parse_args()
    print(json.dumps(evaluate(args.gt, args.pred, args.iou), indent=2))


if __name__ == "__main__":
    main()

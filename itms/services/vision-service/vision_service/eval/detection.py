"""Still-image detector evaluation in the ITMS taxonomy (M8), numpy only.

Scores a detector against labelled images -- UVH-26 / BMD-45 validation
images, or frames of Vijayawada footage labelled by hand -- the way the
rest of the pipeline will use it, not only the way detection papers do:

- **AP50 per class** (class-aware, all-point interpolation): the
  threshold-free number papers report, for comparing detectors;
- **at an operating threshold** (default 0.5, ByteTrack's high-score line):
  what the tracker actually builds tracks from --
  - recall and precision per class,
  - *found as some vehicle* per class (a miss costs the queue a vehicle; a
    wrong type costs it only the PCU difference),
  - the confusion table, truth class -> reported class, with misses,
  - false positives per image,
  - recall by box height (the SimCam error model's size curve),
  - the per-image **PCU count error**: the quantity `queue_pcu` is made of.

Truth boxes labelled with a class the taxonomy drops (UVH-26's "Others")
are *ignore regions*: a detection on one is neither a hit nor a false
positive, as MOTChallenge treats distractors.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from vision_service.classes import ClassTable, VClass
from vision_service.eval.metrics import match_boxes
from vision_service.track.assignment import iou_matrix

SIZE_BINS_PX = (0.0, 20.0, 40.0, 80.0, float("inf"))  # truth box height


def average_precision(scores: Sequence[float], hits: Sequence[bool], n_truth: int) -> float:
    """All-point interpolated AP (VOC 2010+) of one class."""
    if n_truth == 0:
        return float("nan")
    if len(scores) == 0:
        return 0.0
    order = np.argsort(-np.asarray(scores, dtype=np.float64), kind="stable")
    tp = np.asarray(hits, dtype=np.float64)[order]
    ctp, cfp = np.cumsum(tp), np.cumsum(1.0 - tp)
    recall = ctp / n_truth
    precision = ctp / np.maximum(ctp + cfp, 1e-12)
    r = np.concatenate([[0.0], recall, [recall[-1]]])
    p = np.concatenate([[1.0], precision, [0.0]])
    p = np.maximum.accumulate(p[::-1])[::-1]
    step = np.nonzero(r[1:] != r[:-1])[0]
    return float(np.sum((r[step + 1] - r[step]) * p[step + 1]))


def _as_boxes(b) -> np.ndarray:
    return np.asarray(b, dtype=np.float64).reshape(-1, 4)


@dataclass
class DetectionEval:
    op_thresh: float = 0.5
    iou_thresh: float = 0.5
    classes: ClassTable = field(default_factory=ClassTable.default)
    images: int = 0
    n_truth: dict = field(default_factory=lambda: defaultdict(int))
    _ap: dict = field(default_factory=lambda: defaultdict(list))   # class -> [(score, hit)]
    confusion: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    reported: dict = field(default_factory=lambda: defaultdict(int))  # class -> boxes >= op
    false_pos: dict = field(default_factory=lambda: defaultdict(int))
    ignored: int = 0
    _size_hit: list = field(default_factory=lambda: [0] * (len(SIZE_BINS_PX) - 1))
    _size_all: list = field(default_factory=lambda: [0] * (len(SIZE_BINS_PX) - 1))
    pcu_truth: list = field(default_factory=list)
    pcu_found: list = field(default_factory=list)

    def add(self, truth_boxes, truth_cls: Sequence[VClass | None],
            pred_boxes, pred_scores: Sequence[float], pred_cls: Sequence[VClass]) -> None:
        """One image. `truth_cls[i] is None` marks an ignore region."""
        tb, pb = _as_boxes(truth_boxes), _as_boxes(pred_boxes)
        ps = np.asarray(pred_scores, dtype=np.float64)
        keep_t = [i for i, c in enumerate(truth_cls) if c is not None]
        ign = [i for i, c in enumerate(truth_cls) if c is None]
        tcls = [truth_cls[i] for i in keep_t]
        tb_k, tb_ign = tb[keep_t], tb[ign]
        # a prediction lying on an ignore region, and on no real vehicle, is dropped
        on_ign = (iou_matrix(pb, tb_ign).max(axis=1, initial=0.0) >= self.iou_thresh
                  if len(ign) else np.zeros(len(pb), bool))
        on_real = (iou_matrix(pb, tb_k).max(axis=1, initial=0.0) >= self.iou_thresh
                   if len(keep_t) else np.zeros(len(pb), bool))
        drop = on_ign & ~on_real
        self.images += 1
        for c in tcls:
            self.n_truth[c] += 1

        # class-aware, greedy by score (the AP convention)
        for c in {*tcls, *pred_cls}:
            ti = [k for k, tc in enumerate(tcls) if tc == c]
            pi = [k for k, pc in enumerate(pred_cls) if pc == c and not drop[k]]
            pi.sort(key=lambda k: -ps[k])
            iou = iou_matrix(pb[pi], tb_k[ti]) if pi and ti else np.zeros((len(pi), len(ti)))
            used = np.zeros(len(ti), bool)
            for row, k in enumerate(pi):
                hit = False
                if len(ti):
                    cand = np.where(used, -1.0, iou[row])
                    j = int(np.argmax(cand))
                    if cand[j] >= self.iou_thresh:
                        used[j] = hit = True
                self._ap[c].append((float(ps[k]), hit))

        # class-agnostic, optimal, at the operating threshold
        op = [k for k in range(len(pb)) if ps[k] >= self.op_thresh and not drop[k]]
        self.ignored += int(sum(1 for k in range(len(pb)) if ps[k] >= self.op_thresh and drop[k]))
        for k in op:
            self.reported[pred_cls[k]] += 1
        matches, un_p, un_t = match_boxes(pb[op], tb_k, self.iou_thresh)
        for pi_, ti_ in matches:
            self.confusion[tcls[ti_]][pred_cls[op[pi_]]] += 1
        for ti_ in un_t:
            self.confusion[tcls[ti_]]["missed"] += 1
        for pi_ in un_p:
            self.false_pos[pred_cls[op[pi_]]] += 1
        found = {ti_ for _, ti_ in matches}
        for j in range(len(tcls)):
            h = tb_k[j, 3] - tb_k[j, 1]
            b = int(np.searchsorted(SIZE_BINS_PX, h, side="right") - 1)
            self._size_all[b] += 1
            self._size_hit[b] += j in found
        self.pcu_truth.append(sum(self.classes.pcu(c) for c in tcls))
        self.pcu_found.append(sum(self.classes.pcu(pred_cls[k]) for k in op))

    def summary(self) -> dict:
        per_class = {}
        for c in sorted(self.n_truth, key=lambda v: v.value):
            n = self.n_truth[c]
            row = self.confusion[c]
            correct = row.get(c, 0)
            found = sum(v for k, v in row.items() if k != "missed")
            rep = self.reported.get(c, 0)
            sc = self._ap.get(c, [])
            per_class[c.value] = {
                "truth": n,
                "ap50": average_precision([s for s, _ in sc], [h for _, h in sc], n),
                "recall": correct / n if n else float("nan"),
                "found_as_some_vehicle": found / n if n else float("nan"),
                "precision": correct / rep if rep else float("nan"),
                "reported_as": {(k.value if isinstance(k, VClass) else k): v
                                for k, v in sorted(row.items(), key=lambda kv: -kv[1])},
            }
        n_all = sum(self.n_truth.values())
        matched = sum(v for row in self.confusion.values() for k, v in row.items()
                      if k != "missed")
        fp = sum(self.false_pos.values())
        aps = [v["ap50"] for v in per_class.values() if v["truth"] > 0]
        t, f = np.asarray(self.pcu_truth), np.asarray(self.pcu_found)
        bins = [f"{lo:g}-{hi:g}px" for lo, hi in zip(SIZE_BINS_PX[:-1], SIZE_BINS_PX[1:],
                                                      strict=True)]
        return {
            "images": self.images,
            "op_thresh": self.op_thresh,
            "iou_thresh": self.iou_thresh,
            "map50": float(np.mean(aps)) if aps else float("nan"),
            "vehicles": n_all,
            "vehicle_recall": matched / n_all if n_all else float("nan"),
            "vehicle_precision": matched / (matched + fp) if matched + fp else float("nan"),
            "false_pos_per_image": fp / max(self.images, 1),
            "false_pos_by_class": {k.value: v for k, v in sorted(self.false_pos.items(),
                                                                 key=lambda kv: -kv[1])},
            "ignored_detections": self.ignored,
            "recall_by_height": {b: (self._size_hit[i] / self._size_all[i]
                                     if self._size_all[i] else None, self._size_all[i])
                                 for i, b in enumerate(bins)},
            "pcu_per_image": {"truth_mean": float(t.mean()) if len(t) else float("nan"),
                              "bias": float((f - t).mean()) if len(t) else float("nan"),
                              "mae": float(np.abs(f - t).mean()) if len(t) else float("nan")},
            "per_class": per_class,
        }

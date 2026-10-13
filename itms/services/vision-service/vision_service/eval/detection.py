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
  - the per-image **PCU count error**: the quantity `queue_pcu` is made of;
- **per-image counts** (`per_image`), so two detectors scored on the same
  images can be compared pairwise (`paired_bootstrap`).

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
    # per class and box height, at the operating threshold: [found, all] per bin
    _size_cls: dict = field(default_factory=lambda: defaultdict(
        lambda: [[0, 0] for _ in range(len(SIZE_BINS_PX) - 1)]))
    per_image: list = field(default_factory=list)   # what a paired comparison resamples
    per_box: list = field(default_factory=list)     # per truth box: class, height, found, type ok

    def add(self, truth_boxes, truth_cls: Sequence[VClass | None],
            pred_boxes, pred_scores: Sequence[float], pred_cls: Sequence[VClass],
            image: str = "") -> None:
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
        right = {ti_ for pi_, ti_ in matches if pred_cls[op[pi_]] == tcls[ti_]}
        for j in range(len(tcls)):
            h = tb_k[j, 3] - tb_k[j, 1]
            b = int(np.searchsorted(SIZE_BINS_PX, h, side="right") - 1)
            self._size_all[b] += 1
            self._size_hit[b] += j in found
            self._size_cls[tcls[j]][b][0] += j in found
            self._size_cls[tcls[j]][b][1] += 1
            self.per_box.append((tcls[j].value, round(float(h), 1), j in found, j in right))
        pcu_t = sum(self.classes.pcu(c) for c in tcls)
        pcu_f = sum(self.classes.pcu(pred_cls[k]) for k in op)
        self.pcu_truth.append(pcu_t)
        self.pcu_found.append(pcu_f)
        self.per_image.append({
            "image": image, "truth": len(tcls), "found": len(matches),
            "correct": sum(1 for pi_, ti_ in matches if pred_cls[op[pi_]] == tcls[ti_]),
            "false_pos": len(un_p), "pcu_truth": pcu_t, "pcu_found": pcu_f})

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
            "recall_by_height_by_class": {
                c.value: {b: (f / n if n else None, n)
                          for b, (f, n) in zip(bins, rows, strict=True)}
                for c, rows in sorted(self._size_cls.items(), key=lambda kv: kv[0].value)},
            "pcu_per_image": {"truth_mean": float(t.mean()) if len(t) else float("nan"),
                              "bias": float((f - t).mean()) if len(t) else float("nan"),
                              "mae": float(np.abs(f - t).mean()) if len(t) else float("nan")},
            "per_class": per_class,
        }



PAIRED_STATS = ("vehicle_recall", "correct_type_recall", "vehicle_precision",
                "false_pos_per_image", "pcu_mae", "pcu_bias")


def _stats(r: dict[str, np.ndarray], idx: np.ndarray) -> dict[str, np.ndarray]:
    """Every paired statistic for each resample (rows of `idx`)."""
    t, f, c, fp = (r[k][idx].sum(axis=-1) for k in ("truth", "found", "correct", "false_pos"))
    err = (r["pcu_found"] - r["pcu_truth"])[idx]
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"vehicle_recall": f / t, "correct_type_recall": c / t,
                "vehicle_precision": f / (f + fp), "false_pos_per_image": fp / idx.shape[-1],
                "pcu_mae": np.abs(err).mean(axis=-1), "pcu_bias": err.mean(axis=-1)}


def paired_bootstrap(a: list[dict], b: list[dict], *, n: int = 10_000, seed: int = 0) -> dict:
    """B minus A on the same images, with a 95 % interval from resampling
    images (both detectors keep the same resample). Images are matched by
    name; a mismatch is an error, not a silent partial comparison."""
    ia = {r["image"]: r for r in a}
    ib = {r["image"]: r for r in b}
    if set(ia) != set(ib) or len(ia) != len(a) or len(ib) != len(b):
        raise ValueError("the two runs were not scored on the same images")
    names = sorted(ia)
    keys = ("truth", "found", "correct", "false_pos", "pcu_truth", "pcu_found")
    ra = {k: np.array([ia[x][k] for x in names], dtype=np.float64) for k in keys}
    rb = {k: np.array([ib[x][k] for x in names], dtype=np.float64) for k in keys}
    whole = np.arange(len(names))
    pa, pb = _stats(ra, whole), _stats(rb, whole)
    idx = np.random.default_rng(seed).integers(0, len(names), size=(n, len(names)))
    sa, sb = _stats(ra, idx), _stats(rb, idx)
    out = {}
    for s in PAIRED_STATS:
        lo, hi = np.nanpercentile(sb[s] - sa[s], [2.5, 97.5])
        out[s] = {"a": float(pa[s]), "b": float(pb[s]), "diff": float(pb[s] - pa[s]),
                  "ci95": [float(lo), float(hi)], "excludes_zero": bool(lo > 0 or hi < 0)}
    return out

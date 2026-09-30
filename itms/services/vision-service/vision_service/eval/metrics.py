"""Detection and multi-object-tracking metrics, numpy only.

- `match_boxes`: one-to-one IoU matching of predictions to ground truth.
- `ClearMot`: CLEAR-MOT accumulation frame by frame (Bernardin & Stiefelhagen
  2008): misses, false positives, identity switches, MOTA.
- `idf1`: the identity F1 of Ristani et al. (2016) from whole-sequence
  per-(truth, prediction) overlap counts -- the metric that punishes a tracker
  for handing one vehicle's identity to another, which MOTA barely notices.

Used both by the digital-twin gate (truth from SimCam) and by
`vision_service/eval/mot.py` on real annotated video.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from vision_service.track.assignment import gated_assignment, iou_matrix, linear_sum_assignment


def match_boxes(pred: np.ndarray, truth: np.ndarray, iou_thresh: float = 0.5) -> tuple[
    list[tuple[int, int]], list[int], list[int]
]:
    """Optimal one-to-one matching with IoU >= `iou_thresh`. Returns
    `(matches (pred_i, truth_j), unmatched_pred, unmatched_truth)`."""
    if len(pred) == 0 or len(truth) == 0:
        return [], list(range(len(pred))), list(range(len(truth)))
    cost = 1.0 - iou_matrix(pred, truth)
    return gated_assignment(cost, 1.0 - iou_thresh)


@dataclass
class ClearMot:
    iou_thresh: float = 0.5
    gt: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    idsw: int = 0
    _last_match: dict = field(default_factory=dict)          # truth id -> pred id
    pair_counts: dict = field(default_factory=lambda: defaultdict(int))  # (truth, pred) -> frames
    gt_counts: dict = field(default_factory=lambda: defaultdict(int))
    pred_counts: dict = field(default_factory=lambda: defaultdict(int))

    def update(self, pred_ids: list, pred_boxes: np.ndarray, truth_ids: list,
               truth_boxes: np.ndarray) -> None:
        pred_boxes = np.asarray(pred_boxes, dtype=np.float64).reshape(-1, 4)
        truth_boxes = np.asarray(truth_boxes, dtype=np.float64).reshape(-1, 4)
        self.gt += len(truth_ids)
        for tid in truth_ids:
            self.gt_counts[tid] += 1
        for pid in pred_ids:
            self.pred_counts[pid] += 1
        matches, up, ut = self._match(pred_ids, pred_boxes, truth_ids, truth_boxes)
        self.tp += len(matches)
        self.fp += len(up)
        self.fn += len(ut)
        for pi, ti in matches:
            t_id, p_id = truth_ids[ti], pred_ids[pi]
            prev = self._last_match.get(t_id)
            if prev is not None and prev != p_id:
                self.idsw += 1
            self._last_match[t_id] = p_id
            self.pair_counts[(t_id, p_id)] += 1

    def _match(self, pred_ids: list, pred_boxes: np.ndarray, truth_ids: list,
               truth_boxes: np.ndarray) -> tuple[list[tuple[int, int]], list[int], list[int]]:
        """CLEAR-MOT's matching: a truth-track pair from the previous frame is
        kept while it still overlaps (IoU at or above the threshold); only the
        rest go to the optimal assignment. Without this step two tracks side
        by side can trade places in the assignment from one frame to the next
        on a hair's difference in IoU, and every trade is counted as an
        identity switch the tracker never made."""
        if len(pred_ids) == 0 or len(truth_ids) == 0:
            return [], list(range(len(pred_ids))), list(range(len(truth_ids)))
        iou = iou_matrix(pred_boxes, truth_boxes)
        p_index = {pid: i for i, pid in enumerate(pred_ids)}
        kept: list[tuple[int, int]] = []
        used_p: set[int] = set()
        for tj, tid in enumerate(truth_ids):
            pi = p_index.get(self._last_match.get(tid))
            # (a track can be the last match of two truths, one long gone)
            if pi is not None and pi not in used_p and iou[pi, tj] >= self.iou_thresh:
                kept.append((pi, tj))
                used_p.add(pi)
        used_t = {tj for _, tj in kept}
        rest_p = [i for i in range(len(pred_ids)) if i not in used_p]
        rest_t = [j for j in range(len(truth_ids)) if j not in used_t]
        m, up, ut = match_boxes(pred_boxes[rest_p], truth_boxes[rest_t], self.iou_thresh)
        matches = kept + [(rest_p[a], rest_t[b]) for a, b in m]
        return matches, [rest_p[a] for a in up], [rest_t[b] for b in ut]

    @property
    def mota(self) -> float:
        return 1.0 - (self.fn + self.fp + self.idsw) / self.gt if self.gt else float("nan")

    @property
    def recall(self) -> float:
        return self.tp / self.gt if self.gt else float("nan")

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else float("nan")

    @property
    def idf1(self) -> float:
        return idf1(self.pair_counts, self.gt_counts, self.pred_counts)

    def summary(self) -> dict:
        return {
            "gt": self.gt, "tp": self.tp, "fp": self.fp, "fn": self.fn, "idsw": self.idsw,
            "mota": self.mota, "idf1": self.idf1, "recall": self.recall,
            "precision": self.precision,
        }


def idf1(pair_counts, gt_counts, pred_counts) -> float:
    """IDF1 = 2 IDTP / (total truth detections + total predicted detections),
    with IDTP from the optimal one-to-one truth-id <-> prediction-id mapping
    over whole-sequence overlap counts.

    The overlap graph is extremely sparse (a vehicle shares frames with one to
    three tracks), so the assignment is solved per connected component --
    a whole hour of 19 cameras is tens of thousands of identities, which one
    dense Hungarian problem could never handle."""
    n_gt = sum(gt_counts.values())
    n_pred = sum(pred_counts.values())
    if n_gt + n_pred == 0:
        return float("nan")
    if not pair_counts:
        return 0.0
    parent: dict = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for g, pr in pair_counts:
        ra, rb = find(("g", g)), find(("p", pr))
        if ra != rb:
            parent[ra] = rb
    comps: dict = defaultdict(list)
    for (g, pr), c in pair_counts.items():
        comps[find(("g", g))].append((g, pr, c))
    idtp = 0.0
    for edges in comps.values():
        if len(edges) == 1:
            idtp += edges[0][2]
            continue
        gs = sorted({e[0] for e in edges}, key=str)
        ps = sorted({e[1] for e in edges}, key=str)
        gi = {g: i for i, g in enumerate(gs)}
        pi = {p: j for j, p in enumerate(ps)}
        m = np.zeros((len(gs), len(ps)))
        for g, pr, c in edges:
            m[gi[g], pi[pr]] = c
        r, c = linear_sum_assignment(-m)
        idtp += float(m[r, c].sum())
    return 2.0 * idtp / (n_gt + n_pred)


@dataclass
class ErrorStats:
    """Streaming mean / MAE / bias / correlation for paired values."""

    n: int = 0
    sum_t: float = 0.0
    sum_e: float = 0.0
    sum_abs: float = 0.0
    sum_tt: float = 0.0
    sum_ee: float = 0.0
    sum_te: float = 0.0

    def add(self, truth: float, est: float) -> None:
        if not (np.isfinite(truth) and np.isfinite(est)):
            return
        self.n += 1
        self.sum_t += truth
        self.sum_e += est
        self.sum_abs += abs(est - truth)
        self.sum_tt += truth * truth
        self.sum_ee += est * est
        self.sum_te += truth * est

    def summary(self) -> dict:
        n = self.n
        if n == 0:
            return {"n": 0}
        mt, me = self.sum_t / n, self.sum_e / n
        vt = self.sum_tt / n - mt * mt
        ve = self.sum_ee / n - me * me
        cov = self.sum_te / n - mt * me
        corr = cov / np.sqrt(vt * ve) if vt > 1e-12 and ve > 1e-12 else float("nan")
        return {"n": n, "truth_mean": mt, "est_mean": me, "mae": self.sum_abs / n,
                "bias": me - mt, "corr": float(corr)}

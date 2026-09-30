"""Score a whole `VisionSystem` against SUMO ground truth during one run.

Hooks into two places:

- every camera frame (`VisionSystem` pipelines' `observer`): detection
  recall/precision by class against what the camera could actually see, and
  CLEAR-MOT / IDF1 for the tracker;
- every controller tick (`on_tick`): per-link state against
  `QueueStateSampler.sample_extended()` -- the *same code* that feeds the
  controller its ground truth, so "error" means exactly "what the controller
  would see differently" -- plus ground-track position, speed, lane and
  stopped-state accuracy against each vehicle's true state.

"Could actually see" = at least `min_visible` of the box unoccluded and in
frame, and at least `min_box_px` tall: the standard MOT convention of not
charging a tracker for objects nobody could detect. The convention cuts both
ways (MOT17's distractor rule): a box that lands on one of those barely
visible vehicles is not a false positive either, so it is left out of the
scoring rather than charged. The first version charged it, and so counted
the second ByteTrack stage -- which exists to keep half-hidden vehicles
tracked -- against the tracker.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from vision_service.classes import VClass
from vision_service.eval.metrics import ClearMot, ErrorStats, match_boxes
from vision_service.pipeline import VisionSystem
from vision_service.records import Detection, ImageTrack
from vision_service.simcam.render import FilmedObjects
from vision_service.simcam.world import WorldSnapshot

QUANTITIES = ("queue_pcu", "approaching_pcu", "receiving_occupancy", "receiving_queue_pcu")


@dataclass
class TwinRecorder:
    system: VisionSystem
    samplers: Mapping[str, object]      # tls -> QueueStateSampler
    min_visible: float = 0.3
    min_box_px: float = 8.0
    warmup_s: float = 300.0
    link_every_s: float = 1.0
    mot: dict[str, ClearMot] = field(default_factory=dict)
    det_by_class: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    det_fp: int = 0
    det_total: int = 0
    link_err: dict[str, ErrorStats] = field(default_factory=lambda: defaultdict(ErrorStats))
    approach_err: dict[str, ErrorStats] = field(default_factory=lambda: defaultdict(ErrorStats))
    pos_err: list[float] = field(default_factory=list)
    speed_err: list[float] = field(default_factory=list)
    lane_ok: list[int] = field(default_factory=lambda: [0, 0])
    stopped_conf: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    confidence: list[float] = field(default_factory=list)
    truncated_ticks: int = 0
    lane_ticks: int = 0
    _last_link_t: float = -1e9

    def attach(self) -> None:
        for cid, p in self.system.pipelines.items():
            self.mot[cid] = ClearMot()
            p.observer = self.on_frame

    # ---- frames ----------------------------------------------------------------------

    def on_frame(self, cid: str, t: float, filmed: FilmedObjects, dets: list[Detection],
                 tracks: list[ImageTrack]) -> None:
        if t < self.warmup_s:
            return
        vis = filmed.visible * filmed.in_frame if len(filmed) else np.zeros(0)
        h = filmed.boxes[:, 3] - filmed.boxes[:, 1] if len(filmed) else np.zeros(0)
        keep = (vis >= self.min_visible) & (h >= self.min_box_px)
        gt_boxes = filmed.boxes[keep] if len(filmed) else np.zeros((0, 4))
        gt_ids = [filmed.ids[i] for i in np.nonzero(keep)[0]] if len(filmed) else []
        gt_cls = [filmed.vclass[i] for i in np.nonzero(keep)[0]] if len(filmed) else []
        ignore_boxes = filmed.boxes[~keep] if len(filmed) else np.zeros((0, 4))

        det_boxes = np.array([d.box for d in dets]).reshape(-1, 4)
        det_ok = np.array([d.score >= 0.3 for d in dets], dtype=bool).reshape(-1)
        det_ok &= _without_distractors(det_boxes, gt_boxes, ignore_boxes)
        matches, unmatched_pred, _ = match_boxes(det_boxes[det_ok], gt_boxes)
        matched_gt = {j for _, j in matches}
        for j, c in enumerate(gt_cls):
            self.det_by_class[str(c)][0] += 1
            if j in matched_gt:
                self.det_by_class[str(c)][1] += 1
        self.det_fp += len(unmatched_pred)
        self.det_total += int(det_ok.sum())

        tr = [x for x in tracks if not x.coasting]
        tr_boxes = np.array([x.box for x in tr]).reshape(-1, 4)
        scored = _without_distractors(tr_boxes, gt_boxes, ignore_boxes)
        tr = [x for x, k in zip(tr, scored, strict=True) if k]
        self.mot[cid].update(
            [x.track_id for x in tr],
            np.array([x.box for x in tr]).reshape(-1, 4),
            gt_ids,
            gt_boxes,
        )

    # ---- ticks ------------------------------------------------------------------------

    def on_tick(self, t: float, snap: WorldSnapshot) -> None:
        if t < self.warmup_s:
            return
        idx = snap.index()
        # ground-track accuracy (every tick)
        res = self.system.last
        tracks = res.tracks if res is not None else []
        for g in tracks:
            if g.truth_id is None or g.truth_id not in idx:
                continue
            i = idx[g.truth_id]
            self.pos_err.append(float(np.hypot(*(g.xy - snap.xy[i]))))
            if g.speed_known and not g.coasting:
                self.speed_err.append(float(g.speed - snap.speed[i]))
            true_lane = snap.lane_id[i]
            if g.lane_id is not None and not true_lane.startswith(":"):
                self.lane_ok[0] += int(g.lane_id == true_lane)
                self.lane_ok[1] += 1
            truly_stopped = snap.speed[i] < 0.1
            self.stopped_conf[f"truth_{int(truly_stopped)}_est_{int(g.stopped)}"] += 1
        if t - self._last_link_t < self.link_every_s:
            return
        self._last_link_t = t
        est = self.system.estimator
        for tls, smp in self.samplers.items():
            truth = smp.sample_extended()  # type: ignore[attr-defined]
            qs = est.queue_sample(tls)
            for q in QUANTITIES:
                tv: Mapping[str, float] = getattr(truth, q)
                ev = qs[q]
                for link, v in tv.items():
                    self.link_err[q].add(float(v), float(ev.get(link, np.nan)))
            conf = qs["confidence"]
            self.confidence.extend(conf.values())
        # approach totals: the sum over an approach edge's lanes (lane-free traffic view)
        for lane in est.lanes.values():
            self.lane_ticks += 1
            self.truncated_ticks += int(lane.truncated)

    # ---- summary ----------------------------------------------------------------------

    def summary(self) -> dict:
        # Track ids restart per camera and one vehicle is a separate trajectory
        # in every camera that sees it, so identities are namespaced by camera
        # before the whole-rig IDF1 is computed.
        mot_all = ClearMot()
        for cid, m in self.mot.items():
            mot_all.gt += m.gt
            mot_all.tp += m.tp
            mot_all.fp += m.fp
            mot_all.fn += m.fn
            mot_all.idsw += m.idsw
            for (g, pr), v in m.pair_counts.items():
                mot_all.pair_counts[(f"{cid}/{g}", f"{cid}/{pr}")] += v
            for g, v in m.gt_counts.items():
                mot_all.gt_counts[f"{cid}/{g}"] += v
            for pr, v in m.pred_counts.items():
                mot_all.pred_counts[f"{cid}/{pr}"] += v
        det_recall = {c: (v[1] / v[0] if v[0] else float("nan"), v[0])
                      for c, v in self.det_by_class.items()}
        conf = np.array(self.confidence) if self.confidence else np.array([np.nan])
        pe = np.array(self.pos_err) if self.pos_err else np.array([np.nan])
        se = np.array(self.speed_err) if self.speed_err else np.array([np.nan])
        sc = self.stopped_conf
        stopped_prec = sc["truth_1_est_1"] / max(1, sc["truth_1_est_1"] + sc["truth_0_est_1"])
        stopped_rec = sc["truth_1_est_1"] / max(1, sc["truth_1_est_1"] + sc["truth_1_est_0"])
        return {
            "detection": {
                "recall_by_class": det_recall,
                "precision": 1.0 - self.det_fp / self.det_total if self.det_total else None,
            },
            "tracking": mot_all.summary(),
            "ground": {
                "position_err_m_median": float(np.nanmedian(pe)),
                "position_err_m_p90": float(np.nanpercentile(pe, 90)),
                "speed_err_mps_mae": float(np.nanmean(np.abs(se))),
                "speed_err_mps_bias": float(np.nanmean(se)),
                "lane_accuracy": self.lane_ok[0] / self.lane_ok[1] if self.lane_ok[1] else None,
                "stopped_precision": stopped_prec,
                "stopped_recall": stopped_rec,
            },
            "links": {q: self.link_err[q].summary() for q in QUANTITIES},
            "confidence": {
                "mean": float(np.nanmean(conf)),
                "p10": float(np.nanpercentile(conf, 10)),
                "below_0.8": float(np.nanmean(conf < 0.8)),
                "below_0.5": float(np.nanmean(conf < 0.5)),
            },
            "truncated_lane_fraction": self.truncated_ticks / max(1, self.lane_ticks),
        }


def _without_distractors(boxes: np.ndarray, gt_boxes: np.ndarray,
                         ignore_boxes: np.ndarray) -> np.ndarray:
    """Which of `boxes` to score: all but those the optimal matching against
    every filmed vehicle (scored and too-hidden-to-score alike) pairs with a
    too-hidden one."""
    keep = np.ones(len(boxes), dtype=bool)
    if len(boxes) == 0 or len(ignore_boxes) == 0:
        return keep
    matches, _, _ = match_boxes(boxes, np.vstack([gt_boxes, ignore_boxes]))
    for i, j in matches:
        if j >= len(gt_boxes):
            keep[i] = False
    return keep


def class_names() -> list[str]:
    return [str(c) for c in VClass]

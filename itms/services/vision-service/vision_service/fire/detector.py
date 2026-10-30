"""Fire and smoke scoring of one frame: the v4 detector proposes boxes at a
very low confidence, the crop classifier decides which of them are real.

This is `image_scores2` / `alarm2` of the Step 2 notebook, one frame at a
time. Per frame the result is the highest classifier P(fire) over the
detector's *fire* boxes and the highest P(smoke) over its *smoke* boxes (0
when there are none); the frame alarms when either reaches its threshold.

The thresholds (0.80, 0.90) were chosen on validation only, before the test
sets were scored. What Step 2 showed with them, and what it did not, is in
`baselines/2026-10-03_m8_fire_v5_step2/README.md`.

The detector is the Ultralytics model that was tested (`.pt`, imgsz 640,
conf >= 0.05, NMS IoU 0.7). An ONNX export of it has not been checked against
those numbers, so it is not offered here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from vision_service.fire.classifier import CLASS_NAMES, CropClassifier, crop_box

log = logging.getLogger("vision.fire")

Box = tuple[float, float, float, float]

P_FIRE = 0.80       # alarm threshold on the classifier's P(fire), chosen on validation
P_SMOKE = 0.90      # ... and on P(smoke)
DET_CONF = 0.05     # the detector proposes every box at or above this
DET_IOU = 0.7
IMGSZ = 640


@dataclass(frozen=True)
class FireScore:
    """One frame's result. `box_*` is the best-scoring candidate of that
    class in frame pixels (x1, y1, x2, y2), or None when there was none."""

    p_fire: float = 0.0
    p_smoke: float = 0.0
    box_fire: tuple[float, float, float, float] | None = None
    box_smoke: tuple[float, float, float, float] | None = None
    frame_wh: tuple[int, int] = (0, 0)
    n_candidates: int = 0
    thresholds: tuple[float, float] = (P_FIRE, P_SMOKE)
    extras: dict = field(default_factory=dict)

    @property
    def fire_alarm(self) -> bool:
        return self.p_fire >= self.thresholds[0]

    @property
    def smoke_alarm(self) -> bool:
        return self.p_smoke >= self.thresholds[1]

    @property
    def alarm(self) -> bool:
        return self.fire_alarm or self.smoke_alarm


class FireScorer:
    def __init__(self, detector_path: str, classifier: CropClassifier | str, *,
                 p_fire: float = P_FIRE, p_smoke: float = P_SMOKE, device: str | None = None):
        from ultralytics import YOLO  # noqa: PLC0415 -- optional dependency

        self.det = YOLO(detector_path)
        names = self.det.names
        if [names[k] for k in sorted(names)] != ["fire", "smoke"]:
            raise ValueError(f"{detector_path}: expected classes ['fire', 'smoke'], got {names}")
        self.cls = CropClassifier(classifier) if isinstance(classifier, str) else classifier
        self.thresholds = (p_fire, p_smoke)
        self.device = device
        self.name = f"fire:{detector_path}+{self.cls.name}"

    def candidates(self, frame: np.ndarray) -> list[tuple[int, float, Box]]:
        r = self.det.predict(frame, imgsz=IMGSZ, conf=DET_CONF, iou=DET_IOU, verbose=False,  # type: ignore[index]
                             device=self.device)[0]
        bx = r.boxes
        out = [(int(c), float(cf), (float(b[0]), float(b[1]), float(b[2]), float(b[3])))
               for c, cf, b in zip(bx.cls.tolist(), bx.conf.tolist(), bx.xyxy.tolist(), strict=True)  # type: ignore[union-attr]
               if int(c) in (0, 1)]
        return out

    def score(self, frame: np.ndarray) -> FireScore:
        h, w = frame.shape[:2]
        cands = self.candidates(frame)
        if not cands:
            return FireScore(frame_wh=(w, h), thresholds=self.thresholds)
        probs = self.cls.probs(np.stack([crop_box(frame, b) for _, _, b in cands]))
        best = [0.0, 0.0]
        box: list[tuple[float, float, float, float] | None] = [None, None]
        for (c, _conf, b), p in zip(cands, probs, strict=True):
            if p[c] > best[c]:
                best[c], box[c] = float(p[c]), b
        return FireScore(best[0], best[1], box[0], box[1], (w, h), len(cands), self.thresholds,
                         {"classes": CLASS_NAMES})

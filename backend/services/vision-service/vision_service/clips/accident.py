"""The accident video model, as trained by `scripts/m8_accident_train.py`.

A per-frame EfficientNet-B0 (normal vs accident) exported to ONNX
(`itms_accident_224.onnx`: input `image`, float32 RGB in [0, 1], 224 x 224,
NCHW; the ImageNet normalisation is inside the model; output `logit`). It is
run on frames sampled at 2 per second, the rate it was trained and scored
at, and alarms when at least `k` of the last `n` frames reach `thr` -- the
alarm rule the training protocol picks on validation clips
(`chosen_<split>.json`), read here from a JSON file next to the model.

Without that file the model still runs, on defaults marked unvalidated in
every result, so a reviewer can tell a chosen operating point from a guess.

What its test protocol could not measure (`TARGETS_LOCKED.md`): about 80 % of
its clips are from the US; accuracy on Indian junction cameras is unknown.
"""

from __future__ import annotations

import json
import logging
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("vision.clips.accident")

SIZE = 224
SAMPLE_FPS = 2.0
DEFAULT_RULE = {"thr": 0.5, "k": 3, "n": 5}


@dataclass(frozen=True)
class AlarmRule:
    thr: float
    k: int
    n: int
    validated: bool

    @classmethod
    def for_model(cls, model_path: str | Path) -> AlarmRule:
        """The rule chosen on validation, from `<model stem>.json` or a
        `chosen_*.json` beside the model; the unvalidated default otherwise."""
        p = Path(model_path)
        candidates = [p.with_suffix(".json"), *sorted(p.parent.glob("chosen_*.json"))]
        for c in candidates:
            if c.exists():
                cfg = json.loads(c.read_text())
                if all(key in cfg for key in ("thr", "k", "n")):
                    return cls(float(cfg["thr"]), int(cfg["k"]), int(cfg["n"]), validated=True)
        log.warning("no alarm rule beside %s -- using thr=%.2f k/n=%d/%d, NOT validated",
                    p, DEFAULT_RULE["thr"], DEFAULT_RULE["k"], DEFAULT_RULE["n"])
        return cls(float(DEFAULT_RULE["thr"]), int(DEFAULT_RULE["k"]), int(DEFAULT_RULE["n"]),
                   validated=False)


class AccidentModel:
    name = "accident"

    def __init__(self, path: str | Path, rule: AlarmRule | None = None):
        import onnxruntime as ort  # noqa: PLC0415 -- optional dependency (vision-service[onnx])

        self.path = str(path)
        self.session = ort.InferenceSession(self.path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.rule = rule or AlarmRule.for_model(path)

    def prob(self, frame_bgr: np.ndarray) -> float:
        import cv2  # noqa: PLC0415

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        x = cv2.resize(rgb, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
        x = (x.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        logit = float(np.asarray(self.session.run(None, {self.input_name: x})[0]).reshape(-1)[0])
        return 1.0 / (1.0 + math.exp(-logit))


class AccidentAlarm:
    """The k-of-n persistence rule over the 2 fps probabilities. Collects
    alarming runs; a run ends once fewer than `k` of the last `n` frames
    alarm."""

    def __init__(self, rule: AlarmRule):
        self.rule = rule
        self._window: deque[tuple[float, float]] = deque(maxlen=rule.n)
        self.runs: list[dict] = []
        self._open: dict | None = None

    def observe(self, t: float, p: float) -> None:
        self._window.append((t, p))
        hot = [(tt, pp) for tt, pp in self._window if pp >= self.rule.thr]
        if len(hot) >= self.rule.k:
            if self._open is None:
                self._open = {"start_s": hot[0][0], "alarm_s": t, "end_s": t, "peak": 0.0}
                self.runs.append(self._open)
            self._open["end_s"] = t
            self._open["peak"] = max(self._open["peak"], max(pp for _, pp in hot))
        else:
            self._open = None

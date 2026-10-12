"""The Step 2 crop classifier (`baselines/2026-10-03_m8_fire_v5_step2/`):
EfficientNet-B0, 112 x 112 crops, three outputs -- fire, smoke, not.

Preprocessing is the training notebook's, step for step, because the
alarm thresholds were chosen on probabilities made this way:

1. the box grown by 25 % of its width and height on every side (floor of 4 px
   on the box size), clipped to the frame;
2. resized to 112 x 112 with `INTER_AREA`;
3. BGR -> RGB, scaled to [0, 1], ImageNet mean and std.

Two backends with one interface: an ONNX export (`onnxruntime`, no torch --
what the service should run) and the notebook's own `.pt` state dict
(torch + torchvision -- for checking the export against the original).
`scripts/m8_fire_export_cls.py` makes the ONNX file and checks it.
"""

from __future__ import annotations

import numpy as np

CROP = 112
MARGIN = 0.25
CLASS_NAMES = ("fire", "smoke", "not")
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def crop_box(frame: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    """One BGR crop for one detector box, exactly as in training."""
    import cv2  # noqa: PLC0415

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = max(x2 - x1, 4.0), max(y2 - y1, 4.0)
    a, b = int(max(0, x1 - MARGIN * bw)), int(max(0, y1 - MARGIN * bh))
    c, d = int(min(w, x2 + MARGIN * bw)), int(min(h, y2 + MARGIN * bh))
    if c - a < 2 or d - b < 2:
        a, b = max(0, int(x1) - 2), max(0, int(y1) - 2)
        c, d = min(w, int(x2) + 2), min(h, int(y2) + 2)
        if c - a < 2 or d - b < 2:
            return np.zeros((CROP, CROP, 3), np.uint8)
    return cv2.resize(frame[b:d, a:c], (CROP, CROP), interpolation=cv2.INTER_AREA)


def to_input(crops: np.ndarray) -> np.ndarray:
    """uint8 BGR `(N, 112, 112, 3)` -> normalised RGB float32 `(N, 3, 112, 112)`."""
    x = crops[..., ::-1].astype(np.float32) / 255.0
    return np.ascontiguousarray(((x - MEAN) / STD).transpose(0, 3, 1, 2), dtype=np.float32)


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


class CropClassifier:
    """`probs(crops)` -> `(N, 3)` softmax over (fire, smoke, not)."""

    def __init__(self, path: str, *, providers: list[str] | None = None):
        self.path = path
        self.name = f"cls:{path}"
        if path.endswith(".onnx"):
            import onnxruntime as ort  # noqa: PLC0415

            self._sess = ort.InferenceSession(path, providers=providers or ["CPUExecutionProvider"])
            self._in = self._sess.get_inputs()[0].name
            self._torch = None
        else:
            import torch  # noqa: PLC0415
            from torch import nn  # noqa: PLC0415
            from torchvision import models  # noqa: PLC0415

            m = models.efficientnet_b0(weights=None)
            m.classifier[1] = nn.Linear(m.classifier[1].in_features, len(CLASS_NAMES))
            m.load_state_dict(torch.load(path, map_location="cpu"))
            self._torch = m.eval()
            self._sess = None

    def logits(self, crops: np.ndarray) -> np.ndarray:
        x = to_input(crops)
        if self._sess is not None:
            return self._sess.run(None, {self._in: x})[0]
        import torch  # noqa: PLC0415

        with torch.no_grad():
            return self._torch(torch.from_numpy(x)).numpy()

    def probs(self, crops: np.ndarray) -> np.ndarray:
        if len(crops) == 0:
            return np.zeros((0, len(CLASS_NAMES)), np.float32)
        return softmax(self.logits(crops))

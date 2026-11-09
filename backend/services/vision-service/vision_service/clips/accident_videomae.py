"""The V4 accident model at inference: VideoMAE on motion-proposed crops.

Port of `scripts/m8_accident_video4.py` (`TARGETS_VIDEO_V4_LOCKED.md`). Every
second it scores the last 16 frames (sampled at 4 per second, a 4 s window) in
up to three views: the whole frame, and the `K_LOCAL` crops centred on the
hottest cells of a motion heat map. The window's probability is the maximum
over its views. The alarm rule (`thr`, `k`, `n`) is read from the JSON beside
the weights, exactly like the ONNX model's.

Unlike `AccidentModel` this one is stateful: it is fed frames in time order
and answers `None` until a new window is due. Call `reset()` between clips.

What its protocol could not measure: its clips are mostly from outside India
and accuracy on Indian junction cameras is unknown (`TARGETS_VIDEO_V4_LOCKED.md`).
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

import numpy as np

from vision_service.clips.accident import AlarmRule

log = logging.getLogger("vision.clips.accident_videomae")

SAMPLE_FPS = 4.0      # the rate the windows were trained at
NF = 16               # frames per window
STRIDE = 4            # a window is scored every 4 sampled frames = once a second
SIZE = 224
MAXSIDE = 960         # frames are shrunk to this before views are cut
GRID = 32             # motion heat map is GRID x GRID
CROP_FRAC = 0.4
K_LOCAL = 2
JPEG_QUALITY = 90     # the training cache stored JPEGs; match its pixels

_MEAN = np.array([0.485, 0.456, 0.406], np.float32).reshape(1, 1, 3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], np.float32).reshape(1, 1, 3, 1, 1)


def crop_side(w: int, h: int) -> int:
    return max(8, int(CROP_FRAC * min(w, h)))


def proposals(heat: np.ndarray, w: int, h: int, k: int = K_LOCAL) -> list[tuple[float, float]]:
    """Centres (0..1) of the `k` hottest, non-overlapping crop-sized areas."""
    import cv2  # noqa: PLC0415

    side = crop_side(w, h)
    sx, sy = side / w, side / h
    hm = cv2.blur(heat.astype(np.float32), (3, 3)).copy()
    xs = (np.arange(GRID) + 0.5) / GRID
    out: list[tuple[float, float]] = []
    for _ in range(k):
        j = np.unravel_index(np.argmax(hm), hm.shape)
        if hm[j] <= 0:
            break
        cy, cx = xs[j[0]], xs[j[1]]
        out.append((float(np.clip(cx, sx / 2, 1 - sx / 2)), float(np.clip(cy, sy / 2, 1 - sy / 2))))
        hm[(np.abs(xs[None, :] - cx) <= sx) & (np.abs(xs[:, None] - cy) <= sy)] = 0
    return out


def _pick_device(torch) -> str:  # noqa: ANN001
    """CUDA, then Apple's MPS, then CPU; `VISION_DEVICE` overrides."""
    import os  # noqa: PLC0415

    forced = os.environ.get("VISION_DEVICE")
    if forced:
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class VideoMaeAccident:
    name = "accident"
    sample_fps = SAMPLE_FPS

    def __init__(self, path: str | Path, rule: AlarmRule | None = None):
        import torch  # noqa: PLC0415 -- optional dependency
        from transformers import VideoMAEConfig, VideoMAEForVideoClassification  # noqa: PLC0415

        self.path = str(path)
        self.rule = rule or AlarmRule.for_model(path)
        self._torch = torch
        model = VideoMAEForVideoClassification(VideoMAEConfig(num_labels=1))  # type: ignore[call-arg]
        state = torch.load(self.path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)   # strict: a mismatch must fail loudly, not run on noise
        self.device = _pick_device(torch)
        self.model = model.eval().to(self.device)
        log.info("accident model on %s", self.device)
        self.reset()

    def reset(self) -> None:
        self._frames: deque[bytes] = deque(maxlen=NF)     # JPEG-encoded RGB frames
        self._maps: deque[np.ndarray] = deque(maxlen=NF)  # motion maps, one per frame
        self._prev: np.ndarray | None = None
        self._n = 0
        self._hw = (0, 0)

    # ------------------------------------------------------------ frames in
    def prob(self, frame_bgr: np.ndarray) -> float | None:
        """Feed the next sampled frame. Returns the window's probability once a
        second, and None for the frames in between (or before 16 have arrived)."""
        import cv2  # noqa: PLC0415

        f = frame_bgr
        h, w = f.shape[:2]
        scale = min(1.0, MAXSIDE / max(h, w))
        if scale < 1:
            f = cv2.resize(f, (max(2, int(w * scale)), max(2, int(h * scale))),
                           interpolation=cv2.INTER_AREA)
        self._hw = f.shape[:2]
        gray = cv2.GaussianBlur(
            cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (64, 64),
                       interpolation=cv2.INTER_AREA), (3, 3), 0).astype(np.float32)
        self._maps.append(
            np.zeros((GRID, GRID), np.float32) if self._prev is None
            else cv2.resize(np.abs(gray - self._prev), (GRID, GRID), interpolation=cv2.INTER_AREA))
        self._prev = gray
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise ValueError("could not encode a frame")
        self._frames.append(buf.tobytes())
        self._n += 1
        if self._n < NF or (self._n - NF) % STRIDE:
            return None
        return self._score_window()

    # ------------------------------------------------------------- scoring
    def _views(self) -> np.ndarray:
        import cv2  # noqa: PLC0415

        rgb = [cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1]  # type: ignore[index]
               for b in self._frames]
        h, w = self._hw
        heat = np.sum(np.stack(self._maps), 0)
        views: list[np.ndarray] = [
            np.stack([cv2.resize(f, (SIZE, SIZE), interpolation=cv2.INTER_AREA) for f in rgb])]
        side = crop_side(w, h)
        for cx, cy in proposals(heat, w, h):
            x0 = int(np.clip(round(cx * w - side / 2), 0, w - side))
            y0 = int(np.clip(round(cy * h - side / 2), 0, h - side))
            views.append(np.stack([
                cv2.resize(f[y0:y0 + side, x0:x0 + side], (SIZE, SIZE), interpolation=cv2.INTER_AREA)  # noqa: E501
                for f in rgb]))
        return np.stack(views)                                   # V, T, H, W, 3 uint8

    def _score_window(self) -> float:
        torch = self._torch
        x = self._views().transpose(0, 1, 4, 2, 3).astype(np.float32) / 255.0   # V, T, C, H, W
        x = (x - _MEAN) / _STD
        with torch.no_grad():
            batch = torch.from_numpy(np.ascontiguousarray(x)).to(self.device)
            logit = self.model(pixel_values=batch).logits.reshape(-1)
            return float(torch.sigmoid(logit).max().cpu())

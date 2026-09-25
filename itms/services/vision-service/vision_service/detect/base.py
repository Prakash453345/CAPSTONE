"""The detector interface every source of boxes implements."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from vision_service.records import Detection


class Detector(Protocol):
    name: str

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """One BGR frame -> detections in the ITMS taxonomy, *including*
        low-confidence boxes (ByteTrack's second stage needs them)."""
        ...

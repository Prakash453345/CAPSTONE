"""Conformal calibration for anomaly thresholds."""

import numpy as np
import json
from pathlib import Path


class ConformalCalibrator:
    """Split/adaptive conformal calibration for anomaly detection.
    
    Offline: compute threshold tau as (1-alpha) quantile of normal scores.
    Online: operator rejections feed back as confirmed-normal points,
    tau is recomputed with a sliding window.
    """
    
    def __init__(self, alpha: float = 0.05, window_size: int = 500):
        """Initialize the calibrator.
        
        Args:
            alpha: Desired false positive rate (0 < alpha < 1).
            window_size: Size of the sliding window for adaptive calibration.
        """
        self.alpha = alpha
        self.window_size = window_size
        self.scores = []
        self._threshold = float('inf')

    def fit(self, normal_scores: np.ndarray | list[float]) -> float:
        """Fit the initial threshold using normal scores.
        
        Args:
            normal_scores: Array of anomaly scores from normal data.
            
        Returns:
            float: The computed threshold tau.
        """
        scores_list = list(normal_scores)
        # Keep only the most recent window_size scores
        self.scores = scores_list[-self.window_size:]
        self._recompute_threshold()
        return self._threshold

    def update(self, score: float) -> float:
        """Update threshold with a new confirmed-normal score (operator rejection).
        
        Args:
            score: The anomaly score that was actually normal.
            
        Returns:
            float: The new computed threshold tau.
        """
        self.scores.append(score)
        if len(self.scores) > self.window_size:
            self.scores.pop(0)
            
        self._recompute_threshold()
        return self._threshold

    def _recompute_threshold(self) -> None:
        """Internal method to compute the quantile threshold."""
        if not self.scores:
            self._threshold = float('inf')
            return
            
        n = len(self.scores)
        # Calculate index for conformal prediction quantile
        # The true quantile incorporates finite sample correction
        q = (1.0 - self.alpha) * (1.0 + 1.0 / n)
        
        if q >= 1.0:
            self._threshold = max(self.scores)
        else:
            self._threshold = float(np.quantile(self.scores, q, method='higher'))

    @property
    def threshold(self) -> float:
        """Current anomaly threshold."""
        return self._threshold

    def save(self, path: str | Path) -> None:
        """Save calibrator state to file."""
        data = {
            "alpha": self.alpha,
            "window_size": self.window_size,
            "scores": self.scores,
            "threshold": self._threshold
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> 'ConformalCalibrator':
        """Load calibrator state from file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        calibrator = cls(alpha=data["alpha"], window_size=data["window_size"])
        calibrator.scores = data["scores"]
        calibrator._threshold = data["threshold"]
        return calibrator

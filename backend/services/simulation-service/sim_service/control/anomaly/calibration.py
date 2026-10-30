"""Conformal alert threshold with an online recalibration loop -- plan
sections 4.4 and 10.

The detector emits an anomaly score per link per tick. Rather than a
hand-picked cutoff, the alert threshold tau is the (1 - alpha) empirical
quantile of that score on held-out PURE-NORMAL traffic, with the standard
split-conformal finite-sample correction. Then, for a fresh normal score s,
`P(s > tau) <= alpha` -- the per-test false-alarm rate is bounded by a chosen
budget, treated like a validated safety constant.

Two things make it adaptive rather than a one-shot number:

  * sliding window + recency weights -- traffic is not exchangeable across
    demand levels or time of day, so tau is a weighted quantile over a bounded
    window of recent normal scores, recent ones weighing more (plan 10,
    "adaptive conformal anomaly detection").

  * operator rejections feed back -- every candidate an operator rejects was,
    by their judgement, normal; its scores are added to the calibration
    window (plan 4.4, the reject "becomes a training label"), which raises tau
    exactly where the detector is over-firing.

numpy only -- no torch -- so the gate script and the fusion layer can use it
without pulling the model in.
"""

from __future__ import annotations

import json
import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class ConformalConfig:
    alpha: float = 0.05         # target per-test false-alarm rate (the budget)
    window: int = 20_000        # max calibration points kept (sliding)
    decay: float = 1.0          # per-point recency weight base; 1.0 = unweighted
    min_points: int = 500       # below this, tau = +inf (not enough evidence to alert)

    def __post_init__(self) -> None:
        if not 0.0 < self.alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {self.alpha}")
        if self.window < 1:
            raise ValueError("window must be >= 1")
        if not 0.0 < self.decay <= 1.0:
            raise ValueError("decay must be in (0, 1]")


class ConformalCalibrator:
    """Streaming split-conformal threshold on a scalar anomaly score.

    Seed it with `fit(normal_scores)` (a bulk held-out normal set), then keep
    it current with `observe_normal` per confirmed-normal score and
    `observe_rejected` per operator-rejected candidate. `tau` is the live
    threshold; `is_alert(score)` is `score > tau`.
    """

    def __init__(self, cfg: ConformalConfig | None = None):
        self.cfg = cfg or ConformalConfig()
        self._scores: deque[float] = deque(maxlen=self.cfg.window)
        self._n_rejected_absorbed = 0
        self._tau = math.inf
        self._dirty = True

    # ---- ingest -------------------------------------------------------

    def fit(self, normal_scores: Iterable[float]) -> None:
        """Replace the calibration window with `normal_scores` (kept to the
        most recent `window` if longer). Use once at startup with the
        held-out pure-normal score set."""
        self._scores.clear()
        for s in normal_scores:
            self._scores.append(float(s))
        self._dirty = True

    def observe_normal(self, score: float) -> None:
        self._scores.append(float(score))
        self._dirty = True

    def observe_rejected(self, scores: Sequence[float]) -> None:
        """An operator rejected a candidate: every node score it carried is a
        confirmed-normal point. Folds the feedback loop back into tau."""
        for s in scores:
            self._scores.append(float(s))
        self._n_rejected_absorbed += len(scores)
        self._dirty = True

    # ---- threshold ------------------------------------------------

    def _recompute(self) -> None:
        n = len(self._scores)
        if n < self.cfg.min_points:
            self._tau = math.inf
            self._dirty = False
            return
        v = np.fromiter(self._scores, dtype=np.float64, count=n)
        if self.cfg.decay >= 1.0:
            w = np.ones(n)
        else:
            # index 0 is the oldest point in the deque, n-1 the newest
            age = np.arange(n - 1, -1, -1, dtype=np.float64)
            w = np.power(self.cfg.decay, age)
        self._tau = _weighted_conformal_quantile(v, w, self.cfg.alpha)
        self._dirty = False

    @property
    def tau(self) -> float:
        if self._dirty:
            self._recompute()
        return self._tau

    def is_alert(self, score: float) -> bool:
        return score > self.tau

    # ---- introspection -----------------------------------------

    @property
    def n_points(self) -> int:
        return len(self._scores)

    def empirical_fpr(self, scores: Iterable[float] | None = None) -> float:
        """Fraction of `scores` (default: the current calibration window)
        that would alert at the current tau -- should sit near alpha on
        genuinely normal data."""
        v = (
            np.fromiter(self._scores, dtype=np.float64, count=len(self._scores))
            if scores is None
            else np.asarray(list(scores), dtype=np.float64)
        )
        if v.size == 0:
            return 0.0
        t = self.tau
        if not math.isfinite(t):
            return 0.0
        return float(np.mean(v > t))

    def report(self) -> dict:
        return {
            "alpha": self.cfg.alpha,
            "tau": self.tau if math.isfinite(self.tau) else None,
            "n_points": self.n_points,
            "window": self.cfg.window,
            "decay": self.cfg.decay,
            "rejected_points_absorbed": self._n_rejected_absorbed,
            "empirical_fpr_on_window": round(self.empirical_fpr(), 4),
        }

    # ---- persistence -----------------------------------------

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(
                {
                    "cfg": {
                        "alpha": self.cfg.alpha,
                        "window": self.cfg.window,
                        "decay": self.cfg.decay,
                        "min_points": self.cfg.min_points,
                    },
                    "scores": list(self._scores),
                    "n_rejected_absorbed": self._n_rejected_absorbed,
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, path: str | Path) -> ConformalCalibrator:
        raw = json.loads(Path(path).read_text())
        obj = cls(ConformalConfig(**raw["cfg"]))
        obj.fit(raw["scores"])
        obj._n_rejected_absorbed = raw.get("n_rejected_absorbed", 0)
        return obj


def _weighted_conformal_quantile(
    values: np.ndarray, weights: np.ndarray, alpha: float
) -> float:
    """The (1 - alpha) weighted quantile with the split-conformal
    finite-sample bump: with total weight W and a hypothetical unit-weight
    new point, the threshold is the smallest observed value whose cumulative
    weight fraction reaches `(1 - alpha) * (W + 1) / W` (clamped to 1). For
    equal weights and integer n this is exactly the classic
    `ceil((n + 1)(1 - alpha))`-th order statistic."""
    order = np.argsort(values, kind="stable")
    v = values[order]
    w = weights[order]
    total = float(w.sum())
    if total <= 0.0:
        return math.inf
    target = min(1.0, (1.0 - alpha) * (total + 1.0) / total)
    cum = np.cumsum(w) / total
    idx = int(np.searchsorted(cum, target, side="left"))
    if idx >= len(v):
        return math.inf  # not enough mass below the corrected target -> no finite tau
    return float(v[idx])

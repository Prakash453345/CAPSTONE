"""Small, dependency-free statistics helpers for the M3 bench report
[build guide §8.2]: "report mean ± 95% CI" over N seeds per condition.

No `scipy` in this service (see `pyproject.toml`), and a correct 95% CI
over a *small* sample (the gate's own N=10) needs the Student's
t-distribution's critical value, not the normal distribution's 1.96 --
using 1.96 at n=10 understates the interval by a meaningful margin (2.262
vs. 1.96, a ~15% wider interval is the honest one). Rather than pull in a
whole scientific-computing dependency for one number, `_T_CRITICAL_95`
below is the standard two-tailed 95% t-table for df 1-30, the only range
this project's seed counts (10 now, ≥30 at M9) will ever actually hit;
df > 30 falls back to the normal distribution's 1.96, which is already
within about 1% of the true t-value there.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

# Two-tailed 95% critical values, Student's t-distribution, df 1-30.
_T_CRITICAL_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}
_NORMAL_APPROX_95 = 1.96  # df > 30: within ~1% of the true t-value there.


def t_critical_95(df: int) -> float:
    if df < 1:
        raise ValueError(f"degrees of freedom must be >= 1, got {df}")
    return _T_CRITICAL_95.get(df, _NORMAL_APPROX_95)


@dataclass(frozen=True)
class ConfidenceInterval:
    mean: float
    half_width_95: float
    n: int

    def __str__(self) -> str:
        if self.n < 2:
            return f"{self.mean:.1f} (n={self.n}, no CI)"
        return f"{self.mean:.1f} ± {self.half_width_95:.1f} (n={self.n})"


def confidence_interval_95(values: Sequence[float]) -> ConfidenceInterval:
    """Mean and 95% CI half-width over `values` (one number per seed, the
    same metric from each of that condition's independent runs).

    `n < 2` returns a zero-width interval rather than raising -- a
    single-seed run is a legitimate (if statistically unsupported) thing
    to compute during development; `ConfidenceInterval.__str__` makes that
    caveat visible rather than silently printing a false "± 0.0"."""
    n = len(values)
    mean = statistics.fmean(values) if values else 0.0
    if n < 2:
        return ConfidenceInterval(mean=mean, half_width_95=0.0, n=n)
    sample_stdev = statistics.stdev(values)  # n-1 denominator -- sample, not population
    standard_error = sample_stdev / math.sqrt(n)
    half_width = t_critical_95(n - 1) * standard_error
    return ConfidenceInterval(mean=mean, half_width_95=half_width, n=n)

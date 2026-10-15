"""Pure helpers for the V4 false-alarm proxy and parity check (see TARGETS_VIDEO_V4_FALSE_ALARM_LOCKED.md)."""
from __future__ import annotations
import math
import numpy as np


def hot_now(p, i, thr, k, n, delta=0.0):
    """True if at window i at least k of the last n scores are >= thr (and, when delta > 0, also at least delta above the
    clip's recent baseline: the median of the 8 scores before that n-window, if there are >= 3 of them)."""
    p = np.asarray(p, float); lo = max(0, i - n + 1); win = p[lo:i + 1]
    if delta > 0:
        hist = p[max(0, lo - 8):lo]; base = float(np.median(hist)) if len(hist) >= 3 else 0.0
        hot = (win >= thr) & (win - base >= delta)
    else:
        hot = win >= thr
    return int(hot.sum()) >= k


def alarm_runs(times, p, thr, k, n, delta=0.0):
    """Alarm times: the window end at which the rule first holds and no run was open (same as AccidentAlarm)."""
    runs, open_ = [], False
    for i, t in enumerate(times):
        if hot_now(p, i, thr, k, n, delta):
            if not open_: runs.append(float(t)); open_ = True
        else: open_ = False
    return runs


def pre_impact(times, p, ta, rule, gap=1.0):
    """(exposure seconds, runs before impact - gap, any alarm before impact) for one clip."""
    times = np.asarray(times, float); p = np.asarray(p, float)
    runs = alarm_runs(times, p, rule["thr"], rule["k"], rule["n"], rule.get("delta", 0.0))
    exposure = float(np.sum(times <= ta - gap))                # one window = one second of footage
    return exposure, sum(r <= ta - gap for r in runs), any(r < ta for r in runs)


def poisson_ci(k, conf=0.95):
    from scipy.stats import chi2
    a = 1 - conf
    lo = 0.0 if k == 0 else chi2.ppf(a / 2, 2 * k) / 2
    return lo, chi2.ppf(1 - a / 2, 2 * k + 2) / 2


def false_alarm_summary(per_clip):
    """per_clip: list of (exposure_s, runs, any_early). Runs per camera-hour with an exact Poisson CI."""
    exp_h = sum(e for e, _, _ in per_clip) / 3600.0; runs = sum(r for _, r, _ in per_clip)
    lo, hi = poisson_ci(runs)
    exps = sorted(e for e, _, _ in per_clip)
    return dict(clips=len(per_clip), exposure_hours=exp_h, runs=runs,
                runs_per_hour=runs / exp_h if exp_h else float("nan"),
                runs_per_hour_ci95=(lo / exp_h if exp_h else float("nan"), hi / exp_h if exp_h else float("nan")),
                clips_with_early_alarm=float(np.mean([a for _, _, a in per_clip])),
                clips_with_false_run=float(np.mean([r > 0 for _, r, _ in per_clip])),
                median_exposure_s=float(exps[len(exps) // 2]) if exps else 0.0)


def parity(a, b, rule, tol=0.05):
    """a, b: arrays of window scores for one clip from two paths. -> (share within tol, alarm decisions equal)."""
    a = np.asarray(a, float); b = np.asarray(b, float); m = min(len(a), len(b))
    same_len = len(a) == len(b)
    share = float(np.mean(np.abs(a[:m] - b[:m]) <= tol)) if m else 0.0
    t = np.arange(m)
    da = bool(alarm_runs(t, a[:m], rule["thr"], rule["k"], rule["n"])); db = bool(alarm_runs(t, b[:m], rule["thr"], rule["k"], rule["n"]))
    return share, da == db, same_len

"""Indian pole-CCTV suite: accident-clip timing + accident-free false alarms (see TARGETS_INDIAN_SUITE_LOCKED.md). Nothing is trained or tuned."""
from __future__ import annotations
import numpy as np, pandas as pd
import m8_accident_video6 as V6
import m8_accident_false_alarm as F
import m8_accident_normal_check as N

DETECT_WITHIN_S = 10.0

# crash second per accident clip number: (main, alternative). main = Accidents.xlsx (clip 6 and 21-26, 29: timeframe.xlsx); alt = timeframe.xlsx. None = no time.
TIMES = {1: (16, 16), 2: (6, 6), 3: (11, 11), 4: (9, 8), 5: (3, 3), 6: (11, 11), 7: (7, 7), 8: (4, 3), 9: (45, 45), 10: (6, 5),
         11: (8, 8), 12: (10, 9), 13: (3, 2), 14: (9, 8), 15: (9, 9), 16: (9, 9), 17: (7, 3), 18: (17, 17), 19: (5, 4), 20: (8, 6),
         21: (3, 3), 22: (4, 4), 23: (12, 12), 24: (5, 5), 25: (4, 4), 26: (4, 4), 29: (4, 4)}
ACCIDENT_FREE_NUMBERED = (27, 28)      # named accident_27 / accident_28 but the user confirmed they contain no accident: scored as hard negatives


def clip_no(path):
    import re, os
    m = re.search(r"accident_(\d+)_", os.path.basename(path)); return int(m.group(1)) if m else None


def window_scores(model, rule, clips, cache, log=print):
    """-> {path: (window_end_times, score)}, score = max over the model's own views."""
    df = pd.DataFrame({"path": list(clips)}); d = V6.dump(model, df, cache, log=log); out = {}
    for p in clips:
        t, S = d[p]
        out[p] = (np.asarray(t, float), np.nanmax(S[:, :1 + rule["K"]], axis=1).astype(float) if len(t) else np.zeros(0))
    return out


def hot_times(t, s, rule):
    return [float(t[i]) for i in range(len(t)) if F.hot_now(s, i, rule["thr"], rule["k"], rule["n"], rule.get("delta", 0.0))]


def wilson(k, n, z=1.96):
    if n == 0: return (float("nan"), float("nan"))
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def accident_report(scores, rule, which=0):
    """which: 0 = main times, 1 = alternative times. -> per-clip rows and the summary."""
    rows = []
    for p, (t, s) in scores.items():
        n = clip_no(p); ta = TIMES.get(n, (None, None))[which]; hot = hot_times(t, s, rule)
        runs = F.alarm_runs(t, s, rule["thr"], rule["k"], rule["n"], rule.get("delta", 0.0))
        r = {"clip": p.split("/")[-1], "no": n, "ta": ta, "windows": int(len(t)), "max_score": float(np.max(s)) if len(s) else None,
             "any_alarm": bool(hot), "first_alarm": hot[0] if hot else None, "runs": [round(x, 1) for x in runs]}
        if ta is not None:
            post = [a for a in hot if ta <= a <= ta + DETECT_WITHIN_S]
            r.update(early=any(a < ta for a in hot), detected=bool(post), delay=(post[0] - ta) if post else None)
        rows.append(r)
    df = pd.DataFrame(rows).sort_values("no"); timed = df[df["ta"].notna()]; n = len(timed)
    k_det, k_early = int(timed["detected"].sum()), int(timed["early"].sum()); k_strict = int((timed["detected"] & ~timed["early"]).sum())
    summ = {"timed_clips": n, "detect": k_det / n, "detect_ci95": wilson(k_det, n), "early": k_early / n, "early_ci95": wilson(k_early, n),
            "strict": k_strict / n, "strict_ci95": wilson(k_strict, n), "median_delay_s": float(timed["delay"].dropna().median()) if timed["delay"].notna().any() else None,
            "all_clips": len(df), "any_alarm": float(df["any_alarm"].mean()), "any_alarm_ci95": wilson(int(df["any_alarm"].sum()), len(df))}
    return df, summ

"""Stage A: vehicle tracks -> motion triggers -> clip-level scoring (see TARGETS_STAGE_A_LOCKED.md)."""
from __future__ import annotations
import itertools, json, math, os, pathlib, random, re
import numpy as np, pandas as pd

VEH = [1, 2, 3, 5, 7]            # COCO: bicycle, car, motorcycle, bus, truck
DETECT_WITHIN_S = 10.0
MERGE_S = 3.0
MIN_SIZE_PX = 12.0
GRID = {"v_hi": [0.5, 1.0, 1.5, 2.5], "v_lo": [0.1, 0.2, 0.4], "iou": [0.05, 0.1, 0.2]}


# ------------------------------------------------------------ tracking (needs ultralytics + GPU)
def track_clip(model, path, imgsz=960, fps_target=10.0):
    import cv2
    cap = cv2.VideoCapture(str(path)); src = cap.get(cv2.CAP_PROP_FPS) or 15.0
    W, H = int(cap.get(3)), int(cap.get(4)); cap.release()
    stride = max(1, int(round(src / fps_target))); rows = []
    for k, r in enumerate(model.track(source=str(path), stream=True, tracker="bytetrack.yaml", imgsz=imgsz,
                                      vid_stride=stride, classes=VEH, conf=0.25, verbose=False)):
        b = r.boxes
        if b is None or b.id is None:
            continue
        t = k * stride / src
        for (x1, y1, x2, y2), i, c in zip(b.xyxy.cpu().numpy(), b.id.cpu().numpy(), b.cls.cpu().numpy()):
            rows.append((t, int(i), int(c), x1, y1, x2, y2))
    return np.array(rows, dtype=np.float32).reshape(-1, 7), W, H


# ------------------------------------------------------------ triggers (pure numpy)
def _tracks(rows):
    out = {}
    for tid in np.unique(rows[:, 1]):
        r = rows[rows[:, 1] == tid]; r = r[np.argsort(r[:, 0])]
        t = r[:, 0]; w = r[:, 5] - r[:, 3]; h = r[:, 6] - r[:, 4]
        s = np.sqrt(np.maximum(w * h, 1e-6))
        k = 5; sm = np.array([np.median(s[max(0, i - k + 1):i + 1]) for i in range(len(s))])
        out[int(tid)] = dict(t=t, cx=(r[:, 3] + r[:, 5]) / 2, cy=(r[:, 4] + r[:, 6]) / 2, s=sm,
                             box=r[:, 3:7], ok=len(t) >= 6)
    return out


def _speed(tr, tau=0.5):
    t, cx, cy, s = tr["t"], tr["cx"], tr["cy"], tr["s"]
    v = np.full(len(t), np.nan)
    for i in range(len(t)):
        j = np.searchsorted(t, t[i] - tau, side="right") - 1
        if j >= 0 and t[i] - t[j] >= 0.3 and s[i] >= MIN_SIZE_PX:
            v[i] = math.hypot(cx[i] - cx[j], cy[i] - cy[j]) / (t[i] - t[j]) / s[i]
    k = 3                                          # median smoothing of the speed series
    return np.array([np.nanmedian(v[max(0, i - k + 1):i + 1]) if np.isfinite(v[max(0, i - k + 1):i + 1]).any()
                     else np.nan for i in range(len(v))])


def _win(t, v, a, b):
    m = (t >= a) & (t <= b) & np.isfinite(v)
    return v[m]


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def triggers(rows, W, H, v_hi, v_lo, iou, kinds=("T1", "T2")):
    """-> list of (t, x_norm, y_norm, kind), merged within MERGE_S."""
    if len(rows) == 0:
        return []
    trs = {k: v for k, v in _tracks(rows).items() if v["ok"]}
    sp = {k: _speed(v) for k, v in trs.items()}
    ev = []
    if "T1" in kinds:
        for k, tr in trs.items():
            t, v = tr["t"], sp[k]
            for i in range(len(t)):
                pre = _win(t, v, t[i] - 1.2, t[i] - 0.2); post = _win(t, v, t[i], t[i] + 0.8)
                if len(pre) and len(post) >= 2 and t[-1] >= t[i] + 0.6 and pre.max() >= v_hi and post.mean() <= v_lo:
                    ev.append((float(t[i]), float(tr["cx"][i] / W), float(tr["cy"][i] / H), "T1")); break
    if "T2" in kinds:
        frames = {}
        for k, tr in trs.items():
            for i, ti in enumerate(tr["t"]):
                frames.setdefault(round(float(ti), 3), []).append((k, i))
        seen = set()
        for ti in sorted(frames):
            items = frames[ti]
            for (ka, ia), (kb, ib) in itertools.combinations(items, 2):
                if (ka, kb) in seen:
                    continue
                if _iou(trs[ka]["box"][ia], trs[kb]["box"][ib]) < iou:
                    continue
                seen.add((ka, kb))
                pre = np.concatenate([_win(trs[k]["t"], sp[k], ti - 1.5, ti) for k in (ka, kb)])
                if not len(pre) or pre.max() < v_hi:
                    continue
                posts = [_win(trs[k]["t"], sp[k], ti + 0.5, ti + 2.0) for k in (ka, kb)]
                posts = [p for p in posts if len(p) >= 2]
                if posts and all(p.mean() <= v_lo for p in posts):
                    ev.append((float(ti), float((trs[ka]["cx"][ia] + trs[kb]["cx"][ib]) / 2 / W),
                               float((trs[ka]["cy"][ia] + trs[kb]["cy"][ib]) / 2 / H), "T2"))
    ev.sort(); out = []
    for e in ev:
        if not out or e[0] - out[-1][0] >= MERGE_S:
            out.append(e)
    return out


# ------------------------------------------------------------ scoring
def coverage(rows, W, H, r, tol=1.0):
    """A tracked vehicle centre inside the annotated crash box (grown 2x) within `tol` s of impact?"""
    if len(rows) == 0:
        return False
    ta = float(r["accident_time"]); cx, cy = (r.x1 + r.x2) / 2, (r.y1 + r.y2) / 2
    hw, hh = (r.x2 - r.x1), (r.y2 - r.y1)
    m = (np.abs(rows[:, 0] - ta) <= tol)
    x = (rows[m, 3] + rows[m, 5]) / 2 / W; y = (rows[m, 4] + rows[m, 6]) / 2 / H
    return bool(((np.abs(x - cx) <= hw) & (np.abs(y - cy) <= hh)).any())


def score_clip(ev, r):
    ta = float(r["accident_time"]); cx, cy = (r.x1 + r.x2) / 2, (r.y1 + r.y2) / 2
    hw, hh = (r.x2 - r.x1), (r.y2 - r.y1)
    post = [e for e in ev if ta <= e[0] <= ta + DETECT_WITHIN_S]
    loc = [e for e in post if abs(e[1] - cx) <= hw and abs(e[2] - cy) <= hh]
    return dict(early=any(e[0] < ta for e in ev), early_tol=any(e[0] < ta - 1.0 for e in ev),
                detected=bool(post), located=bool(loc),
                delay=(post[0][0] - ta) if post else None, n_early=sum(1 for e in ev if e[0] < ta),
                pre_s=max(0.0, ta), kinds=sorted({e[3] for e in post}))


def run_split(df, tracks, cfg, kinds=("T1", "T2")):
    rows = []
    for _, r in df.iterrows():
        z = tracks[r["path"]]
        ev = triggers(z["rows"], z["W"], z["H"], cfg["v_hi"], cfg["v_lo"], cfg["iou"], kinds)
        d = score_clip(ev, r); d["covered"] = coverage(z["rows"], z["W"], z["H"], r); d["path"] = r["path"]
        rows.append(d)
    d = pd.DataFrame(rows)
    delays = d["delay"].dropna()
    return {"n": len(d), "SA1_trigger_within_10s": float(d.detected.mean()), "SA2_trigger_before_impact": float(d.early.mean()),
            "located_recall": float(d.located.mean()), "tracker_coverage": float(d.covered.mean()),
            "early_tol1s": float(d.early_tol.mean()), "median_delay_s": float(delays.median()) if len(delays) else None,
            "early_triggers_per_preimpact_hour": float(d.n_early.sum() / max(1e-9, d.pre_s.sum() / 3600.0))}, d


def choose(df, tracks):
    best = None
    for v_hi, v_lo, iou in itertools.product(*GRID.values()):
        cfg = dict(v_hi=v_hi, v_lo=v_lo, iou=iou); m, _ = run_split(df, tracks, cfg)
        feas = m["SA1_trigger_within_10s"] >= 0.80
        key = (feas, -m["SA2_trigger_before_impact"] if feas else m["SA1_trigger_within_10s"] - m["SA2_trigger_before_impact"])
        if best is None or key > best[0]:
            best = (key, cfg, m, feas)
    return {**best[1], "val": best[2], "feasible_on_val": best[3]}


def group_id(p):
    return pathlib.Path(p).stem[:11]


def split_train_val(df, frac=0.2, seed=0):
    g = sorted({group_id(p) for p in df["path"]}); random.Random(seed).shuffle(g)
    val = set(g[:max(1, int(len(g) * frac))]); m = df["path"].map(lambda p: group_id(p) in val)
    return df[~m], df[m]


def breakdown(d, df, cols=("day_time", "weather", "scene_layout", "quality", "type")):
    m = d.merge(df, on="path"); out = {}
    for c in cols:
        out[c] = {str(v): {"n": int(len(g)), "trigger": round(float(g.detected.mean()), 3), "early": round(float(g.early.mean()), 3),
                           "covered": round(float(g.covered.mean()), 3)} for v, g in m.groupby(c)}
    return out

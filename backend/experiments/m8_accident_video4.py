"""V4: motion-proposed local crops + VideoMAE (see TARGETS_VIDEO_V4_LOCKED.md). Reuses V3 training/protocol code."""
from __future__ import annotations
import os, pathlib, random
from multiprocessing import Pool
import cv2, numpy as np, pandas as pd, torch
import m8_accident_video as V
import m8_accident_train_v2 as A

FPS, NF, SIZE = V.FPS, V.NF, V.SIZE
MAXSIDE, GRID, CROP_FRAC, K_LOCAL = 960, 32, 0.4, 2


# ------------------------------------------------------------ cache: JPEG frames + motion maps
def _extract(args):
    src, dst = args
    if os.path.exists(dst + ".npz"): return dst
    cap = cv2.VideoCapture(src); sfps = cap.get(cv2.CAP_PROP_FPS) or 15.0; step = max(1, int(round(sfps / FPS)))
    bufs, ts, mm, prev, i, hw = [], [], [], None, 0, (0, 0)
    while cap.grab():
        if i % step == 0:
            ok, f = cap.retrieve()
            if ok:
                h, w = f.shape[:2]; s = min(1.0, MAXSIDE / max(h, w))
                if s < 1: f = cv2.resize(f, (max(2, int(w * s)), max(2, int(h * s))), interpolation=cv2.INTER_AREA)
                hw = f.shape[:2]
                g = cv2.GaussianBlur(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (64, 64), interpolation=cv2.INTER_AREA), (3, 3), 0).astype(np.float32)
                mm.append(np.zeros((GRID, GRID), np.float32) if prev is None else cv2.resize(np.abs(g - prev), (GRID, GRID), interpolation=cv2.INTER_AREA)); prev = g
                bufs.append(cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].ravel()); ts.append(i / sfps)
        i += 1
    cap.release()
    lens = np.array([len(b) for b in bufs], np.int64)
    np.savez(dst + ".npz", blob=np.concatenate(bufs) if bufs else np.zeros(0, np.uint8), off=np.concatenate([[0], np.cumsum(lens)]),
             t=np.array(ts), m=np.stack(mm).astype(np.float16) if mm else np.zeros((0, GRID, GRID), np.float16), hw=np.array(hw))
    return dst


def extract_all(items, cache_dir):
    pathlib.Path(cache_dir).mkdir(parents=True, exist_ok=True)
    jobs = [(str(p), str(pathlib.Path(cache_dir) / k)) for p, k in items]
    with Pool(os.cpu_count() or 2) as pool:
        for n, _ in enumerate(pool.imap_unordered(_extract, jobs, chunksize=4)):
            if n % 200 == 0: print(f"  extracted {n}/{len(jobs)}", flush=True)
    return {k: str(pathlib.Path(cache_dir) / (k + ".npz")) for _, k in items}


class Clip:
    def __init__(s, path):
        z = np.load(path); s.blob, s.off, s.t = z["blob"], z["off"], z["t"]; s.h, s.w = [int(v) for v in z["hw"]]
        s.cs = np.cumsum(z["m"].astype(np.float32), 0); s._fc = {}
    def n(s): return len(s.t)
    def frame(s, i):
        if i not in s._fc: s._fc[i] = cv2.imdecode(s.blob[s.off[i]:s.off[i + 1]], cv2.IMREAD_COLOR)[:, :, ::-1]
        return s._fc[i]
    def heat(s, e): return s.cs[e] - s.cs[e - NF + 1]


# ------------------------------------------------------------ proposals + views
def crop_side(w, h): return max(8, int(CROP_FRAC * min(w, h)))


def proposals(heat, w, h, k=K_LOCAL):
    S = crop_side(w, h); sx, sy = S / w, S / h; hm = cv2.blur(heat.astype(np.float32), (3, 3)).copy(); xs = (np.arange(GRID) + .5) / GRID; out = []
    for _ in range(k):
        j = np.unravel_index(np.argmax(hm), hm.shape)
        if hm[j] <= 0: break
        cy, cx = xs[j[0]], xs[j[1]]; out.append((float(np.clip(cx, sx / 2, 1 - sx / 2)), float(np.clip(cy, sy / 2, 1 - sy / 2))))
        hm[(np.abs(xs[None, :] - cx) <= sx) & (np.abs(xs[:, None] - cy) <= sy)] = 0
    return out


def covers(view, crash, w, h):
    if view is None or crash is None or not np.isfinite(crash).all(): return False
    S = crop_side(w, h); return abs(crash[0] - view[0]) <= S / w / 2 and abs(crash[1] - view[1]) <= S / h / 2


def make_view(c, e, view):
    fr = [c.frame(i) for i in V.win_idx(e)]
    if view is None: return np.stack([cv2.resize(f, (SIZE, SIZE), interpolation=cv2.INTER_AREA) for f in fr])
    S = crop_side(c.w, c.h); x0 = int(np.clip(round(view[0] * c.w - S / 2), 0, c.w - S)); y0 = int(np.clip(round(view[1] * c.h - S / 2), 0, c.h - S))
    return np.stack([cv2.resize(f[y0:y0 + S, x0:x0 + S], (SIZE, SIZE), interpolation=cv2.INTER_AREA) for f in fr])


def proposal_coverage(df, cache, n=300, seed=0):
    d = df.sample(min(len(df), n), random_state=seed); rng = random.Random(seed); hit, frac, chance = [], [], []
    for _, r in d.iterrows():
        c = Clip(cache[A.clip_key(r["path"])]); ta = float(r["accident_time"]); crash = (float(r["center_x"]), float(r["center_y"]))
        ends = [e for e in range(NF - 1, c.n()) if V.window_label(c.t[e], ta) == 1]
        if not ends: continue
        cov = [any(covers(v, crash, c.w, c.h) for v in proposals(c.heat(e), c.w, c.h)) for e in ends]
        rnd = [any(covers((rng.random(), rng.random()), crash, c.w, c.h) for _ in range(K_LOCAL)) for _ in ends]
        hit.append(any(cov)); frac.append(np.mean(cov)); chance.append(np.mean(rnd))
    return dict(clips=len(hit), clip_has_covering_crop=float(np.mean(hit)), windows_covered=float(np.mean(frac)), windows_covered_by_random_crops=float(np.mean(chance)))


# ------------------------------------------------------------ training data + inference
class ClipDS4(torch.utils.data.Dataset):
    def __init__(self, df, cache, seed=0): self.df, self.cache, self.seed = df.reset_index(drop=True), cache, seed
    def __len__(self): return len(self.df)
    def __getitem__(self, i):
        r = self.df.iloc[i]; c = Clip(self.cache[A.clip_key(r["path"])]); ta = float(r["accident_time"]); rng = random.Random(hash((self.seed, i, random.random())))
        if c.n() < NF: return torch.zeros(0, NF, SIZE, SIZE, 3, dtype=torch.uint8), torch.zeros(0)
        crash = (float(r["center_x"]), float(r["center_y"])); xs, ys = [], []
        for e, y in V.sample_windows(c.t, ta, rng):
            locs = proposals(c.heat(e), c.w, c.h)
            if y == 1:
                cov = [v for v in locs if covers(v, crash, c.w, c.h)]; v = rng.choice(cov + [None]) if cov else None
            else: v = rng.choice([None] + locs)
            xs.append(make_view(c, e, v)); ys.append(y)
        return (torch.from_numpy(np.stack(xs)), torch.tensor(ys, dtype=torch.float32)) if xs else (torch.zeros(0, NF, SIZE, SIZE, 3, dtype=torch.uint8), torch.zeros(0))


@torch.no_grad()
def clip_probs(model, df, cache, device=None, bs=12):
    device = device or next(model.parameters()).device; model.eval(); out = {}
    for _, r in df.iterrows():
        c = Clip(cache[A.clip_key(r["path"])]); ends = V.window_ends(c.n()); items, owner = [], []
        for k, e in enumerate(ends):
            for v in [None] + proposals(c.heat(e), c.w, c.h): items.append(make_view(c, e, v)); owner.append(k)
        p = np.zeros(len(ends), np.float32)
        for i in range(0, len(items), bs):
            with torch.autocast(device_type="cuda", enabled=str(device).startswith("cuda")):
                q = torch.sigmoid(V.logits(model, V.to_input(torch.from_numpy(np.stack(items[i:i + bs])), device)).float()).cpu().numpy()
            np.maximum.at(p, np.array(owner[i:i + bs]), q)
        out[r["path"]] = (np.array([c.t[e] for e in ends]), p); c._fc.clear()
    return out


def install():
    V.ClipDS = ClipDS4; V.clip_probs = clip_probs


def run_protocol(real, cache, split_col, out_dir, **kw):
    install(); return V.run_protocol(real, cache, split_col, out_dir, **kw)

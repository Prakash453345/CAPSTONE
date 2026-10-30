"""V8: V5 recipe + crash-centred crops for positive windows no motion crop covers (see TARGETS_VIDEO_V8_LOCKED.md).
Call patch() once (after the V4/V5 modules are imported) so BOTH training datasets (stage 1 ClipDS4, stage 2 ClipDS5) use the change; then run_protocol5 is unchanged."""
from __future__ import annotations
import random
import numpy as np, torch
import m8_accident_video as V
import m8_accident_video4 as V4
import m8_accident_video5 as V5
import m8_accident_train_v2 as A

K = 3
JITTER = 0.08
_STATE = {"patched": False}


def positive_view(rng, locs, crash, w, h):
    """Training view of a positive window: the V4 rule when a motion crop covers the crash, otherwise a crop centred on the labelled crash point."""
    cov = [v for v in locs if V4.covers(v, crash, w, h)]
    if cov: return rng.choice(cov + [None])
    if crash is None or not np.isfinite(crash).all(): return None
    S = V4.crop_side(w, h); sx, sy = S / w, S / h
    cx = float(np.clip(crash[0] + rng.uniform(-JITTER, JITTER), sx / 2, 1 - sx / 2)); cy = float(np.clip(crash[1] + rng.uniform(-JITTER, JITTER), sy / 2, 1 - sy / 2))
    return (cx, cy)


class ClipDS8(torch.utils.data.Dataset):
    """V4 stage-1 windows with the crash-centred fallback."""
    def __init__(self, df, cache, seed=0): self.df, self.cache, self.seed = df.reset_index(drop=True), cache, seed
    def __len__(self): return len(self.df)
    def __getitem__(self, i):
        empty = (torch.zeros(0, V.NF, V.SIZE, V.SIZE, 3, dtype=torch.uint8), torch.zeros(0))
        r = self.df.iloc[i]; c = V4.Clip(self.cache[A.clip_key(r["path"])]); ta = float(r["accident_time"]); rng = random.Random(hash((self.seed, i, random.random())))
        if c.n() < V.NF: return empty
        crash = (float(r["center_x"]), float(r["center_y"])); xs, ys = [], []
        for e, y in V.sample_windows(c.t, ta, rng):
            locs = V4.proposals(c.heat(e), c.w, c.h)
            v = positive_view(rng, locs, crash, c.w, c.h) if y == 1 else rng.choice([None] + locs)
            xs.append(V4.make_view(c, e, v)); ys.append(y)
        return (torch.from_numpy(np.stack(xs)), torch.tensor(ys, dtype=torch.float32)) if xs else empty


class ClipDS8Hard(torch.utils.data.Dataset):
    """V5 stage-2 windows (mined hard negatives) with the crash-centred fallback."""
    def __init__(self, df, cache, hard, seed=0): self.df, self.cache, self.hard, self.seed = df.reset_index(drop=True), cache, hard, seed
    def __len__(self): return len(self.df)
    def __getitem__(self, i):
        empty = (torch.zeros(0, V.NF, V.SIZE, V.SIZE, 3, dtype=torch.uint8), torch.zeros(0))
        r = self.df.iloc[i]; c = V4.Clip(self.cache[A.clip_key(r["path"])]); ta = float(r["accident_time"]); rng = random.Random(hash((self.seed, i, random.random())))
        if c.n() < V.NF: return empty
        crash = (float(r["center_x"]), float(r["center_y"])); ws = V.sample_windows(c.t, ta, rng)
        pos = [w for w in ws if w[1] == 1]; neg = [w for w in ws if w[1] == 0]
        hard = self.hard.get(r["path"], []); h = rng.sample(hard, min(V5.HARD_PER_CLIP, len(hard))) if hard else []
        neg = neg[:max(0, len(neg) - len(h))]; xs, ys = [], []
        for e, y in pos + neg:
            locs = V4.proposals(c.heat(e), c.w, c.h)
            v = positive_view(rng, locs, crash, c.w, c.h) if y == 1 else rng.choice([None] + locs)
            xs.append(V4.make_view(c, e, v)); ys.append(y)
        for e, v in h: xs.append(V4.make_view(c, e, v)); ys.append(0)
        return (torch.from_numpy(np.stack(xs)), torch.tensor(ys, dtype=torch.float32)) if xs else empty


def patch():
    V4.ClipDS4 = ClipDS8; V5.ClipDS5 = ClipDS8Hard; _STATE["patched"] = True       # install() / stage2() resolve these names at call time


def run8(real, cache, out_dir, epochs=4, log=print, model_fn=None):
    assert _STATE["patched"] and V4.ClipDS4 is ClipDS8 and V5.ClipDS5 is ClipDS8Hard, "call patch() first"
    V4.install(); V5.set_k(K); assert V.ClipDS is ClipDS8
    return V5.run_protocol5(real, cache, "split_geo_aware", out_dir, stage1=None, epochs=epochs, seed=0, log=log, model_fn=model_fn or V.build_model)


def verdict8(res):
    import m8_accident_video6 as V6
    rows, extra = V6.verdict6(res)
    return [(r[0].replace("E", "J", 1), r[1], r[2]) for r in rows], {"adopt_v8": bool(extra["adopt_ensemble"]), "highway_detect_reported": extra["highway_detect_reported"]}

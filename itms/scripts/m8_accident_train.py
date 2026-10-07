"""ACCIDENT-benchmark training + one-shot scoring (see TARGETS_LOCKED.md).

Per-frame EfficientNet-B0 (normal vs accident), a k-of-n persistence alarm, thresholds chosen on a
validation split of the TRAIN clips, each test split scored once. Frames before the impact time are
"normal", frames after are "accident"; the +-window around the impact is ignored when training.
"""
from __future__ import annotations
import json, os, pathlib, random, re, time
from multiprocessing import Pool
import cv2, numpy as np, pandas as pd, torch, torch.nn as nn

SIZE, FPS = 224, 2.0
GAP_BEFORE_S, GAP_AFTER_S = 1.0, 0.5       # ignored around the impact when training
DETECT_WITHIN_S = 10.0                      # B1 window
CFG_GRID = [(k, n) for k, n in ((2, 3), (3, 5), (3, 4), (4, 6))]
THR_GRID = [round(x, 2) for x in np.arange(0.30, 0.96, 0.05)]
VAL_EARLY_CAP = 0.04                        # margin under the locked B2 bar of 5 %


# ---------------------------------------------------------------- frames
def sample_frames(path, fps=FPS, size=SIZE):
    cap = cv2.VideoCapture(str(path)); src = cap.get(cv2.CAP_PROP_FPS) or 15.0
    step = max(1, int(round(src / fps))); frames, times, i = [], [], 0
    while cap.grab():
        if i % step == 0:
            ok, f = cap.retrieve()
            if ok:
                frames.append(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2RGB), (size, size),
                                         interpolation=cv2.INTER_AREA))
                times.append(i / src)
        i += 1
    cap.release()
    if not frames:
        return np.zeros((0, size, size, 3), np.uint8), np.zeros(0)
    return np.stack(frames), np.array(times)


def _extract(args):
    src, dst = args
    if os.path.exists(dst + ".npz"):
        return dst
    fr, t = sample_frames(src)
    np.savez(dst + ".npz", f=fr, t=t)
    return dst


def extract_all(items, cache_dir, workers=None):
    """items: list of (video_path, key). Returns {key: npz path}."""
    pathlib.Path(cache_dir).mkdir(parents=True, exist_ok=True)
    jobs = [(str(p), str(pathlib.Path(cache_dir) / k)) for p, k in items]
    with Pool(workers or os.cpu_count() or 2) as pool:
        for n, _ in enumerate(pool.imap_unordered(_extract, jobs, chunksize=4)):
            if n % 200 == 0:
                print(f"  extracted {n}/{len(jobs)}", flush=True)
    return {k: str(pathlib.Path(cache_dir) / (k + ".npz")) for _, k in items}


def clip_key(path):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(path))


def group_id(path):
    return pathlib.Path(path).stem[:11]       # YouTube id: clips of one source video share it


# ---------------------------------------------------------------- data
def build_frames(df, cache, path_col, kind):
    """-> arrays X (uint8 N,H,W,3), y (N), clip index, for training frames."""
    X, y = [], []
    for _, r in df.iterrows():
        z = np.load(cache[clip_key(r[path_col])]); fr, t = z["f"], z["t"]
        ta = float(r["accident_time"])
        lab = np.full(len(t), -1)
        lab[t < ta - GAP_BEFORE_S] = 0
        lab[t >= ta + GAP_AFTER_S] = 1
        keep = lab >= 0
        X.append(fr[keep]); y.append(lab[keep])
    return (np.concatenate(X), np.concatenate(y)) if X else (np.zeros((0, SIZE, SIZE, 3), np.uint8), np.zeros(0))


MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


class Net(nn.Module):
    """uint8-range RGB in [0,1], NCHW -> logit. Normalisation inside, so the ONNX takes [0,1] pixels."""
    def __init__(self, pretrained=True):
        super().__init__()
        import timm
        self.m = timm.create_model("efficientnet_b0", pretrained=pretrained, num_classes=1)
        self.register_buffer("mean", MEAN.clone()); self.register_buffer("std", STD.clone())

    def forward(self, x):
        return self.m((x - self.mean) / self.std).squeeze(1)


def to_t(xb, device):
    return torch.from_numpy(xb).to(device).permute(0, 3, 1, 2).float() / 255.0


def augment(x):
    if random.random() < 0.5:
        x = x.flip(3)
    b = 1 + (torch.rand(x.shape[0], 1, 1, 1, device=x.device) - 0.5) * 0.5
    c = 1 + (torch.rand(x.shape[0], 1, 1, 1, device=x.device) - 0.5) * 0.5
    m = x.mean(dim=(1, 2, 3), keepdim=True)
    return ((x - m) * c + m * b).clamp(0, 1)


def train(X, y, epochs=8, bs=64, lr=3e-4, pretrained=True, device=None, seed=0, log=print):
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(seed); random.seed(seed); np.random.seed(seed)
    net = Net(pretrained).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    steps = epochs * max(1, len(X) // bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps)
    pw = torch.tensor((y == 0).sum() / max(1, (y == 1).sum()), device=device).float()
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
    scaler = torch.amp.GradScaler(enabled=device == "cuda")
    for ep in range(epochs):
        net.train(); idx = np.random.permutation(len(X)); tot = 0.0
        for s in range(0, len(idx) - bs + 1, bs):
            b = idx[s:s + bs]
            xb = augment(to_t(X[b], device)); yb = torch.from_numpy(y[b]).float().to(device)
            with torch.autocast(device_type="cuda", enabled=device == "cuda"):
                loss = lossf(net(xb), yb)
            opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
            tot += float(loss)
        log(f"  epoch {ep + 1}/{epochs} loss {tot / max(1, len(idx) // bs):.4f}")
    return net


@torch.no_grad()
def clip_probs(net, df, cache, path_col, device=None, bs=128):
    device = device or next(net.parameters()).device
    net.eval(); out = {}
    for _, r in df.iterrows():
        z = np.load(cache[clip_key(r[path_col])]); fr, t = z["f"], z["t"]
        p = np.concatenate([torch.sigmoid(net(to_t(fr[i:i + bs], device))).cpu().numpy()
                            for i in range(0, len(fr), bs)]) if len(fr) else np.zeros(0)
        out[r[path_col]] = (t, p)
    return out


# ---------------------------------------------------------------- alarm + metrics
def first_alarm_times(t, p, thr, k, n):
    """Times at which >= k of the last n frames are >= thr (every alarming frame)."""
    hot = (p >= thr).astype(int); out = []
    for i in range(len(hot)):
        if hot[max(0, i - n + 1):i + 1].sum() >= k:
            out.append(t[i])
    return out


def evaluate(probs, df, path_col, thr, k, n):
    rows = []
    for _, r in df.iterrows():
        t, p = probs[r[path_col]]; ta = float(r["accident_time"])
        al = first_alarm_times(t, p, thr, k, n)
        early = any(a < ta for a in al)
        post = [a for a in al if ta <= a <= ta + DETECT_WITHIN_S]
        rows.append({"path": r[path_col], "early": early, "detected": bool(post),
                     "delay": (post[0] - ta) if post else None, "ta": ta})
    d = pd.DataFrame(rows)
    det = d["detected"].mean(); early = d["early"].mean()
    strict = (d["detected"] & ~d["early"]).mean()
    delays = d["delay"].dropna()
    return {"n": len(d), "B1_detect_within_10s": float(det), "B2_early_alarm": float(early),
            "strict_detect_no_early": float(strict),
            "B3_median_delay_s": float(delays.median()) if len(delays) else None}, d


def choose_config(probs, df, path_col):
    best = None
    for k, n in CFG_GRID:
        for thr in THR_GRID:
            m, _ = evaluate(probs, df, path_col, thr, k, n)
            feas = m["B2_early_alarm"] <= VAL_EARLY_CAP
            key = (feas, m["B1_detect_within_10s"] if feas else -m["B2_early_alarm"],
                   -(m["B3_median_delay_s"] or 99))
            if best is None or key > best[0]:
                best = (key, {"thr": thr, "k": k, "n": n, "val": m, "feasible": feas})
    return best[1]


def breakdown(d, df, path_col, cols=("day_time", "weather", "scene_layout", "quality", "type")):
    m = d.merge(df, left_on="path", right_on=path_col)
    out = {}
    for c in cols:
        if c in m:
            out[c] = {str(v): {"n": int(len(g)), "detect": round(float(g["detected"].mean()), 3),
                               "early": round(float(g["early"].mean()), 3)}
                      for v, g in m.groupby(c)}
    return out


def split_train_val(df, path_col, frac=0.2, seed=0):
    g = sorted({group_id(p) for p in df[path_col]}); rng = random.Random(seed); rng.shuffle(g)
    val = set(g[:max(1, int(len(g) * frac))])
    isval = df[path_col].map(lambda p: group_id(p) in val)
    return df[~isval].copy(), df[isval].copy()


def export_onnx(net, path):
    net.eval().cpu()
    kw = dict(input_names=["image"], output_names=["logit"],
              dynamic_axes={"image": {0: "b"}, "logit": {0: "b"}}, opset_version=17)
    try:
        torch.onnx.export(net, torch.rand(1, 3, SIZE, SIZE), path, dynamo=False, **kw)
    except TypeError:   # older torch has no `dynamo` argument
        torch.onnx.export(net, torch.rand(1, 3, SIZE, SIZE), path, **kw)


# ---------------------------------------------------------------- protocol
def run_protocol(real, syn, cache, split_col, out_dir, synth_n=300, epochs=8, pretrained=True,
                 seed=0, bs=64, log=print):
    """real/syn: metadata frames whose clips are already in `cache`. Trains real-only and
    real+synthetic, picks the variant + alarm config on the validation clips, then scores the
    split's test clips ONCE. Returns the results dict (also written to out_dir)."""
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    tr_all = real[real[split_col] == "train"]; te = real[real[split_col] == "test"]
    tr, va = split_train_val(tr_all, "path", seed=seed)
    log(f"[{split_col}] train {len(tr)} val {len(va)} test {len(te)} clips")
    Xr, yr = build_frames(tr, cache, "path", "real")
    syn_s = syn.sample(n=min(synth_n, len(syn)), random_state=seed) if len(syn) else syn
    Xs, ys = build_frames(syn_s, cache, "rgb_path", "syn") if len(syn_s) else (Xr[:0], yr[:0])
    log(f"  frames: real {len(yr)} (acc {int(yr.sum())}), synthetic {len(ys)}")
    variants, picks = {}, {}
    for name, (X, y) in {"real_only": (Xr, yr),
                         "real_plus_synth": (np.concatenate([Xr, Xs]), np.concatenate([yr, ys]))}.items():
        if name == "real_plus_synth" and len(ys) == 0:
            continue
        log(f" training {name} ({len(y)} frames)")
        net = train(X, y, epochs=epochs, bs=bs, pretrained=pretrained, seed=seed, log=log)
        pv = clip_probs(net, va, cache, "path")
        cfg = choose_config(pv, va, "path")
        log(f"  val: {cfg['val']}  thr {cfg['thr']} k/n {cfg['k']}/{cfg['n']} feasible {cfg['feasible']}")
        variants[name] = net; picks[name] = cfg
    def score_key(c):
        return (c["feasible"], c["val"]["B1_detect_within_10s"] if c["feasible"] else -c["val"]["B2_early_alarm"])
    chosen = max(picks, key=lambda n: score_key(picks[n]))
    cfg = picks[chosen]
    (out / f"chosen_{split_col}.json").write_text(json.dumps({"variant": chosen, **cfg, "picks": picks}, indent=1, default=str))
    log(f" CHOSEN on validation: {chosen} {cfg['thr']} {cfg['k']}/{cfg['n']} -- config frozen, scoring test once")
    net = variants[chosen]
    pt = clip_probs(net, te, cache, "path")
    m, d = evaluate(pt, te, "path", cfg["thr"], cfg["k"], cfg["n"])
    res = {"split": split_col, "variant": chosen, "thr": cfg["thr"], "k": cfg["k"], "n": cfg["n"],
           "val": cfg["val"], "test": m, "breakdown": breakdown(d, te, "path"),
           "val_picks": {k: v["val"] for k, v in picks.items()}}
    (out / f"results_{split_col}.json").write_text(json.dumps(res, indent=1, default=str))
    torch.save(net.state_dict(), out / f"accident_effb0_{split_col}.pt")
    return res, net


def verdict(res_in, res_geo):
    a, b = res_in["test"], res_geo["test"]
    rows = [("B1 in-dist detect<=10s >=70%", a["B1_detect_within_10s"], a["B1_detect_within_10s"] >= 0.70),
            ("B2 in-dist early alarm <=5%", a["B2_early_alarm"], a["B2_early_alarm"] <= 0.05),
            ("B3 median delay <=5s", a["B3_median_delay_s"], (a["B3_median_delay_s"] is not None and a["B3_median_delay_s"] <= 5)),
            ("B4a geo detect >=60%", b["B1_detect_within_10s"], b["B1_detect_within_10s"] >= 0.60),
            ("B4b geo early alarm <=8%", b["B2_early_alarm"], b["B2_early_alarm"] <= 0.08)]
    return rows

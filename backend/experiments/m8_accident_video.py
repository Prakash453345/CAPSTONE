"""V3: fine-tune a pretrained video backbone (VideoMAE) on ACCIDENT windows (see TARGETS_VIDEO_LOCKED.md).
Reuses the v2 protocol helpers (grouped validation split, k-of-n alarm, locked metrics)."""
from __future__ import annotations
import json, os, pathlib, random
from multiprocessing import Pool
import cv2, numpy as np, pandas as pd, torch, torch.nn as nn
import m8_accident_train_v2 as A

FPS, SIZE, NF, STRIDE = 4.0, 224, 16, 4          # 16 frames at 4 fps = 4-s window; scored every 4 frames = 1 s
GAP_BEFORE_S, GAP_AFTER_S, POS_MAX_S = 1.0, 0.5, 3.0
MODEL_ID = os.environ.get("ACC_VID", "MCG-NJU/videomae-base-finetuned-kinetics")
A.CFG_GRID = [(1, 1), (2, 3), (2, 4), (3, 5)]    # persistence in units of 1-s windows
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 1, 3, 1, 1); STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 1, 3, 1, 1)


# ------------------------------------------------------------ frames cache (4 fps, 224 px)
def _extract(args):
    src, dst = args
    if os.path.exists(dst + ".npz"): return dst
    cap = cv2.VideoCapture(src); sfps = cap.get(cv2.CAP_PROP_FPS) or 15.0; step = max(1, int(round(sfps / FPS))); fr, ts, i = [], [], 0
    while cap.grab():
        if i % step == 0:
            ok, f = cap.retrieve()
            if ok: fr.append(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2RGB), (SIZE, SIZE), interpolation=cv2.INTER_AREA)); ts.append(i / sfps)
        i += 1
    cap.release()
    np.savez(dst + ".npz", f=np.stack(fr) if fr else np.zeros((0, SIZE, SIZE, 3), np.uint8), t=np.array(ts))
    return dst


def extract_all(items, cache_dir):
    pathlib.Path(cache_dir).mkdir(parents=True, exist_ok=True)
    jobs = [(str(p), str(pathlib.Path(cache_dir) / k)) for p, k in items]
    with Pool(os.cpu_count() or 2) as pool:
        for n, _ in enumerate(pool.imap_unordered(_extract, jobs, chunksize=4)):
            if n % 200 == 0: print(f"  extracted {n}/{len(jobs)}", flush=True)
    return {k: str(pathlib.Path(cache_dir) / (k + ".npz")) for _, k in items}


# ------------------------------------------------------------ windows + labels (pure)
def win_idx(e, n=None):
    return np.clip(np.arange(e - NF + 1, e + 1), 0, None)


def window_ends(n):
    return list(range(NF - 1, n, STRIDE))


def window_label(te, ta):
    if te <= ta - GAP_BEFORE_S: return 0
    if ta + GAP_AFTER_S <= te <= ta + POS_MAX_S: return 1
    return -1


def sample_windows(t, ta, rng, n_pos=4, n_neg=4):
    """Training windows for one clip: any frame as the window end (not just the 1-s grid)."""
    ends = list(range(NF - 1, len(t)))
    pos = [e for e in ends if window_label(t[e], ta) == 1]; neg = [e for e in ends if window_label(t[e], ta) == 0]
    P = rng.sample(pos, min(n_pos, len(pos))) if pos else []; N = rng.sample(neg, min(n_neg, len(neg))) if neg else []
    return [(e, 1) for e in P] + [(e, 0) for e in N]


class ClipDS(torch.utils.data.Dataset):
    def __init__(self, df, cache, seed=0): self.df, self.cache, self.seed = df.reset_index(drop=True), cache, seed
    def __len__(self): return len(self.df)
    def __getitem__(self, i):
        r = self.df.iloc[i]; z = np.load(self.cache[A.clip_key(r["path"])]); fr, t = z["f"], z["t"]
        rng = random.Random(hash((self.seed, i, random.random())))
        ws = sample_windows(t, float(r["accident_time"]), rng) if len(fr) >= NF else []
        if not ws: return torch.zeros(0, NF, SIZE, SIZE, 3, dtype=torch.uint8), torch.zeros(0)
        x = np.stack([fr[win_idx(e)] for e, _ in ws]); return torch.from_numpy(x), torch.tensor([y for _, y in ws], dtype=torch.float32)


def collate(b):
    xs = [x for x, _ in b if len(x)]; ys = [y for _, y in b if len(y)]
    return (torch.cat(xs), torch.cat(ys)) if xs else (None, None)


# ------------------------------------------------------------ model
def build_model():
    from transformers import VideoMAEForVideoClassification
    m = VideoMAEForVideoClassification.from_pretrained(MODEL_ID, num_labels=1, ignore_mismatched_sizes=True)
    b = m.videomae.encoder.layer[0].attention.attention.value.bias       # older transformers 5.x drop the checkpoint's q/v biases silently
    if b is not None and float(b.abs().sum()) == 0 and not os.environ.get("ACC_ALLOW_BIAS_RESET"):
        raise RuntimeError("Pretrained VideoMAE q/v biases were NOT loaded (old transformers). Run: pip install -U transformers, restart the session, re-run.")
    m.gradient_checkpointing_enable()          # 8 windows x 1568 tokens would not fit a 16-GB T4 otherwise
    return m


def to_input(x, device, train=False):
    x = x.to(device).permute(0, 1, 4, 2, 3).float() / 255.0          # B,T,C,H,W
    if train:
        flip = torch.rand(x.shape[0], device=device) < 0.5; x = torch.where(flip.view(-1, 1, 1, 1, 1), x.flip(-1), x)
        x = (x * (0.8 + 0.4 * torch.rand(x.shape[0], 1, 1, 1, 1, device=device))).clamp(0, 1)
    return (x - MEAN.to(device)) / STD.to(device)


def logits(model, x):
    o = model(pixel_values=x); o = getattr(o, "logits", o); return o.view(o.shape[0])


def train(model, df, cache, epochs=4, lr=5e-5, clips_per_batch=1, device=None, log=print, seed=0):
    device = device or ("cuda" if torch.cuda.is_available() else "cpu"); model.to(device).train()
    dl = torch.utils.data.DataLoader(ClipDS(df, cache, seed), batch_size=clips_per_batch, shuffle=True, num_workers=2, collate_fn=collate)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.05); steps = epochs * len(dl)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.1)
    scaler = torch.amp.GradScaler(enabled=device == "cuda"); lossf = nn.BCEWithLogitsLoss()
    for ep in range(epochs):
        tot, n = 0.0, 0
        for x, y in dl:
            if x is None: sched.step(); continue
            with torch.autocast(device_type=device if device == "cuda" else "cpu", enabled=device == "cuda"):
                loss = lossf(logits(model, to_input(x, device, True)).float(), y.to(device))
            opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
            tot += loss.item() * len(y); n += len(y)
        log(f"  epoch {ep + 1}/{epochs} loss {tot / max(1, n):.4f} ({n} windows)")
    return model


@torch.no_grad()
def clip_probs(model, df, cache, device=None, bs=16):
    device = device or next(model.parameters()).device; model.eval(); out = {}
    for _, r in df.iterrows():
        z = np.load(cache[A.clip_key(r["path"])]); fr, t = z["f"], z["t"]; ends = window_ends(len(fr)); ps = []
        for i in range(0, len(ends), bs):
            x = torch.from_numpy(np.stack([fr[win_idx(e)] for e in ends[i:i + bs]]))
            with torch.autocast(device_type="cuda", enabled=str(device).startswith("cuda")):
                ps.append(torch.sigmoid(logits(model, to_input(x, device)).float()).cpu().numpy())
        out[r["path"]] = (np.array([t[e] for e in ends]), np.concatenate(ps) if ps else np.zeros(0))
    return out


# ------------------------------------------------------------ protocol
def run_protocol(real, cache, split_col, out_dir, epochs=4, seed=0, log=print, model_fn=build_model):
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    tr_all = real[real[split_col] == "train"]; te = real[real[split_col] == "test"]
    tr, va = A.split_train_val(tr_all, "path", seed=seed); log(f"[{split_col}] train {len(tr)} val {len(va)} test {len(te)}")
    torch.manual_seed(seed); model = train(model_fn(), tr, cache, epochs=epochs, log=log, seed=seed)
    cfg = A.choose_config(clip_probs(model, va, cache), va, "path")
    log(f" CHOSEN on validation: thr {cfg['thr']} k/n {cfg['k']}/{cfg['n']} feasible {cfg['feasible']} val {cfg['val']}")
    (out / f"chosen_{split_col}.json").write_text(json.dumps(cfg, indent=1, default=str))
    m, d = A.evaluate(clip_probs(model, te, cache), te, "path", cfg["thr"], cfg["k"], cfg["n"])      # test scored ONCE
    res = {"split": split_col, "thr": cfg["thr"], "k": cfg["k"], "n": cfg["n"], "val": cfg["val"], "test": m, "breakdown": A.breakdown(d, te, "path")}
    (out / f"results_{split_col}.json").write_text(json.dumps(res, indent=1, default=str)); return res, model

"""V5: V4 + hard-negative mining stage + K local crops + rise-over-baseline alarm rule (see TARGETS_VIDEO_V5_LOCKED.md).
Reuses the V3/V4 training and cache code; nothing here reads a test split before the single scoring pass."""
from __future__ import annotations
import json, pathlib, random
import numpy as np, pandas as pd, torch
import m8_accident_video as V
import m8_accident_video4 as V4
import m8_accident_train_v2 as A
import m8_accident_false_alarm as F

NF, SIZE = V.NF, V.SIZE
DELTA_GRID = [0.0, 0.15, 0.30]
MINE_GAP_S, MINE_MIN_P, MINE_MAX_PER_CLIP, HARD_PER_CLIP = 2.0, 0.4, 4, 2
STAGE2_EPOCHS, STAGE2_LR = 2, 2e-5
_ORIG_PROPOSALS = V4.proposals


# ------------------------------------------------------------ K local crops
def set_k(k):
    """Make every V4 function (training views, inference views, coverage) use `k` local crops."""
    V4.K_LOCAL = k
    V4.proposals = lambda heat, w, h, kk=None: _ORIG_PROPOSALS(heat, w, h, k if kk is None else kk)


def choose_k(train_df, cache, n=300, seed=0, min_gain=0.04):
    """K = 3 only if it lifts clip coverage by >= min_gain over K = 2 (measured on TRAIN clips)."""
    cov = {}
    for k in (2, 3):
        set_k(k); cov[k] = V4.proposal_coverage(train_df, cache, n=n, seed=seed)
    k = 3 if cov[3]["clip_has_covering_crop"] - cov[2]["clip_has_covering_crop"] >= min_gain else 2
    set_k(k); return k, cov


# ------------------------------------------------------------ alarm rule with a rise condition
def alarm_times(t, p, thr, k, n, delta=0.0):
    return [t[i] for i in range(len(p)) if F.hot_now(p, i, thr, k, n, delta)]


def evaluate5(probs, df, thr, k, n, delta):
    old = A.first_alarm_times
    A.first_alarm_times = lambda t, p, thr_, k_, n_: alarm_times(t, p, thr_, k_, n_, delta)
    try: return A.evaluate(probs, df, "path", thr, k, n)
    finally: A.first_alarm_times = old


def choose5(probs, df):
    best = None
    for k, n in A.CFG_GRID:
        for delta in DELTA_GRID:
            for thr in A.THR_GRID:
                m, _ = evaluate5(probs, df, thr, k, n, delta); feas = m["B2_early_alarm"] <= A.VAL_EARLY_CAP
                key = (feas, m["B1_detect_within_10s"] if feas else -m["B2_early_alarm"], -(m["B3_median_delay_s"] or 99), -delta)
                if best is None or key > best[0]: best = (key, {"thr": thr, "k": k, "n": n, "delta": delta, "val": m, "feasible": feas})
    return best[1]


# ------------------------------------------------------------ hard-negative mining + stage-2 data
@torch.no_grad()
def mine(model, df, cache, device=None, bs=12, log=print):
    """{path: [(window end index, view)]}: the pre-impact windows of TRAIN clips that the model scores highest, with their top view."""
    device = device or next(model.parameters()).device; model.eval(); hard = {}
    for _, r in df.iterrows():
        c = V4.Clip(cache[A.clip_key(r["path"])]); ta = float(r["accident_time"])
        ends = [e for e in V.window_ends(c.n()) if c.t[e] <= ta - MINE_GAP_S]
        items, meta = [], []
        for e in ends:
            for v in [None] + V4.proposals(c.heat(e), c.w, c.h): items.append(V4.make_view(c, e, v)); meta.append((e, v))
        ps = []
        for i in range(0, len(items), bs):
            with torch.autocast(device_type="cuda", enabled=str(device).startswith("cuda")):
                ps.extend(torch.sigmoid(V.logits(model, V.to_input(torch.from_numpy(np.stack(items[i:i + bs])), device)).float()).cpu().numpy().tolist())
        best = {}
        for (e, v), q in zip(meta, ps):
            if e not in best or q > best[e][0]: best[e] = (q, v)
        cand = sorted(((q, e, v) for e, (q, v) in best.items() if q >= MINE_MIN_P), key=lambda x: -x[0])[:MINE_MAX_PER_CLIP]
        if cand: hard[r["path"]] = [(int(e), v) for _, e, v in cand]
        c._fc.clear()
    log(f"  mined {sum(len(v) for v in hard.values())} hard negatives from {len(hard)}/{len(df)} train clips")
    return hard


class ClipDS5(torch.utils.data.Dataset):
    """V4 windows, but up to HARD_PER_CLIP of each clip's normal windows are its mined hard negatives."""
    def __init__(self, df, cache, hard, seed=0): self.df, self.cache, self.hard, self.seed = df.reset_index(drop=True), cache, hard, seed
    def __len__(self): return len(self.df)
    def __getitem__(self, i):
        empty = (torch.zeros(0, NF, SIZE, SIZE, 3, dtype=torch.uint8), torch.zeros(0))
        r = self.df.iloc[i]; c = V4.Clip(self.cache[A.clip_key(r["path"])]); ta = float(r["accident_time"]); rng = random.Random(hash((self.seed, i, random.random())))
        if c.n() < NF: return empty
        crash = (float(r["center_x"]), float(r["center_y"])); ws = V.sample_windows(c.t, ta, rng)
        pos = [w for w in ws if w[1] == 1]; neg = [w for w in ws if w[1] == 0]
        hard = self.hard.get(r["path"], []); h = rng.sample(hard, min(HARD_PER_CLIP, len(hard))) if hard else []
        neg = neg[:max(0, len(neg) - len(h))]
        xs, ys = [], []
        for e, y in pos + neg:
            locs = V4.proposals(c.heat(e), c.w, c.h)
            if y == 1:
                cov = [v for v in locs if V4.covers(v, crash, c.w, c.h)]; v = rng.choice(cov + [None]) if cov else None
            else: v = rng.choice([None] + locs)
            xs.append(V4.make_view(c, e, v)); ys.append(y)
        for e, v in h: xs.append(V4.make_view(c, e, v)); ys.append(0)
        return (torch.from_numpy(np.stack(xs)), torch.tensor(ys, dtype=torch.float32)) if xs else empty


def stage2(model, tr, cache, hard, seed=0, log=print):
    V.ClipDS = lambda df, cache_, seed_=0: ClipDS5(df, cache_, hard, seed_)
    try: return V.train(model, tr, cache, epochs=STAGE2_EPOCHS, lr=STAGE2_LR, log=log, seed=seed + 1)
    finally: V4.install()


# ------------------------------------------------------------ threshold-free extras + false-alarm proxy
def window_metrics(probs, df):
    from sklearn.metrics import average_precision_score, roc_auc_score
    y, s = [], []
    for _, r in df.iterrows():
        t, p = probs[r["path"]]; ta = float(r["accident_time"])
        for tt, pp in zip(t, p):
            lab = V.window_label(tt, ta)
            if lab >= 0: y.append(lab); s.append(float(pp))
    return {"windows": len(y), "positives": int(sum(y)), "AUROC": float(roc_auc_score(y, s)), "AP": float(average_precision_score(y, s))}


def false_alarm(probs, df, rule):
    return F.false_alarm_summary([F.pre_impact(*probs[r["path"]], float(r["accident_time"]), rule) for _, r in df.iterrows() if len(probs[r["path"]][0])])


# ------------------------------------------------------------ protocol
def run_protocol5(real, cache, split_col, out_dir, stage1=None, epochs=4, seed=0, log=print, model_fn=V.build_model):
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True); V4.install()
    tr_all = real[real[split_col] == "train"]; te = real[real[split_col] == "test"]
    tr, va = A.split_train_val(tr_all, "path", seed=seed); log(f"[{split_col}] train {len(tr)} val {len(va)} test {len(te)} | K={V4.K_LOCAL}")
    torch.manual_seed(seed)
    model = stage1 if stage1 is not None else V.train(model_fn(), tr, cache, epochs=epochs, log=log, seed=seed)     # stage 1 (V4 recipe)
    hard = mine(model, tr, cache, log=log)
    model = stage2(model, tr, cache, hard, seed=seed, log=log)
    cfg = choose5(V4.clip_probs(model, va, cache), va)
    log(f" CHOSEN on validation: thr {cfg['thr']} k/n {cfg['k']}/{cfg['n']} delta {cfg['delta']} feasible {cfg['feasible']} val {cfg['val']}")
    (out / f"chosen_v5_{split_col}.json").write_text(json.dumps({**cfg, "K_LOCAL": V4.K_LOCAL, "hard_negatives": sum(len(v) for v in hard.values())}, indent=1, default=str))
    probs = V4.clip_probs(model, te, cache)                                              # test scored ONCE
    m, d = evaluate5(probs, te, cfg["thr"], cfg["k"], cfg["n"], cfg["delta"])
    res = {"split": split_col, "thr": cfg["thr"], "k": cfg["k"], "n": cfg["n"], "delta": cfg["delta"], "K_LOCAL": V4.K_LOCAL, "val": cfg["val"], "test": m,
           "window_metrics": window_metrics(probs, te), "false_alarm": false_alarm(probs, te, cfg), "breakdown": A.breakdown(d, te, "path"),
           "hard_negatives": sum(len(v) for v in hard.values())}
    (out / f"results_v5_{split_col}.json").write_text(json.dumps(res, indent=1, default=str)); return res, model, probs


def verdict5(res_in, res_geo, auroc_ref_geo):
    a, g = res_in["test"], res_geo["test"]; bd = res_geo["breakdown"]["scene_layout"].get("highway", {"detect": 0})["detect"]
    fa = res_geo["false_alarm"]["runs_per_hour"]; au = res_geo["window_metrics"]["AUROC"]
    rows = [("I1 in-dist detect >= 72%", a["B1_detect_within_10s"], a["B1_detect_within_10s"] >= .72),
            ("I2 in-dist early <= 5%", a["B2_early_alarm"], a["B2_early_alarm"] <= .05),
            ("I3 in-dist strict >= 66%", a["strict_detect_no_early"], a["strict_detect_no_early"] >= .66),
            ("I4 in-dist median delay <= 5 s", a["B3_median_delay_s"], a["B3_median_delay_s"] is not None and a["B3_median_delay_s"] <= 5),
            ("G1 geo detect >= 64%", g["B1_detect_within_10s"], g["B1_detect_within_10s"] >= .64),
            ("G2 geo early <= 5%", g["B2_early_alarm"], g["B2_early_alarm"] <= .05),
            ("G3 geo strict >= 60%", g["strict_detect_no_early"], g["strict_detect_no_early"] >= .60),
            ("G4 geo highway detect >= 52%", bd, bd >= .52),
            ("G5 geo false-alarm proxy < 48 runs/h", fa, fa < 48)]
    adopt = rows[4][2] and rows[5][2] and rows[6][2] and au >= auroc_ref_geo
    return rows, {"geo_AUROC_v5": au, "geo_AUROC_v4": auroc_ref_geo, "ADOPT_V5": bool(adopt)}

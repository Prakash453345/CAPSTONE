"""V6: ensemble of V5-recipe members (see TARGETS_VIDEO_V6_LOCKED.md).
Members record per-view window scores once (`dump`); the ensemble analysis (`analyse`) runs on CPU from those dumps and
touches the test split only for the one configuration chosen on validation."""
from __future__ import annotations
import json, pathlib, pickle, random
import numpy as np, pandas as pd, torch
import m8_accident_video as V
import m8_accident_video4 as V4
import m8_accident_train_v2 as A
import m8_accident_false_alarm as F
import m8_accident_video5 as V5

K = 3                                    # crops per window (V5's choice)
VAL_EARLY_CAP = 0.03                     # locked in TARGETS_VIDEO_V6_LOCKED.md
V5_PUBLISHED = {"thr": 0.85, "k": 3, "n": 5, "detect": 0.6764, "tol": 0.005}
REF = {"V4_proxy": 64.7, "V5_auroc": 0.815}


# ------------------------------------------------------------ per-view scores of one model
@torch.no_grad()
def dump(model, df, cache, device=None, bs=12, log=print):
    """{path: (window times, S)} with S (n_windows, 1 + K): global view first, then the motion-peak crops (NaN where a window has fewer)."""
    V4.install(); V5.set_k(K)
    device = device or next(model.parameters()).device; model.eval(); out = {}
    for j, (_, r) in enumerate(df.iterrows()):
        c = V4.Clip(cache[A.clip_key(r["path"])]); ends = V.window_ends(c.n()); items, owner, slot = [], [], []
        for w, e in enumerate(ends):
            for s, v in enumerate([None] + V4.proposals(c.heat(e), c.w, c.h)):
                items.append(V4.make_view(c, e, v)); owner.append(w); slot.append(s)
        S = np.full((len(ends), 1 + K), np.nan, np.float32)
        for i in range(0, len(items), bs):
            with torch.autocast(device_type="cuda", enabled=str(device).startswith("cuda")):
                q = torch.sigmoid(V.logits(model, V.to_input(torch.from_numpy(np.stack(items[i:i + bs])), device)).float()).cpu().numpy()
            for qq, w, s in zip(q, owner[i:i + bs], slot[i:i + bs]): S[w, s] = qq
        out[r["path"]] = (np.array([c.t[e] for e in ends]), S); c._fc.clear()
        if j % 200 == 0: log(f"  dumped {j}/{len(df)}")
    return out


def save_dump(d, path):
    with open(path, "wb") as f: pickle.dump(d, f, protocol=4)


def load_dump(path):
    with open(path, "rb") as f: return pickle.load(f)


# ------------------------------------------------------------ training one member (V5 recipe, different training seed)
def train_member(real, cache, train_seed, epochs=4, log=print, model_fn=V.build_model):
    V4.install(); V5.set_k(K)
    tr_all = real[real["split_geo_aware"] == "train"]
    tr, va = A.split_train_val(tr_all, "path", seed=0)           # SAME partition as V4 / V5 whatever the training seed
    torch.manual_seed(train_seed); random.seed(train_seed); np.random.seed(train_seed)
    model = V.train(model_fn(), tr, cache, epochs=epochs, log=log, seed=train_seed)
    hard = V5.mine(model, tr, cache, log=log)
    model = V5.stage2(model, tr, cache, hard, seed=train_seed, log=log)
    return model, tr, va


def member_dumps(model, real, cache, log=print):
    """Validation and test per-view scores of one member (nothing is thresholded here)."""
    tr_all = real[real["split_geo_aware"] == "train"]; te = real[real["split_geo_aware"] == "test"]
    _, va = A.split_train_val(tr_all, "path", seed=0)
    return {"val": dump(model, va, cache, log=log), "test": dump(model, te, cache, log=log)}


# ------------------------------------------------------------ analysis (CPU, from dumps)
def member_probs(d, df):
    return {p: (d[p][0], np.nanmax(d[p][1], axis=1).astype(np.float32) if len(d[p][0]) else np.zeros(0, np.float32)) for p in df["path"]}


def ensemble_probs(ds, df):
    mp = [member_probs(d, df) for d in ds]
    return {p: (mp[0][p][0], np.mean([m[p][1] for m in mp], axis=0).astype(np.float32)) for p in df["path"]}


def _score(probs, df, cfg):
    m, d = A.evaluate(probs, df, "path", cfg["thr"], cfg["k"], cfg["n"])
    return m, d


def choose(probs_val, va):
    old = A.VAL_EARLY_CAP; A.VAL_EARLY_CAP = VAL_EARLY_CAP
    try: return A.choose_config(probs_val, va, "path")
    finally: A.VAL_EARLY_CAP = old


def sanity_v5(dump_v5_test, te):
    """M0 with V5's published configuration must reproduce V5's published test detect rate."""
    m, _ = A.evaluate(member_probs(dump_v5_test, te), te, "path", V5_PUBLISHED["thr"], V5_PUBLISHED["k"], V5_PUBLISHED["n"])
    ok = abs(m["B1_detect_within_10s"] - V5_PUBLISHED["detect"]) <= V5_PUBLISHED["tol"]
    return ok, m["B1_detect_within_10s"]


def analyse(real, dumps, log=print):
    """dumps: {member name: {"val": dump, "test": dump}}. The test split is scored for the ONE chosen configuration (plus
    the per-member context rows, each with its own validation-chosen configuration)."""
    tr_all = real[real["split_geo_aware"] == "train"]; te = real[real["split_geo_aware"] == "test"]
    _, va = A.split_train_val(tr_all, "path", seed=0)
    names = sorted(dumps)
    if "M0" in dumps:
        ok, got = sanity_v5(dumps["M0"]["test"], te); log(f"sanity: M0 + published V5 config -> test detect {got:.4f} ({'OK' if ok else 'MISMATCH - result void'})")
        if not ok: raise RuntimeError("M0 dump does not reproduce V5's published test result; the dump is wrong")
    cfg = choose(ensemble_probs([dumps[n]["val"] for n in names], va), va)
    log(f"ensemble {names}: CHOSEN on validation thr {cfg['thr']} k/n {cfg['k']}/{cfg['n']} feasible {cfg['feasible']} val {cfg['val']}")
    probs = ensemble_probs([dumps[n]["test"] for n in names], te)               # test scored ONCE for the chosen config
    m, d = _score(probs, te, cfg)
    res = {"members": names, "thr": cfg["thr"], "k": cfg["k"], "n": cfg["n"], "val": cfg["val"], "feasible": cfg["feasible"], "test": m,
           "window_metrics": V5.window_metrics(probs, te), "false_alarm": V5.false_alarm(probs, te, cfg), "breakdown": A.breakdown(d, te, "path")}
    ctx = {}
    for n in names:                                                              # context only
        c = choose(member_probs(dumps[n]["val"], va), va); mm, _ = _score(member_probs(dumps[n]["test"], te), te, c)
        ctx[n] = {"thr": c["thr"], "k": c["k"], "n": c["n"], "test": mm}
    res["members_alone"] = ctx
    return res


def verdict6(res):
    t = res["test"]; fa = res["false_alarm"]["runs_per_hour"]; au = res["window_metrics"]["AUROC"]
    hw = res["breakdown"]["scene_layout"].get("highway", {"detect": float("nan")})["detect"]
    rows = [("E1 geo detect >= 66%", t["B1_detect_within_10s"], t["B1_detect_within_10s"] >= .66),
            ("E2 geo early <= 5%", t["B2_early_alarm"], t["B2_early_alarm"] <= .05),
            ("E3 geo strict >= 61%", t["strict_detect_no_early"], t["strict_detect_no_early"] >= .61),
            ("E4 geo false-alarm proxy <= 64.7 runs/h", fa, fa <= REF["V4_proxy"]),
            ("E5 geo window AUROC >= 0.815", au, au >= REF["V5_auroc"])]
    return rows, {"adopt_ensemble": all(r[2] for r in rows), "highway_detect_reported": hw}

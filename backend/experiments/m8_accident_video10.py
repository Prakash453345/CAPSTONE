"""V10: does accident-free Indian footage as extra negatives lower false alarms on UNSEEN cameras? Leave-one-camera-group-out test (see TARGETS_CAMERA_GROUP_LOCKED.md).
Fine-tunes the V9 weights briefly on a benchmark replay plus accident-free windows from the other camera groups, with the V9 alarm rule fixed (nothing tuned on a held-out group)."""
from __future__ import annotations
import json, os, pathlib, random
import numpy as np, pandas as pd, torch
import m8_accident_video as V
import m8_accident_video4 as V4
import m8_accident_video5 as V5
import m8_accident_video8 as V8
import m8_accident_train_v2 as A
import m8_accident_false_alarm as F
import m8_accident_normal_check as N
import m8_accident_indian_suite as I

K = 3
LR, EPOCHS, BENCH_CLIPS, NEG_WINDOWS, CHUNK = 1e-5, 1, 600, 1500, 16     # fixed in advance, not tuned
GROUPS = {"airpix": ["normal_01"], "atcc": ["normal_02", "normal_03", "normal_04"], "pune": ["normal_05", "normal_11"], "hyderabad": ["normal_06"],
          "delhi": ["normal_07", "normal_08", "normal_09", "normal_10"], "tirupati_signal": ["accident_27", "accident_28"]}


def group_of(path):
    b = os.path.basename(path)
    for g, keys in GROUPS.items():
        if any(b.startswith(k + "_") for k in keys): return g
    return None


class NegDS(torch.utils.data.Dataset):
    """Chunks of CHUNK random windows from accident-free clips (label 0), random view per window; a clip gets windows in proportion to its length."""
    def __init__(self, paths, cache, seed=0, total=NEG_WINDOWS, chunk=CHUNK):
        self.cache, self.seed, self.chunk, self.items = cache, seed, chunk, []
        n = {p: max(0, V4.Clip(cache[A.clip_key(p)]).n() - V.NF + 1) for p in paths}; tot = max(1, sum(n.values()))
        for p in paths:
            if not n[p]: continue
            k = int(np.clip(round(total * n[p] / tot), chunk, 400)); self.items += [p] * int(np.ceil(k / chunk))
    def __len__(self): return len(self.items)
    def __getitem__(self, i):
        rng = random.Random(hash((self.seed, i, random.random()))); c = V4.Clip(self.cache[A.clip_key(self.items[i])])
        ends = list(range(V.NF - 1, c.n())); es = rng.sample(ends, min(self.chunk, len(ends))); xs = []
        for e in es: xs.append(V4.make_view(c, e, rng.choice([None] + V4.proposals(c.heat(e), c.w, c.h))))
        c._fc.clear(); return torch.from_numpy(np.stack(xs)), torch.zeros(len(xs))


class MixDS(torch.utils.data.Dataset):
    def __init__(self, bench_df, neg_paths, cache, seed=0):
        self.b = V8.ClipDS8(bench_df, cache, seed); self.n = NegDS(list(neg_paths), cache, seed) if len(neg_paths) else []
    def __len__(self): return len(self.b) + len(self.n)
    def __getitem__(self, i): return self.b[i] if i < len(self.b) else self.n[i - len(self.b)]


def finetune(model, bench_df, neg_paths, cache, epochs=EPOCHS, lr=LR, seed=0, log=print):
    V8.patch(); V4.install(); V5.set_k(K); torch.manual_seed(seed); random.seed(seed); np.random.seed(seed)
    V.ClipDS = lambda df, cache_, seed_=0: MixDS(bench_df, neg_paths, cache_, seed_)
    try: return V.train(model, bench_df, cache, epochs=epochs, lr=lr, log=log, seed=seed)
    finally: V4.install()


def summarise(sc, rule, acc, neg):
    """sc: window scores for (some of) the clips. -> accident metrics on `acc` present in sc, and per-clip accident-free (seconds, runs)."""
    a = [p for p in acc if p in sc]
    rows, summ = I.accident_report({p: sc[p] for p in a}, rule, 0) if a else (None, None)
    negs = {}
    for p in neg:
        if p in sc:
            t, s = sc[p]; negs[p] = (float(len(t)), len(F.alarm_runs(t, s, rule["thr"], rule["k"], rule["n"], rule.get("delta", 0.0))))
    return summ, negs


def pooled(negs_by_path):
    return F.false_alarm_summary([(e, r, r > 0) for e, r in negs_by_path.values()]) if negs_by_path else None


def run_cv(real, cache, clips, base_weights, out_dir, config=None, bench_clips=BENCH_CLIPS, log=print, do_final=True):
    """clips: all Indian suite clip paths (cache keys via A.clip_key). Returns the results dict (also written as json)."""
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True); rule = N.rule_for(base_weights); assert rule["K"] == K, rule
    acc = [p for p in clips if I.clip_no(p) in I.TIMES]; neg = [p for p in clips if p not in acc]; assert all(group_of(p) for p in neg), "unmapped accident-free clip"
    bench = real.sample(n=min(bench_clips, len(real)), random_state=0).reset_index(drop=True); res = {"rule": rule, "bench_clips": len(bench)}
    def load(): return N.load_model(base_weights, "cuda" if torch.cuda.is_available() else "cpu", config)
    def score(m, which): return I.window_scores(m, rule, which, cache, log=log)
    m = load(); sc = score(m, clips); del m; torch.cuda.empty_cache()
    res["base"] = summarise(sc, rule, acc, neg); log("base", res["base"][0] and {k: v for k, v in res["base"][0].items() if "ci" not in k}, pooled(res["base"][1]))
    m = finetune(load(), bench, [], cache, log=log); sc = score(m, clips); del m; torch.cuda.empty_cache()
    res["control"] = summarise(sc, rule, acc, neg); log("control (replay only)", pooled(res["control"][1]))
    held, fold_acc = {}, {}
    for g in GROUPS:
        train_neg = [p for p in neg if group_of(p) != g]; test_neg = [p for p in neg if group_of(p) == g]
        if not test_neg: continue
        m = finetune(load(), bench, train_neg, cache, log=log); sc = score(m, acc + test_neg); del m; torch.cuda.empty_cache()
        s, negs = summarise(sc, rule, acc, test_neg); held.update(negs); fold_acc[g] = s
        base_g = pooled({p: res["base"][1][p] for p in test_neg}); new_g = pooled(negs)
        res.setdefault("groups", {})[g] = {"clips": [os.path.basename(p) for p in test_neg], "base_runs_per_h": base_g["runs_per_hour"], "heldout_runs_per_h": new_g["runs_per_hour"], "base_runs": base_g["runs"], "heldout_runs": new_g["runs"],
                                            "seconds": new_g["exposure_hours"] * 3600, "accident": s}
        log(g, res["groups"][g]); (out / "results_partial.json").write_text(json.dumps(res, indent=1, default=str))
    res["heldout_pooled"] = pooled(held); res["base_pooled"] = pooled(res["base"][1]); res["control_pooled"] = pooled(res["control"][1])
    res["fold_accident_mean"] = {k: float(np.mean([fold_acc[g][k] for g in fold_acc])) for k in ("detect", "early", "strict")}
    if do_final:
        m = finetune(load(), bench, neg, cache, log=log); torch.save({k: (v.half() if v.is_floating_point() else v).cpu() for k, v in m.state_dict().items()}, out / "itms_accident_v10.pt")
        json.dump({**{k: rule[k] for k in ("thr", "k", "n", "delta")}, "K_LOCAL": K, "note": "V9 + accident-free Indian windows from all 6 camera groups; not scored on any held-out camera"}, open(out / "itms_accident_v10.json", "w"), indent=1)
    (out / "results_v10_camera_group_cv.json").write_text(json.dumps(res, indent=1, default=str)); return res


def verdict(res):
    g = res["groups"]; hp, bp = res["heldout_pooled"], res["base_pooled"]; better = sum(v["heldout_runs_per_h"] < v["base_runs_per_h"] for v in g.values())
    rows = [("L1 pooled held-out false alarms <= half of base", hp["runs_per_hour"], hp["runs_per_hour"] <= 0.5 * bp["runs_per_hour"]),
            ("L2a mean accident detect over fold models >= 70%", res["fold_accident_mean"]["detect"], res["fold_accident_mean"]["detect"] >= 0.70),
            ("L2b mean accident early <= 25%", res["fold_accident_mean"]["early"], res["fold_accident_mean"]["early"] <= 0.25),
            ("L3 held-out rate below base in >= 4 of 6 groups", better, better >= 4)]
    return rows, {"all_pass": all(r[2] for r in rows), "groups_better": better, "base_runs_per_h": bp["runs_per_hour"], "control_runs_per_h": res["control_pooled"]["runs_per_hour"]}

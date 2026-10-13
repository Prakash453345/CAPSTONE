"""Zero-shot VLM window scorer for the ACCIDENT benchmark (see TARGETS_VLM_LOCKED.md)."""
from __future__ import annotations
import json, math, os, pathlib, random
import numpy as np, pandas as pd

MODEL_ID = os.environ.get("ACC_VLM", "Qwen/Qwen2.5-VL-7B-Instruct")
WIN_S, STRIDE_S, NFR, MAXSIDE, EXTRA_S, DETECT_WITHIN_S = 6.0, 3.0, 8, 448, 10.0, 10.0
PROMPTS = {
    "P1": "This is a clip from a traffic surveillance camera. Does a vehicle collision or crash happen in this clip? Answer Yes or No.",
    "P2": "Look at the road users in this traffic camera clip. Is there a traffic accident, such as vehicles hitting each other, hitting an object, or a vehicle or rider falling? Answer Yes or No.",
}
THRS = [0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 0.98]


# ---------------------------------------------------------------- pure helpers
def plan_windows(ta, dur):
    """Window (start, end) pairs covering [0, ta + EXTRA_S]; the end bound only limits compute."""
    stop = min(dur, ta + EXTRA_S); out = []; s = 0.0
    while s + 1e-6 < stop:
        e = min(s + WIN_S, dur)
        if e - s >= 2.0: out.append((round(s, 2), round(e, 2)))
        if e >= stop - 1e-6: break
        s += STRIDE_S
    return out


def score_windows(wins, probs, thr, ta):
    ends = [e for (s, e), p in zip(wins, probs) if p >= thr]
    post = [e for e in ends if ta <= e <= ta + DETECT_WITHIN_S]
    return dict(early=any(e < ta for e in ends), detected=bool(post), delay=(post[0] - ta) if post else None,
                n_early=sum(1 for e in ends if e < ta))


def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def summarise(per_clip):
    n = len(per_clip); det = sum(d["detected"] for d in per_clip); ear = sum(d["early"] for d in per_clip)
    dl = [d["delay"] for d in per_clip if d["delay"] is not None]
    return dict(n=n, detect=det / n, detect_ci=wilson(det, n), early=ear / n, early_ci=wilson(ear, n),
                median_delay_s=float(np.median(dl)) if dl else None)


def run(cache, df, prompt, thr):
    out = []
    for _, r in df.iterrows():
        c = cache[prompt][r["path"]]; out.append(score_windows(c["wins"], c["p"], thr, float(r["accident_time"])))
    return out


def choose(cache, val):
    best = None
    for pr in PROMPTS:
        for thr in THRS:
            m = summarise(run(cache, val, pr, thr)); feas = m["early"] <= 0.05
            key = (feas, m["detect"] if feas else m["detect"] - 2 * m["early"])
            if best is None or key > best[0]: best = (key, dict(prompt=pr, thr=thr), m, feas)
    return {**best[1], "val": best[2], "feasible_on_val": best[3]}


def pick_clips(real, seed=0, n_val=100, n_test=300):
    A, G = "split_in_distribution", "split_geo_aware"
    val = real[(real[A] == "train") & (real[G] == "train")]
    val = val.sample(n=min(n_val, len(val)), random_state=seed)
    ta = real[real[A] == "test"].sample(n=n_test, random_state=seed)
    tg = real[real[G] == "test"].sample(n=n_test, random_state=seed)
    return val, ta, tg


def verdict(a, g):
    def ok(v, bar, up=True): return v is not None and (v >= bar if up else v <= bar)
    def tag(p, lo, hi, bar, up=True):
        if not ok(p, bar, up): return "FAIL"
        return "PASS" if ok(lo if up else hi, bar, up) else "MARGINAL"
    return [("B1 detect<=10s (in-dist) >=0.70", a["detect"], tag(a["detect"], a["detect_ci"][0], a["detect_ci"][1], 0.70)),
            ("B2 early (in-dist) <=0.05", a["early"], tag(a["early"], a["early_ci"][0], a["early_ci"][1], 0.05, False)),
            ("B3 median delay <=5s", a["median_delay_s"], "PASS" if ok(a["median_delay_s"], 5.0, False) else "FAIL"),
            ("B4 geo detect >=0.60", g["detect"], tag(g["detect"], g["detect_ci"][0], g["detect_ci"][1], 0.60)),
            ("B4 geo early <=0.08", g["early"], tag(g["early"], g["early_ci"][0], g["early_ci"][1], 0.08, False))]


# ---------------------------------------------------------------- video + model (Colab GPU)
def read_frames(path, fps=2.0):
    import cv2
    cap = cv2.VideoCapture(str(path)); src = cap.get(cv2.CAP_PROP_FPS) or 15.0; step = max(1, int(round(src / fps)))
    fr, ts, i = [], [], 0
    while True:
        ok = cap.grab()
        if not ok: break
        if i % step == 0:
            ok, f = cap.retrieve()
            if ok:
                h, w = f.shape[:2]; s = MAXSIDE / max(h, w)
                if s < 1: f = cv2.resize(f, (int(w * s) // 28 * 28 or 28, int(h * s) // 28 * 28 or 28))
                else: f = cv2.resize(f, (w // 28 * 28 or 28, h // 28 * 28 or 28))
                fr.append(f[:, :, ::-1]); ts.append(i / src)
        i += 1
    cap.release(); return np.stack(fr), np.array(ts), (i / src)


def load_model():
    import torch
    from transformers import AutoProcessor, BitsAndBytesConfig
    try: from transformers import Qwen2_5_VLForConditionalGeneration as M
    except ImportError: from transformers import AutoModelForVision2Seq as M
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, bnb_4bit_quant_type="nf4")
    model = M.from_pretrained(MODEL_ID, quantization_config=q, device_map="auto", torch_dtype=torch.float16).eval()
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    tok = proc.tokenizer; yes = [tok.encode(x, add_special_tokens=False)[0] for x in ("Yes", "yes")]; no = [tok.encode(x, add_special_tokens=False)[0] for x in ("No", "no")]
    return model, proc, yes, no


def p_yes(model, proc, yes, no, frames, prompt):
    import torch
    msgs = [{"role": "user", "content": [{"type": "video"}, {"type": "text", "text": prompt}]}]
    text = proc.apply_chat_template(msgs, add_generation_prompt=True)
    inp = proc(text=[text], videos=[frames], return_tensors="pt", padding=True).to(model.device)
    with torch.no_grad(): lg = model(**inp).logits[0, -1].float()
    ly = torch.logsumexp(lg[yes], 0); ln = torch.logsumexp(lg[no], 0)
    return float(torch.sigmoid(ly - ln))


def score_clip_windows(model_bundle, path, ta, prompts=tuple(PROMPTS)):
    model, proc, yes, no = model_bundle
    fr, ts, dur = read_frames(path); wins = plan_windows(ta, dur); res = {p: [] for p in prompts}
    for s, e in wins:
        idx = np.where((ts >= s) & (ts < e))[0]
        if len(idx) < 2: idx = np.arange(max(0, len(ts) - 2), len(ts))
        pick = idx[np.linspace(0, len(idx) - 1, NFR).round().astype(int)]
        for p in prompts: res[p].append(p_yes(model, proc, yes, no, fr[pick], PROMPTS[p]))
    return wins, res

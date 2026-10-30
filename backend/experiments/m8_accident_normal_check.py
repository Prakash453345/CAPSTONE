"""False alarms on ordinary (accident-free) footage: how often does each accident model raise an alarm per camera-hour?
Nothing is trained or tuned here. Each clip must be accident-free; each window scored = one second of footage (the same exposure unit as the benchmark's
false-alarm proxy). Per-view scores are dumped once per model with K = 3 crops; a K = 2 model (V4) uses the global view and the first two crops, which is exactly
what it computes in the app because crops are picked greedily from the same motion map."""
from __future__ import annotations
import json, pathlib
import numpy as np, pandas as pd, torch
import m8_accident_video as V
import m8_accident_video6 as V6
import m8_accident_false_alarm as F


def load_model(weights, device="cuda", config=None):
    from transformers import VideoMAEConfig, VideoMAEForVideoClassification
    m = VideoMAEForVideoClassification(config or VideoMAEConfig(num_labels=1)); sd = torch.load(weights, map_location="cpu")
    m.load_state_dict({k: v.float() if v.is_floating_point() else v for k, v in sd.items()}); m.gradient_checkpointing_enable()
    return m.to(device if torch.cuda.is_available() else "cpu").eval()


def rule_for(weights):
    cfg = json.loads(pathlib.Path(weights).with_suffix(".json").read_text())
    return {"thr": float(cfg["thr"]), "k": int(cfg["k"]), "n": int(cfg["n"]), "delta": float(cfg.get("delta", 0.0)), "K": int(cfg.get("K_LOCAL", 2))}


def check(model, rule, clips, cache, log=print):
    """clips: list of clip paths (keys of `cache`). -> dict with the summary, per-clip rows and the highest-scoring windows."""
    df = pd.DataFrame({"path": list(clips)}); d = V6.dump(model, df, cache, log=log); rows, wins, per_clip = [], [], []
    for p in df["path"]:
        t, S = d[p]
        if not len(t): rows.append({"clip": p, "windows": 0, "runs": 0, "max_score": None, "alarm_times_s": []}); continue
        s = np.nanmax(S[:, :1 + rule["K"]], axis=1).astype(float)
        runs = F.alarm_runs(t, s, rule["thr"], rule["k"], rule["n"], rule["delta"])
        per_clip.append((float(len(t)), len(runs), bool(runs)))                      # exposure: one window = one second
        rows.append({"clip": p, "windows": int(len(t)), "runs": len(runs), "max_score": float(s.max()), "alarm_times_s": [round(float(r), 2) for r in runs]})
        wins += [(float(x), p, round(float(tt), 2)) for x, tt in zip(s, t)]
    wins.sort(reverse=True)
    return {"rule": rule, "summary": F.false_alarm_summary(per_clip) if per_clip else None, "clips": rows, "top_windows": [{"score": round(a, 3), "clip": b, "t_s": c} for a, b, c in wins[:15]]}

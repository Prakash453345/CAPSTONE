"""'V9': the V8 recipe trained on ALL labelled clips (see PROCEDURE_VIDEO_V9_ALL_DATA_LOCKED.md). No test split is scored; validation only."""
from __future__ import annotations
import json, pathlib, random
import numpy as np, torch
import m8_accident_video as V
import m8_accident_video4 as V4
import m8_accident_video5 as V5
import m8_accident_video8 as V8
import m8_accident_train_v2 as A

K = 3
VAL_EARLY_CAP = 0.03


def run9(real, cache, out_dir, epochs=4, log=print, model_fn=None, expect_clips=2027):
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    if expect_clips: assert len(real) == expect_clips, f"expected {expect_clips} clips, got {len(real)}"
    V8.patch(); V4.install(); V5.set_k(K); assert V.ClipDS is V8.ClipDS8 and V5.ClipDS5 is V8.ClipDS8Hard
    tr, va = A.split_train_val(real, "path", seed=0); log(f"[all data] train {len(tr)} val {len(va)} (no test split)")
    torch.manual_seed(0); random.seed(0); np.random.seed(0)
    model = V.train((model_fn or V.build_model)(), tr, cache, epochs=epochs, log=log, seed=0)
    torch.save({k: (v.half() if v.is_floating_point() else v).cpu() for k, v in model.state_dict().items()}, out / "stage1_checkpoint.pt")
    hard = V5.mine(model, tr, cache, log=log); model = V5.stage2(model, tr, cache, hard, seed=0, log=log)
    probs = V4.clip_probs(model, va, cache)
    old = A.VAL_EARLY_CAP; A.VAL_EARLY_CAP = VAL_EARLY_CAP
    try: cfg = V5.choose5(probs, va)
    finally: A.VAL_EARLY_CAP = old
    log(f" CHOSEN on validation: thr {cfg['thr']} k/n {cfg['k']}/{cfg['n']} delta {cfg['delta']} feasible {cfg['feasible']} val {cfg['val']}")
    m, d = V5.evaluate5(probs, va, cfg["thr"], cfg["k"], cfg["n"], cfg["delta"])
    res = {"train_clips": len(tr), "val_clips": len(va), "thr": cfg["thr"], "k": cfg["k"], "n": cfg["n"], "delta": cfg["delta"], "feasible": cfg["feasible"], "K_LOCAL": K,
           "val": m, "window_metrics_val": V5.window_metrics(probs, va), "false_alarm_val": V5.false_alarm(probs, va, cfg), "breakdown_val": A.breakdown(d, va, "path"),
           "hard_negatives": sum(len(v) for v in hard.values()), "note": "validation only; no test split; not a performance estimate"}
    (out / "results_v9_validation.json").write_text(json.dumps(res, indent=1, default=str))
    return res, model

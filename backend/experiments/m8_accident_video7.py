"""V7: V5 recipe started from the self-supervised VideoMAE-base (see TARGETS_VIDEO_V7_LOCKED.md).
Nothing new is modelled here: the backbone comes from the ACC_VID environment variable (set BEFORE importing m8_accident_video),
stage 1 is 6 epochs, everything else is run_protocol5 (hard-negative stage, K=3 crops, delta grid, validation-chosen alarm, test scored once)."""
from __future__ import annotations
import os
import m8_accident_video as V
import m8_accident_video4 as V4
import m8_accident_video5 as V5
import m8_accident_video6 as V6

BACKBONE = "MCG-NJU/videomae-base"
K = 3                      # V5's measured choice, not re-chosen
STAGE1_EPOCHS = 6          # the one locked deviation from V5 (4)


def check_backbone(model_id=None):
    """Void-the-run guard: the encoder and embedding weights must load from the checkpoint (only the new head / fc_norm may be missing)."""
    from transformers import VideoMAEForVideoClassification
    mid = model_id or V.MODEL_ID
    _, info = VideoMAEForVideoClassification.from_pretrained(mid, num_labels=1, ignore_mismatched_sizes=True, output_loading_info=True)
    missing = sorted(info.get("missing_keys", []))
    bad = [k for k in missing if "encoder" in k or "embeddings" in k]
    if bad: raise RuntimeError(f"{mid}: encoder / embedding weights NOT loaded: {bad[:5]} ... ({len(bad)} keys); result would be void")
    return {"model_id": mid, "missing_keys": missing, "unexpected": len(info.get("unexpected_keys", [])), "mismatched": len(info.get("mismatched_keys", []))}


def run7(real, cache, out_dir, epochs=STAGE1_EPOCHS, log=print, model_fn=None):
    V4.install(); V5.set_k(K)
    return V5.run_protocol5(real, cache, "split_geo_aware", out_dir, stage1=None, epochs=epochs, seed=0, log=log, model_fn=model_fn or V.build_model)


def verdict7(res):
    rows, extra = V6.verdict6(res)
    rows = [(r[0].replace("E", "H", 1), r[1], r[2]) for r in rows]
    return rows, {"adopt_v7": bool(extra["adopt_ensemble"]), "highway_detect_reported": extra["highway_detect_reported"]}

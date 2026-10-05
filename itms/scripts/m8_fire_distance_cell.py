# ---- How far is validation from training? Recall of the v5 thresholds on "unseen-scene" validation images ----
# Diagnostic only. Nothing is chosen or trained. D-Fire test images are only fingerprinted (distances to training), never scored here.
assert "choice" in report, "fire_report.json with the v5 Step 1 choice is not in the Drive folder " + OUT
TF, TS = report["choice"]["chosen"]["t_fire"], report["choice"]["chosen"]["t_smoke"]
T1 = report["choice"]["single_threshold_best"]["t_fire"]
BUCKETS = [("0-40 bits (near-copy of a training image)", 0, 40), ("41-72 bits (probably the same video)", 41, 72), (">72 bits (an unseen scene)", 73, 256)]
vp_, vhas_, vblr_ = split_table("val")
vstem_ = [os.path.basename(p)[:-4] for p in vp_]
vs_ = scores(vp_)
tr_idx_ = [i for i in range(len(TV_STEM)) if TV_SPLIT[i] == "train" and not str(TV_STEM[i]).startswith(("blr_", "blrh_", "blrp_"))]
trfp_ = TV_FP[tr_idx_]
vfp_ = np.stack([TV_FP[FP_BY[("val", s)]] for s in vstem_])
dval_ = hamming_min(vfp_, trfp_)
al_ = (vs_[:, 0] >= TF) | (vs_[:, 1] >= TS)
al1_ = (vs_[:, 0] >= T1) | (vs_[:, 1] >= T1)
pos_ = vhas_.any(1) & ~vblr_
neg_ = ~vhas_.any(1) & ~vblr_
rows_ = []
for name, lo, hi in BUCKETS:
    m = (dval_ >= lo) & (dval_ <= hi)
    rows_.append({"bucket": name, "positives": int((m & pos_).sum()), "recall_v5": round(float(al_[m & pos_].mean()), 4) if (m & pos_).any() else None,
                  "recall_single_0.36": round(float(al1_[m & pos_].mean()), 4) if (m & pos_).any() else None,
                  "negatives": int((m & neg_).sum()), "negative_alarms_v5": round(float(al_[m & neg_].mean()), 4) if (m & neg_).any() else None})
# the same distances for the D-Fire TEST images (distribution only; no test score is computed here)
tp_, thas_, tblr_ = split_table("test")
tfp_ = np.stack([dhash16(cv2.imread(p)) for p in tp_])
dtest_ = hamming_min(tfp_, trfp_)
q = [10, 25, 50, 75, 90]
dist = {"thresholds": {"fire": TF, "smoke": TS}, "val_positives": int(pos_.sum()), "test_images": int(len(tp_)),
        "buckets_on_validation": rows_,
        "distance_to_nearest_training_image_percentiles": {"percentiles": q,
            "validation_positives": [int(v) for v in np.percentile(dval_[pos_], q)],
            "test_positives": [int(v) for v in np.percentile(dtest_[thas_.any(1)], q)]},
        "share_over_72_bits": {"validation_positives": round(float((dval_[pos_] > 72).mean()), 3),
                               "test_positives": round(float((dtest_[thas_.any(1)] > 72).mean()), 3)}}
report["val_distance"] = dist
json.dump(dist, open(f"{OUT}/val_distance.json", "w"), indent=1)
# the stems of validation images that are an unseen scene, for use as a stricter validation set later
json.dump(sorted(s for s, d in zip(vstem_, dval_) if d > 72), open(f"{OUT}/val_unseen_scene_stems.json", "w"))
print(json.dumps(dist, indent=1))

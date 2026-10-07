# ---- Step 2: image scores (detector candidates x classifier) and the choice of (p_fire, p_smoke), on VALIDATION only ----
import math

def image_scores2(paths, cands=None):
    """Per image: highest P(fire) over fire candidates and highest P(smoke) over smoke candidates (0 if none)."""
    out = np.zeros((len(paths), 2), np.float32)
    for s in range(0, len(paths), 32):
        chunk = paths[s:s + 32]
        cd = candidates(chunk) if cands is None else cands[s:s + 32]
        crops, owner = [], []
        for j, (p, cl) in enumerate(zip(chunk, cd)):
            if not cl:
                continue
            img = cv2.imread(p)
            for c in cl:
                crops.append(crop_box(img, c[2:]))
                owner.append((s + j, c[0]))
        if crops:
            pr = crop_probs(np.stack(crops))
            for (i, c), pp in zip(owner, pr):
                out[i, c] = max(out[i, c], pp[c])
    return out

def alarm2(sc, pf=None, ps=None):
    pf, ps = PF if pf is None else pf, PS if ps is None else ps
    return (sc[:, 0] >= pf) | (sc[:, 1] >= ps)

if "choice" not in r2:
    vp, vhas, vblr = split_table("val")
    vstem = [os.path.basename(p)[:-4] for p in vp]
    vs = image_scores2(vp, pickle.load(open(f"{S2}/cand_val.pkl", "rb")))
    vpos = vhas.any(1) & ~vblr
    tr_idx = [i for i in range(len(TV_STEM)) if TV_SPLIT[i] == "train" and not str(TV_STEM[i]).startswith(("blr_", "blrh_", "blrp_"))]
    trfp = TV_FP[tr_idx]
    pos_idx = np.where(vpos)[0]
    vfp = np.stack([TV_FP[FP_BY[("val", vstem[i])]] for i in pos_idx])
    dist = hamming_min(vfp, trfp)
    keep = pos_idx[dist > NEAR_DUP_BITS]
    n_before, n_after = len(pos_idx), len(keep)
    print(f"validation images with fire or smoke (not Bengaluru): {n_before}; after removing near-copies of training: {n_after}")
    assert n_after >= MIN_RECALL_IMAGES, f"STOP: only {n_after} validation images with fire or smoke are left; no honest choice"
    dneg = np.where(~vhas.any(1) & ~vblr)[0]
    nbl = int(vblr.sum())
    max_fa = int(math.floor(FA_TARGET * nbl))
    rows = []
    for pf in GRID2:
        af = vs[:, 0] >= pf
        for ps in GRID2:
            al = af | (vs[:, 1] >= ps)
            rows.append((float(al[keep].mean()), -float(al[dneg].mean()) if len(dneg) else 0.0, pf + ps, pf, ps, int(al[vblr].sum())))
    ok_rows = [r for r in rows if r[5] <= max_fa]
    assert ok_rows, f"no pair keeps Bengaluru validation false alarms at or under {max_fa} frames"
    best = max(ok_rows)
    mk = lambda r: {"p_fire": r[3], "p_smoke": r[4], "val_recall": r[0], "val_fa_dfire_negatives": -r[1], "bengaluru_val_alarms": r[5]}
    # recall by distance to training on validation (reported)
    dall = hamming_min(np.stack([TV_FP[FP_BY[("val", s)]] for s in vstem]), trfp)
    al_b = alarm2(vs, best[3], best[4])
    by_d = {}
    for name, lo, hi in (("near-copy 0-40", 0, 40), ("same video 41-72", 41, 72), ("unseen scene >72", 73, 256)):
        m = (dall >= lo) & (dall <= hi) & vpos
        by_d[name] = {"positives": int(m.sum()), "recall": round(float(al_b[m].mean()), 4) if m.any() else None}
    r2["choice"] = {"rule": "max recall on validation images with fire or smoke (near-copies of training removed) subject to "
                            f"Bengaluru validation alarms <= {max_fa} of {nbl}; ties: fewer D-Fire-negative alarms, larger sum",
                    "validation_positives_before_dedupe": n_before, "validation_positives_used": n_after,
                    "bengaluru_val_frames": nbl, "max_alarms": max_fa, "chosen": mk(best),
                    "top10": [mk(r) for r in sorted(ok_rows, reverse=True)[:10]], "recall_by_distance_to_training": by_d}
    save_r2()
CH2 = r2["choice"]
PF, PS = CH2["chosen"]["p_fire"], CH2["chosen"]["p_smoke"]
print("chosen (validation):", json.dumps(CH2["chosen"]))
print("recall by distance to training (validation, reported):", json.dumps(CH2["recall_by_distance_to_training"]))

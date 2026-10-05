# ---- Probe on VALIDATION images: lenient box matching, NMS variants, larger inference size ----
# Diagnostic only: nothing is trained; no test image is used. Each configuration re-chooses its own two thresholds on validation
# with the same rule as v5 Step 1 (Bengaluru validation alarms <= floor(0.003 x n); highest recall; ties: fewer alarms on other negatives),
# except that near-copy removal is skipped here, so the 640 row is the control for every other row.
CONFIGS = [("640, NMS IoU 0.7 (as now)", 640, 0.7, False), ("640, NMS IoU 0.5", 640, 0.5, False),
           ("640, NMS IoU 0.5, class-agnostic", 640, 0.5, True), ("960, NMS IoU 0.7", 960, 0.7, False),
           ("1280, NMS IoU 0.7", 1280, 0.7, False)]
vp_, vhas_, vblr_ = split_table("val")
mm = YOLO(PT)
GTS, SIZES = [], []
for p in vp_:
    h_, w_ = cv2.imread(p).shape[:2]
    GTS.append(read_gts(p.replace("/images/", "/labels/")[:-4] + ".txt", w_, h_))
    SIZES.append((w_, h_))

def lenient_hit(pb, gb):
    if iou_1toN(np.array(pb, float), np.array([gb], float))[0] >= 0.1:
        return True
    pc = ((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2); gc = ((gb[0] + gb[2]) / 2, (gb[1] + gb[3]) / 2)
    return (gb[0] <= pc[0] <= gb[2] and gb[1] <= pc[1] <= gb[3]) or (pb[0] <= gc[0] <= pb[2] and pb[1] <= gc[1] <= pb[3])

def bucket(a):
    return next(n for lo, hi, n in AREA_BINS if lo <= a < hi)

pos_img = vhas_.any(1) & ~vblr_
neg_other = ~vhas_.any(1) & ~vblr_
cap = int(np.floor(FA_TARGET * vblr_.sum()))
probe = {"images": int(len(vp_)), "bengaluru_val_frames": int(vblr_.sum()), "bengaluru_alarm_cap": cap, "rows": []}
for name, isz, nms_iou, agn in CONFIGS:
    t0 = time.time()
    P, M = [], np.zeros((len(vp_), 2), np.float32)
    for s in range(0, len(vp_), 16):
        for i, res in zip(range(s, min(s + 16, len(vp_))), mm.predict(vp_[s:s + 16], imgsz=isz, conf=0.05, iou=nms_iou, agnostic_nms=agn, verbose=False)):
            bx = res.boxes
            pr = [(int(c), float(cf), *xy) for c, cf, xy in zip(bx.cls.tolist(), bx.conf.tolist(), bx.xyxy.tolist()) if int(c) in (0, 1)]
            P.append(pr)
            for c, cf, *_ in pr:
                M[i, c] = max(M[i, c], cf)
    G = np.array(GRID)
    alarm = (M[:, 0][None, None, :] >= G[:, None, None]) | (M[:, 1][None, None, :] >= G[None, :, None])      # [tf, ts, image]
    blr_al = alarm[:, :, vblr_].sum(2); rec = alarm[:, :, pos_img].mean(2); fa = alarm[:, :, neg_other].mean(2)
    ok = blr_al <= cap
    best = None
    for a_ in range(len(G)):
        for b_ in range(len(G)):
            if ok[a_, b_]:
                key = (round(rec[a_, b_], 6), -fa[a_, b_], G[a_] + G[b_])
                if best is None or key > best[0]:
                    best = (key, a_, b_)
    row = {"config": name, "seconds": round(time.time() - t0)}
    if best is None:
        row["chosen"] = None
    else:
        _, a_, b_ = best
        row["chosen"] = {"t_fire": float(G[a_]), "t_smoke": float(G[b_]), "val_recall": round(float(rec[a_, b_]), 4),
                         "val_other_negative_alarms": round(float(fa[a_, b_]), 4), "bengaluru_val_alarms": int(blr_al[a_, b_])}
    af = alarm[GRID.index(0.44), GRID.index(0.11)]
    row["at_0.44_0.11"] = {"val_recall": round(float(af[pos_img].mean()), 4), "val_other_negative_alarms": round(float(af[neg_other].mean()), 4),
                           "bengaluru_val_alarms": int(af[vblr_].sum())}
    # lenient box recall by size, at (0.44, 0.11)
    miss = {0: Counter(), 1: Counter()}; tot = {0: Counter(), 1: Counter()}
    nfp = {0: 0, 1: 0}
    for i, (pr, gts) in enumerate(zip(P, GTS)):
        w_, h_ = SIZES[i]
        for g in gts:
            n_ = bucket(((g[3] - g[1]) * (g[4] - g[2])) / (w_ * h_)); tot[g[0]][n_] += 1
            if not any(p[0] == g[0] and p[1] >= THR[g[0]] and lenient_hit(p[2:], g[1:]) for p in pr):
                miss[g[0]][n_] += 1
        for p in pr:
            if p[1] >= THR[p[0]] and not any(g[0] == p[0] and lenient_hit(p[2:], g[1:]) for g in gts):
                nfp[p[0]] += 1
    row["lenient_box_miss_rate_by_size"] = {NAMES[k]: {n: (round(miss[k][n] / tot[k][n], 3) if tot[k][n] else None) for _, _, n in AREA_BINS} for k in (0, 1)}
    row["lenient_box_overall_miss_rate"] = {NAMES[k]: round(sum(miss[k].values()) / max(sum(tot[k].values()), 1), 3) for k in (0, 1)}
    row["boxes_with_no_object_near_them"] = {NAMES[k]: nfp[k] for k in (0, 1)}
    probe["rows"].append(row)
    print(json.dumps(row))
report["probe_val"] = probe
json.dump(probe, open(f"{OUT}/probe_val.json", "w"), indent=1)
# gallery of RANDOM false positives that sit on NO labelled object (kind 'background'), at the current setting; seeded
bgs = [e for e in FPS if e["kind"] == "background"]
rng2 = random.Random(SEED + 1)
pick = rng2.sample(bgs, min(30, len(bgs)))
montage([crop(e["img"], e["box"], f"{NAMES[e['cls']]} {e['conf']:.2f} {'BLR' if e['bengaluru'] else ''}") for e in pick], f"{OUT}/val_fp_background_random30.jpg")
print("background false positives:", len(bgs), "of", len(FPS))

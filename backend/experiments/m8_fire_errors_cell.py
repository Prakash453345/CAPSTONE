# ---- Error analysis on VALIDATION images (not test): where do the false positives and false negatives come from? ----
# Reported only. Thresholds come from fire_report.json; nothing is chosen or tuned here, and no test image is looked at.
assert "choice" in report, "fire_report.json with the v5 Step 1 choice is not in the Drive folder " + OUT
TF, TS = report["choice"]["chosen"]["t_fire"], report["choice"]["chosen"]["t_smoke"]
THR = {0: TF, 1: TS}
IOU_MATCH = 0.5
AREA_BINS = [(0, 0.001, "<0.1%"), (0.001, 0.01, "0.1-1%"), (0.01, 0.05, "1-5%"), (0.05, 0.2, "5-20%"), (0.2, 1.01, ">20%")]

def iou_1toN(b, bs):
    x1 = np.maximum(b[0], bs[:, 0]); y1 = np.maximum(b[1], bs[:, 1])
    x2 = np.minimum(b[2], bs[:, 2]); y2 = np.minimum(b[3], bs[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    ua = (b[2] - b[0]) * (b[3] - b[1]) + (bs[:, 2] - bs[:, 0]) * (bs[:, 3] - bs[:, 1]) - inter
    return inter / np.maximum(ua, 1e-9)

def read_gts(label_path, w, h):
    gts = []
    if os.path.exists(label_path):
        for line in open(label_path):
            q = line.split()
            if len(q) < 5:
                continue
            c, cx, cy, bw, bh = int(q[0]), *map(float, q[1:5])
            gts.append((c, (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
    return gts

def analyse_image(preds, gts):
    """preds (cls, conf, x1,y1,x2,y2) at conf >= 0.05; gts (cls, x1,y1,x2,y2).
    Returns (false positives, false negatives) at the alarm thresholds. A false positive is labelled:
    duplicate (a second box on an already-found object), wrong class (IoU >= 0.5 with the other class),
    poorly placed (0.1 <= IoU < 0.5 with a same-class object), background (no object there).
    A false negative records the best same-class score at IoU >= 0.5 (None: nothing even at 0.05) and the best other-class score."""
    fps, fns = [], []
    G = np.array([g[1:] for g in gts], float).reshape(-1, 4)
    GC = np.array([g[0] for g in gts], int)
    used = np.zeros(len(gts), bool)
    for p in sorted(preds, key=lambda x: -x[1]):
        k, cf, box = p[0], p[1], np.array(p[2:], float)
        if cf < THR[k]:
            continue
        io = iou_1toN(box, G) if len(G) else np.zeros(0)
        same = np.where(GC == k)[0]
        cand = [j for j in same if not used[j]]
        if cand and io[cand].max() >= IOU_MATCH:
            used[cand[int(io[cand].argmax())]] = True
            continue
        if len(same) and io[same].max() >= IOU_MATCH:
            kind = "duplicate"
        elif len(G) and io[GC != k].size and io[GC != k].max() >= IOU_MATCH:
            kind = "wrong class"
        elif len(same) and io[same].max() >= 0.1:
            kind = "poorly placed"
        else:
            kind = "background"
        fps.append({"cls": k, "conf": cf, "box": p[2:], "kind": kind})
    for j in np.where(~used)[0]:
        k = int(GC[j]); gb = G[j]
        best_same = max([p[1] for p in preds if p[0] == k and iou_1toN(np.array(p[2:], float), gb[None])[0] >= IOU_MATCH], default=None)
        best_other = max([p[1] for p in preds if p[0] != k and iou_1toN(np.array(p[2:], float), gb[None])[0] >= IOU_MATCH], default=None)
        fns.append({"cls": k, "box": [float(v) for v in gb], "best_same_score": best_same, "best_other_class_score": best_other})
    return fps, fns

if "errors_val" not in report:
    vp_, vhas_, vblr_ = split_table("val")
    mm = YOLO(PT)
    FPS, FNS, ALLGT, NGT = [], [], 0, {0: 0, 1: 0}
    imgsz = {}
    t0 = time.time()
    for s in range(0, len(vp_), 16):
        for i, res in zip(range(s, min(s + 16, len(vp_))), mm.predict(vp_[s:s + 16], imgsz=SIZE, conf=0.05, iou=0.7, verbose=False)):
            h_, w_ = res.orig_shape
            imgsz[i] = (w_, h_)
            bx = res.boxes
            preds = [(int(c), float(cf), *xy) for c, cf, xy in zip(bx.cls.tolist(), bx.conf.tolist(), bx.xyxy.tolist()) if int(c) in (0, 1)]
            gts = read_gts(vp_[i].replace("/images/", "/labels/")[:-4] + ".txt", w_, h_)
            for g in gts:
                NGT[g[0]] += 1
            fp, fn = analyse_image(preds, gts)
            for e in fp + fn:
                e["img"] = i
                e["area"] = ((e["box"][2] - e["box"][0]) * (e["box"][3] - e["box"][1])) / (w_ * h_)
                e["bengaluru"] = bool(vblr_[i])
            FPS += fp; FNS += fn
    print(f"scored {len(vp_)} validation images in {time.time() - t0:.0f}s")
    def bucket(a):
        return next(n for lo, hi, n in AREA_BINS if lo <= a < hi)
    summ = {"images": int(len(vp_)), "thresholds": {"fire": TF, "smoke": TS}, "gt_boxes": {NAMES[k]: NGT[k] for k in NGT},
            "false_positives": {}, "false_negatives": {}}
    for k in (0, 1):
        f = [e for e in FPS if e["cls"] == k]
        summ["false_positives"][NAMES[k]] = {
            "total": len(f), "by_kind": dict(Counter(e["kind"] for e in f)),
            "on_bengaluru_frames": sum(e["bengaluru"] for e in f),
            "by_size": {n: sum(1 for e in f if bucket(e["area"]) == n) for _, _, n in AREA_BINS},
            "conf_quartiles": [round(float(q), 3) for q in np.percentile([e["conf"] for e in f], [25, 50, 75])] if f else None}
        n_ = [e for e in FNS if e["cls"] == k]
        gtsz = Counter()
        for e in n_:
            gtsz[bucket(e["area"])] += 1
        summ["false_negatives"][NAMES[k]] = {
            "total": len(n_), "of_gt_boxes": NGT[k], "miss_rate": round(len(n_) / max(NGT[k], 1), 3),
            "nothing_found_even_at_0.05": sum(1 for e in n_ if e["best_same_score"] is None and e["best_other_class_score"] is None),
            "found_but_below_threshold": sum(1 for e in n_ if e["best_same_score"] is not None),
            "found_as_other_class": sum(1 for e in n_ if e["best_same_score"] is None and e["best_other_class_score"] is not None),
            "by_size": {n: gtsz.get(n, 0) for _, _, n in AREA_BINS}}
    # miss rate by size needs the size of ALL ground-truth boxes
    allsz = {0: Counter(), 1: Counter()}
    for i, p in enumerate(vp_):
        w_, h_ = imgsz[i]
        for g in read_gts(p.replace("/images/", "/labels/")[:-4] + ".txt", w_, h_):
            allsz[g[0]][bucket(((g[3] - g[1]) * (g[4] - g[2])) / (w_ * h_))] += 1
    for k in (0, 1):
        summ["false_negatives"][NAMES[k]]["gt_boxes_by_size"] = {n: allsz[k].get(n, 0) for _, _, n in AREA_BINS}
        summ["false_negatives"][NAMES[k]]["miss_rate_by_size"] = {
            n: (round(summ["false_negatives"][NAMES[k]]["by_size"][n] / allsz[k][n], 3) if allsz[k].get(n) else None) for _, _, n in AREA_BINS}
    report["errors_val"] = summ
    json.dump(summ, open(f"{OUT}/errors_val.json", "w"), indent=1)

    # galleries: the 24 most confident false positives, and 24 RANDOM false negatives (seeded; not picked by eye)
    def crop(i, box, cap, m=0.25):
        img = cv2.imread(vp_[i]); h, w = img.shape[:2]
        x1, y1, x2, y2 = box; bw, bh = x2 - x1, y2 - y1
        a, b_, c_, d_ = int(max(0, x1 - m * bw)), int(max(0, y1 - m * bh)), int(min(w, x2 + m * bw)), int(min(h, y2 + m * bh))
        t = img[b_:d_, a:c_].copy()
        cv2.rectangle(t, (int(x1) - a, int(y1) - b_), (int(x2) - a, int(y2) - b_), (0, 255, 0), 2)
        t = cv2.resize(t, (240, 180))
        cv2.putText(t, cap, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        return t
    def montage(tiles, out, cols=6):
        while tiles and len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        if tiles:
            cv2.imwrite(out, np.vstack([np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)]))
    topfp = sorted(FPS, key=lambda e: -e["conf"])[:24]
    montage([crop(e["img"], e["box"], f"{NAMES[e['cls']]} {e['conf']:.2f} {e['kind']}") for e in topfp], f"{OUT}/val_fp_top24.jpg")
    rng_ = random.Random(SEED)
    rfn = rng_.sample(FNS, min(24, len(FNS)))
    montage([crop(e["img"], e["box"], f"MISSED {NAMES[e['cls']]} best={e['best_same_score'] and round(e['best_same_score'], 2)}") for e in rfn], f"{OUT}/val_fn_random24.jpg")
    # every false-positive box on validation, for hard-negative mining in Step 2 (stems and boxes only; no test image)
    json.dump([{"stem": os.path.basename(vp_[e["img"]])[:-4], **{k: e[k] for k in ("cls", "conf", "box", "kind", "bengaluru")}} for e in FPS],
              open(f"{OUT}/val_false_positive_boxes.json", "w"))
print(json.dumps(report["errors_val"], indent=1))

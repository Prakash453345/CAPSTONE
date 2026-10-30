# ---- Box-level metrics on the D-Fire test split: the version 4 weights, the v5 Step 1 thresholds ----
# Nothing is chosen here: the thresholds come from fire_report.json (made by the v5 Step 1 run).
assert "choice" in report, "fire_report.json with the v5 Step 1 choice is not in the Drive folder " + OUT
TF, TS = report["choice"]["chosen"]["t_fire"], report["choice"]["chosen"]["t_smoke"]
T1 = report["choice"]["single_threshold_best"]["t_fire"]
IOU_MATCH = 0.5
YAML_M = f"{WORK}/metrics.yaml"
with open(YAML_M, "w") as f:
    f.write(f"path: {DS}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: fire\n  1: smoke\n")

def iou_1toN(b, bs):
    x1 = np.maximum(b[0], bs[:, 0]); y1 = np.maximum(b[1], bs[:, 1])
    x2 = np.minimum(b[2], bs[:, 2]); y2 = np.minimum(b[3], bs[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    ua = (b[2] - b[0]) * (b[3] - b[1]) + (bs[:, 2] - bs[:, 0]) * (bs[:, 3] - bs[:, 1]) - inter
    return inter / np.maximum(ua, 1e-9)

def match_counts(preds, gts, thr):
    """preds: list of (cls, conf, x1, y1, x2, y2); gts: list of (cls, x1, y1, x2, y2); thr: {cls: min conf}.
    Greedy match by confidence, IoU >= IOU_MATCH, same class. Returns {cls: [tp, fp, fn]}."""
    out = {}
    for k in (0, 1):
        g = np.array([x[1:] for x in gts if x[0] == k], float).reshape(-1, 4)
        p = sorted([x for x in preds if x[0] == k and x[1] >= thr[k]], key=lambda x: -x[1])
        used = np.zeros(len(g), bool)
        tp = 0
        for x in p:
            if len(g):
                io = iou_1toN(np.array(x[2:], float), g)
                io[used] = -1
                j = int(io.argmax())
                if io[j] >= IOU_MATCH:
                    used[j] = True
                    tp += 1
        out[k] = [tp, len(p) - tp, int(len(g) - used.sum())]
    return out

def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f}

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

def box_counts(all_pred, all_gt, thr, idx=None):
    tot = {0: [0, 0, 0], 1: [0, 0, 0]}
    for i in (range(len(all_pred)) if idx is None else idx):
        m = match_counts(all_pred[i], all_gt[i], thr)
        for k in (0, 1):
            for j in range(3):
                tot[k][j] += m[k][j]
    allc = [sum(tot[k][j] for k in (0, 1)) for j in range(3)]
    return {"fire": prf(*tot[0]), "smoke": prf(*tot[1]), "all (micro)": prf(*allc)}

if "box_metrics" not in report:
    tp_, thas_, tblr_ = split_table("test")
    mm = YOLO(PT)
    # 1) Ultralytics' own COCO-style metrics (mAP at IoU 0.5 and 0.5:0.95, precision/recall at the best-F1 confidence)
    r = mm.val(data=YAML_M, split="test", imgsz=SIZE, batch=16, conf=0.001, iou=0.7, plots=True,
               project=OUT, name="val_test", exist_ok=True, verbose=False)
    b = r.box
    bestc = {}
    try:
        px = np.array(b.px); f1c = np.array(b.f1_curve)
        for ci, k in enumerate(NAMES):
            bestc[k] = round(float(px[int(f1c[ci].argmax())]), 3)
    except Exception:  # noqa: BLE001
        pass
    ul = {"images": int(len(tp_)), "map50": float(b.map50), "map50_95": float(b.map),
          "per_class": {NAMES[int(c)]: {"ap50": float(b.ap50[j]), "ap50_95": float(b.all_ap[j].mean()),
                                        "precision_at_best_f1": float(b.p[j]), "recall_at_best_f1": float(b.r[j]),
                                        "f1_at_best_f1": float(b.f1[j]), "best_f1_conf": bestc.get(NAMES[int(c)])}
                        for j, c in enumerate(b.ap_class_index)}}
    # 2) Our own box-level counts at the alarm thresholds (a prediction is right at IoU >= 0.5, same class)
    all_pred, all_gt = [], []
    for s in range(0, len(tp_), 16):
        for p, res in zip(tp_[s:s + 16], mm.predict(tp_[s:s + 16], imgsz=SIZE, conf=0.05, iou=0.7, verbose=False)):
            h_, w_ = res.orig_shape
            bx = res.boxes
            all_pred.append([(int(c), float(cf), *xy) for c, cf, xy in zip(bx.cls.tolist(), bx.conf.tolist(), bx.xyxy.tolist())])
            all_gt.append(read_gts(p.replace("/images/", "/labels/")[:-4] + ".txt", w_, h_))
    pos = [i for i in range(len(tp_)) if thas_[i].any()]
    neg = [i for i in range(len(tp_)) if not thas_[i].any()]
    own = {"match_iou": IOU_MATCH, "thresholds_v5": {"fire": TF, "smoke": TS}, "thresholds_single": {"fire": T1, "smoke": T1},
           "v5_two_thresholds": box_counts(all_pred, all_gt, {0: TF, 1: TS}),
           "v4_single_threshold": box_counts(all_pred, all_gt, {0: T1, 1: T1}),
           "v5_boxes_on_images_without_fire_or_smoke": {
               "images": len(neg), "predicted_boxes": box_counts(all_pred, all_gt, {0: TF, 1: TS}, neg)["all (micro)"]["fp"],
               "of_which_fire": box_counts(all_pred, all_gt, {0: TF, 1: TS}, neg)["fire"]["fp"],
               "of_which_smoke": box_counts(all_pred, all_gt, {0: TF, 1: TS}, neg)["smoke"]["fp"]},
           "v5_on_images_with_fire_or_smoke": box_counts(all_pred, all_gt, {0: TF, 1: TS}, pos)}
    # 3) a sweep, so the report shows the precision/recall trade-off (not used to choose anything)
    sweep = []
    for tf_ in (0.2, 0.3, 0.44, 0.6, 0.8):
        for ts_ in (0.05, 0.11, 0.2, 0.3, 0.5):
            c = box_counts(all_pred, all_gt, {0: tf_, 1: ts_})["all (micro)"]
            sweep.append({"t_fire": tf_, "t_smoke": ts_, "precision": c["precision"], "recall": c["recall"], "f1": c["f1"]})
    report["box_metrics"] = {"ultralytics_val_on_test": ul, "own_box_level": own, "sweep_not_used_for_choice": sweep,
                             "note": "test split = D-Fire test + Bengaluru negatives as in the v4 dataset; reported, not judged"}
    json.dump(report["box_metrics"], open(f"{OUT}/box_metrics.json", "w"), indent=1)
print(json.dumps(report["box_metrics"], indent=1)[:6000])

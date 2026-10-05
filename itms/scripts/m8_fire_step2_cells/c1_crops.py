# ---- Step 2: candidate boxes and crops (TRAINING and VALIDATION images only; no test image is touched here) ----
import pickle
S2 = f"{OUT}/s2"
os.makedirs(S2, exist_ok=True)
CROP, MARGIN, DET_CONF = 112, 0.25, 0.05
GRID2 = [round(0.05 + 0.05 * i, 2) for i in range(19)]         # 0.05 ... 0.95
S2_REPORT_PATH = f"{OUT}/s2_report.json"
r2 = json.load(open(S2_REPORT_PATH)) if os.path.exists(S2_REPORT_PATH) else {}

def save_r2():
    json.dump(r2, open(S2_REPORT_PATH + ".part", "w"), indent=1)
    os.replace(S2_REPORT_PATH + ".part", S2_REPORT_PATH)

det = YOLO(PT)

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

def candidates(paths):
    """Detector boxes (class, conf, x1, y1, x2, y2) at conf >= DET_CONF, NMS IoU 0.7, for each image."""
    out = []
    for s in range(0, len(paths), 32):
        for r in det.predict(paths[s:s + 32], imgsz=SIZE, conf=DET_CONF, iou=0.7, verbose=False):
            bx = r.boxes
            out.append([(int(c), float(cf), *xy) for c, cf, xy in zip(bx.cls.tolist(), bx.conf.tolist(), bx.xyxy.tolist()) if int(c) in (0, 1)])
    return out

def crop_box(img, box):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = max(x2 - x1, 4.0), max(y2 - y1, 4.0)
    a, b = int(max(0, x1 - MARGIN * bw)), int(max(0, y1 - MARGIN * bh))
    c, d = int(min(w, x2 + MARGIN * bw)), int(min(h, y2 + MARGIN * bh))
    if c - a < 2 or d - b < 2:
        a, b, c, d = max(0, int(x1) - 2), max(0, int(y1) - 2), min(w, int(x2) + 2), min(h, int(y2) + 2)
        if c - a < 2 or d - b < 2:
            return np.zeros((CROP, CROP, 3), np.uint8)
    return cv2.resize(img[b:d, a:c], (CROP, CROP), interpolation=cv2.INTER_AREA)

def flame_blobs(img, k=4):
    """Flame-coloured regions (orange / yellow, saturated, bright): plates, lamps, clothing. Boxes (x1, y1, x2, y2)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (3, 110, 140), (35, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H, W = img.shape[:2]
    boxes = []
    for c in sorted(cs, key=cv2.contourArea, reverse=True)[:k]:
        x, y, w, h = cv2.boundingRect(c)
        if 0.00015 * H * W <= w * h <= 0.25 * H * W:
            boxes.append((x, y, x + max(w, 12), y + max(h, 12)))
    return boxes

def jitter(box, rng, amt=0.12):
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    return (x1 + rng.uniform(-amt, amt) * bw, y1 + rng.uniform(-amt, amt) * bh,
            x2 + rng.uniform(-amt, amt) * bw, y2 + rng.uniform(-amt, amt) * bh)

def build_crops(split):
    rows = [r for r in man["images"] if r["split"] == split]
    paths = [f"{DS}/images/{split}/{r['stem']}.jpg" for r in rows]
    cache = f"{S2}/cand_{split}.pkl"
    if os.path.exists(cache):
        cands = pickle.load(open(cache, "rb"))
        assert len(cands) == len(paths), "stale candidate cache"
    else:
        t0 = time.time()
        cands = candidates(paths)
        pickle.dump(cands, open(cache + ".part", "wb"))
        os.replace(cache + ".part", cache)
        print(f"{split}: detector ran on {len(paths)} images in {time.time() - t0:.0f} s")
    rng = random.Random(SEED + (1 if split == "train" else 2))
    pos, neg_det, neg_blob, neg_rand, sizes, ignored = [], [], [], [], [], 0
    for r, p, cd in zip(rows, paths, cands):
        img = cv2.imread(p)
        h, w = img.shape[:2]
        gts = read_gts(f"{DS}/labels/{split}/{r['stem']}.txt", w, h)
        blr = r["stem"].startswith(("blr_", "blrh_"))
        if gts:
            G = np.array([g[1:] for g in gts], float)
            GC = np.array([g[0] for g in gts])
            for g in gts:
                sizes.append(((g[3] - g[1]) / w, (g[4] - g[2]) / h))
                for _ in range(2 if split == "train" else 1):
                    pos.append((crop_box(img, jitter(g[1:], rng) if split == "train" else g[1:]), g[0]))
            for c in cd:
                same = np.where(GC == c[0])[0]
                if len(same) and iou_1toN(np.array(c[2:], float), G[same]).max() >= 0.3:
                    pos.append((crop_box(img, c[2:]), c[0]))
                else:
                    ignored += 1          # a candidate in an image WITH a label that matches no box: maybe unlabelled fire
        else:
            for c in cd:
                neg_det.append((crop_box(img, c[2:]), 2))
            if blr:
                for b in flame_blobs(img):
                    neg_blob.append((crop_box(img, b), 2))
            for _ in range(2):
                sw, sh = rng.choice(sizes) if sizes else (0.15, 0.15)
                bw, bh = max(sw * w, 12), max(sh * h, 12)
                x1, y1 = rng.uniform(0, max(w - bw, 1)), rng.uniform(0, max(h - bh, 1))
                neg_rand.append((crop_box(img, (x1, y1, x1 + bw, y1 + bh)), 2))
    cap = 3 * len(pos)
    srcs = [neg_det, neg_blob, neg_rand]
    for s_ in srcs:
        rng.shuffle(s_)
    take, left = [0, 0, 0], cap
    while left > 0 and any(take[i] < len(srcs[i]) for i in range(3)):       # even thirds, the short source gives way
        for i in range(3):
            if left > 0 and take[i] < len(srcs[i]):
                take[i] += 1
                left -= 1
    neg = [x for i in range(3) for x in srcs[i][:take[i]]]
    X = np.stack([c for c, _ in pos + neg]) if pos + neg else np.zeros((0, CROP, CROP, 3), np.uint8)
    y = np.array([l for _, l in pos + neg], np.int64)
    info = {"images": len(rows), "positives_fire": int((y == 0).sum()), "positives_smoke": int((y == 1).sum()),
            "negatives": int((y == 2).sum()),
            "negative_sources_available": {"detector_candidates_in_label_free_images": len(neg_det), "flame_blobs_bengaluru": len(neg_blob), "random_boxes": len(neg_rand)},
            "negative_sources_used": dict(zip(["detector", "blobs", "random"], take)),
            "ignored_candidates_in_labelled_images": ignored}
    return X, y, info

X_tr, y_tr, info_tr = build_crops("train")
X_va, y_va, info_va = build_crops("val")
r2["crops"] = {"train": info_tr, "val": info_va, "settings": {"CROP": CROP, "MARGIN": MARGIN, "DET_CONF": DET_CONF}}
save_r2()
print(json.dumps(r2["crops"], indent=1))
assert info_tr["positives_fire"] > 0 and info_tr["positives_smoke"] > 0 and info_tr["negatives"] > 0, "STOP: the training crops lack a class"
# a look at what the classifier will learn from (a seeded sample of every kind), for the eyeball check in the rules
rs = np.random.RandomState(SEED)
tiles = []
for lab in (0, 1, 2):
    idx = np.where(y_tr == lab)[0]
    sel = rs.choice(idx, min(12, len(idx)), replace=False) if len(idx) else []
    row = [X_tr[i] for i in sel]
    while len(row) < 12:
        row.append(np.zeros((CROP, CROP, 3), np.uint8))
    tiles.append(np.hstack(row))
cv2.imwrite(f"{OUT}/s2_training_crops_sample.jpg", np.vstack(tiles))
display(_Img(f"{OUT}/s2_training_crops_sample.jpg"))

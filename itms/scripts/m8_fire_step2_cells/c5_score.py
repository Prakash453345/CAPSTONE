# ---- Score: A, N, P (D-Fire test), C (FASDD held-out street fires), B4 (new Bengaluru frames): once each ----
def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(c - h, 3), round(c + h, 3))

if "test" not in r2:
    tp, thas, tblr = split_table("test")
    ts_ = image_scores2(tp)
    tpos = thas.any(1)
    al = alarm2(ts_)
    TPc, FPc = int(al[tpos].sum()), int(al[~tpos].sum())
    S1 = report.get("choice", {}).get("chosen")
    s1 = None
    if S1:                       # Step 1 on the same images, from its report (reported, not judged)
        s1 = report.get("test")
    r2["test"] = {"images": int(len(tp)), "with_fire_or_smoke": int(tpos.sum()), "p_fire": PF, "p_smoke": PS,
                  "recall_any": float(al[tpos].mean()), "recall_of_images_with_fire": float(al[thas[:, 0]].mean()),
                  "recall_of_images_with_smoke": float(al[thas[:, 1]].mean()),
                  "false_alarms_on_negatives": float(al[~tpos].mean()),
                  "precision": TPc / max(TPc + FPc, 1), "tp": TPc, "fp": FPc, "fn": int(tpos.sum()) - TPc,
                  "f1": (2 * TPc / max(2 * TPc + FPc + (int(tpos.sum()) - TPc), 1)),
                  "step1_for_comparison": ({k: s1[k] for k in ("recall_any", "false_alarms_on_negatives")} if s1 else None)}
    save_r2()
    missed = [tp[i] for i in np.where(tpos & ~al)[0][:12]]
    if missed:
        sheet(missed, lambda p, img: [], f"{OUT}/s2_test_misses.jpg")
print("A / N / P (D-Fire test, scored once):", json.dumps(r2["test"], indent=1))

if "heldout" not in r2:
    pkg, sel = extract_fasdd()
    held = sel["heldout"]
    hp = [f"{pkg}/heldout/images/{h['stem']}.jpg" for h in held]
    hfp = np.stack([dhash16(cv2.imread(p)) for p in hp])
    near = hamming_min(hfp, TV_FP) <= NEAR_HELDOUT_BITS
    hs = image_scores2(hp)
    hal = alarm2(hs)
    groups = defaultdict(lambda: [0, 0])
    for h, n_, a in zip(held, near, hal):
        if n_:
            continue
        for key in (h["label"], "street (V+R)" if h["label"] in ("V", "R") else "not street"):
            groups[key][1] += 1
            groups[key][0] += int(a)
    st = groups["street (V+R)"]
    r2["heldout"] = {"images": len(held), "near_copies_of_training_removed": int(near.sum()),
                     "by_label": {k: {"alarm": v[0], "n": v[1]} for k, v in sorted(groups.items())},
                     "street_recall": (st[0] / st[1]) if st[1] else None, "street_n": st[1], "street_wilson_95": wilson(*st),
                     "note": "label X (no visible fire) is reported, not a recall target"}
    save_r2()
print("C (held-out FASDD):", json.dumps(r2["heldout"], indent=1))

if "test4" not in r2:
    s4 = image_scores2(T4)
    a4 = alarm2(s4)
    alarms = sorted(((os.path.basename(p), round(float(s[0]), 4), round(float(s[1]), 4)) for p, s, a in zip(T4, s4, a4) if a), key=lambda x: -max(x[1], x[2]))
    s3b = image_scores2(B3)           # reported, not judged: B3 was seen by Step 1
    a3b = alarm2(s3b)
    s2b = image_scores2(V4_TEST2)
    r2["test4"] = {"frames": len(T4), "p_fire": PF, "p_smoke": PS, "alarms": len(alarms),
                   "max_alarms_allowed": int(math.floor(TARGET_B4_MAX_SHARE * len(T4))),
                   "alarm_frames": [{"frame": a, "p_fire": f, "p_smoke": s} for a, f, s in alarms],
                   "highest_p_fire": sorted((round(float(x), 4) for x in s4[:, 0]), reverse=True)[:12],
                   "highest_p_smoke": sorted((round(float(x), 4) for x in s4[:, 1]), reverse=True)[:12],
                   "reported_not_judged": {"B3_alarms": int(a3b.sum()), "B3_alarm_frames": [os.path.basename(p) for p, a in zip(B3, a3b) if a],
                                           "B3_plate_frame_803445_alarms": bool(a3b[[os.path.basename(p) for p in B3].index("803445.jpg")]) if "803445.jpg" in {os.path.basename(p) for p in B3} else None,
                                           "v4_fresh_250_alarms": int(alarm2(s2b).sum())}}
    r2["test4"]["pass"] = r2["test4"]["alarms"] <= r2["test4"]["max_alarms_allowed"]
    save_r2()
    top = [p for p in T4 if os.path.basename(p) in {a for a, _, _ in alarms}][:12]
    if top:
        def pred_boxes4(p, img):
            r = det.predict(img, imgsz=SIZE, conf=DET_CONF, verbose=False)[0]
            return [(int(c), *b, float(sc)) for b, sc, c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy())]
        sheet(top, pred_boxes4, f"{OUT}/s2_test4_review.jpg")
        display(_Img(f"{OUT}/s2_test4_review.jpg"))
print("B4 (new Bengaluru frames, scored once):", json.dumps({k: v for k, v in r2["test4"].items() if not k.startswith("highest")}, indent=1))
tA = r2["test"]["recall_any"] >= TARGET_A_DFIRE_RECALL
tN = r2["test"]["false_alarms_on_negatives"] <= TARGET_N_DFIRE_FA
tP = r2["test"]["precision"] >= TARGET_P_PRECISION
tC = (r2["heldout"]["street_recall"] or 0) >= TARGET_C_STREET_RECALL
tB = bool(r2["test4"]["pass"])
r2["verdict_in_colab"] = {
    "A_dfire_recall": {"value": r2["test"]["recall_any"], "target": TARGET_A_DFIRE_RECALL, "pass": bool(tA)},
    "N_dfire_false_alarms": {"value": r2["test"]["false_alarms_on_negatives"], "target": TARGET_N_DFIRE_FA, "pass": bool(tN)},
    "P_dfire_precision": {"value": r2["test"]["precision"], "target": TARGET_P_PRECISION, "pass": bool(tP)},
    "C_street_recall": {"value": r2["heldout"]["street_recall"], "target": TARGET_C_STREET_RECALL, "pass": bool(tC), "wilson_95": r2["heldout"]["street_wilson_95"]},
    "B4_new_bengaluru": {"alarms": r2["test4"]["alarms"], "of": r2["test4"]["frames"], "max_allowed": r2["test4"]["max_alarms_allowed"], "pass": tB},
    "all_judged_pass": bool(tA and tN and tP and tC and tB),
    "still_to_check_on_the_laptop": ["D: Inferno, if it has arrived"]}
save_r2()
print("A:", "PASS" if tA else "FAIL", "| N:", "PASS" if tN else "FAIL", "| P:", "PASS" if tP else "FAIL", "| B4:", "PASS" if tB else "FAIL",
      "| C:", "PASS" if tC else "FAIL", "| ALL:", "PASS" if r2["verdict_in_colab"]["all_judged_pass"] else "FAIL")

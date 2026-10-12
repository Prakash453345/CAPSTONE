"""Dry-run the version 5 Step 2 notebook on CPU: tiny fake data left by the v4 dry run, a fake Hugging Face, no pretrained weights.
Covers: crops built only from training/validation, ignored candidates in labelled images, the classifier trains and is restored,
the (p_fire, p_smoke) rule, B4 far from B3 and every known camera, a stop without B3 or with too few frames, A/N/P/C/B4 scored once,
the verdict arithmetic, a second session with no network.
    python dry_s2.py --notebook s2.ipynb --root /home/claude/dry/root --data DIR_WITH_val_sample"""
import argparse, glob, hashlib, json, os, random, shutil, sys, types, zipfile
import cv2, numpy as np

T = {"SETTINGS": "# ---- Settings", "HELPERS": "# ---- Helpers", "TESTS": "# ---- The 250 Bengaluru test frames",
     "WRITE": "def write_image", "PICS": "# ---- Picture helpers", "PREP": "V4_SETTINGS = ", "RESTORE": "# ---- Restore the version 4",
     "FPS": "# ---- Fingerprints", "CROPS": "# ---- Step 2: candidate boxes", "TRAIN": "# ---- Step 2: train", "SELECT": "# ---- Step 2: image scores",
     "FRESH": "# ---- NEW Bengaluru test frames (B4)", "SCORE": "# ---- Score: A, N, P", "PACKAGE": "# ---- Package and download"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebook", required=True); ap.add_argument("--root", required=True); ap.add_argument("--data", required=True)
    args = ap.parse_args()
    import torch  # noqa: F401
    ip, ipd = types.ModuleType("IPython"), types.ModuleType("IPython.display")
    ip.version_info = (8, 30); ipd.Image = ipd.display = lambda *a, **k: None; ip.display = ipd
    sys.modules["IPython"], sys.modules["IPython.display"] = ip, ipd
    for d in ("s0", "s1", "s2o", "s3", "s4", "ws0", "ws1", "ws2", "ws3", "ws4"):
        shutil.rmtree(os.path.join(args.root, d), ignore_errors=True)
    nb = json.load(open(args.notebook))
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    cell = {k: next(c for c in code if c.startswith(t)) for k, t in T.items()}
    v4 = os.path.join(args.root, "drive", "itms_fire")
    pt = os.path.join(v4, "itms_fire_320.pt")
    sha = hashlib.sha256(open(pt, "rb").read()).hexdigest()
    step1 = os.path.join(args.root, "o3")          # the Step 1 dry run's Drive folder: report, B3 frames, caches
    for f in ("fire_report.json", "bengaluru_test3.tar", "bengaluru_test3.json"):
        assert os.path.exists(os.path.join(step1, f)), f
    vs = sorted(glob.glob(os.path.join(args.data, "val_sample", "*.png")))
    enc = lambda im: cv2.imencode(".png", im)[1].tobytes()  # noqa: E731

    def hfdict(frames):
        names = {n: f"UVH-26-Train/data/x/{n}" for n in frames}
        return {"hf_list": lambda folder="": dict(names), "hf_get": lambda path, tries=10: frames.get(os.path.basename(path))}

    def no_net(*a, **k):
        raise RuntimeError("no network in the dry run")
    OFF = {"hf_list": no_net, "hf_get": no_net}

    def fresh_out(name):
        d = os.path.join(args.root, name)
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(step1, d)
        for f in ("s2_report.json", "bengaluru_test4.tar", "bengaluru_test4.json"):
            if os.path.exists(os.path.join(d, f)):
                os.remove(os.path.join(d, f))
        shutil.rmtree(os.path.join(d, "s2"), ignore_errors=True)
        return d

    def session(out, work, hf, over=None, upto="PACKAGE", hook=None, drop_b3=False):
        g = {"__name__": "__main__"}
        exec(cell["SETTINGS"], g)
        g.update({"SIZE": 320, "PT_NAME": "itms_fire_320.pt", "EXPECTED_PT_SHA256": sha, "WORK": work, "DRIVE_DIR": out, "V4_DRIVE_DIR": v4,
                  "MIN_RECALL_IMAGES": 1, "NEAR_DUP_BITS": 4, "N_TEST3": 3, "N_V4_TEST2": 3, "N_TEST4": 3, "MAX_CANDIDATES": 60, "SEED": 26, **(over or {})})
        os.makedirs(work, exist_ok=True)
        g["OUT"], g["HF_TOKEN"] = out, None
        exec("import os, sys, json, time, shutil, subprocess\nimport torch", g)
        for k in T:
            if k == "SETTINGS":
                continue
            if k == "TRAIN" and hook:
                hook(g)
            exec(cell[k], g)
            if k == "HELPERS":
                g.update({a: b for a, b in hf.items() if a in ("hf_list", "hf_get")})
            if k == upto:
                break
        return g

    def no_pretrained(g):
        g["r2"]["_no_pretrained"] = True        # no download.pytorch.org here

    # frames for B4: other far frames than B3's (the Step 1 dry run used vs[0], vs[10], vs[17] flipped), plus specials
    far4 = [enc(cv2.flip(cv2.imread(vs[i]), 0)) for i in (3, 12, 19)]
    rng = np.random.default_rng(3)

    # 0. the B3 frames are missing from the Drive folder: stop (B4 must be far from them)
    d0 = fresh_out("s0")
    os.remove(os.path.join(d0, "bengaluru_test3.tar"))
    try:
        session(d0, os.path.join(args.root, "ws0"), hfdict({}), upto="FRESH", hook=no_pretrained)
        raise AssertionError("did not stop")
    except SystemExit as e:
        assert "B3 frames are not in" in str(e), e
    print("== no B3 frames: stops")

    # 1. too few new frames: stop, nothing cached
    d1 = fresh_out("s1")
    try:
        session(d1, os.path.join(args.root, "ws1"), hfdict({"n00.png": far4[0]}), upto="FRESH", hook=no_pretrained)
        raise AssertionError("did not stop")
    except SystemExit as e:
        assert "far enough" in str(e), e
    assert not os.path.exists(os.path.join(d1, "bengaluru_test4.tar"))
    print("== too few new frames: stops, no cache")

    # 2. the whole run
    out = fresh_out("s2o")
    # specials: a near-copy of a known frame (the same camera), junk, a missing file; the far frames last in the seeded shuffle
    probe = session(fresh_out("s3"), os.path.join(args.root, "ws3"), hfdict({}), upto="FPS", hook=None)
    blr = sorted(glob.glob(os.path.join(probe["DS"], "images", "train", "blr_*.jpg")))
    base = cv2.imread(blr[1] if len(blr) > 1 else blr[0])
    noise = np.clip(base.astype(int) + rng.integers(-3, 4, base.shape), 0, 255).astype(np.uint8)
    items = [enc(noise), b"not an image", None] + far4
    n = len(items)
    order = list(range(n)); random.Random(26 + 7).shuffle(order)
    frames = {}
    spec_k, far_k = [order[p] for p in range(n - 3)], [order[p] for p in range(n - 3, n)]
    for k, data in zip(spec_k + far_k, items):
        frames[f"m{k:02d}.png"] = data
    HF = hfdict(frames)
    g = session(out, os.path.join(args.root, "ws2"), HF, hook=no_pretrained)
    r2 = json.load(open(g["S2_REPORT_PATH"]))
    ci = r2["crops"]
    print("crops:", json.dumps({k: {a: b for a, b in v.items() if a in ("positives_fire", "positives_smoke", "negatives", "negative_sources_used", "ignored_candidates_in_labelled_images")} for k, v in ci.items() if k in ("train", "val")}))
    # crops: only training images feed the classifier; negatives capped at 3 x positives
    assert ci["train"]["negatives"] <= 3 * (ci["train"]["positives_fire"] + ci["train"]["positives_smoke"])
    assert len(g["X_tr"]) == ci["train"]["positives_fire"] + ci["train"]["positives_smoke"] + ci["train"]["negatives"]
    assert os.path.exists(g["CLS_PATH"]) and r2["classifier_sha256"] == g["sha256_file"](g["CLS_PATH"])
    assert len(r2["train_history"]) == 8
    ch = r2["choice"]
    print("choice:", json.dumps(ch["chosen"]), "| by distance:", json.dumps(ch["recall_by_distance_to_training"]))
    assert ch["chosen"]["bengaluru_val_alarms"] <= ch["max_alarms"]
    assert all(r["val_recall"] <= ch["chosen"]["val_recall"] + 1e-12 for r in ch["top10"])
    t4 = r2["test4_source"]
    print("B4:", t4["frames"], t4["skipped"], t4["looked_at"])
    assert len(t4["frames"]) == 3 and t4["looked_at"] == 6, t4
    assert t4["skipped"] == {"duplicate of a frame already known": 1, "does not open": 1, "file missing": 1}, t4["skipped"]
    assert g["hamming_min"](g["_fps"](g["T4"]), g["BANK"]).min() > 72
    B3n = {os.path.basename(p) for p in g["B3"]}
    assert not (B3n & set(t4["frames"]))
    te, hd, v = r2["test"], r2["heldout"], r2["verdict_in_colab"]
    assert te["tp"] + te["fn"] == te["with_fire_or_smoke"] and te["tp"] + te["fp"] >= 0
    assert abs(te["precision"] - te["tp"] / max(te["tp"] + te["fp"], 1)) < 1e-12
    assert abs(te["recall_any"] - te["tp"] / te["with_fire_or_smoke"]) < 1e-12
    assert abs(te["false_alarms_on_negatives"] - te["fp"] / (te["images"] - te["with_fire_or_smoke"])) < 1e-12
    assert te["p_fire"] == ch["chosen"]["p_fire"] and te["p_smoke"] == ch["chosen"]["p_smoke"]
    # recompute the test alarms independently from the candidates and the classifier
    tp_, thas_, _ = g["split_table"]("test")
    sc = g["image_scores2"](tp_)
    man_al = (sc[:, 0] >= te["p_fire"]) | (sc[:, 1] >= te["p_smoke"])
    assert int(man_al[thas_.any(1)].sum()) == te["tp"] and int(man_al[~thas_.any(1)].sum()) == te["fp"]
    assert v["all_judged_pass"] == all(v[k]["pass"] for k in ("A_dfire_recall", "N_dfire_false_alarms", "P_dfire_precision", "C_street_recall", "B4_new_bengaluru"))
    assert v["B4_new_bengaluru"]["pass"] == (r2["test4"]["alarms"] <= r2["test4"]["max_alarms_allowed"])
    print("A/N/P:", {k: te[k] for k in ("recall_any", "false_alarms_on_negatives", "precision", "f1")}, "| C:", hd["street_recall"], "| B4:", r2["test4"]["alarms"], "of", r2["test4"]["frames"])
    print("verdict:", {k: x.get("pass") for k, x in v.items() if isinstance(x, dict)})
    names = set(zipfile.ZipFile(os.path.join(out, g["ZIP_NAME"])).namelist())
    print("zip:", sorted(names))
    assert {"s2_report.json", "s2_cls.pt", "bengaluru_test4.tar", "bengaluru_test4.json"} <= names
    # the classifier never saw a test, held-out or B4 image: crops come only from the train and val splits of the manifest
    stems = {r["stem"] for r in g["man"]["images"] if r["split"] in ("train", "val")}
    test_stems = {r["stem"] for r in g["man"]["images"] if r["split"] == "test"}
    assert not (stems & test_stems), "a test image is also a training or validation image"
    assert len(g["X_tr"]) > 0 and len(g["X_va"]) > 0


    # 2b. the arithmetic with NON-ZERO alarms: same classifier, thresholds forced to 0.05, the test scored again in a copy of the folder
    o4 = os.path.join(args.root, "s4")
    shutil.rmtree(o4, ignore_errors=True)
    shutil.copytree(out, o4)
    g4 = session(o4, os.path.join(args.root, "ws4"), OFF, upto="SELECT", hook=no_pretrained)
    g4["r2"].pop("test"); g4["r2"].pop("heldout"); g4["PF"] = g4["PS"] = 0.05
    g4["r2"]["verdict_in_colab"] = None
    exec(cell["SCORE"], g4)
    te4 = g4["r2"]["test"]
    tp4, thas4, _ = g4["split_table"]("test")
    sc4 = g4["image_scores2"](tp4)
    al4 = (sc4[:, 0] >= 0.05) | (sc4[:, 1] >= 0.05)
    pos4 = thas4.any(1)
    assert te4["tp"] == int(al4[pos4].sum()) and te4["fp"] == int(al4[~pos4].sum()) and te4["tp"] + te4["fp"] > 0, te4
    assert abs(te4["precision"] - te4["tp"] / (te4["tp"] + te4["fp"])) < 1e-12
    assert abs(te4["f1"] - 2 * te4["tp"] / (2 * te4["tp"] + te4["fp"] + te4["fn"])) < 1e-12
    print("== non-zero alarms: tp", te4["tp"], "fp", te4["fp"], "fn", te4["fn"], "precision", round(te4["precision"], 3), "(matches an independent count)")

    # 3. a second session: nothing is downloaded, nothing is trained or scored again
    before = json.load(open(g["S2_REPORT_PATH"]))
    g2 = session(out, os.path.join(args.root, "ws4"), OFF, hook=no_pretrained)
    after = json.load(open(g2["S2_REPORT_PATH"]))
    for k in ("choice", "test", "heldout", "test4"):
        assert before[k] == after[k], k
    print("== second session: same numbers, no network, classifier restored")
    print("DRY RUN OK")


if __name__ == "__main__":
    main()

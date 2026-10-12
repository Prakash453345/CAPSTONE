"""Dry-run the version 5 Step 1 notebook (`notebooks/m8_fire_smoke_v5_step1.ipynb`) on CPU (M8).

It needs a fake version 4 Drive folder: the one left behind by `scripts/m8_fire_notebook_dryrun.py --work ROOT`
(dataset tar, manifest, tiny weights, fresh frames, FASDD package). Then the notebook's own cells run against it with a
fake Hugging Face. Covers: the weights checksum refused when wrong, the threshold choice (validation near-copies removed,
the rule, the stop on too few images), the new test frames (far from every known camera, none identical to an old test
frame, a stop when too few), A, C and B3 scored once, a second session that reuses everything (no network), the zip.

    python dry_v5.py --notebook v5.ipynb --root ROOT --data DIR_WITH_val_sample
"""
import argparse, glob, hashlib, json, os, shutil, sys, types, zipfile
import cv2, numpy as np

TITLES = {"SETTINGS": "# ---- Settings", "HELPERS": "# ---- Helpers", "TESTS": "# ---- The 250 Bengaluru test frames",
          "WRITE": "def write_image", "PICS": "# ---- Picture helpers", "PREP": "V4_SETTINGS = ", "RESTORE": "# ---- Restore the version 4",
          "FPS": "# ---- Fingerprints", "SELECT": "# ---- Choose the two thresholds", "FRESH": "# ---- NEW Bengaluru test frames",
          "SCORE": "# ---- Score: A", "PACKAGE": "# ---- Package and download"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebook", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--data", required=True)
    args = ap.parse_args()
    import torch  # noqa: F401

    ip, ipd = types.ModuleType("IPython"), types.ModuleType("IPython.display")
    ip.version_info = (8, 30)
    ipd.Image = ipd.display = lambda *a, **k: None
    ip.display = ipd
    sys.modules["IPython"], sys.modules["IPython.display"] = ip, ipd

    for d in ("o0","o1","o2","o3","w0","w1","w2","w3","w4","probe_out","work_probe"):
        shutil.rmtree(os.path.join(args.root, d), ignore_errors=True)
    nb = json.load(open(args.notebook))
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    cell = {k: next(c for c in code if c.startswith(t)) for k, t in TITLES.items()}
    v4 = os.path.join(args.root, "drive", "itms_fire")
    pt = os.path.join(v4, "itms_fire_320.pt")
    for f in ("fire_dataset.tar", "fire_manifest.json", "itms_fire_320.pt", "bengaluru_fresh.tar", "fasdd_v3_package.tar"):
        assert os.path.exists(os.path.join(v4, f)), f
    sha = hashlib.sha256(open(pt, "rb").read()).hexdigest()
    vs = sorted(glob.glob(os.path.join(args.data, "val_sample", "*.png")))
    assert len(vs) >= 10, len(vs)
    enc = lambda im: cv2.imencode(".png", im)[1].tobytes()  # noqa: E731

    # a fake UVH-26. The notebook shuffles the sorted names with Random(SEED + 5); names are chosen so that the 3 far frames
    # come LAST in that order and every special frame (old test frame, same camera, junk) is looked at first.
    import random
    rng = np.random.default_rng(11)
    far = [enc(cv2.flip(cv2.imread(vs[i]), 0)) for i in (0, 10, 17)]
    ds_probe = None
    special = {}      # filled after the dataset is restored (same-camera frames need a training frame)
    FARS = far
    def make_session(out5, work, over=None, hf=None, upto="PACKAGE"):
        g = {"__name__": "__main__"}
        exec(cell["SETTINGS"], g)
        g.update({"SIZE": 320, "PT_NAME": "itms_fire_320.pt", "EXPECTED_PT_SHA256": sha, "WORK": work, "DRIVE_DIR": out5,
                  "V4_DRIVE_DIR": v4, "MIN_RECALL_IMAGES": 3, "N_TEST3": 3, "N_V4_TEST2": 3, "MAX_CANDIDATES": 60, "SEED": 26,
                  **(over or {})})
        os.makedirs(g["WORK"], exist_ok=True)
        os.makedirs(out5, exist_ok=True)
        g["OUT"], g["HF_TOKEN"] = out5, None
        exec("import os, sys, json, time, shutil, subprocess\nimport torch", g)
        for k in TITLES:
            if k == "SETTINGS":
                continue
            exec(cell[k], g)
            if k == "HELPERS":
                g.update({a: b for a, b in (hf if hf is not None else HF).items() if a in ("hf_list", "hf_get")})
            if k == "PREP" and hf is not None and "next" in hf:
                g.update(hf["next"])
            if k == upto:
                break
        return g

    def hfdict(frames):
        names = {n: f"UVH-26-Train/data/x/{n}" for n in frames}
        return {"hf_list": lambda folder="": dict(names), "hf_get": lambda path, tries=10: frames.get(os.path.basename(path))}

    def no_net(*a, **k):
        raise RuntimeError("no network in the dry run")

    # ---- the fake Bengaluru frames that are the same camera as a training frame need the restored dataset first
    probe = make_session(os.path.join(args.root, "probe_out"), os.path.join(args.root, "work_probe"), upto="RESTORE", hf=hfdict({}))
    blr = sorted(f for f in glob.glob(os.path.join(probe["DS"], "images", "train", "blr_*.jpg")))
    assert blr, "no Bengaluru training frames in the fake dataset"
    base = cv2.imread(blr[0])
    noise = np.clip(base.astype(int) + rng.integers(-3, 4, base.shape), 0, 255).astype(np.uint8)
    shifted = np.clip(np.roll(base, 14, axis=1).astype(int) + rng.integers(-3, 4, base.shape), 0, 255).astype(np.uint8)
    items = [("special", enc(noise)), ("special", enc(shifted)), ("special", b"not an image"),
             ("special", open(vs[1], "rb").read()), ("special", None)]   # None: file missing
    items += [("far", f) for f in FARS]
    n = len(items)
    order = list(range(n))
    random.Random(probe["SEED"] + 5).shuffle(order)      # shuffled[p] = sorted_names[order[p]]
    # positions: specials first, far frames last
    frames, names_for = {}, {}
    far_k = [order[p] for p in range(n - 3, n)]
    spec_k = [order[p] for p in range(n - 3)]
    for k, (kind, data) in zip(spec_k + far_k, items):
        frames[f"n{k:02d}.png"] = data
    HF = hfdict(frames)
    OFF = {"hf_list": no_net, "hf_get": no_net}

    # 0. a wrong weights checksum is refused
    try:
        make_session(os.path.join(args.root, "o0"), os.path.join(args.root, "w0"), over={"EXPECTED_PT_SHA256": "0" * 64}, upto="RESTORE")
        raise AssertionError("a wrong checksum was accepted")
    except AssertionError as e:
        assert "not the version 4 model" in str(e), e
    print("== wrong weights refused")

    # 1. too few validation images with fire or smoke: stop, no choice
    try:
        make_session(os.path.join(args.root, "o1"), os.path.join(args.root, "w1"), over={"MIN_RECALL_IMAGES": 10 ** 6}, upto="SELECT")
        raise AssertionError("did not stop")
    except AssertionError as e:
        assert "STOP: only" in str(e), e
    print("== stops when too few validation positives")

    # 2. too few new test frames: stop, no verdict
    out5 = os.path.join(args.root, "o2")
    try:
        make_session(out5, os.path.join(args.root, "w2"), over={"MAX_CANDIDATES": 2, "NEAR_DUP_BITS": 4, "MIN_RECALL_IMAGES": 1}, upto="FRESH")
        raise AssertionError("did not stop")
    except SystemExit as e:
        assert "only" in str(e) and "far enough" in str(e), e
    assert not os.path.exists(os.path.join(out5, "bengaluru_test3.tar")), "a cache was written for an incomplete draw"
    print("== stops when too few new frames")

    # 3. the whole run
    out5 = os.path.join(args.root, "o3")
    work = os.path.join(args.root, "w3")
    g = make_session(out5, work, over={"NEAR_DUP_BITS": 4, "MIN_RECALL_IMAGES": 1})
    rep = json.load(open(g["REPORT_PATH"]))
    ch = rep["choice"]
    print("choice:", json.dumps(ch["chosen"]), "| single:", json.dumps(ch["single_threshold_best"]))
    print("validation positives:", ch["validation_positives_before_dedupe"], "->", ch["validation_positives_used"])
    assert ch["validation_positives_used"] <= ch["validation_positives_before_dedupe"]
    assert ch["chosen"]["bengaluru_val_alarms"] <= ch["max_alarms"]
    # the rule: no other pair under the Bengaluru cap has higher validation recall
    assert all(r["val_recall"] <= ch["chosen"]["val_recall"] + 1e-12 for r in ch["top10"]), ch["top10"]
    t3 = rep["test3_source"]
    print("new frames:", t3["frames"], "| skipped:", t3["skipped"], "| looked at:", t3["looked_at"])
    assert len(t3["frames"]) == 3
    assert t3["skipped"].get("identical to an old test frame", 0) + 0 >= 0
    assert len(t3["frames"]) == 3 and t3["looked_at"] == 8, t3
    assert t3["skipped"] == {"duplicate of a frame already known": 1, "same camera as a known frame": 1, "does not open": 1,
                             "identical to an old test frame": 1, "file missing": 1}, t3["skipped"]
    # every new test frame is more than 72 bits from every known camera (also asserted inside the notebook)
    assert g["hamming_min"](g["t3fp"], g["BANK"]).min() > 72
    sk = t3["skipped"]
    assert set(sk) <= {"identical to an old test frame", "file missing", "does not open", "duplicate of a frame already known",
                       "same camera as a known frame"}, sk
    # the A, C and B3 verdicts exist and are consistent with the targets
    v = rep["verdict_in_colab"]
    assert set(v) >= {"A_dfire_recall", "C_street_recall", "B3_new_bengaluru", "all_judged_pass"}, v
    assert v["B3_new_bengaluru"]["pass"] == (v["B3_new_bengaluru"]["alarms"] <= v["B3_new_bengaluru"]["max_allowed"])
    assert v["all_judged_pass"] == (v["A_dfire_recall"]["pass"] and v["C_street_recall"]["pass"] and v["B3_new_bengaluru"]["pass"])
    te = rep["test"]
    assert te["t_fire"] == ch["chosen"]["t_fire"] and te["t_smoke"] == ch["chosen"]["t_smoke"]
    print("A:", {k: te[k] for k in ("recall_any", "recall_of_images_with_fire", "recall_of_images_with_smoke", "false_alarms_on_negatives")})
    print("C:", {k: rep["heldout"][k] for k in ("street_recall", "street_n", "near_copies_of_training_removed")})
    print("B3:", {k: rep["test3"][k] for k in ("alarms", "max_alarms_allowed", "pass", "reported_not_judged_v4_fresh_250_alarms")})
    assert rep["heldout"]["near_copies_of_training_removed"] >= 1
    # the two-threshold rule: recompute the alarms on the test split independently
    tp, thas, _ = g["split_table"]("test")
    sc = g["scores"](tp)
    manual = ((sc[:, 0] >= te["t_fire"]) | (sc[:, 1] >= te["t_smoke"]))
    assert abs(manual[thas.any(1)].mean() - te["recall_any"]) < 1e-9
    names = set(zipfile.ZipFile(os.path.join(out5, g["ZIP_NAME"])).namelist())
    print("zip:", sorted(names))
    assert {"fire_report.json", "bengaluru_test3.tar", "bengaluru_test3.json"} <= names

    # 5. the version 4 dataset is NOT in Drive: rebuild it with version 4's own code and check it against the manifest
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import dry_v4
    import tarfile, random as _random  # noqa: F401
    # version 4's fake frames, exactly as its own dry run made them
    vs4 = sorted(glob.glob(os.path.join(args.data, "val_sample", "*.png")))
    base5 = [cv2.resize(cv2.imread(f), (1280, 720)) for f in vs4[:5]]
    enc_ = lambda im: cv2.imencode(".png", im)[1].tobytes()  # noqa: E731
    fr4 = {}
    for i, f in enumerate(vs4):
        im = cv2.imread(f)
        for j, t in enumerate((lambda a: cv2.flip(a, 1), lambda a: cv2.rotate(a, cv2.ROTATE_180))):
            x = t(im)
            if (i + j) % 7 == 0:
                h_, w_ = x.shape[:2]
                cv2.rectangle(x, (w_ // 5, h_ // 2), (w_ // 5 + w_ // 6, h_ // 2 + h_ // 5), (0, 140, 255), -1)
            fr4[f"f{i:02d}{j}.png"] = enc_(x)
    rng_ = np.random.default_rng(5)
    for k in range(6):
        b = np.roll(base5[k % 5], 14 + 3 * (k // 5), axis=1)
        fr4[f"near{k}.png"] = enc_(np.clip(b.astype(int) + rng_.integers(-3, 4, b.shape), 0, 255).astype(np.uint8))
    n0 = np.clip(base5[0].astype(int) + rng_.integers(-3, 4, base5[0].shape), 0, 255).astype(np.uint8)
    fr4["dup0.png"] = enc_(n0)
    fr4["bad_sha.png"] = open(vs4[1], "rb").read()
    fr4["bad_cam.png"] = enc_(np.clip(cv2.imread(vs4[0]).astype(int) + rng_.integers(-6, 7, cv2.imread(vs4[0]).shape), 0, 255).astype(np.uint8))
    fr4["bad_open.png"] = b"not an image"
    fr4["zz_named_like_test.png"] = open(vs4[0], "rb").read()
    HF4 = hfdict(fr4)

    def v4b_dir(name, manifest=True, folder=True):
        d = os.path.join(args.root, name)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        shutil.copy(pt, d)
        if manifest:
            shutil.copy(os.path.join(v4, "fire_manifest.json"), d)
        if folder:       # the FASDD package as an unpacked folder, like the Drive upload
            with tarfile.open(os.path.join(v4, "fasdd_v3_package.tar")) as t:
                t.extractall(d)
            os.rename(os.path.join(d, "v3_package"), os.path.join(d, "v3_package 3"))
        else:
            shutil.copy(os.path.join(v4, "fasdd_v3_package.tar"), d)
        return d

    def rebuild_session(v4b, out, extra=None, upto="PREP"):
        os.makedirs(os.path.join(out, "v4_rebuild"), exist_ok=True)
        shutil.copy(os.path.join(v4, "D-Fire.zip"), os.path.join(out, "v4_rebuild"))   # D-Fire from a Drive zip (no Kaggle here)
        small = {k: v for k, v in dry_v4.SMALL.items()}
        ov = {"V4_DRIVE_DIR": v4b, "REBUILD_OVERRIDES": {**small, "UVH_DRIVE_DIR": os.path.join(args.root, "drive", "itms_uvh"),
              "V3_DRIVE_DIR": os.path.join(args.root, "nonexistent_v3"), "BASE_WEIGHTS": "yolo11s.pt"}, **(extra or {})}
        return make_session(out, os.path.join(args.root, "w5_" + os.path.basename(out)), over=ov, upto=upto,
                            hf={**HF4, "next": HF})

    # 5a. a tampered reference manifest (one row removed): the rebuild must be refused
    d_bad = v4b_dir("v4b_bad")
    m = json.load(open(os.path.join(d_bad, "fire_manifest.json")))
    m["images"] = [r for r in m["images"] if not r["stem"].startswith("blr_")][:] + [r for r in m["images"] if r["stem"].startswith("blr_")][1:]
    json.dump(m, open(os.path.join(d_bad, "fire_manifest.json"), "w"))
    try:
        rebuild_session(d_bad, os.path.join(args.root, "o5a"))
        raise AssertionError("a different dataset was accepted")
    except SystemExit as e:
        assert "not the version 4 dataset" in str(e), e
    print("== a rebuilt dataset that differs from the version 4 manifest is refused")
    # 5b. no reference manifest: stop with a plain message
    d_nom = v4b_dir("v4b_nomanifest", manifest=False)
    try:
        rebuild_session(d_nom, os.path.join(args.root, "o5b"))
        raise AssertionError("no manifest, no stop")
    except SystemExit as e:
        assert "fire_manifest.json" in str(e), e
    print("== no reference manifest: stops")
    # 5c. the real thing: rebuild, check, then run Step 1 end to end (FASDD as an unpacked folder)
    d_ok = v4b_dir("v4b_ok")
    out5 = os.path.join(args.root, "o5c")
    shutil.rmtree(out5, ignore_errors=True)
    g5 = rebuild_session(d_ok, out5, extra={"NEAR_DUP_BITS": 4, "MIN_RECALL_IMAGES": 1, "MAX_CANDIDATES": 60, "SEED": 26}, upto="PACKAGE")
    rep5 = json.load(open(g5["REPORT_PATH"]))
    assert g5["V4"].endswith("v4_rebuild"), g5["V4"]
    assert set(rep5["verdict_in_colab"]) >= {"A_dfire_recall", "C_street_recall", "B3_new_bengaluru"}
    print("5c verdict:", {k: v.get("pass") for k, v in rep5["verdict_in_colab"].items() if isinstance(v, dict)})
    print("== rebuild from scratch (FASDD as a folder) matched version 4 and Step 1 ran on it")

    # 4. a second session: nothing is downloaded, nothing is scored again
    before = json.load(open(g["REPORT_PATH"]))
    g2 = make_session(out5, os.path.join(args.root, "w4"), hf=OFF, over={"NEAR_DUP_BITS": 4, "MIN_RECALL_IMAGES": 1})
    after = json.load(open(g2["REPORT_PATH"]))
    for k in ("choice", "test", "heldout", "test3"):
        assert before[k] == after[k], k
    print("== second session: same numbers, no network")
    print("DRY RUN OK")


if __name__ == "__main__":
    main()

"""Dry-run the fire and smoke notebook (`notebooks/m8_fire_smoke_v4.ipynb`) on CPU (M8).

A small fake D-Fire is painted onto the labelled test sample's frames
(orange flames, grey smoke), zipped into a fake Google Drive, and the
notebook's own cells run against it: every code path the Colab run takes
except the GPU and the downloads.

It covers:
- finding the zip in Drive, the D-Fire folder layout, and `__MACOSX` junk;
- which label id is fire, told from the box colours (the fake uses D-Fire's
  smoke = 0, fire = 1) and checked against a names file, including a names
  file that disagrees (the run must stop);
- broken labels: out-of-range, degenerate and malformed boxes, an unknown
  class id, a missing label file, an image that does not open;
- a validation split carved from training;
- a training image identical to a test image and one that is a near-copy
  of one;
- the Bengaluru negatives from the vehicle notebook's Drive folder;
- a disconnect after the first epoch and the resume;
- the threshold chosen on validation, the test scored once, and the ONNX
  export and its check;
- a second session with nothing left to do;
- a changed setting refused;
- version 4: fresh Bengaluru frames (extra validation, a fresh test set, hard negatives picked by flame-coloured area),
  training frames of the same camera as a fresh test frame dropped, the test frames kept out of the dataset;
- version 3: the FASDD package (a copy of a D-Fire test image in it must be dropped, by checksum and by
  fingerprint), flame pasting from D-Fire train crops, and the held-out street test with its near-copy
  removal and target verdicts.

Needs torch, ultralytics==8.4.163, onnx, onnxruntime and onnxslim: not the
project venv.

    python scripts/m8_fire_notebook_dryrun.py --data data/uvh26 --weights yolo11s.pt
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import zipfile

import cv2
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLES = {
    "SETTINGS": "# ---- Settings",
    "HELPERS": "# ---- Helpers",
    "TESTS": "# ---- The 250 Bengaluru test frames",
    "GET": "# ---- Get D-Fire",
    "READ": "# ---- Read it",
    "BUILD": "# ---- Build the training set",
    "SHEET": "# ---- Look at the labels",
    "TRAIN": "# ---- Train",
    "EVAL": "# ---- The model in full precision",
    "HELDOUT": "# ---- The FASDD held-out",
    "FRESH": "# ---- The FRESH Bengaluru test frames",
    "EXPORT": "# ---- Export to ONNX",
    "PACKAGE": "# ---- Package and download",
}
SMALL = {
    "SIZE": 320,
    "EPOCHS": 2,
    "PATIENCE": 5,
    "BATCH": 4,
    "WORKERS": 0,
    "N_NEG_TRAIN": 6,
    "MIN_IMAGES": 30,
    "N_PASTE": 4,
    "PASTE_MIN_BOX": 12,
    "PASTE_HEIGHTS": (20, 60),
    "MIN_FLAME_CROPS": 5,
    "N_NEG_VAL": 8,
    "N_NEG_VAL_BASE": 4,
    "N_TEST2": 3,
    "N_MINE_POOL": 8,
    "N_HARD": 3,
}


class Disconnect(Exception):
    """A simulated Colab disconnect."""


def paint(base: np.ndarray, rng: np.random.Generator, fire: bool, smoke: bool) -> tuple:
    """A frame with a flame (saturated orange-yellow) and/or a smoke plume (grey), and its YOLO
    label lines in D-Fire's ids."""
    img = base.copy()
    H, W = img.shape[:2]
    lines = []
    if smoke:
        w, h = int(rng.integers(W // 6, W // 3)), int(rng.integers(H // 5, H // 3))
        x, y = int(rng.integers(0, W - w)), int(rng.integers(0, H - h))
        blob = np.zeros((H, W), np.float32)
        cv2.ellipse(blob, (x + w // 2, y + h // 2), (w // 2, h // 2), 0, 0, 360, 1.0, -1)
        blob = cv2.GaussianBlur(blob, (0, 0), max(3, w // 10))[..., None] * 0.8
        img = (img * (1 - blob) + np.full_like(img, 170) * blob).astype(np.uint8)
        lines.append(f"0 {(x + w / 2) / W:.6f} {(y + h / 2) / H:.6f} {w / W:.6f} {h / H:.6f}")
    if fire:
        w, h = int(rng.integers(W // 10, W // 5)), int(rng.integers(H // 8, H // 4))
        x, y = int(rng.integers(0, W - w)), int(rng.integers(0, H - h))
        for _ in range(12):
            cx, cy = x + int(rng.integers(0, w)), y + int(rng.integers(0, h))
            col = (0, int(rng.integers(90, 200)), 255)
            cv2.ellipse(img, (cx, cy), (max(2, w // 5), max(2, h // 4)), 0, 0, 360, col, -1)
        cv2.rectangle(
            img, (x + w // 4, y + h // 4), (x + 3 * w // 4, y + 3 * h // 4), (0, 150, 255), -1
        )
        lines.append(f"1 {(x + w / 2) / W:.6f} {(y + h / 2) / H:.6f} {w / W:.6f} {h / H:.6f}")
    return img, lines


def fake_dfire(
    data: str, drive: str, uvh_drive: str, with_names: str | None, flat: bool = False
) -> dict:
    frames = sorted(glob.glob(os.path.join(data, "val_sample", "*.png")))[:5]
    assert len(frames) == 5, (
        f"need 5 frames in {data}/val_sample (scripts/m8_fetch_uvh26_sample.py)"
    )
    bases = [cv2.resize(cv2.imread(f), (640, 360)) for f in frames]
    rng = np.random.default_rng(0)
    root = tempfile.mkdtemp(prefix="dfire_")
    top = os.path.join(root, "D-Fire")
    for sp in ("train", "test"):
        for sub in ("images", "labels"):
            os.makedirs(os.path.join(top, sp, sub))
    kinds = [(True, True), (True, False), (False, True), (False, False)]
    made = {"train": [], "test": []}
    for sp, n in (("train", 44), ("test", 16)):
        for i in range(n):
            fire, smoke = kinds[i % 4]
            base = bases[i % 5] if sp == "train" else cv2.flip(bases[i % 5], 1)
            noisy = np.clip(base.astype(int) + rng.integers(-6, 7, base.shape), 0, 255).astype(
                np.uint8
            )
            img, lines = paint(noisy, rng, fire, smoke)
            stem = f"{sp}_{i:03d}"
            cv2.imwrite(os.path.join(top, sp, "images", stem + ".jpg"), img)
            with open(os.path.join(top, sp, "labels", stem + ".txt"), "w") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))
            made[sp].append(stem)
    tr = os.path.join(top, "train")
    # a training image identical to a test image, and a near-copy of another
    shutil.copy(
        os.path.join(top, "test", "images", "test_000.jpg"),
        os.path.join(tr, "images", "leak_same.jpg"),
    )
    shutil.copy(
        os.path.join(top, "test", "labels", "test_000.txt"),
        os.path.join(tr, "labels", "leak_same.txt"),
    )
    near = cv2.imread(os.path.join(top, "test", "images", "test_001.jpg"))
    cv2.imwrite(os.path.join(tr, "images", "leak_near.jpg"), cv2.GaussianBlur(near, (3, 3), 0))
    shutil.copy(
        os.path.join(top, "test", "labels", "test_001.txt"),
        os.path.join(tr, "labels", "leak_near.txt"),
    )
    fake_fasdd(drive, bases, os.path.join(top, "test"))
    # broken things
    with open(os.path.join(tr, "images", "broken.jpg"), "wb") as f:
        f.write(b"not an image")
    open(os.path.join(tr, "labels", "broken.txt"), "w").close()
    cv2.imwrite(os.path.join(tr, "images", "no_label.jpg"), bases[0])
    cv2.imwrite(os.path.join(tr, "images", "odd_labels.jpg"), bases[1])
    with open(os.path.join(tr, "labels", "odd_labels.txt"), "w") as f:
        f.write("1 0.95 0.5 0.2 0.3\n")  # runs off the right edge: clipped
        f.write("0 0.5 0.5 0.0 0.1\n")  # zero width: dropped
        f.write("5 0.5 0.5 0.1 0.1\n")  # unknown class id: dropped
        f.write("1 0.5 0.5 0.1\n")  # malformed: dropped
        f.write("0 nan 0.5 0.1 0.1\n")  # non-finite: dropped
    if flat:  # no train / test folders at all
        for sub in ("images", "labels"):
            os.makedirs(os.path.join(top, sub))
            for sp in ("train", "test"):
                d = os.path.join(top, sp, sub)
                for fn in os.listdir(d):
                    shutil.move(os.path.join(d, fn), os.path.join(top, sub, fn))
        for sp in ("train", "test"):
            shutil.rmtree(os.path.join(top, sp))
    os.makedirs(os.path.join(root, "__MACOSX", "D-Fire"))
    open(os.path.join(root, "__MACOSX", "D-Fire", "._train_000.jpg"), "w").close()
    if with_names:
        with open(os.path.join(top, "data.yaml"), "w") as f:
            f.write(f"nc: 2\nnames: {with_names}\n")
    os.makedirs(drive, exist_ok=True)
    zp = os.path.join(drive, "D-Fire.zip")
    shutil.make_archive(zp[:-4], "zip", root)
    # the vehicle notebook's prepared dataset: Bengaluru frames with no fire
    uvh = tempfile.mkdtemp(prefix="uvh_")
    for sp, n in (("train", 10), ("val", 4)):
        os.makedirs(os.path.join(uvh, "ds", "images", sp))
        for i in range(n):
            b = cv2.resize(cv2.imread(frames[i % 5]), (1280, 720))
            b = np.clip(b.astype(int) + rng.integers(-4, 5, b.shape), 0, 255).astype(np.uint8)
            cv2.imwrite(os.path.join(uvh, "ds", "images", sp, f"uvh{sp}{i}.jpg"), b)
    os.makedirs(uvh_drive, exist_ok=True)
    subprocess.run(
        ["tar", "-cf", os.path.join(uvh_drive, "dataset.tar"), "-C", uvh, "ds"], check=True
    )
    return made


def fake_fasdd(drive: str, bases: list, test_dir: str) -> None:
    """A small FASDD package as `fasdd_select.py` writes it (fire = 0, smoke = 1): one file that is a byte-for-byte
    copy of a D-Fire test image and one that is a blurred copy (both must be dropped), and a held-out set with
    letters that includes a near-copy of a training image (dropped from the test)."""
    rng = np.random.default_rng(11)
    pkg = tempfile.mkdtemp(prefix="fasdd_")
    top = os.path.join(pkg, "v3_package")
    for d in ("images/train", "images/val", "labels/train", "labels/val", "heldout/images"):
        os.makedirs(os.path.join(top, d))
    images, held = [], []

    def write(sp: str, stem: str, img: np.ndarray, lines: list) -> None:
        cv2.imwrite(os.path.join(top, "images", sp, stem + ".jpg"), img)
        with open(os.path.join(top, "labels", sp, stem + ".txt"), "w") as f:
            f.write("\n".join(lines) + "\n")

    swap = lambda ls: [("1" if x[0] == "0" else "0") + x[1:] for x in ls]  # noqa: E731  D-Fire's ids -> FASDD's
    for i in range(20):
        sp = "val" if i % 10 == 9 else "train"
        base = cv2.rotate(bases[i % 5], cv2.ROTATE_180)
        noisy = np.clip(base.astype(int) + rng.integers(-6, 7, base.shape), 0, 255).astype(np.uint8)
        img, lines = paint(noisy, rng, True, i % 2 == 0)
        write(sp, f"fd_{i:03d}", img, swap(lines))
        images.append({"stem": f"fd_{i:03d}", "split": sp, "kind": "street" if i % 3 else "other",
                       "file": f"fire_{i}.jpg", "veh": 0.5, "cluster": i})
    shutil.copy(os.path.join(test_dir, "images", "test_002.jpg"), os.path.join(top, "images", "train", "fd_leak_same.jpg"))
    with open(os.path.join(top, "labels", "train", "fd_leak_same.txt"), "w") as f:
        f.write("0 0.5 0.5 0.2 0.2\n")
    near = cv2.GaussianBlur(cv2.imread(os.path.join(test_dir, "images", "test_003.jpg")), (3, 3), 0)
    write("train", "fd_leak_near", near, ["0 0.5 0.5 0.2 0.2"])
    for stem in ("fd_leak_same", "fd_leak_near"):
        images.append({"stem": stem, "split": "train", "kind": "street", "file": stem + ".jpg", "veh": 0.5, "cluster": 99})
    for j, letter in enumerate("VRBOFIXV"):
        base = cv2.flip(cv2.rotate(bases[j % 5], cv2.ROTATE_180), 1) if j % 2 else cv2.flip(bases[j % 5], 0)
        noisy = np.clip(base.astype(int) + rng.integers(-6, 7, base.shape), 0, 255).astype(np.uint8)
        img, _ = paint(noisy, rng, letter != "X", False)
        cv2.imwrite(os.path.join(top, "heldout", "images", f"held_{j}.jpg"), img)
        held.append({"stem": f"held_{j}", "file": f"held_{j}.jpg", "label": letter})
    shutil.copy(os.path.join(top, "images", "train", "fd_003.jpg"), os.path.join(top, "heldout", "images", "held_near.jpg"))
    held.append({"stem": "held_near", "file": "held_near.jpg", "label": "V"})
    json.dump({"stats": {"fake": True}, "settings": {"fake": True}, "images": images, "heldout": held},
              open(os.path.join(top, "fasdd_selection.json"), "w"))
    os.makedirs(drive, exist_ok=True)
    subprocess.run(["tar", "-cf", os.path.join(drive, "fasdd_v3_package.tar"), "-C", pkg, "v3_package"], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--notebook", default=os.path.join(REPO_ROOT, "notebooks", "m8_fire_smoke_v4.ipynb")
    )
    ap.add_argument(
        "--data",
        default=os.path.join(REPO_ROOT, "data", "uvh26"),
        help="holds val_sample/ (5 frames are enough)",
    )
    ap.add_argument("--weights", default="yolo11s.pt", help="Ultralytics' COCO-pretrained YOLO11-S")
    ap.add_argument("--work", default=None)
    args = ap.parse_args()

    import torch  # noqa: PLC0415
    import ultralytics  # noqa: PLC0415

    nb = json.load(open(args.notebook))
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    cell = {k: next(c for c in code if c.startswith(t)) for k, t in TITLES.items()}
    root = args.work or tempfile.mkdtemp(prefix="fire_dryrun_")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    drive, uvh_drive = (
        os.path.join(root, "drive", "itms_fire"),
        os.path.join(root, "drive", "itms_uvh"),
    )
    fake_dfire(args.data, drive, uvh_drive, with_names="['smoke', 'fire']")

    ip, ipd = types.ModuleType("IPython"), types.ModuleType("IPython.display")
    ip.version_info = (8, 30)
    ipd.Image = ipd.display = lambda *a, **k: None
    ip.display = ipd
    sys.modules["IPython"], sys.modules["IPython.display"] = ip, ipd
    real = ultralytics.YOLO

    class Interrupting(real):
        armed = False

        def train(self, **kw):  # noqa: ANN003, ANN201
            if Interrupting.armed and not kw.get("resume"):
                Interrupting.armed = False

                def cut(trainer) -> None:  # noqa: ANN001
                    if trainer.epoch == 0:
                        raise Disconnect

                self.add_callback("on_fit_epoch_end", cut)
            return super().train(**kw)

    ultralytics.YOLO = Interrupting

    def no_network(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("no network in the dry run")

    offline = {"hf_list": no_network, "hf_get": no_network}

    # a fake UVH-26 for the fresh frames: bad files, frames far from everything, frames that are the same camera as a
    # base (training) frame, a duplicate of a base frame, and frames with a big orange patch (hard negatives)
    import random as _random  # noqa: PLC0415

    vs = sorted(glob.glob(os.path.join(args.data, "val_sample", "*.png")))
    base5 = [cv2.resize(cv2.imread(f), (1280, 720)) for f in vs[:5]]
    enc_ = lambda im: cv2.imencode(".png", im)[1].tobytes()  # noqa: E731
    fr = {}
    for i, f in enumerate(vs):
        im = cv2.imread(f)
        for j, t in enumerate((lambda a: cv2.flip(a, 1), lambda a: cv2.rotate(a, cv2.ROTATE_180))):
            x = t(im)
            if (i + j) % 7 == 0:   # some get a big orange blob: what the hard negatives should pick
                h_, w_ = x.shape[:2]
                cv2.rectangle(x, (w_ // 5, h_ // 2), (w_ // 5 + w_ // 6, h_ // 2 + h_ // 5), (0, 140, 255), -1)
            fr[f"f{i:02d}{j}.png"] = enc_(x)
    rng_ = np.random.default_rng(5)
    for k in range(6):   # same camera as a base frame, but shifted: near (9-72 bits), not a duplicate
        b = np.roll(base5[k % 5], 14 + 3 * (k // 5), axis=1)
        fr[f"near{k}.png"] = enc_(np.clip(b.astype(int) + rng_.integers(-3, 4, b.shape), 0, 255).astype(np.uint8))
    n0 = np.clip(base5[0].astype(int) + rng_.integers(-3, 4, base5[0].shape), 0, 255).astype(np.uint8)
    fr["dup0.png"] = enc_(n0)   # a duplicate of a base frame (within 8 bits)
    fr["bad_sha.png"] = open(vs[1], "rb").read()   # an old test frame under another name
    fr["bad_cam.png"] = enc_(np.clip(cv2.imread(vs[0]).astype(int) + rng_.integers(-6, 7, cv2.imread(vs[0]).shape), 0, 255).astype(np.uint8))
    fr["bad_open.png"] = b"not an image"
    fr["zz_named_like_test.png"] = open(vs[0], "rb").read()
    fresh_names = {n: f"UVH-26-Train/data/x/{n}" for n in fr}
    fresh_repo = {"hf_list": lambda folder="": dict(fresh_names), "hf_get": lambda path, tries=10: fr[os.path.basename(path)]}

    def session(
        overrides: dict | None = None, upto: str = "PACKAGE", hf: dict | None = None
    ) -> dict:
        g = {"__name__": "__main__"}
        exec(cell["SETTINGS"], g)
        g.update(
            {
                **SMALL,
                "BASE_WEIGHTS": args.weights,
                "WORK": os.path.join(root, "work"),
                "DRIVE_DIR": drive,
                "UVH_DRIVE_DIR": uvh_drive,
                **(overrides or {}),
            }
        )
        shutil.rmtree(g["WORK"], ignore_errors=True)
        g["OUT"] = drive  # replaces the setup cell (pip, GPU, Drive)
        os.makedirs(g["WORK"], exist_ok=True)
        exec("import os, sys, json, time, shutil, subprocess\nimport torch", g)
        for k in TITLES:
            if k == "SETTINGS":
                continue
            exec(cell[k], g)
            if k == "HELPERS":  # Hugging Face: the fake repository unless a scenario says otherwise
                g.update(hf or fresh_repo)
            if k == upto:
                break
        return g

    def report(g: dict) -> dict:
        return json.load(open(g["REPORT_PATH"]))

    # 1. first session: builds the dataset, and is cut off after the first epoch
    Interrupting.armed = True
    try:
        session()
        raise AssertionError("the simulated disconnect did not happen")
    except Disconnect:
        print("== simulated disconnect after epoch 1")
    man = json.load(open(os.path.join(drive, "fire_manifest.json")))
    print(
        "id map:",
        man["id_map"],
        "| flame share by id:",
        {k: round(v, 3) for k, v in man["flame_share_by_id"].items()},
    )
    print("split:", man["split"])
    print("counts:", man["counts"])
    print("skipped:", man["skipped"])
    print("boxes:", man["box_stats"])
    assert man["id_map"] == {"1": "fire", "0": "smoke"}, man["id_map"]
    assert man["skipped"].get("train: identical to a test image") == 1, man["skipped"]
    assert man["skipped"].get("train: near-copy of a test image", 0) >= 1, man["skipped"]
    assert man["skipped"].get("does not open") == 1, man["skipped"]
    assert man["skipped"].get("no label file") == 1, man["skipped"]
    for k in (
        "box clipped to the image",
        "box empty, tiny or outside the image",
        "malformed line",
        "non-finite box",
        "box with an unknown class id dropped",
    ):
        assert man["box_stats"].get(k), (k, man["box_stats"])
    dr = man["fresh"]["dropped_as_same_camera_as_a_fresh_test_frame"]
    assert man["counts"]["train"]["Bengaluru frames with no fire"] == SMALL["N_NEG_TRAIN"] - dr.get("train", 0)
    assert man["counts"]["val"]["Bengaluru frames with no fire"] == 4 - dr.get("val", 0) + man["fresh"]["extra_val"]
    assert len(man["fresh"]["test2"]) == SMALL["N_TEST2"], man["fresh"]
    assert man["counts"]["train"]["Bengaluru hard negatives (flame-coloured)"] == man["fresh"]["hard_kept"]
    assert not any(r["split"] == "test2" for r in man["images"]), "fresh test frames are in the dataset"
    # version 3: FASDD copies of a D-Fire test image dropped (checksum and fingerprint), the rest imported;
    # flames pasted into Bengaluru training frames (never validation), labelled fire
    assert man["skipped"].get("FASDD: identical to a D-Fire test image") == 1, man["skipped"]
    assert man["skipped"].get("FASDD: near-copy of a D-Fire test image", 0) >= 1, man["skipped"]
    assert man["counts"]["train"]["FASDD images"] > 0 and man["counts"]["val"]["FASDD images"] > 0, man["counts"]
    assert man["counts"]["test"].get("FASDD images", 0) == 0, "FASDD images leaked into the test split"
    assert man["fasdd"]["median_flame_share_id0_id1"][0] >= 0.05, man["fasdd"]
    assert man["pasted"]["frames"] == SMALL["N_PASTE"], man["pasted"]
    assert man["counts"]["train"]["Bengaluru frames with pasted flames"] == SMALL["N_PASTE"]
    assert not man["counts"]["val"].get("Bengaluru frames with pasted flames"), "flames pasted into validation"
    pasted = [r for r in man["images"] if r["stem"].startswith("blrp_")]
    assert len(pasted) == SMALL["N_PASTE"] and all(r["split"] == "train" for r in pasted)
    for r in pasted:
        lab = open(os.path.join(drive, "..", "..", "work", "ds", "labels", "train", r["stem"] + ".txt")).read().split("\n")
        lab = [x for x in lab if x]
        assert lab and all(x.startswith("0 ") for x in lab), (r["stem"], lab)
        assert all(0 <= float(v) <= 1 for x in lab for v in x.split()[1:]), (r["stem"], lab)
    assert "carved" not in man["split"] or man["counts"]["val"]["images"] > 0

    # 2. second session: resumes, finishes, picks the threshold, scores the test, exports, packages
    g = session()
    rep = report(g)
    print(
        "threshold:", rep["threshold"]["t"], rep["threshold"]["chosen_on"], rep["threshold"]["at_t"]
    )
    print("test:", {k: v for k, v in rep["test"].items() if k != "bar"}, rep["test"]["bar"])
    print(
        "onnx check:",
        rep["onnx_max_score_diff"],
        "| bn:",
        rep["bn"],
        "| sessions:",
        rep["sessions"],
    )
    assert rep["threshold"]["at_t"]["fa_bengaluru"] <= 0.01
    ho = rep["heldout"]
    print("held-out:", {k: v for k, v in ho.items() if k != "by_label"}, "| by label:", ho["by_label"])
    assert ho["near_copies_of_training_removed"] >= 1 and ho["images"] == 9, ho
    assert sum(v["n"] for k, v in ho["by_label"].items() if len(k) == 1) == 8, ho["by_label"]
    assert "street (V+R)" in ho["by_label"] and ho["street_n"] == 3, ho   # V, R, and the second V (held_near removed)
    assert set(rep["verdict_in_colab"]) >= {"A_dfire_recall", "C_street_recall", "still_to_check_on_the_laptop"}
    last = torch.load(
        os.path.join(g["RUN"], "weights", "last.pt"), map_location="cpu", weights_only=False
    )
    assert last["optimizer"] is None, "the run did not finish"
    names = set(zipfile.ZipFile(os.path.join(drive, g["ZIP_NAME"])).namelist())
    print("zip:", sorted(names))
    assert {
        "fire_report.json",
        "fire_manifest.json",
        "label_check.jpg",
        "itms_fire_320.onnx",
        "itms_fire_320.pt",
        "runs/fire_320/results.csv",
    } <= names, names

    # version 4: the fresh test frames are kept out of the dataset, by name and by camera; the hard negatives are the
    # most flame-coloured of the pool; the fresh test is scored once and the verdict is written
    man4 = json.load(open(os.path.join(drive, "fire_manifest.json")))
    ds4, uf = os.path.join(g["WORK"], "ds"), os.path.join(g["WORK"], "uvh_fresh")
    t2 = sorted(glob.glob(os.path.join(uf, "test2", "*.jpg")))
    assert len(t2) == SMALL["N_TEST2"], t2
    t2stems = {os.path.basename(x)[:-4] for x in t2}
    assert not any(r["stem"].endswith(x) for r in man4["images"] for x in t2stems), "a fresh test frame is in the dataset"
    t2fp = np.stack([g["dhash16"](cv2.imread(x)) for x in t2])
    assert g["hamming_min"](t2fp, g["TEST_FPS"]).min() > SMALL.get("SAME_CAMERA_BITS", 72), "a fresh frame is an old test camera"
    for x in t2:
        assert hashlib.sha256(open(x, "rb").read()).hexdigest() not in g["TEST_SHA"]
    blr_files = [f for f in glob.glob(os.path.join(ds4, "images", "*", "*.jpg"))
                 if os.path.basename(f).startswith(("blr_", "blrh_"))]
    assert blr_files
    near_t2 = g["hamming_min"](np.stack([g["dhash16"](cv2.imread(f)) for f in blr_files]), t2fp)
    assert near_t2.min() > 72, ("a training or validation frame is the same camera as a fresh test frame", near_t2.min())
    kept = json.load(open(os.path.join(drive, "bengaluru_fresh.json")))["kept"]
    pool_stems = [n[:-4] for n, r in kept if r == "pool"]
    sc = sorted(((g["orange_score"](cv2.imread(os.path.join(uf, "pool", n + ".jpg"))), n) for n in pool_stems), reverse=True)
    dropped_hard = man4["fresh"]["dropped_as_same_camera_as_a_fresh_test_frame"].get("hard negatives", 0)
    top = {n for _, n in sc[: SMALL["N_HARD"] + dropped_hard]}
    hard_stems = {r["stem"][len("blrh_"):] for r in man4["images"] if r["stem"].startswith("blrh_")}
    assert hard_stems and hard_stems <= top, (hard_stems, sc)
    print("fresh frames: test2", len(t2), "| dropped as same camera:", man4["fresh"]["dropped_as_same_camera_as_a_fresh_test_frame"],
          "| hard negatives", sorted(hard_stems), "| skipped:", man4["fresh"]["skipped"])
    t2r = rep["test2"]
    assert t2r["frames"] == SMALL["N_TEST2"] and t2r["max_alarms_allowed"] == 0, t2r
    assert set(rep["verdict_in_colab"]) >= {"A_dfire_recall", "B2_fresh_bengaluru", "C_street_recall", "all_judged_pass"}
    assert "bengaluru_test2_frames.tar" in set(zipfile.ZipFile(os.path.join(drive, g["ZIP_NAME"])).namelist())

    # 3. the export runs as a two-class ONNX model the laptop scorer can read
    import onnxruntime as ort  # noqa: PLC0415

    s = ort.InferenceSession(
        os.path.join(drive, "itms_fire_320.onnx"), providers=["CPUExecutionProvider"]
    )
    meta = s.get_modelmeta().custom_metadata_map
    print("onnx names:", meta.get("names"))
    assert "fire" in meta.get("names", "") and "smoke" in meta.get("names", "")

    # 4. third session: nothing left to do
    t0 = os.path.getmtime(os.path.join(drive, "itms_fire_320.onnx"))
    session()
    assert os.path.getmtime(os.path.join(drive, "itms_fire_320.onnx")) == t0, (
        "finished work was redone"
    )

    # 5. a changed setting is refused
    try:
        session({"SEED": 27}, upto="BUILD")
        raise AssertionError("a changed setting was accepted")
    except AssertionError as e:
        assert "made with" in str(e), e
        print("changed setting refused")

    # 6. a names file that disagrees with the box colours stops the run
    g = session(upto="HELPERS")
    raw = tempfile.mkdtemp(prefix="dfire_wrong_")
    with zipfile.ZipFile(os.path.join(drive, "D-Fire.zip")) as z:
        z.extractall(raw)
    with open(os.path.join(raw, "D-Fire", "data.yaml"), "w") as f:
        f.write("nc: 2\nnames: ['fire', 'smoke']\n")
    g["RAW"] = raw
    exec(cell["READ"].split("if NEED_BUILD:")[0], g)  # scan, names_file, identify_classes
    items, _ = g["scan"](raw)
    try:
        g["identify_classes"](items)
        raise AssertionError("a wrong names file was accepted")
    except AssertionError as e:
        assert "disagrees" in str(e), e
        print("wrong names file refused")
    # 7. a download with no split at all: a seeded split by groups of near-copies
    root2 = tempfile.mkdtemp(prefix="fire_flat_")
    drive2 = os.path.join(root2, "drive", "itms_fire")
    fake_dfire(args.data, drive2, uvh_drive, with_names=None, flat=True)
    drive_saved = drive
    drive = drive2
    session(upto="BUILD")
    man = json.load(open(os.path.join(drive2, "fire_manifest.json")))
    drive = drive_saved
    counts = {k: v.get("images", 0) for k, v in man["counts"].items()}
    print("flat download:", man["split"], "| D-Fire images:", counts, "| skipped:", man["skipped"])
    assert man["split"].startswith("no split in the download"), man["split"]
    assert all(counts[sp] > 0 for sp in ("train", "val", "test")), counts
    assert not any("near-copy of a test image" in k for k in man["skipped"]), (
        "the grouped split left near-copies across it"
    )
    # 8. no Bengaluru frames: version 2 stops instead of carrying on without them --
    # both when building a new dataset and when a dataset built without them is in Drive
    nowhere = os.path.join(root, "drive", "nowhere")
    drive3 = os.path.join(tempfile.mkdtemp(prefix="fire_noblr_"), "drive", "itms_fire")
    unused = os.path.join(root, "drive", "unused_uvh")
    fake_dfire(args.data, drive3, unused, with_names="['smoke', 'fire']")
    drive = drive3
    for case, overrides in (("building", {"UVH_DRIVE_DIR": nowhere}),
                            ("restoring", {"REQUIRE_BENGALURU": True})):
        if case == "restoring":  # a dataset built with the switch off, then a run with it on
            session({"UVH_DRIVE_DIR": nowhere, "REQUIRE_BENGALURU": False}, upto="BUILD", hf=offline)
        try:
            session(overrides, upto="BUILD", hf=offline)
            raise AssertionError(f"{case}: the run carried on without the Bengaluru frames")
        except SystemExit as e:
            assert "no Bengaluru frames" in str(e), e
            print(f"missing Bengaluru frames ({case}): stops")
    drive = drive_saved

    # 9. no Bengaluru frames in Drive: version 2 downloads them from UVH-26 (a fake repository
    # here), keeping out the test frames by name, by content and by camera
    import random  # noqa: PLC0415

    test_pngs = sorted(glob.glob(os.path.join(args.data, "val_sample", "*.png")))
    names = [f"u{i:02d}.png" for i in range(30)] + [os.path.basename(test_pngs[0])]
    order = sorted(names[:-1])  # the test-named file never enters the pool
    random.Random(SMALL.get("SEED", 26)).shuffle(order)
    enc = lambda im: cv2.imencode(".png", im)[1].tobytes()  # noqa: E731
    first = cv2.imread(test_pngs[0])
    rng = np.random.default_rng(3)
    noisy = np.clip(first.astype(int) + rng.integers(-6, 7, first.shape), 0, 255).astype(np.uint8)
    bad = {
        order[0]: open(test_pngs[1], "rb").read(),  # a test frame under another name
        order[1]: enc(noisy),  # a test camera
        order[2]: b"not an image",
        order[3]: None,  # listed, but the download finds nothing
    }
    good = [
        enc(t(cv2.imread(p)))
        for p in test_pngs
        for t in (lambda im: cv2.flip(im, 1), lambda im: cv2.rotate(im, cv2.ROTATE_180))
    ]
    repo = dict(bad)
    for n, data in zip(order[4:], good, strict=False):
        repo[n] = data
    repo[names[-1]] = open(test_pngs[0], "rb").read()  # named like a test frame
    calls = []

    def fake_get(path, tries=10):  # noqa: ANN001, ANN202, ARG001
        calls.append(path)
        return repo[os.path.basename(path)]

    fake = {"hf_list": lambda folder="": {n: f"UVH-26-Train/data/x/{n}" for n in repo},
            "hf_get": fake_get}
    drive4 = os.path.join(tempfile.mkdtemp(prefix="fire_hf_"), "drive", "itms_fire")
    fake_dfire(args.data, drive4, unused, with_names="['smoke', 'fire']")
    drive = drive4
    g = session({"UVH_DRIVE_DIR": nowhere}, upto="BUILD", hf=fake)
    man = json.load(open(os.path.join(drive4, "fire_manifest.json")))
    blr = man["bengaluru"]
    n_blr = {sp: man["counts"][sp].get("Bengaluru frames with no fire") for sp in ("train", "val")}
    print("downloaded Bengaluru frames:", blr["source"], "| skipped:", blr["skipped"], "|", n_blr)
    assert blr["source"].startswith("Hugging Face"), blr
    assert blr["skipped"] == {"identical to a test frame": 1, "looks like a test camera": 1,
                              "does not open": 1, "file missing": 1}, blr["skipped"]
    assert blr["pool"] == len(repo) - 1, "the test-named file entered the pool"
    dr9 = man["fresh"]["dropped_as_same_camera_as_a_fresh_test_frame"]
    assert man["counts"]["train"]["Bengaluru frames with no fire"] == SMALL["N_NEG_TRAIN"] - dr9.get("train", 0)
    assert man["counts"]["val"]["Bengaluru frames with no fire"] == 4 - dr9.get("val", 0) + man["fresh"]["extra_val"]
    kept = {r["source"] for r in man["images"] if r["source"].startswith("uvh26:")}
    assert not kept & {f"uvh26:{os.path.splitext(n)[0]}.jpg" for n in bad}, kept
    assert os.path.exists(os.path.join(drive4, "bengaluru_frames.tar"))
    # a later session that has to rebuild uses the frames saved in Drive, not the network
    for fn in ("fire_manifest.json", "fire_dataset.tar"):
        os.remove(os.path.join(drive4, fn))
    n_calls = len(calls)
    session({"UVH_DRIVE_DIR": nowhere}, upto="BUILD", hf=offline)  # offline: base and fresh frames from Drive's copies
    assert len(calls) == n_calls
    man2 = json.load(open(os.path.join(drive4, "fire_manifest.json")))
    assert man2["counts"] == man["counts"], "the rebuild from Drive's copy differs"
    print("Bengaluru frames: downloaded once, reused from Drive")
    drive = drive_saved

    # 10. the fresh Bengaluru frames cannot be downloaded and are not in Drive: version 4 stops (they are its test)
    drive5 = os.path.join(tempfile.mkdtemp(prefix="fire_nofresh_"), "drive", "itms_fire")
    fake_dfire(args.data, drive5, uvh_drive, with_names="['smoke', 'fire']")
    drive = drive5
    try:
        session(upto="BUILD", hf=offline)
        raise AssertionError("the run carried on without the fresh test frames")
    except SystemExit as e:
        assert "could not get the fresh Bengaluru test frames" in str(e), e
        print("missing fresh Bengaluru frames: stops")
    drive = drive_saved

    # 11. the fresh download: every kind of bad file is counted; a frame of the same camera as a fresh test frame is
    # dropped from training and validation; a duplicate of a used frame is not taken
    def dh(img):
        gr = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sm = cv2.resize(gr, (17, 16), interpolation=cv2.INTER_AREA)
        return np.packbits((sm[:, 1:] > sm[:, :-1]).flatten())

    bits = lambda a, b: int(np.unpackbits(a ^ b).sum())  # noqa: E731
    rg = np.random.default_rng(9)
    repo2 = {}
    for k in range(5):   # pairs of frames of one camera: a frame and the same frame shifted (9-72 bits apart)
        f0 = cv2.flip(cv2.imread(vs[k + 5]), 1)
        f1 = np.roll(f0, 14, axis=1)
        f1 = np.clip(f1.astype(int) + rg.integers(-3, 4, f1.shape), 0, 255).astype(np.uint8)
        d = bits(dh(f0), dh(f1))
        assert 8 < d <= 72, ("the fake same-camera pair is not in the 9-72 bit band", k, d)
        repo2[f"pair{k}a.png"], repo2[f"pair{k}b.png"] = enc_(f0), enc_(f1)
    repo2["dup0.png"] = fr["dup0.png"]   # a copy of a base frame, which is also an old test frame here: caught as that
    pa = cv2.imdecode(np.frombuffer(repo2["pair0a.png"], np.uint8), cv2.IMREAD_COLOR)
    dupa = np.clip(pa.astype(int) + rg.integers(-2, 3, pa.shape), 0, 255).astype(np.uint8)
    assert bits(dh(pa), dh(dupa)) <= 8
    repo2["dupA.png"] = enc_(dupa)   # a duplicate of a fresh frame: whichever comes second is not taken
    repo2["bad_sha.png"], repo2["bad_cam.png"] = fr["bad_sha.png"], fr["bad_cam.png"]
    repo2["bad_open.png"], repo2["missing.png"] = b"not an image", None
    hf2 = {"hf_list": lambda folder="": {n: f"UVH-26-Train/data/x/{n}" for n in repo2},
           "hf_get": lambda path, tries=10: repo2[os.path.basename(path)]}
    drive6 = os.path.join(tempfile.mkdtemp(prefix="fire_fresh_"), "drive", "itms_fire")
    fake_dfire(args.data, drive6, uvh_drive, with_names="['smoke', 'fire']")
    drive = drive6
    g = session({"WORK": os.path.join(root, "work_unit"), "N_MINE_POOL": 20}, upto="BUILD", hf=hf2)   # more wanted than there is: all are looked at
    man6 = json.load(open(os.path.join(drive6, "fire_manifest.json")))
    fi = man6["fresh"]
    print("fresh download skipped:", fi["skipped"], "| dropped as same camera:", fi["dropped_as_same_camera_as_a_fresh_test_frame"])
    assert fi["skipped"] == {"identical to an old test frame": 1, "looks like an old test camera": 2, "does not open": 1,
                             "file missing": 1, "duplicate of a frame already used": 1}, fi["skipped"]
    # every frame left in training, validation and the hard negatives is more than 72 bits from every fresh test frame
    ds6, uf6 = os.path.join(g["WORK"], "ds"), os.path.join(g["WORK"], "uvh_fresh")
    t26 = np.stack([g["dhash16"](cv2.imread(x)) for x in sorted(glob.glob(os.path.join(uf6, "test2", "*.jpg")))])
    left = [f for f in glob.glob(os.path.join(ds6, "images", "*", "*.jpg")) if os.path.basename(f).startswith(("blr_", "blrh_"))]
    assert g["hamming_min"](np.stack([g["dhash16"](cv2.imread(f)) for f in left]), t26).min() > 72
    assert sum(fi["dropped_as_same_camera_as_a_fresh_test_frame"].values()) > 0, (
        "no frame was dropped although fresh test frames share cameras with others", fi)
    drive = drive_saved
    print("DRY RUN OK")


if __name__ == "__main__":
    main()

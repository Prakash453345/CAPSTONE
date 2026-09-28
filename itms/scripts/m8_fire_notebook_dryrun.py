"""Dry-run the fire and smoke notebook (`notebooks/m8_fire_smoke.ipynb`) on CPU (M8).

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
- a changed setting refused.

Needs torch, ultralytics==8.4.163, onnx, onnxruntime and onnxslim: not the
project venv.

    python scripts/m8_fire_notebook_dryrun.py --data data/uvh26 --weights yolo11s.pt
"""

from __future__ import annotations

import argparse
import glob
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--notebook", default=os.path.join(REPO_ROOT, "notebooks", "m8_fire_smoke.ipynb")
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
            if k == "HELPERS":  # Hugging Face: offline unless a scenario brings a fake repository
                g.update(hf or offline)
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
    assert man["counts"]["train"]["Bengaluru frames with no fire"] == SMALL["N_NEG_TRAIN"]
    assert man["counts"]["val"]["Bengaluru frames with no fire"] == 4
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
    assert not any("near-copy" in k for k in man["skipped"]), (
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
            session({"UVH_DRIVE_DIR": nowhere, "REQUIRE_BENGALURU": False}, upto="BUILD")
        try:
            session(overrides, upto="BUILD")
            raise AssertionError(f"{case}: the run carried on without the Bengaluru frames")
        except SystemExit as e:
            assert "no Bengaluru frames" in str(e), e
            print(f"missing Bengaluru frames ({case}): stops")
    drive = drive_saved

    # 9. no Bengaluru frames in Drive: version 2 downloads them from UVH-26 (a fake repository
    # here), keeping out the test frames by name, by content and by camera
    import random  # noqa: PLC0415

    test_pngs = sorted(glob.glob(os.path.join(args.data, "val_sample", "*.png")))
    names = [f"u{i:02d}.png" for i in range(14)] + [os.path.basename(test_pngs[0])]
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
    g = session({"UVH_DRIVE_DIR": nowhere, "N_NEG_VAL": 4}, upto="BUILD", hf=fake)
    man = json.load(open(os.path.join(drive4, "fire_manifest.json")))
    blr = man["bengaluru"]
    n_blr = {sp: man["counts"][sp].get("Bengaluru frames with no fire") for sp in ("train", "val")}
    print("downloaded Bengaluru frames:", blr["source"], "| skipped:", blr["skipped"], "|", n_blr)
    assert blr["source"].startswith("Hugging Face"), blr
    assert blr["skipped"] == {"identical to a test frame": 1, "looks like a test camera": 1,
                              "does not open": 1, "file missing": 1}, blr["skipped"]
    assert blr["pool"] == len(repo) - 1, "the test-named file entered the pool"
    assert man["counts"]["train"]["Bengaluru frames with no fire"] == SMALL["N_NEG_TRAIN"]
    assert man["counts"]["val"]["Bengaluru frames with no fire"] == 4
    kept = {r["source"] for r in man["images"] if r["source"].startswith("uvh26:")}
    assert not kept & {f"uvh26:{os.path.splitext(n)[0]}.jpg" for n in bad}, kept
    assert os.path.exists(os.path.join(drive4, "bengaluru_frames.tar"))
    # a later session that has to rebuild uses the frames saved in Drive, not the network
    for fn in ("fire_manifest.json", "fire_dataset.tar"):
        os.remove(os.path.join(drive4, fn))
    n_calls = len(calls)
    session({"UVH_DRIVE_DIR": nowhere, "N_NEG_VAL": 4}, upto="BUILD")  # offline
    assert len(calls) == n_calls
    man2 = json.load(open(os.path.join(drive4, "fire_manifest.json")))
    assert man2["counts"] == man["counts"], "the rebuild from Drive's copy differs"
    print("Bengaluru frames: downloaded once, reused from Drive")
    drive = drive_saved
    print("DRY RUN OK")


if __name__ == "__main__":
    main()

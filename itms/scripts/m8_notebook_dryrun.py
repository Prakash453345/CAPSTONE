"""Dry-run the fine-tuning notebook (`notebooks/m8_uvh26_finetune.ipynb`) on CPU (M8).

A tiny fake copy of IISc's repository is built from the labelled test sample,
and the notebook's own cells run against it: every code path the Colab run
takes except the GPU, Google Drive and the network.

It covers the dataset guards (an exact copy of a test frame, a same-camera
look-alike, a broken file, a wrong size, an empty frame; 'Others', crowd,
tiny, clipped and duplicate boxes), the BatchNorm repair and the control
export, full-precision training with a disconnect after the first epoch and
an exact resume, the export checks, a run with nothing left to do, the
fallback when no full-precision copy exists, a changed setting, and the NaN
guard.

Needs torch, ultralytics==8.4.163, onnx, onnxruntime and onnxslim: not the
project venv.

    python scripts/m8_notebook_dryrun.py --data data/uvh26
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import zipfile

import cv2
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLES = {
    "SETTINGS": "# ---- Settings",
    "TESTC": "# ---- The 250 test frames",
    "HELPERS": "# ---- Helpers",
    "LABELS": "# ---- Labels",
    "DATASET": "# ---- The dataset",
    "SHEET": "# ---- Look at the labels",
    "IISC": "# ---- IISc's model",
    "STEPS": "# ---- Training and export",
    "RUN": "# ---- Run:",
    "DOWNLOAD": "# ---- Download",
}
SMALL = {
    "N_TRAIN": 4,
    "N_HOLDOUT": 1,
    "SIZES": [320],
    "EPOCHS": 2,
    "PATIENCE": 5,
    "BATCH": {320: 2},
    "BN_BATCHES": 2,
    "BN_WORKERS": 0,
}


class Disconnect(Exception):
    """A simulated Colab disconnect."""


class FakeRepo:
    """IISc's repository in miniature: five labelled sample frames, each playing an edge case."""

    def __init__(self, data: str, iisc_pt: str) -> None:
        self.files: dict[str, bytes] = {}
        self.images: list[dict] = []
        self.annots: list[dict] = []
        self.calls: list[str] = []
        coco = json.load(open(os.path.join(data, "val_sample.json")))
        self.cats = coco["categories"]
        cid = {c["name"]: c["id"] for c in self.cats}
        by_name = {im["file_name"]: im for im in coco["images"]}
        frames = sorted(glob.glob(os.path.join(data, "val_sample", "*.png")))[:5]
        assert len(frames) == 5, (
            f"need 5 frames in {data}/val_sample (scripts/m8_fetch_uvh26_sample.py)"
        )

        def boxes(fn: str) -> list:
            iid = by_name[os.path.basename(fn)]["id"]
            return [
                (a["category_id"], a["bbox"]) for a in coco["annotations"] if a["image_id"] == iid
            ]

        def noisy(fn: str, seed: int) -> bytes:
            img = cv2.imread(fn).astype(np.int16)
            img += np.random.default_rng(seed).integers(-3, 4, img.shape).astype(np.int16)
            return cv2.imencode(".png", np.clip(img, 0, 255).astype(np.uint8))[1].tobytes()

        # the first two frames play test frames; the other 248 fingerprints are random,
        # far from anything
        self.test = {"dhash16": {}, "sha256": {}}
        for fn in frames[:2]:
            b = open(fn, "rb").read()
            g = cv2.cvtColor(
                cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY
            )
            g = cv2.resize(g, (17, 16), interpolation=cv2.INTER_AREA)
            self.test["dhash16"][os.path.basename(fn)] = (
                np.packbits((g[:, 1:] > g[:, :-1]).flatten()).tobytes().hex()
            )
            self.test["sha256"][os.path.basename(fn)] = hashlib.sha256(b).hexdigest()
        rng = np.random.default_rng(0)
        for k in range(248):
            self.test["dhash16"][f"pad{k}.png"] = (
                rng.integers(0, 256, 32, dtype=np.uint8).tobytes().hex()
            )
            self.test["sha256"][f"pad{k}.png"] = f"{k:064x}"

        self.add("a_exact_copy.png", open(frames[0], "rb").read(), boxes(frames[0]))
        self.add("b_same_camera.png", noisy(frames[1], 1), boxes(frames[1]))
        dup = boxes(frames[2])[0]
        edge = [
            *boxes(frames[2]),
            (cid["Others"], [10, 10, 50, 50]),
            (cid["Sedan"], [1900, 1000, 100, 200]),  # clipped at the right and bottom
            (cid["Sedan"], [500, 500, 0.5, 30]),  # too thin
            (cid["Sedan"], [3000, 500, 40, 40]),  # outside the image
            (cid["Bus"], [100, 100, 80, 60], {"iscrowd": 1}),
            (dup[0], [dup[1][0] + 0.5, dup[1][1], dup[1][2], dup[1][3]]),
        ]  # a duplicate
        self.add("c_edges.png", noisy(frames[2], 2), edge)
        self.add("d_ok.png", noisy(frames[3], 3), boxes(frames[3]))
        self.add("e_ok.png", noisy(frames[4], 4), boxes(frames[4]))
        self.add("f_broken.png", b"not a png at all", boxes(frames[4]))
        small = cv2.imencode(".png", cv2.resize(cv2.imread(frames[3]), (960, 540)))[1].tobytes()
        self.add("g_wrong_size.png", small, boxes(frames[3]))
        self.add("h_empty.png", noisy(frames[4], 9), [])
        self.add("j_ok.png", noisy(frames[3], 7), boxes(frames[3]))
        self.add("pad0.png", noisy(frames[3], 8), boxes(frames[3]))  # named like a test frame
        self.add("k_missing.png", None, boxes(frames[4]))  # listed, but the download fails
        self.files["UVH-26-Train/UVH-26-MV-Train.json"] = json.dumps(
            {"categories": self.cats, "images": self.images, "annotations": self.annots}
        ).encode()
        self.files["weights/YOLOv11-S/UVH-26-MV-YOLOv11-S.pt"] = open(iisc_pt, "rb").read()
        self.files["UVH-26-Train/data/000/unlabelled.png"] = b"x"
        self.probe = frames[3]

    def add(
        self, name: str, data: bytes | None, boxes: list, w: int = 1920, h: int = 1080
    ) -> None:
        iid = len(self.images) + 1
        self.images.append({"id": iid, "file_name": name, "width": w, "height": h})
        for cat, bbox, *extra in boxes:
            self.annots.append(
                {
                    "id": len(self.annots) + 1,
                    "image_id": iid,
                    "category_id": cat,
                    "bbox": bbox,
                    "area": bbox[2] * bbox[3],
                    **(extra[0] if extra else {}),
                }
            )
        self.files[f"UVH-26-Train/data/000/{name}"] = data

    def fetch(
        self, path: str, size: int | None = None, dataset: bool = True, tries: int = 10
    ) -> bytes | None:
        self.calls.append(path)
        data = self.files.get(path)
        if data is not None and size is not None and len(data) != size:
            raise RuntimeError("size mismatch in the fake repository")
        return data

    def api(self):  # noqa: ANN201 -- stands in for huggingface_hub.HfApi
        repo = self

        class Entry:
            def __init__(self, path: str, size: int) -> None:
                self.path, self.size, self.lfs = path, size, {"size": size}

        class Api:
            def __init__(self, token: str | None = None) -> None:
                pass

            def list_repo_tree(self, repo_id, repo_type, path_in_repo, recursive):  # noqa: ANN001, ANN202
                return [
                    Entry(p, 100 if b is None else len(b))
                    for p, b in repo.files.items()
                    if p.startswith(path_in_repo)
                ]

        return Api


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--notebook", default=os.path.join(REPO_ROOT, "notebooks", "m8_uvh26_finetune.ipynb")
    )
    ap.add_argument(
        "--data",
        default=os.path.join(REPO_ROOT, "data", "uvh26"),
        help="holds val_sample/, val_sample.json and UVH-26-MV-YOLOv11-S.pt",
    )
    ap.add_argument("--work", default=None, help="scratch folder (default: a new temporary one)")
    args = ap.parse_args()

    import huggingface_hub  # noqa: PLC0415
    import torch  # noqa: PLC0415

    nb = json.load(open(args.notebook))
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    cell = {k: next(c for c in code if c.startswith(t)) for k, t in TITLES.items()}
    root = args.work or tempfile.mkdtemp(prefix="nb_dryrun_")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    repo = FakeRepo(args.data, os.path.join(args.data, "UVH-26-MV-YOLOv11-S.pt"))
    huggingface_hub.HfApi = repo.api()
    ip, ipd = types.ModuleType("IPython"), types.ModuleType("IPython.display")
    ip.version_info = (8, 30)
    ipd.Image = ipd.display = lambda *a, **k: None
    ip.display = ipd
    sys.modules["IPython"], sys.modules["IPython.display"] = ip, ipd

    def session(overrides: dict | None = None) -> dict:
        """One 'Run all' in a fresh runtime (local disk wiped, Drive kept), up to the
        training steps."""
        g = {"__name__": "__main__"}
        exec(cell["SETTINGS"], g)
        g.update(
            SMALL,
            WORK=os.path.join(root, "work"),
            DRIVE_DIR=os.path.join(root, "drive"),
            **(overrides or {}),
        )
        shutil.rmtree(g["WORK"], ignore_errors=True)
        g.update(OUT=g["DRIVE_DIR"], HF_TOKEN=None)  # replaces the setup cell (pip, GPU, Drive)
        os.makedirs(g["OUT"], exist_ok=True)
        os.makedirs(g["WORK"], exist_ok=True)
        exec("import os, sys, json, time, shutil, subprocess\nimport torch", g)
        exec(cell["TESTC"], g)
        g["TEST"] = repo.test
        exec(cell["HELPERS"], g)
        g["fetch_bytes"] = repo.fetch
        for k in ("LABELS", "DATASET", "SHEET", "IISC", "STEPS"):
            exec(cell[k], g)
        return g

    def report(g: dict) -> dict:
        return json.load(open(g["REPORT_PATH"]))

    # 1. first session: builds the dataset; training is cut off after its first epoch
    g = session()
    man = g["man"]
    assert man["train"] and len(man["holdout"]) == 1, man
    assert set(man["skipped"]) >= {
        "identical to a test frame",
        "looks like a test camera",
        "does not open",
        "size differs from the label file",
        "file missing",
    }, man["skipped"]
    assert "pad0.png" not in man["train"] + man["holdout"], "a frame named like a test frame got in"
    print("skipped:", man["skipped"])
    try:
        g["six_of"]("Tractor")
        raise AssertionError("an unknown label was accepted")
    except ValueError as e:
        print("unknown label stops the run:", e)

    def disconnect(trainer) -> None:  # noqa: ANN001
        if trainer.epoch == 0:
            raise Disconnect

    g["CALLBACKS"].append(("on_fit_epoch_end", disconnect))
    try:
        exec(cell["RUN"], g)
        raise AssertionError("the simulated disconnect did not happen")
    except Disconnect:
        print("== simulated disconnect after epoch 1")
    c = report(g)["controls"]["320"]
    print(
        "control:",
        c["bn_before"]["nonfinite_channels"],
        "broken channels ->",
        c["bn_recalibration"]["nonfinite_channels"],
        "| above half precision:",
        c["bn_recalibration"]["channels_over_fp16_max"],
        "| max variance",
        c["bn_recalibration"]["max_running_var"],
        "|",
        c["onnx_check"],
    )
    assert (
        c["bn_before"]["nonfinite_channels"] == 584
        and c["bn_recalibration"]["nonfinite_channels"] == 0
    )
    assert c["onnx_check"]["outputs"] == 4 + 14
    run_dir = os.path.join(g["RUNS"], "ft6fp32_320", "weights")
    best = torch.load(os.path.join(run_dir, "best_fp32.pt"), map_location="cpu", weights_only=False)
    assert best["optimizer"] is None and best["model"].model[0].conv.weight.dtype == torch.float32
    assert os.path.exists(os.path.join(run_dir, "last.pt"))

    # 2. second session: resumes exactly, finishes, exports, packages
    n_calls = len(repo.calls)
    g = session()
    assert "UVH-26-Train/data/000/d_ok.png" not in repo.calls[n_calls:], (
        "the dataset was rebuilt, not restored"
    )
    exec(cell["RUN"], g)
    m = report(g)["models"]["320"]
    print(
        "model:",
        {k: m[k] for k in ("source", "best_epoch", "holdout_map50", "onnx_check", "sessions")},
    )
    print("model BatchNorm after the resume:", m["bn"])
    assert m["source"].startswith("best epoch") and m["onnx_check"]["outputs"] == 4 + 6
    assert m["sessions"][0]["resumed"] == [{"from_epoch": 1, "full_precision_restored": True}], m[
        "sessions"
    ]
    assert m["bn"]["nonfinite_channels"] == 0 and m["bn"]["channels_at_fp16_max"] == 0, m["bn"]
    assert m["bn"]["channels_over_fp16_max"] > 0, "the resumed model lost its large variances"
    last = torch.load(os.path.join(run_dir, "last.pt"), map_location="cpu", weights_only=False)
    assert last["optimizer"] is None, "the run did not finish"
    names = set(zipfile.ZipFile(os.path.join(g["OUT"], g["ZIP_NAME"])).namelist())
    assert {
        "train_report_v2.json",
        "dataset_manifest.json",
        "iisc_bnfix_320.onnx",
        "itms_six_fp32_320.onnx",
        "itms_six_fp32_320.pt",
        "runs/ft6fp32_320/results.csv",
    } <= names, names

    # 3. the exports run in the project's own detector
    sys.path.insert(0, os.path.join(REPO_ROOT, "services", "vision-service"))
    from vision_service.detect.yolo import OnnxDetector  # noqa: PLC0415

    for fn in ("iisc_bnfix_320.onnx", "itms_six_fp32_320.onnx"):
        dets = OnnxDetector(os.path.join(g["OUT"], fn), conf=0.1, imgsz=320).detect(
            cv2.imread(repo.probe)
        )
        print(fn, len(dets), "detections:", sorted({str(d.vclass) for d in dets}))

    # 4. third session: nothing left to do but the zip
    onnx = os.path.join(g["OUT"], "itms_six_fp32_320.onnx")
    t0 = os.path.getmtime(onnx)
    g = session()
    exec(cell["RUN"], g)
    assert os.path.getmtime(onnx) == t0, "finished work was redone"
    exec(cell["DOWNLOAD"], g)

    # 5. no full-precision copy: the statistics are re-estimated from the half-precision best.pt
    os.remove(os.path.join(run_dir, "best_fp32.pt"))
    rep = report(g)
    del rep["models"]["320"]
    json.dump(rep, open(g["REPORT_PATH"], "w"))
    g = session()
    exec(cell["RUN"], g)
    m = report(g)["models"]["320"]
    print("fallback:", m["source"], m["onnx_check"])
    assert m["source"].startswith("best.pt") and m["bn"]["nonfinite_channels"] == 0

    # 6. the repair is reproducible: the same statistics again, from scratch
    from ultralytics import YOLO  # noqa: PLC0415

    again = YOLO(g["w_path"]).model
    g["bn_recalibrate"](again, g["YAML"], 320, g["IISC_ARGS"], batch=16)
    saved = torch.load(
        os.path.join(g["OUT"], "iisc_bnfix_320.pt"), map_location="cpu", weights_only=False
    )["model"]
    pairs = [
        (a, b)
        for a, b in zip(again.modules(), saved.modules(), strict=True)
        if isinstance(a, torch.nn.BatchNorm2d)
    ]
    worst = max(
        float(((a.running_var - b.running_var).abs() / b.running_var.abs().clamp(min=1.0)).max())
        for a, b in pairs
    )
    print(f"repair repeated: {len(pairs)} BatchNorm layers, largest relative change {worst:.1e}")
    assert worst < 1e-5, "the repair is not reproducible"  # the same images; float rounding only
    # 7. a changed setting is refused, not mixed with the dataset made under the old one
    try:
        session({"SEED": 27})
        raise AssertionError("a changed setting was accepted")
    except AssertionError as e:
        assert "made with" in str(e), e

    # 8. the NaN guard
    trainer = types.SimpleNamespace(epoch=3, loss=torch.tensor(float("nan")))
    try:
        g["nan_guard"](trainer)
        raise AssertionError("a NaN loss passed the guard")
    except RuntimeError as e:
        print("nan guard:", e)
    for ok in (torch.tensor(1.5), None):
        g["nan_guard"](types.SimpleNamespace(epoch=3, loss=ok))
    print("fetched:", sorted(set(repo.calls)))
    print("DRY RUN OK")


if __name__ == "__main__":
    main()

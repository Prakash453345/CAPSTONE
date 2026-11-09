"""Train the M8 vehicle detector on the FULL UVH-26 training split (M8).

Targets and pass bars: baselines/2026-10-28_m8_full_train/TARGETS_LOCKED.md (fixed before any training).

    prep   fetch every labelled UVH-26-MV-Train frame (about 21,000), store it at most 1,280 px wide as JPEG, write YOLO labels
           with all 14 UVH classes, set aside 500 hold-out frames (seed 26) that only decide the best epoch, and check that no
           validation file name is among the training names.  Resumable.  Needs the internet; no GPU.
    train  one run of three (`s_iisc`, `s_coco`, `m_coco`) for a fixed time budget, the best hold-out epoch kept in full
           precision, exported to ONNX (dynamic, 640 px) and checked against the PyTorch model.  Needs a GPU.

    python scripts/m8_train_full.py prep  --out /kaggle/working/ds
    python scripts/m8_train_full.py train --ds /kaggle/input/uvh26-train-1280/ds --run s_iisc --time 8 --out /kaggle/working/run_s_iisc \\
           --iisc-weights /kaggle/input/uvh26-fullval-bundle/models/UVH-26-MV-YOLOv11-S.pt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
import threading
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import numpy as np

REPO = "iisc-aim/UVH-26"
TRAIN_LABELS = "UVH-26-Train/UVH-26-MV-Train.json"
VAL_LABELS = "UVH-26-Val/UVH-26-MV-Val.json"
ULTRALYTICS_VERSION = "8.4.163"
ALBUMENTATIONS_VERSION = "2.0.8"
IISC_SHA256 = "12dbeb8f6fa207d19446fa652fc4313359fbec267027c8c01641004dcf1d0150"
MAX_SIDE, N_HOLDOUT, SEED, IMGSZ = 1280, 500, 26, 640
FP16_MAX = 65504.0
BN_BATCHES = 64

# fixed in TARGETS_LOCKED.md
RUNS = {
    "s_iisc": dict(start="iisc_bnfix", amp=False, lr0=0.0005, batch=16, mosaic=0.5, close_mosaic=5),
    "s_coco": dict(start="yolo11s.pt", amp=True, lr0=0.001, batch=32, mosaic=1.0, close_mosaic=3),
    "m_coco": dict(start="yolo11m.pt", amp=True, lr0=0.001, batch=16, mosaic=1.0, close_mosaic=3),
}


# ------------------------------------------------------------------ prep

_local = threading.local()


def _session():
    import requests  # noqa: PLC0415

    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        tok = os.environ.get("HF_TOKEN")
        if tok:
            _local.s.headers["Authorization"] = f"Bearer {tok}"
    return _local.s


def fetch_bytes(path: str, size: int | None = None, tries: int = 10) -> bytes | None:
    import requests  # noqa: PLC0415

    delay = 5
    for _ in range(tries):
        try:
            r = _session().get(f"https://huggingface.co/datasets/{REPO}/resolve/main/{path}", timeout=180)
            if r.status_code == 200 and (size is None or len(r.content) == size):
                return r.content
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep(min(int(r.headers.get("Retry-After", delay)), 300))
        except requests.RequestException:
            pass
        time.sleep(delay)
        delay = min(delay * 2, 300)
    raise RuntimeError(f"could not download {path} after {tries} tries")


def sha256_file(p: str | Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def yolo_lines(anns: list[dict], W: int, H: int, cls_of: dict[int, int], names: list[str]):
    """COCO boxes of one image -> YOLO label lines (all 14 classes kept), with what was dropped."""
    lines, st, kept = [], Counter(), []
    for a in anns:
        if a.get("iscrowd", 0):
            st["crowd box dropped"] += 1
            continue
        x, y, w, h = (float(v) for v in a["bbox"])
        x1, y1, x2, y2 = max(0.0, x), max(0.0, y), min(float(W), x + w), min(float(H), y + h)
        if x2 - x1 < 2 or y2 - y1 < 2:
            st["box empty, tiny or outside the image"] += 1
            continue
        k = cls_of[a["category_id"]]
        if any(k == k2 and _iou((x1, y1, x2, y2), b2) > 0.95 for k2, b2 in kept):
            st["duplicate box dropped"] += 1
            continue
        if (x1, y1, x2, y2) != (x, y, x + w, y + h):
            st["box clipped to the image"] += 1
        kept.append((k, (x1, y1, x2, y2)))
        lines.append(f"{k} {(x1 + x2) / 2 / W:.6f} {(y1 + y2) / 2 / H:.6f} {(x2 - x1) / W:.6f} {(y2 - y1) / H:.6f}")
        st[f"boxes: {names[k]}"] += 1
    return lines, st


def cmd_prep(a) -> None:
    import cv2  # noqa: PLC0415

    out = Path(a.out)
    for d in ("images/train", "images/val", "labels/train", "labels/val"):
        (out / d).mkdir(parents=True, exist_ok=True)
    if a.local_images:
        coco = json.loads(Path(a.local_labels).read_text())
        files = {p.name: (str(p), None) for p in Path(a.local_images).iterdir()}
        val_names = {im["file_name"] for im in json.loads(Path(a.local_val_labels).read_text())["images"]}

        def get(path, size):
            return Path(path).read_bytes()
    else:
        coco = json.loads(fetch_bytes(TRAIN_LABELS))
        val_names = {os.path.basename(im["file_name"]) for im in json.loads(fetch_bytes(VAL_LABELS))["images"]}
        from huggingface_hub import HfApi  # noqa: PLC0415

        files = {}
        for f in HfApi(token=os.environ.get("HF_TOKEN")).list_repo_tree(
                REPO, repo_type="dataset", path_in_repo="UVH-26-Train/data", recursive=True):
            if f.path.lower().endswith((".png", ".jpg", ".jpeg")):
                lfs = getattr(f, "lfs", None)
                size = lfs.get("size") if isinstance(lfs, dict) else getattr(lfs, "size", None)
                files[os.path.basename(f.path)] = (f.path, size or getattr(f, "size", None))
        get = fetch_bytes
    cats = sorted(coco["categories"], key=lambda c: c["id"])
    names = [c["name"] for c in cats]
    cls_of = {c["id"]: i for i, c in enumerate(cats)}
    (out / "names.json").write_text(json.dumps(names))
    anns: dict[int, list] = {}
    for an in coco["annotations"]:
        anns.setdefault(an["image_id"], []).append(an)
    images = {}
    for im in coco["images"]:
        n = os.path.basename(im["file_name"])
        assert n not in images, f"two labelled images share the name {n}"
        images[n] = im
    pool = sorted(set(images) & set(files))
    leak = sorted(set(pool) & val_names)
    if leak:
        raise SystemExit(f"{len(leak)} training file names are validation file names, e.g. {leak[:3]}; stopping")
    print(f"{len(images)} labelled training frames, {len(files)} image files, {len(pool)} usable; "
          f"0 share a name with the {len(val_names)} validation frames", flush=True)
    order = pool[:]
    random.Random(SEED).shuffle(order)
    n_hold = a.holdout
    holdout = set(order[:n_hold])
    skipped: dict[str, list] = {}
    stats: Counter = Counter()

    def one(name: str):
        split = "val" if name in holdout else "train"
        stem = os.path.splitext(name)[0]
        jpg, txt = out / f"images/{split}/{stem}.jpg", out / f"labels/{split}/{stem}.txt"
        if jpg.exists() and txt.exists():
            return name, split, None, None
        data = get(*files[name])
        if data is None:
            return name, split, "file missing", None
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return name, split, "does not open", None
        meta = images[name]
        H, W = img.shape[:2]
        if (W, H) != (meta["width"], meta["height"]):
            return name, split, "size differs from the label file", None
        lines, st = yolo_lines(anns.get(meta["id"], []), W, H, cls_of, names)
        if max(H, W) > MAX_SIDE:
            s = MAX_SIDE / max(H, W)
            img = cv2.resize(img, (round(W * s), round(H * s)), interpolation=cv2.INTER_AREA)
        assert cv2.imwrite(str(jpg) + ".tmp.jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        os.replace(str(jpg) + ".tmp.jpg", jpg)
        txt.write_text("\n".join(lines) + ("\n" if lines else ""))
        return name, split, None, st

    t0, done = time.time(), 0
    todo = order[:a.limit] if a.limit else order
    with ThreadPoolExecutor(a.workers) as ex:
        for i in range(0, len(todo), 64):
            for name, split, why, st in ex.map(one, todo[i:i + 64]):
                done += 1
                if why:
                    skipped.setdefault(why, []).append(name)
                if st:
                    stats.update(st)
            print(f"  {done}/{len(todo)} done, {sum(map(len, skipped.values()))} skipped, {time.time() - t0:.0f} s",
                  flush=True)
    tr = sorted(p.stem for p in (out / "images/train").glob("*.jpg"))
    ho = sorted(p.stem for p in (out / "images/val").glob("*.jpg"))
    by_stem = {os.path.splitext(n)[0]: n for n in pool}
    counts = {sp: Counter() for sp in ("train", "val")}
    for sp in counts:
        for p in (out / f"labels/{sp}").glob("*.txt"):
            for line in p.read_text().splitlines():
                counts[sp][names[int(line.split()[0])]] += 1
    if not a.limit and not a.local_images:
        assert len(ho) >= n_hold - 20, f"only {len(ho)} hold-out frames"
    man = {"settings": {"N_HOLDOUT": n_hold, "SEED": SEED, "MAX_SIDE": MAX_SIDE, "classes": 14},
           "labels_file": TRAIN_LABELS, "names": names,
           "train": [by_stem[s] for s in tr], "holdout": [by_stem[s] for s in ho],
           "skipped": skipped, "box_stats": dict(stats), "boxes_by_class": {sp: dict(c) for sp, c in counts.items()},
           "validation_names_checked": len(val_names), "shared_with_validation": 0}
    (out / "dataset_manifest.json").write_text(json.dumps(man, indent=1))
    print(f"done: {len(tr)} train + {len(ho)} hold-out frames; skipped {({k: len(v) for k, v in skipped.items()})}",
          flush=True)


# ------------------------------------------------------------------ pack / unpack
# Kaggle keeps at most 500 files of a notebook's output, so the 21,000 frames travel as a few large tar files.

def cmd_pack(a) -> None:
    import tarfile  # noqa: PLC0415

    ds, out = Path(a.ds).resolve(), Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    man = json.loads((ds / "dataset_manifest.json").read_text())
    files = sorted(p for sp in ("train", "val") for d in ("images", "labels") for p in (ds / d / sp).iterdir()
                   if p.is_file() and not p.name.endswith(".tmp.jpg"))
    limit, shards, cur, size, tf = a.shard_mb * 1024 * 1024, [], [], 0, None

    def close():
        nonlocal tf, cur, size
        if tf:
            tf.close()
            shards.append({"name": f"shard_{len(shards):04d}.tar", "files": len(cur)})
            cur, size, tf = [], 0, None

    for p in files:
        if tf is None:
            tf = tarfile.open(out / f"shard_{len(shards):04d}.tar", "w")
        tf.add(p, arcname=str(p.relative_to(ds)))
        cur.append(p.name)
        size += p.stat().st_size
        if size >= limit:
            close()
    close()
    n_img = {sp: len(list((ds / f"images/{sp}").glob("*.jpg"))) for sp in ("train", "val")}
    assert n_img["train"] == len(man["train"]) and n_img["val"] == len(man["holdout"]), (n_img, len(man["train"]))
    info = {"shards": shards, "files": len(files), "images": n_img}
    (out / "shards.json").write_text(json.dumps(info))
    for n in ("dataset_manifest.json", "names.json"):
        shutil.copy(ds / n, out / n)
    print(f"packed {len(files)} files ({n_img['train']} train + {n_img['val']} hold-out frames) into {len(shards)} tar files; "
          f"{len(shards) + 3} output files in all", flush=True)


def cmd_unpack(a) -> None:
    import tarfile  # noqa: PLC0415

    src, out = Path(a.src).resolve(), Path(a.out).resolve()
    info = json.loads((src / "shards.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    print("dataset folder:", src, "->", sorted(p.name for p in src.iterdir())[:14], flush=True)
    roots = [src, src.parent]
    tars = {}
    for sh in info["shards"]:
        for r in roots:
            hit = [p for p in r.rglob(sh["name"]) if p.is_file()]
            if hit:
                tars[sh["name"]] = hit[0]
                break
    if len(tars) == len(info["shards"]):
        for i, sh in enumerate(info["shards"]):
            with tarfile.open(tars[sh["name"]]) as tf:
                tf.extractall(out)
            print(f"  unpacked {i + 1}/{len(info['shards'])}", flush=True)
    else:
        # Kaggle may have unpacked the tar files into folders when the dataset was made: gather the frames from them
        print(f"only {len(tars)} of {len(info['shards'])} tar files found; looking for unpacked frames", flush=True)
        jobs = []
        for p in src.rglob("*"):
            if p.is_file() and p.parent.name in ("train", "val") and p.parent.parent.name in ("images", "labels"):
                d = out / p.parent.parent.name / p.parent.name
                d.mkdir(parents=True, exist_ok=True)
                jobs.append((p, d / p.name))
        print(f"  {len(jobs)} files to copy", flush=True)
        n = 0
        with ThreadPoolExecutor(16) as ex:      # many small reads from the dataset mount: threads hide the latency
            for i in range(0, len(jobs), 2000):
                list(ex.map(lambda j: shutil.copyfile(*j), jobs[i:i + 2000]))
                n = min(i + 2000, len(jobs))
                print(f"  copied {n} files", flush=True)
        if n == 0:
            for r in roots:
                for p in sorted(r.rglob("*"))[:60]:
                    print("   ", p, flush=True)
            raise SystemExit("neither the tar files nor unpacked frames were found in the dataset; the listing above shows what it holds")
        print(f"copied {n} files from unpacked folders", flush=True)
    for n in ("dataset_manifest.json", "names.json"):
        shutil.copy(src / n, out / n)
    man = json.loads((out / "dataset_manifest.json").read_text())
    n_img = {sp: len(list((out / f"images/{sp}").glob("*.jpg"))) for sp in ("train", "val")}
    assert n_img == info["images"] and n_img["train"] == len(man["train"]) and n_img["val"] == len(man["holdout"]), \
        ("unpacked frame counts differ from the manifest", n_img, info["images"])
    print(f"unpacked {n_img['train']} train + {n_img['val']} hold-out frames", flush=True)


# ------------------------------------------------------------------ training helpers

def bn_report(model) -> dict:
    import torch  # noqa: PLC0415

    bns = [m for m in model.modules() if isinstance(m, torch.nn.BatchNorm2d)]
    rv = torch.cat([m.running_var.detach().float().flatten().cpu() for m in bns])
    rm = torch.cat([m.running_mean.detach().float().flatten().cpu() for m in bns])
    bad = ~(torch.isfinite(rv) & torch.isfinite(rm))
    return {"bn_layers": len(bns), "channels": int(rv.numel()), "nonfinite_channels": int(bad.sum()),
            "channels_over_fp16_max": int((rv[~bad] > FP16_MAX).sum()),
            "channels_at_fp16_max": int((rv[~bad] == FP16_MAX).sum()),
            "max_running_var": float(rv[~bad].max()) if (~bad).any() else None}


AUG_KEYS = ("mosaic", "mixup", "cutmix", "copy_paste", "degrees", "translate", "scale", "shear", "perspective",
            "flipud", "fliplr", "hsv_h", "hsv_s", "hsv_v", "bgr")


def bn_recalibrate(model, data_yaml, size, train_args, n_batches=BN_BATCHES, batch=16, workers=2, seed=SEED) -> dict:
    """Re-estimate every BatchNorm layer's statistics in full precision (cumulative average over `n_batches`
    training batches augmented as the model was trained). Only the statistics change."""
    import torch  # noqa: PLC0415
    from ultralytics.cfg import get_cfg  # noqa: PLC0415
    from ultralytics.data import build_dataloader, build_yolo_dataset  # noqa: PLC0415
    from ultralytics.data.utils import check_det_dataset  # noqa: PLC0415
    from ultralytics.utils.torch_utils import init_seeds  # noqa: PLC0415

    init_seeds(seed, deterministic=True)
    aug = {k: train_args[k] for k in AUG_KEYS if k in train_args}
    cfg = get_cfg(overrides={**aug, "imgsz": size, "rect": False, "cache": False, "fraction": 1.0,
                             "seed": seed, "deterministic": True})
    data = check_det_dataset(data_yaml)
    ds = build_yolo_dataset(cfg, data["train"], batch, data, mode="train", stride=32)
    dl = build_dataloader(ds, batch, workers, shuffle=True, rank=-1)
    dev = next(model.parameters()).device
    model.float()
    bns = [m for m in model.modules() if isinstance(m, torch.nn.BatchNorm2d)]
    for m in bns:
        m.reset_running_stats()
        m.momentum = None
    model.train()
    seen = 0
    try:
        with torch.no_grad(), torch.autocast(dev.type, enabled=False):
            for i, b in enumerate(dl):
                if i >= n_batches:
                    break
                model(b["img"].to(dev).float() / 255)
                seen += b["img"].shape[0]
    finally:
        model.eval()
        for m in bns:
            m.momentum = 0.03
        if hasattr(dl, "close"):
            dl.close()
    rep = bn_report(model)
    assert seen > 0 and rep["nonfinite_channels"] == 0, rep
    return {"images": seen, "imgsz": size, "augment": aug, **rep}


def save_fp32(model, path, train_args, **extra) -> str:
    import torch  # noqa: PLC0415

    ck = {"epoch": -1, "best_fitness": None, "model": deepcopy(model).float().cpu(), "ema": None,
          "optimizer": None, "train_args": dict(train_args), "date": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra}
    torch.save(ck, path + ".part")
    os.replace(path + ".part", path)
    return path


def letterbox_rect(img, size, stride=32):
    import cv2  # noqa: PLC0415

    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    ch, cw = nh + (size - nh) % stride, nw + (size - nw) % stride
    canvas = np.full((ch, cw, 3), 114, np.uint8)
    top, left = (ch - nh) // 2, (cw - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return canvas


def verify_onnx(onnx_path, torch_model, images, size) -> dict:
    import cv2  # noqa: PLC0415
    import onnxruntime as ort  # noqa: PLC0415
    import torch  # noqa: PLC0415

    s = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    net = deepcopy(torch_model).float().cpu().eval()
    wb, ws, n_out = 0.0, 0.0, None
    for p in images:
        x = letterbox_rect(cv2.imread(p), size)
        x = np.ascontiguousarray(x[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        a = s.run(None, {s.get_inputs()[0].name: x})[0]
        with torch.no_grad():
            b = net(torch.from_numpy(x))
        b = (b[0] if isinstance(b, (list, tuple)) else b).numpy()
        assert a.shape == b.shape and np.isfinite(a).all(), (a.shape, b.shape)
        n_out = a.shape[1]
        wb = max(wb, float(np.abs(a[:, :4] - b[:, :4]).max()))
        ws = max(ws, float(np.abs(a[:, 4:] - b[:, 4:]).max()))
    assert wb < 0.05 and ws < 1e-3, ("exported model disagrees with the original", wb, ws)
    return {"frames": len(images), "outputs": n_out, "max_box_diff_px": round(wb, 5), "max_score_diff": float(f"{ws:.2e}")}


def make_augmentations():
    """Version 3's image degradations (dimming, noise, blur, headlight glare); JPEG, haze and rain stay untrained."""
    import albumentations as A  # noqa: PLC0415

    class HeadlightGlare(A.ImageOnlyTransform):
        def __init__(self, p=0.15):
            super().__init__(p=p)

        def apply(self, img, **params):
            h, w = img.shape[:2]
            x = img.astype(np.float32)
            if np.random.rand() < 0.6:
                x = (x / 255.0) ** np.random.uniform(1.5, 2.5) * np.random.uniform(0.35, 0.7) * 255.0
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            for _ in range(np.random.randint(1, 5)):
                cx, cy = np.random.uniform(0.05 * w, 0.95 * w), np.random.uniform(0.35 * h, 0.95 * h)
                s = np.random.uniform(0.012, 0.05) * w
                x += np.random.uniform(120, 255) * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * s * s)))[..., None]
            return np.clip(x, 0, 255).astype(np.uint8)

        def get_transform_init_args_names(self):
            return ()

    return [A.RandomGamma(gamma_limit=(100, 220), p=0.25),
            A.RandomBrightnessContrast(brightness_limit=(-0.3, 0.1), contrast_limit=(-0.3, 0.2), p=0.25),
            A.GaussNoise(std_range=(0.02, 0.09), p=0.30),
            A.GaussianBlur(blur_limit=(3, 9), sigma_limit=(0.5, 2.5), p=0.15),
            A.MotionBlur(blur_limit=(3, 9), p=0.10),
            HeadlightGlare(p=0.15)]


# ------------------------------------------------------------------ train

def cmd_train(a) -> None:
    import torch  # noqa: PLC0415
    from ultralytics import YOLO  # noqa: PLC0415
    from ultralytics.utils.torch_utils import unwrap_model  # noqa: PLC0415

    cfg = RUNS[a.run]
    cuda = torch.cuda.is_available()
    if a.device == "cpu":
        cuda = False
    elif not cuda:
        raise SystemExit("No GPU. Kaggle: Settings -> Accelerator -> GPU T4 x2 (one is used) or P100.")
    dev = torch.device("cuda" if cuda else "cpu")
    out = Path(a.out).resolve()   # absolute: Ultralytics prefixes a relative project with runs/detect/
    out.mkdir(parents=True, exist_ok=True)
    ds = Path(a.ds).resolve()
    names = json.loads((ds / "names.json").read_text())
    man = json.loads((ds / "dataset_manifest.json").read_text())
    assert man["shared_with_validation"] == 0 and len(names) == 14
    yaml_path = out / "uvh14.yaml"
    yaml_path.write_text(f"path: {ds.resolve()}\ntrain: images/train\nval: images/val\nnames:\n"
                         + "".join(f"  {i}: {n}\n" for i, n in enumerate(names)))
    probe = sorted(str(p) for p in (ds / "images/val").glob("*.jpg"))[:4]
    report_path = out / f"train_report_{a.run}.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    report.update({"run": a.run, "config": cfg, "time_hours": a.time, "epochs_override": a.epochs, "seed": SEED,
                   "ultralytics": ULTRALYTICS_VERSION, "torch": torch.__version__,
                   "gpu": torch.cuda.get_device_name(0) if cuda else "cpu",
                   "train_frames": len(man["train"]), "holdout_frames": len(man["holdout"])})

    def save_report():
        report_path.write_text(json.dumps(report, indent=1))

    aug = make_augmentations()
    fp32 = not cfg["amp"]

    # ---- start weights
    if cfg["start"] == "iisc_bnfix":
        w = a.iisc_weights
        assert sha256_file(w) == IISC_SHA256, "IISc's model file changed; stop and check"
        pt = out / "iisc_bnfix_14.pt"
        if "control" not in report or not pt.exists():
            yolo = YOLO(w)
            iisc_args = torch.load(w, map_location="cpu", weights_only=False)["train_args"]
            before = bn_report(yolo.model)
            yolo.model.to(dev)
            info = bn_recalibrate(yolo.model, str(yaml_path), IMGSZ, iisc_args, n_batches=a.bn_batches,
                                  workers=a.workers)
            save_fp32(yolo.model, str(pt), iisc_args, bn_recalibrated=info)
            assert bn_report(YOLO(str(pt)).model)["nonfinite_channels"] == 0
            report["control"] = {"bn_before": before, "bn_recalibration": info}
            save_report()
            print("BatchNorm re-estimated:", before["nonfinite_channels"], "broken channels before,",
                  info["nonfinite_channels"], "after")
        start = str(pt)
        report["start_note"] = "IISc YOLO11-S, BatchNorm re-estimated on this training split"
    else:
        start = cfg["start"]
        report["start_note"] = f"stock {start} (COCO)"

    def check_start(trainer):
        assert not trainer.amp, "mixed precision is on; this run must train in full precision"
        for mod in (trainer.model, trainer.ema.ema):
            rep = bn_report(unwrap_model(mod))
            assert rep["nonfinite_channels"] == 0, ("broken statistics at the start", rep)

    def nan_guard(trainer):
        if trainer.loss is not None and not torch.isfinite(trainer.loss).all():
            raise RuntimeError(f"non-finite loss (epoch {trainer.epoch + 1}); stop and send Claude this output")

    def save_best_fp32(trainer):
        if trainer.best_fitness is not None and trainer.fitness == trainer.best_fitness:
            save_fp32(unwrap_model(trainer.ema.ema), str(trainer.wdir / "best_fp32.pt"), vars(trainer.args),
                      trained_epoch=trainer.epoch + 1, best_fitness=float(trainer.best_fitness))

    def save_last_fp32(trainer):
        sd = {k: v.detach().cpu().clone().float() if v.is_floating_point() else v.detach().cpu().clone()
              for k, v in unwrap_model(trainer.ema.ema).state_dict().items()}
        p = str(trainer.wdir / "last_fp32.pt")
        torch.save({"epoch": trainer.epoch, "ema": sd}, p + ".part")
        os.replace(p + ".part", p)

    def restore_fp32(trainer):
        p = trainer.wdir / "last_fp32.pt"
        ck = torch.load(p, map_location="cpu", weights_only=False) if p.exists() else None
        if ck is None or ck["epoch"] != trainer.start_epoch - 1:
            print("WARNING: no full-precision copy for this epoch; continuing from the half-precision file")
            return
        for mod in (trainer.model, trainer.ema.ema):
            m = unwrap_model(mod)
            d = next(m.parameters()).device
            m.load_state_dict({k: v.to(d) for k, v in ck["ema"].items()})
        print("resumed with the full-precision copy of epoch", ck["epoch"] + 1)

    callbacks = [("on_model_save", save_best_fp32), ("on_model_save", save_last_fp32)]
    fresh_cb = [("on_pretrain_routine_end", check_start)] if fp32 else []
    if fp32:
        callbacks.append(("on_train_batch_end", nan_guard))

    runs_dir = out / "runs"
    last = runs_dir / a.run / "weights" / "last.pt"
    t0 = time.time()
    if last.exists() and torch.load(last, map_location="cpu", weights_only=False).get("optimizer") is not None:
        print(a.run, "continuing from an earlier session")
        yolo = YOLO(str(last))
        for ev, fn in ([("on_pretrain_routine_end", restore_fp32)] if fp32 else []) + callbacks:
            yolo.add_callback(ev, fn)
        yolo.train(resume=True)
    elif not last.exists() or report.get("trained") is not True:
        yolo = YOLO(start)
        for ev, fn in fresh_cb + callbacks:
            yolo.add_callback(ev, fn)
        kw = dict(time=a.time) if a.time else dict(epochs=a.epochs)
        yolo.train(data=str(yaml_path), imgsz=IMGSZ, patience=15, batch=a.batch or cfg["batch"], optimizer="AdamW",
                   lr0=cfg["lr0"], lrf=0.1, cos_lr=True, warmup_epochs=2, weight_decay=5e-4, mosaic=cfg["mosaic"],
                   close_mosaic=cfg["close_mosaic"], scale=0.3, translate=0.1, fliplr=0.5, mixup=0.0, seed=SEED,
                   deterministic=True, workers=a.workers, cache=False, amp=cfg["amp"], augmentations=aug,
                   device=0 if cuda else "cpu", project=str(runs_dir), name=a.run, exist_ok=True, plots=True,
                   save_period=-1, **kw)
    report["trained"] = True
    report["minutes_this_session"] = round((time.time() - t0) / 60)
    save_report()

    # ---- finalize: best epoch in full precision, ONNX, checks, hold-out score
    wdir = runs_dir / a.run / "weights"
    out_pt, out_onnx = out / f"itms_{a.run}_640.pt", out / f"itms_{a.run}_640.onnx"
    if (wdir / "best_fp32.pt").exists():
        shutil.copy(wdir / "best_fp32.pt", out_pt)
        yolo = YOLO(str(out_pt))
        report["best_epoch"] = yolo.ckpt.get("trained_epoch")
        report["source"] = "best epoch kept in full precision during training"
    else:
        yolo = YOLO(str(wdir / "best.pt"))
        yolo.model.to(dev)
        report["bn_recalibration"] = bn_recalibrate(yolo.model, str(yaml_path), IMGSZ, yolo.ckpt["train_args"],
                                                    n_batches=a.bn_batches, workers=a.workers)
        save_fp32(yolo.model, str(out_pt), yolo.ckpt["train_args"])
        yolo = YOLO(str(out_pt))
        report["source"] = "best.pt with BatchNorm statistics re-estimated (no full-precision copy found)"
    assert list(yolo.names.values()) == names, yolo.names
    report["bn"] = bn_report(yolo.model)
    assert report["bn"]["nonfinite_channels"] == 0, report["bn"]
    exp = yolo.export(format="onnx", dynamic=True, imgsz=IMGSZ, half=False, simplify=True, device="cpu")
    if os.path.abspath(exp) != str(out_onnx.resolve()):
        shutil.copy(exp, out_onnx)
    report["onnx_check"] = verify_onnx(str(out_onnx), yolo.model, probe, IMGSZ)
    r = YOLO(str(out_pt)).val(data=str(yaml_path), imgsz=IMGSZ, batch=8, split="val", half=False, plots=False,
                              verbose=False, device=0 if cuda else "cpu")
    report.update({"holdout_map50": round(float(r.box.map50), 4), "holdout_map50_95": round(float(r.box.map), 4),
                   "holdout_ap50_by_class": {names[int(c)]: round(float(r.box.ap50[i]), 4)
                                             for i, c in enumerate(r.box.ap_class_index)},
                   "pt_sha256": sha256_file(out_pt), "onnx_sha256": sha256_file(out_onnx),
                   "augmentation": [type(t).__name__ for t in aug], "albumentations": ALBUMENTATIONS_VERSION})
    save_report()
    zp = out / f"uvh26_{a.run}_results.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in (report_path, ds / "dataset_manifest.json", out_pt, out_onnx):
            z.write(p, p.name)
        for fn in ("results.csv", "args.yaml", "results.png", "confusion_matrix.png"):
            p = runs_dir / a.run / fn
            if p.exists():
                z.write(p, f"runs/{a.run}/{fn}")
    print(json.dumps({k: report[k] for k in ("best_epoch", "holdout_map50", "holdout_map50_95", "onnx_check")
                      if k in report}), "\nsaved", zp, f"({os.path.getsize(zp) / 1e6:.0f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, help="dry runs: only this many frames")
    p.add_argument("--holdout", type=int, default=N_HOLDOUT)
    p.add_argument("--local-images")
    p.add_argument("--local-labels")
    p.add_argument("--local-val-labels")
    k = sub.add_parser("pack")
    k.add_argument("--ds", required=True)
    k.add_argument("--out", required=True)
    k.add_argument("--shard-mb", type=int, default=900)
    u = sub.add_parser("unpack")
    u.add_argument("--src", required=True)
    u.add_argument("--out", required=True)
    t = sub.add_parser("train")
    t.add_argument("--ds", required=True)
    t.add_argument("--run", required=True, choices=sorted(RUNS))
    t.add_argument("--out", required=True)
    t.add_argument("--time", type=float, help="hours; fixed for the real runs (8)")
    t.add_argument("--epochs", type=int, default=1, help="only when --time is not given (dry runs)")
    t.add_argument("--iisc-weights")
    t.add_argument("--batch", type=int)
    t.add_argument("--workers", type=int, default=4)
    t.add_argument("--bn-batches", type=int, default=BN_BATCHES)
    t.add_argument("--device", default="gpu", choices=("gpu", "cpu"))
    a = ap.parse_args()
    {"prep": cmd_prep, "pack": cmd_pack, "unpack": cmd_unpack, "train": cmd_train}[a.cmd](a)


if __name__ == "__main__":
    main()

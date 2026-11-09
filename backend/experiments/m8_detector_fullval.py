"""Score the M8 vehicle detectors on the FULL UVH-26 validation split (M8).

Two steps, so the (slow, internet-needing) detection and the (fast, locked)
scoring are separate and the scoring can be repeated:

    detect  -- on a machine that reaches huggingface.co (Colab / Kaggle): downloads
               the validation frames one by one, runs every model once per frame and
               saves the detections (6-class pipeline output at score floor 0.05 for
               every model; the raw 14-class output for IISc's models).  Resumable:
               a finished shard of frames is never redone.  Frames are deleted
               after use, so disk stays small.
    score   -- anywhere: reads the detections and the labels, and writes the tables
               fixed in baselines/2026-10-27_m8_uvh26_fullval/TARGETS_LOCKED.md.

    python scripts/m8_detector_fullval.py detect --labels data/uvh26/UVH-26-MV-Val.json \\
        --model iisc=UVH-26-MV-YOLOv11-S.onnx --model iisc_bnfix=iisc_bnfix_640.onnx \\
        --model ft_v2=itms_six_fp32_640.onnx --model ft_v3=itms_six_aug_640.onnx \\
        --model14 iisc --model14 iisc_bnfix --manifest dataset_manifest.json --out run/
    python scripts/m8_detector_fullval.py score --labels data/uvh26/UVH-26-MV-Val.json \\
        --run run/ --old250 data/uvh26/val_sample.json --fresh250 fresh_names.json --out results/

Models are `.onnx` exports with dynamic shapes, run by `OnnxDetector`'s own
letterbox and session so the numbers are those of every earlier baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

CONF14, IOU14, MAXDET14, MAXNMS14 = 0.001, 0.7, 300, 30000   # Ultralytics validation settings
FLOOR6, IOU6, OP = 0.05, 0.6, 0.5                            # m8_detector_eval.py's
IMGSZ = 640

# IISc's paper (arXiv 2511.02563v1, Tables 6-7): YOLO11-S, 13 classes ('Others' excluded),
# on a 400-image gold test set, not on UVH-26-Val.  AP50 / AP75 / AP50:95.
PUBLISHED = {
    "bicycle": (0.2853, 0.2489, 0.2075), "Two-wheeler": (0.6950, 0.4565, 0.4249),
    "Bus": (0.3115, 0.2166, 0.2118), "Mini-bus": (0.0297, 0.0297, 0.0178),
    "Truck": (0.5220, 0.5022, 0.3861), "LCV": (0.6165, 0.5074, 0.4392),   # paper row "TCV"
    "tempo-traveller": (0.8031, 0.7735, 0.7062), "Van": (0.4846, 0.4846, 0.3913),
    "Sedan": (0.4491, 0.4232, 0.3626), "Hatchback": (0.4512, 0.4300, 0.3624),
    "SUV": (0.2321, 0.2217, 0.1976), "MUV": (0.1473, 0.1402, 0.1257),
    "Three-wheeler": (0.8042, 0.6588, 0.5747)}
PUBLISHED_OVERALL = {"map50": 0.4486, "map50_95": 0.3391, "map75": 0.3918}


# ---------------------------------------------------------------- detect

def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def decode14(pred: np.ndarray, *, r: float, pad: tuple[float, float], shape: tuple[int, int]):
    """Raw `(4 + C, N)` head -> Ultralytics' validation post-processing: every
    (box, class) pair above CONF14 is a candidate (multi-label), class-wise NMS,
    best MAXDET14 kept, boxes clipped to the image."""
    from vision_service.detect.yolo import nms  # noqa: PLC0415

    p = pred.T
    sc = p[:, 4:]
    ii, jj = np.nonzero(sc > CONF14)
    s = sc[ii, jj]
    if len(s) > MAXNMS14:
        top = np.argsort(-s)[:MAXNMS14]
        ii, jj, s = ii[top], jj[top], s[top]
    cx, cy, bw, bh = p[ii, 0], p[ii, 1], p[ii, 2], p[ii, 3]
    b = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    b[:, [0, 2]] = (b[:, [0, 2]] - pad[0]) / r
    b[:, [1, 3]] = (b[:, [1, 3]] - pad[1]) / r
    keep = []
    for c in np.unique(jj):
        idx = np.nonzero(jj == c)[0]
        keep.append(idx[nms(b[idx], s[idx], IOU14)])
    if not keep:
        return np.zeros((0, 4), np.float32), np.zeros(0, np.float32), np.zeros(0, np.int16)
    keep = np.concatenate(keep)
    keep = keep[np.argsort(-s[keep])][:MAXDET14]
    h, w = shape
    out = b[keep]
    out[:, [0, 2]] = out[:, [0, 2]].clip(0, w)
    out[:, [1, 3]] = out[:, [1, 3]].clip(0, h)
    return out.astype(np.float32), s[keep].astype(np.float32), jj[keep].astype(np.int16)


def raw_output(det, frame: np.ndarray):
    img, r, pad = det._letterbox(frame)  # noqa: SLF001 -- exactly OnnxDetector.detect's input
    x = img[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    return det.session.run(None, {det.input_name: x})[0][0], r, pad


def download(fetch, path: str, size: int, dest: Path) -> Path:
    last = None
    for attempt in range(3):
        try:
            fetch("dataset", path, dest, size)
            return dest
        except (SystemExit, OSError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"cannot download {path}: {last}")


def cmd_detect(a) -> None:
    import cv2  # noqa: PLC0415
    import onnxruntime as ort  # noqa: PLC0415
    from vision_service.classes import VClass  # noqa: PLC0415
    from vision_service.detect.yolo import OnnxDetector, decode  # noqa: PLC0415

    classes = list(VClass)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    coco = json.loads(Path(a.labels).read_text())
    names = sorted(im["file_name"] for im in coco["images"])
    val = set(names)

    leak = {}
    for m in a.manifest:
        man = json.loads(Path(m).read_text())
        used = {Path(x).name for k in ("train", "holdout") for x in man.get(k, [])}
        leak[m] = {"training_frames": len(used), "shared_with_validation": len(used & val)}
        if used & val:
            raise SystemExit(f"{m}: {len(used & val)} training frames are validation frames")
    print("leakage check:", leak, flush=True)

    if a.images_dir:
        have = {p.name for p in Path(a.images_dir).iterdir()}
        names = [n for n in names if n in have]
    if a.limit:
        names = names[:a.limit]

    providers = {"cpu": ["CPUExecutionProvider"],
                 "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"]}.get(a.providers)
    if providers is None:   # auto
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] \
            if "CUDAExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]
    models = {}
    meta_models = {}
    for spec in a.model:
        key, path = spec.split("=", 1)
        det = OnnxDetector(path, conf=FLOOR6, iou=IOU6, imgsz=IMGSZ, providers=providers)
        models[key] = det
        meta_models[key] = {"path": path, "sha256": sha256(path), "providers": det.session.get_providers()}
        print(f"{key}: {path} {meta_models[key]['sha256'][:12]} {det.session.get_providers()}", flush=True)
    two = set(a.model14)
    if not two <= set(models):
        raise SystemExit(f"--model14 names unknown: {two - set(models)}")

    where = {}
    if not a.images_dir:
        from m8_fetch_uvh26_sample import VAL_DIRS, fetch, list_dir  # noqa: PLC0415

        work = out / ".work"
        work.mkdir(exist_ok=True)
        print("listing validation images...", flush=True)
        for d in VAL_DIRS:
            for n, size in list_dir(d, work).items():
                where[n] = (f"{d}/{n}", size)
        missing = [n for n in names if n not in where]
        if missing:
            raise SystemExit(f"{len(missing)} labelled frames not in the repository listing, e.g. {missing[:3]}")
        tmp = Path(a.tmp)
        tmp.mkdir(parents=True, exist_ok=True)

    shard_of = {n: i // a.shard for i, n in enumerate(names)}
    done = {int(p.stem.split("_")[1]) for p in out.glob("dets_*.npz")}
    todo = [n for n in names if shard_of[n] not in done]
    print(f"{len(names)} frames, {len(done)} shards already done, {len(todo)} to do", flush=True)

    meta = {"labels": a.labels, "labels_sha256": sha256(a.labels), "frames": len(names), "shard": a.shard,
            "models": meta_models, "model14": sorted(two), "leakage": leak,
            "settings": {"floor6": FLOOR6, "iou6": IOU6, "op": OP, "conf14": CONF14, "iou14": IOU14,
                         "maxdet14": MAXDET14, "imgsz": IMGSZ},
            "versions": {"onnxruntime": ort.__version__, "numpy": np.__version__, "opencv": cv2.__version__,
                         "python": sys.version.split()[0]},
            "classes": [c.value for c in classes], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))

    def flush(shard: int, buf: dict) -> None:
        arrs = {"names": np.array(buf["names"])}
        for key, rows in buf.items():
            if key == "names":
                continue
            if key.endswith("_ms"):
                arrs[key] = np.array(rows, np.float32)
                continue
            off = np.cumsum([0] + [len(r[1]) for r in rows])
            arrs[key + "_off"] = off.astype(np.int64)
            arrs[key + "_box"] = np.concatenate([r[0] for r in rows]).astype(np.float32).reshape(-1, 4)
            arrs[key + "_sc"] = np.concatenate([r[1] for r in rows]).astype(np.float32)
            arrs[key + "_cls"] = np.concatenate([r[2] for r in rows]).astype(np.int16)
        np.savez_compressed(out / f"dets_{shard:03d}.npz", **arrs)

    def source(n: str) -> Path:
        return Path(a.images_dir) / n

    ex = ThreadPoolExecutor(a.workers) if where else None
    pending: deque = deque()
    it = iter(todo)

    def submit() -> None:
        n = next(it, None)
        if n is not None:
            pending.append((n, ex.submit(download, fetch, *where[n], tmp / n)))

    if ex:
        for _ in range(a.workers * 3):
            submit()
    cur, buf, t0, count = None, None, time.time(), 0
    for n in todo:
        if ex:
            n2, fut = pending.popleft()
            assert n2 == n
            path = fut.result()
            submit()
        else:
            path = source(n)
        frame = cv2.imread(str(path))
        if frame is None:
            raise SystemExit(f"cannot read {path}")
        if shard_of[n] != cur:
            if buf is not None:
                flush(cur, buf)
            cur, buf = shard_of[n], {"names": []}
        buf["names"].append(n)
        for key, det in models.items():
            t = time.perf_counter()
            pred, r, pad = raw_output(det, frame)
            d6 = decode(pred, det.class_map, conf=FLOOR6, iou=IOU6, r=r, pad=pad)
            ms = 1000 * (time.perf_counter() - t)
            buf.setdefault(key + "_6", []).append((
                np.array([x.box for x in d6], np.float32).reshape(-1, 4),
                np.array([x.score for x in d6], np.float32),
                np.array([classes.index(x.vclass) for x in d6], np.int16)))
            buf.setdefault(key + "_ms", []).append(ms)
            if key in two:
                buf.setdefault(key + "_14", []).append(decode14(pred, r=r, pad=pad, shape=frame.shape[:2]))
        if ex:
            Path(path).unlink(missing_ok=True)
        count += 1
        if count % 25 == 0:
            rate = (time.time() - t0) / count
            print(f"  {count}/{len(todo)}  {rate:.2f} s/frame  ~{(len(todo) - count) * rate / 60:.0f} min left", flush=True)
    if buf is not None:
        flush(cur, buf)
    meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    print("done", flush=True)


# ---------------------------------------------------------------- score

def load_dets(run: Path):
    meta = json.loads((run / "meta.json").read_text())
    dets: dict[str, dict] = {}
    ms: dict[str, list] = {}
    for p in sorted(run.glob("dets_*.npz")):
        z = np.load(p)
        for key in {f[:-4] for f in z.files if f.endswith("_off")}:
            off, box, sc, cl = (z[key + sfx] for sfx in ("_off", "_box", "_sc", "_cls"))  # read each array once
            d = dets.setdefault(key, {})
            for i, n in enumerate(z["names"]):
                s = slice(off[i], off[i + 1])
                d[str(n)] = (box[s].copy(), sc[s].copy(), cl[s].copy())
        for f in z.files:
            if f.endswith("_ms"):
                ms.setdefault(f[:-3], []).extend(z[f].tolist())
    return meta, dets, ms


def boot_one(per_image: list[dict], n: int = 2000, seed: int = 0) -> dict:
    from vision_service.eval.detection import _stats  # noqa: PLC0415

    keys = ("truth", "found", "correct", "false_pos", "pcu_truth", "pcu_found")
    r = {k: np.array([x[k] for x in per_image], dtype=np.float64) for k in keys}
    idx = np.random.default_rng(seed).integers(0, len(per_image), size=(n, len(per_image)))
    st = _stats(r, idx)
    whole = _stats(r, np.arange(len(per_image)))
    return {k: {"value": float(whole[k]), "ci95": [float(v) for v in np.nanpercentile(st[k], [2.5, 97.5])]}
            for k in ("vehicle_recall", "vehicle_precision", "pcu_mae")}


def cmd_score(a) -> None:
    from vision_service.classes import VClass, vclass_from_name  # noqa: PLC0415
    from vision_service.eval.detection import DetectionEval, paired_bootstrap  # noqa: PLC0415

    classes = list(VClass)
    run, out = Path(a.run), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    meta, dets, ms = load_dets(run)
    coco = json.loads(Path(a.labels).read_text())
    cat = {c["id"]: c["name"] for c in coco["categories"]}
    img_by = {im["file_name"]: im for im in coco["images"]}
    done_names = sorted(set.intersection(*[set(d) for d in dets.values()]))
    truth: dict[str, tuple] = {n: ([], []) for n in done_names}
    id2name = {im["id"]: im["file_name"] for im in coco["images"]}
    for an in coco["annotations"]:
        n = id2name[an["image_id"]]
        if n in truth:
            x, y, w, h = an["bbox"]
            truth[n][0].append([x, y, x + w, y + h])
            truth[n][1].append(vclass_from_name(cat[an["category_id"]]))

    old = {im["file_name"] for im in json.loads(Path(a.old250).read_text())["images"]}
    fresh = {str(x) for x in json.loads(Path(a.fresh250).read_text())}
    S = set(done_names)
    subsets = {"ALL": done_names, "OLD250": sorted(old & S), "FRESH250": sorted(fresh & S),
               "UNTOUCHED": sorted(S - old - fresh)}
    subsets = {k: v for k, v in subsets.items() if len(v) >= 20}
    keys6 = sorted(k[:-2] for k in dets if k.endswith("_6"))

    res: dict = {"meta": meta, "frames": len(done_names), "subsets": {k: len(v) for k, v in subsets.items()},
                 "six_class": {}, "paired": {}, "checks": {}}

    def eval6(model: str, names: list[str]) -> dict:
        ev = DetectionEval(op_thresh=OP)
        for n in names:
            tb, tc = truth[n]
            b, s, c = dets[model + "_6"][n]
            ev.add(tb, tc, b, s, [classes[i] for i in c], image=n)
        s = ev.summary()
        s["per_image"] = ev.per_image
        return s

    for model in keys6:
        res["six_class"][model] = {}
        for sub, names in subsets.items():
            s = eval6(model, names)
            res["six_class"][model][sub] = s
            print(f"{model:12s} {sub:10s} found {s['vehicle_recall']:.3f} prec {s['vehicle_precision']:.3f} "
                  f"AP50 {s['map50']:.3f} FP/img {s['false_pos_per_image']:.2f} "
                  f"PCUerr {s['pcu_per_image']['mae']:.2f} bias {s['pcu_per_image']['bias']:+.2f}", flush=True)
        res["six_class"][model]["ms_median"] = float(np.median(ms[model])) if model in ms else None

    # intervals on ALL and on OLD250 (for F1)
    for model in keys6:
        for sub in ("ALL", "OLD250"):
            if sub in subsets:
                res["six_class"][model][sub]["boot"] = boot_one(res["six_class"][model][sub]["per_image"])

    # R: reproduction of earlier baselines on OLD250
    refs = {}
    for spec in a.ref:
        m, path = spec.split("=", 1)
        mod = json.loads(Path(path).read_text())["models"]
        refs[m] = mod[next(iter(mod))]
    for m, ref in refs.items():
        if m in res["six_class"] and "OLD250" in subsets:
            ours = res["six_class"][m]["OLD250"]
            res["checks"].setdefault("R", {})[m] = {
                k: {"earlier": ref[k], "now": ours[k], "diff": ours[k] - ref[k],
                    "pass": abs(ours[k] - ref[k]) <= 0.003} for k in ("vehicle_recall", "vehicle_precision")}
    # F1: ALL value inside OLD250's interval
    if "OLD250" in subsets:
        for m in keys6:
            row = {}
            for k in ("vehicle_recall", "vehicle_precision"):
                lo, hi = res["six_class"][m]["OLD250"]["boot"][k]["ci95"]
                v = res["six_class"][m]["ALL"][k]
                row[k] = {"all": v, "old250_ci95": [lo, hi], "inside": bool(lo <= v <= hi)}
            res["checks"].setdefault("F1", {})[m] = row

    # F2 / F3
    pairs = [(b, a_) for b in ("ft_v2", "ft_v3") for a_ in ("iisc", "iisc_bnfix")] + [("ft_v3", "ft_v2")]
    for sub in ("ALL", "UNTOUCHED"):
        if sub not in subsets:
            continue
        for newer, older in pairs:
            if newer not in keys6 or older not in keys6:
                continue
            pb = paired_bootstrap(res["six_class"][older][sub]["per_image"],
                                  res["six_class"][newer][sub]["per_image"], n=a.boot)
            v = {"more_vehicles_found": pb["vehicle_recall"]["ci95"][0] > 0,
                 "smaller_pcu_error": pb["pcu_mae"]["ci95"][1] < 0,
                 "precision_at_least_0.90": pb["vehicle_precision"]["b"] >= 0.90}
            v["pass"] = all(v.values())
            res["paired"][f"{sub}: {newer} vs {older}"] = {"paired": pb, "verdict": v}
    for sub in ("ALL", "UNTOUCHED"):
        if sub in subsets:
            res["checks"].setdefault("F3", {})[sub] = {
                "by_found": sorted(keys6, key=lambda m: -res["six_class"][m][sub]["vehicle_recall"]),
                "by_pcu_error": sorted(keys6, key=lambda m: res["six_class"][m][sub]["pcu_per_image"]["mae"])}

    # 14-class, COCO evaluation, IISc's models only
    keys14 = sorted(k[:-3] for k in dets if k.endswith("_14"))
    if keys14:
        from pycocotools.coco import COCO  # noqa: PLC0415
        from pycocotools.cocoeval import COCOeval  # noqa: PLC0415

        gt = COCO()
        sub_ids = [img_by[n]["id"] for n in done_names]
        gt.dataset = {"images": [img_by[n] for n in done_names], "categories": coco["categories"],
                      "annotations": [x for x in coco["annotations"] if id2name[x["image_id"]] in S]}
        gt.createIndex()
        cnames = [c["name"] for c in sorted(coco["categories"], key=lambda c: c["id"])]
        res["fourteen_class"] = {}
        for model in keys14:
            rows = []
            for n in done_names:
                b, s, c = dets[model + "_14"][n]
                for bb, ss, cc in zip(b, s, c, strict=True):
                    rows.append({"image_id": img_by[n]["id"], "category_id": int(cc) + 1,
                                 "bbox": [float(bb[0]), float(bb[1]), float(bb[2] - bb[0]), float(bb[3] - bb[1])],
                                 "score": float(ss)})
            E = COCOeval(gt, gt.loadRes(rows), "bbox")
            E.params.imgIds = sub_ids
            E.params.maxDets = [1, 10, 300]
            E.evaluate()
            E.accumulate()
            P = E.eval["precision"]   # T, R, K, A, M

            def ap(ks, ts=None, P=P):
                v = []
                for k in ks:
                    p = (P[:, :, k, 0, 2] if ts is None else P[ts, :, k, 0, 2])
                    p = p[p > -1]
                    v.append(float(p.mean()) if p.size else float("nan"))
                return v

            per = {cnames[k]: {"ap50": ap([k], [0])[0], "ap75": ap([k], [5])[0], "ap50_95": ap([k])[0]}
                   for k in range(14)}
            summ = {}
            for tag, ks in (("13_classes", range(13)), ("14_classes", range(14))):
                ks = list(ks)
                summ[tag] = {"map50": float(np.nanmean(ap(ks, [0]))), "map75": float(np.nanmean(ap(ks, [5]))),
                             "map50_95": float(np.nanmean(ap(ks)))}
            res["fourteen_class"][model] = {"overall": summ, "per_class": per}
            print(f"{model}: 13-class mAP50 {summ['13_classes']['map50']:.4f} mAP50:95 "
                  f"{summ['13_classes']['map50_95']:.4f}; 14-class mAP50 {summ['14_classes']['map50']:.4f} "
                  f"mAP50:95 {summ['14_classes']['map50_95']:.4f}", flush=True)
        res["published"] = {"overall_13": PUBLISHED_OVERALL, "per_class": PUBLISHED,
                            "note": "paper's set is a 400-image gold test, preliminary v1; not UVH-26-Val"}
        if "iisc" in res["fourteen_class"]:
            o = res["fourteen_class"]["iisc"]["overall"]["13_classes"]
            res["checks"]["P"] = {"ours_map50": o["map50"], "paper_map50": PUBLISHED_OVERALL["map50"],
                                  "ours_map50_95": o["map50_95"], "paper_map50_95": PUBLISHED_OVERALL["map50_95"],
                                  "map50_95_within_0.03": abs(o["map50_95"] - PUBLISHED_OVERALL["map50_95"]) <= 0.03}
        if "iisc" in res["fourteen_class"] and "iisc_bnfix" in res["fourteen_class"]:
            x, y = (res["fourteen_class"][m]["overall"]["14_classes"] for m in ("iisc", "iisc_bnfix"))
            res["checks"]["B"] = {k: y[k] - x[k] for k in ("map50", "map50_95")}

    for m in keys6:      # per_image is big and already summarised
        for sub in subsets:
            res["six_class"][m][sub].pop("per_image", None)
    (out / "fullval_results.json").write_text(json.dumps(res, indent=1, default=float))
    print(f"wrote {out / 'fullval_results.json'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--labels", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--model", action="append", required=True, help="name=model.onnx")
    d.add_argument("--model14", action="append", default=[], help="model name that also gets 14-class output")
    d.add_argument("--manifest", action="append", default=[], help="fine-tune dataset_manifest.json (leak check)")
    d.add_argument("--images-dir", help="read frames from here instead of downloading (dry runs)")
    d.add_argument("--providers", default="cpu", choices=("cpu", "cuda", "auto"))
    d.add_argument("--limit", type=int)
    d.add_argument("--shard", type=int, default=250)
    d.add_argument("--workers", type=int, default=6)
    d.add_argument("--tmp", default="/tmp/uvh26_val")
    s = sub.add_parser("score")
    s.add_argument("--labels", required=True)
    s.add_argument("--run", required=True)
    s.add_argument("--old250", required=True)
    s.add_argument("--fresh250", required=True)
    s.add_argument("--ref", action="append", default=[], help="name=earlier m8_detector_eval.py json (check R)")
    s.add_argument("--boot", type=int, default=2000)
    s.add_argument("--out", required=True)
    args = ap.parse_args()
    cmd_detect(args) if args.cmd == "detect" else cmd_score(args)


if __name__ == "__main__":
    main()

"""Does the fire detector still see fire in a Bengaluru street? (M8)

The fire and smoke detector (version 2, `baselines/2026-09-28_m8_fire_v2/`)
passed both of its bars, but in a way that needs checking. At its alarm
threshold (0.05) it alarms on 28 % of D-Fire's own test images with no fire,
yet the Bengaluru traffic frames score almost zero (median 0.0007). It may
have learned "orange autos and haze are not fire" -- or "a Bengaluru CCTV
picture is never a fire", which would make it miss the very fires it is for.
D-Fire has no junction fires, and there is no labelled Indian junction fire
footage, so this probe pastes real flames and smoke into the frames instead.

Each crop is a box cut from a D-Fire *test* image (none was trained on;
`notebooks/m8_fire_crops.ipynb`), with a little of its surroundings. It is
scaled to a height of 64, 128 or 256 px and pasted, with feathered edges,
at the same place into two backgrounds:

* one of the 250 Bengaluru test frames (street context), and
* a plain grey picture of the same size (no context: the control).

A paste counts as found when the detector raises a candidate at or above the
alarm threshold, of either class, centred on the pasted patch. A frame that
alarms by itself cannot fake a hit, because the candidate must be on the
patch.

Bar, set before any result: at 128 and 256 px, pasted **fire** must be found
in the street at least 0.8 times as often as on the grey control. Below
that, the street context suppresses fire, and the detector is not trusted
for junction fires even though it passed its bars. Smoke is reported but not
judged: a pasted rectangle of smoke is a poor imitation of real smoke over a
street.

    python scripts/m8_fire_paste_probe.py --model ../itms_fire_v2_results/itms_fire_640.onnx \\
        --report ../itms_fire_v2_results/fire_report.json --crops ../fire_crops \\
        --frames data/uvh26/val_sample --out fire_paste_probe.json --sheet fire_paste_probe.jpg
"""

from __future__ import annotations

import argparse
import ast
import json
import random
from pathlib import Path

import cv2
import numpy as np
from vision_service.detect.yolo import letterbox

HEIGHTS = (64, 128, 256)
BAR_HEIGHTS = (128, 256)
BAR_RATIO = 0.8
SEED = 26


def feathered(patch: np.ndarray, bg: np.ndarray, x: int, y: int, edge: float = 0.15) -> np.ndarray:
    """`patch` pasted into a copy of `bg` at (x, y), fading out over `edge` of its size."""
    h, w = patch.shape[:2]
    ry = np.minimum(np.arange(h), np.arange(h)[::-1]) / max(1.0, edge * h)
    rx = np.minimum(np.arange(w), np.arange(w)[::-1]) / max(1.0, edge * w)
    a = np.clip(np.minimum.outer(ry, rx), 0, 1)[..., None]
    out = bg.copy()
    roi = out[y : y + h, x : x + w].astype(np.float32)
    out[y : y + h, x : x + w] = (a * patch + (1 - a) * roi).astype(np.uint8)
    return out


def candidates(sess, inp: str, img: np.ndarray, n_cls: int) -> tuple[np.ndarray, np.ndarray]:
    """Every raw candidate: centres in image pixels (N, 2) and best class score (N,)."""
    x, r, (left, top) = letterbox(img, 640, rect=True, stride=32)
    x = np.ascontiguousarray(x[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
    y = sess.run(None, {inp: x})[0][0]  # (4 + n_cls, N)
    cx = (y[0] - left) / r
    cy = (y[1] - top) / r
    return np.stack([cx, cy], 1), y[4 : 4 + n_cls].max(0)


def found(cands: tuple, t: float, rect: tuple) -> bool:
    (c, s), (x1, y1, x2, y2) = cands, rect
    mx, my = 0.1 * (x2 - x1), 0.1 * (y2 - y1)
    inside = (c[:, 0] >= x1 - mx) & (c[:, 0] <= x2 + mx)
    inside &= (c[:, 1] >= y1 - my) & (c[:, 1] <= y2 + my)
    return bool((s[inside] >= t).any())


def trial(c: dict, crops: Path, frames: list, sess, inp: str, n_cls: int, t: float) -> tuple:
    """One crop at every height, street and grey. The background and positions come from a
    random stream seeded by the crop's name, so a crop's result does not depend on which
    others ran with it (the work can be split into parts)."""
    patch0 = cv2.imread(str(crops / c["file"]))
    if patch0 is None:
        return [], None
    rng = random.Random(f"{SEED}:{c['file']}")
    bg = cv2.imread(str(frames[rng.randrange(len(frames))]))
    H, W = bg.shape[:2]
    grey = np.full_like(bg, 128)
    rows, example = [], None
    for h in HEIGHTS:
        w = min(3 * h, max(8, round(patch0.shape[1] * h / patch0.shape[0])))
        patch = cv2.resize(patch0, (w, h), interpolation=cv2.INTER_AREA)
        x = rng.randrange(int(0.05 * W), int(0.95 * W) - w)
        y = rng.randrange(int(0.35 * H), int(0.95 * H) - h)
        rect = (x, y, x + w, y + h)
        street, plain = feathered(patch, bg, x, y), feathered(patch, grey, x, y)
        hit_s = found(candidates(sess, inp, street, n_cls), t, rect)
        hit_g = found(candidates(sess, inp, plain, n_cls), t, rect)
        rows.append({"crop": c["file"], "class": c["class"], "height": h,
                     "street": hit_s, "grey": hit_g})
        if h == 128:
            img = street.copy()
            cv2.rectangle(img, rect[:2], rect[2:], (0, 200, 0) if hit_s else (0, 0, 255), 4)
            example = cv2.resize(img, (480, 270))
    return rows, example


def summarise(rows: list) -> tuple[dict, bool]:
    summary: dict = {}
    for cls in ("fire", "smoke"):
        for h in HEIGHTS:
            sel = [r for r in rows if r["class"] == cls and r["height"] == h]
            if not sel:
                continue
            s = sum(r["street"] for r in sel) / len(sel)
            g = sum(r["grey"] for r in sel) / len(sel)
            summary[f"{cls}@{h}"] = {"n": len(sel), "found_in_street": round(s, 3),
                                     "found_on_grey": round(g, 3),
                                     "ratio": round(s / g, 3) if g else None}
    judged = [summary[f"fire@{h}"] for h in BAR_HEIGHTS if f"fire@{h}" in summary]
    passes = bool(judged) and all(
        j["ratio"] is not None and j["ratio"] >= BAR_RATIO for j in judged
    )
    return summary, passes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--report", required=True, help="fire_report.json (the alarm threshold)")
    ap.add_argument("--crops", required=True, help="the unzipped fire_crops folder (crops.json)")
    ap.add_argument("--frames", default="data/uvh26/val_sample")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sheet", help="a sheet of examples (.jpg)")
    ap.add_argument("--part", help="only crops a:b of crops.json, rows only (merge with --merge)")
    ap.add_argument("--merge", nargs="+", help="part files to combine into --out")
    args = ap.parse_args()

    import onnxruntime as ort  # noqa: PLC0415

    t = json.loads(Path(args.report).read_text())["threshold"]["t"]
    sess = ort.InferenceSession(args.model, providers=["CPUExecutionProvider"])
    meta = sess.get_modelmeta().custom_metadata_map
    names = ast.literal_eval(meta["names"]) if "names" in meta else {0: "fire", 1: "smoke"}
    inp = sess.get_inputs()[0].name
    crops = Path(args.crops)
    index = json.loads((crops / "crops.json").read_text())["crops"]
    frames = sorted(p for p in Path(args.frames).iterdir() if p.suffix.lower() in (".png", ".jpg"))
    assert frames and index
    if args.merge:
        rows = [r for p in args.merge for r in json.loads(Path(p).read_text())["rows"]]
        done = {r["crop"] for r in rows}
        missing = [c["file"] for c in index if c["file"] not in done]
        assert not missing, f"{len(missing)} crops in no part, e.g. {missing[:3]}"
        assert len(rows) == len({(r["crop"], r["height"]) for r in rows}), "a crop is in two parts"
    else:
        a, b = (int(v) for v in args.part.split(":")) if args.part else (0, len(index))
        rows = []
        for k in range(a, min(b, len(index))):
            rows += trial(index[k], crops, frames, sess, inp, len(names), t)[0]
            if k % 50 == 0:
                print(f"{k}/{len(index)} crops", flush=True)
        if args.part:
            Path(args.out).write_text(json.dumps({"part": args.part, "rows": rows}))
            print(f"part {args.part}: {len(rows)} rows -> {args.out}")
            return
    summary, passes = summarise(rows)
    out = {"model": args.model, "threshold": t, "heights": HEIGHTS,
           "bar": {"heights": BAR_HEIGHTS, "min_ratio_street_to_grey": BAR_RATIO,
                   "class": "fire"},
           "passes": passes, "summary": summary, "rows": rows}
    Path(args.out).write_text(json.dumps(out, indent=1))
    for key, v in summary.items():
        print(f"{key:10s} n={v['n']:4d}  street {v['found_in_street']:.2f}  "
              f"grey {v['found_on_grey']:.2f}  ratio {v['ratio']}")
    print("bar (fire at 128 and 256 px, street >= 0.8 x grey):", "passes" if passes else "FAILS")
    if args.sheet:  # every 50th crop of each class, redrawn (the same draws as its trial)
        examples = []
        for cls in ("fire", "smoke"):
            for c in [c for c in index if c["class"] == cls][::50][:4]:
                ex = trial(c, crops, frames, sess, inp, len(names), t)[1]
                if ex is not None:
                    examples.append(ex)
        if examples:
            while len(examples) % 4:
                examples.append(np.zeros_like(examples[0]))
            grid = np.vstack([np.hstack(examples[i : i + 4]) for i in range(0, len(examples), 4)])
            cv2.imwrite(args.sheet, grid, [cv2.IMWRITE_JPEG_QUALITY, 85])


if __name__ == "__main__":
    main()

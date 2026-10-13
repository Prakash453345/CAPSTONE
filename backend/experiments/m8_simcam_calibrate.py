"""Fit SimCam's detector error model to a measured detector (M8).

SimCam's `PerceptionErrorModel` says a vehicle is detected with probability

    base_recall[class] x size(h) x visibility x (burst state),
    size(h) = sigmoid((h - size_h50_px) / (0.25 * size_h50_px)),

and relabels a detected vehicle with `confusion[class]`. Until now those
numbers were assumptions. This fits them to a detector scored on labelled
1080p CCTV frames by `scripts/m8_detector_eval.py` (its `per_box` records:
every labelled vehicle's class, box height and whether it was found at the
tracker's 0.5 line):

- `base_recall` and `size_h50_by_class` per class (one shared
  `size_h50_px` for classes with under `MIN_BOXES` labelled boxes), by
  maximum likelihood on the per-box outcomes (visibility taken as 1: the labels do not say how
  hidden a vehicle is, so occlusion misses land in `base_recall` -- and
  SimCam applies its visibility curve on top, which makes the fitted preset
  a little pessimistic, not optimistic);
- `confusion` from which type each found vehicle was reported as.

What a still-image test cannot measure is left as the preset it starts
from: bursts (they are about consecutive frames), false positives (a
still image cannot separate a detector hotspot from an unlabelled vehicle
or a badly placed box), person recall.

    python scripts/m8_simcam_calibrate.py uvh26_640.json stock_640.json --out simcam_fit.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

BINS = (0.0, 20.0, 40.0, 80.0, 160.0, float("inf"))
MIN_BOXES = 100   # fewer labelled boxes than this: the class shares the pooled size curve
H50_GRID = np.arange(5.0, 400.0 + 1e-9, 0.25)
B_GRID = np.arange(0.002, 1.0 + 1e-9, 0.002)


def size_factor(h: np.ndarray, h50: float) -> np.ndarray:
    """SimCam's size curve (`PerceptionErrorModel._recall`)."""
    return 1.0 / (1.0 + np.exp(-(h - h50) / max(1.0, 0.25 * h50)))


def _loglik_best_b(y: np.ndarray, s: np.ndarray) -> tuple[float, float]:
    p = np.clip(B_GRID[:, None] * s[None, :], 1e-9, 1 - 1e-9)
    ll = (y[None, :] * np.log(p) + (1 - y[None, :]) * np.log(1 - p)).sum(axis=1)
    k = int(np.argmax(ll))
    return float(ll[k]), float(B_GRID[k])


def _best(y: np.ndarray, h: np.ndarray) -> tuple[float, float, float]:
    """(log-likelihood, h50, base) maximising the likelihood of one set of boxes."""
    best = (-np.inf, 0.0, 0.0)
    for h50 in H50_GRID:
        ll, b = _loglik_best_b(y, size_factor(h, h50))
        if ll > best[0]:
            best = (ll, float(h50), b)
    return best


def fit(per_box: list) -> dict:
    cls = np.array([str(b[0]) for b in per_box])
    h = np.array([b[1] for b in per_box], dtype=np.float64)
    y = np.array([b[2] for b in per_box], dtype=np.float64)
    classes = sorted({str(c) for c in cls})
    # the pooled curve: one h50, a base per class
    pooled = (-np.inf, 0.0)
    for h50 in H50_GRID:
        s = size_factor(h, h50)
        total = sum(_loglik_best_b(y[cls == c], s[cls == c])[0] for c in classes)
        if total > pooled[0]:
            pooled = (total, float(h50))
    shared = pooled[1]
    h50s, bases, ll = {}, {}, 0.0
    for c in classes:
        m = cls == c
        if m.sum() >= MIN_BOXES:
            lc, h50s[c], bases[c] = _best(y[m], h[m])
        else:
            lc, bases[c] = _loglik_best_b(y[m], size_factor(h[m], shared))
            h50s[c] = shared
        ll += lc
    # goodness of fit: measured against predicted share found, by class and height
    base_of = np.array([bases[c] for c in cls])
    h50_of = np.array([h50s[c] for c in cls])
    pred = base_of / (1.0 + np.exp(-(h - h50_of) / np.maximum(1.0, 0.25 * h50_of)))
    table = {}
    for c in [*classes, "all"]:
        m = np.ones(len(cls), bool) if c == "all" else cls == c
        rows = {}
        for lo, hi in zip(BINS[:-1], BINS[1:], strict=True):
            k = m & (h >= lo) & (h < hi)
            if k.sum():
                rows[f"{lo:g}-{hi:g}px"] = {"n": int(k.sum()),
                                           "measured": round(float(y[k].mean()), 3),
                                           "fitted": round(float(pred[k].mean()), 3)}
        table[c] = rows
    return {"size_h50_px": shared, "size_h50_by_class": h50s,
            "base_recall": {c: round(b, 3) for c, b in bases.items()},
            "loglik": round(ll, 1), "loglik_pooled_curve": round(pooled[0], 1),
            "boxes": len(per_box), "boxes_by_class": {c: int((cls == c).sum()) for c in classes},
            "fit_by_class_and_height": table}


def confusion(per_class: dict) -> dict:
    out = {}
    for c, r in per_class.items():
        found = {k: v for k, v in r["reported_as"].items() if k != "missed"}
        n = sum(found.values())
        if n:
            wrong = {k: round(v / n, 3) for k, v in sorted(found.items()) if k != c and v}
            if wrong:
                out[c] = wrong
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("evals", nargs="+", help="outputs of m8_detector_eval.py with per_box records")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = {}
    for path in args.evals:
        for key, m in json.loads(Path(path).read_text())["models"].items():
            if "per_box" not in m:
                raise SystemExit(f"{path} {key}: no per_box records; re-run m8_detector_eval.py")
            f = fit(m["per_box"])
            f["confusion"] = confusion(m["per_class"])
            f["source"] = {"file": Path(path).name, "model": key, "weights": m.get("weights"),
                           "images": m["images"], "op_thresh": m["op_thresh"]}
            result[key] = f
            print(f"{key}: base_recall {f['base_recall']}")
            print(f"   size_h50 {f['size_h50_by_class']} (pooled {f['size_h50_px']}); "
                  f"log-lik {f['loglik']} against {f['loglik_pooled_curve']} pooled")
            print("   confusion", f["confusion"])
            for c, rows in f["fit_by_class_and_height"].items():
                cells = (f"{b} {r['measured']:.2f}/{r['fitted']:.2f} (n={r['n']})"
                         for b, r in rows.items())
                print(f"   {c:14s}", "  ".join(cells))
    Path(args.out).write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()

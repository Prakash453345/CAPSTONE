"""Compare two detectors scored on the same labelled images (M8).

Reads two outputs of `scripts/m8_detector_eval.py` (each holding one model
run, or pick one with `name@imgsz`), pairs them image by image and reports
the difference B - A with a 95 % interval from resampling images
(`vision_service.eval.detection.paired_bootstrap`). Then applies the bar set
before the fine-tuned models were trained:

- more vehicles found, with the interval above zero;
- a smaller per-image queue PCU error, with the interval below zero;
- precision at least 0.90;
- CPU time at most 1.25x A's.

    python scripts/m8_detector_compare.py A.json B.json [--a uvh26@640] [--b ft6@640] --out cmp.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vision_service.eval.detection import PAIRED_STATS, paired_bootstrap

BAR = {"min_precision": 0.90, "max_cpu_ratio": 1.25}


def pick(path: str, key: str | None) -> tuple[str, dict]:
    models = json.loads(Path(path).read_text())["models"]
    if key is None:
        if len(models) != 1:
            raise SystemExit(f"{path} holds {sorted(models)}; name one")
        key = next(iter(models))
    if "per_image" not in models[key]:
        raise SystemExit(f"{path} {key}: no per-image counts; re-run m8_detector_eval.py")
    return key, models[key]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--a-key", dest="ak")
    ap.add_argument("--b-key", dest="bk")
    ap.add_argument("--n", type=int, default=10_000)
    ap.add_argument("--out")
    args = ap.parse_args()
    ka, a = pick(args.a, args.ak)
    kb, b = pick(args.b, args.bk)
    cmp = paired_bootstrap(a["per_image"], b["per_image"], n=args.n)
    ms_a, ms_b = a["cpu_ms_per_image"]["median"], b["cpu_ms_per_image"]["median"]
    verdict = {
        "more_vehicles_found": cmp["vehicle_recall"]["ci95"][0] > 0,
        "smaller_pcu_error": cmp["pcu_mae"]["ci95"][1] < 0,
        "precision_at_least_0.90": cmp["vehicle_precision"]["b"] >= BAR["min_precision"],
        "cpu_time_at_most_1.25x": ms_b <= BAR["max_cpu_ratio"] * ms_a,
    }
    verdict["adopt"] = all(verdict.values())
    out = {"a": ka, "b": kb, "images": len(a["per_image"]), "resamples": args.n,
           "cpu_ms_median": {"a": ms_a, "b": ms_b}, "paired": cmp, "bar": BAR, "verdict": verdict}
    print(f"B = {kb}  vs  A = {ka}  ({out['images']} images, {args.n} resamples)")
    for s in PAIRED_STATS:
        r = cmp[s]
        star = "  *" if r["excludes_zero"] else ""
        print(f"  {s:22s} A {r['a']:.3f}  B {r['b']:.3f}  B-A {r['diff']:+.3f}  "
              f"95% [{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}]{star}")
    print(f"  cpu ms/image           A {ms_a:.0f}  B {ms_b:.0f}")
    print("  verdict:", verdict)
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

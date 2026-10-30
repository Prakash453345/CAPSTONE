"""Judge detector candidates at a MATCHED precision on the untouched validation frames (M8).

The procedure fixed in baselines/2026-10-28_m8_full_train/TARGETS_LOCKED.md:
  - DEV = old 250 + fresh 250 validation frames; UNTOUCHED = every other validation frame.
  - For each candidate: the LOWEST score line in 0.50..0.85 (step 0.05) whose DEV precision >= --precision
    (0.943, the repaired IISc model's precision at 0.50). That one line is then scored once on UNTOUCHED.
  - The reference (default `iisc_bnfix`) is scored at 0.50, unchanged.
  - Targets P1-P3 (P5 from the run's own per-frame timings); P4 is read from a 14-class result if given.

    python scripts/m8_detector_matched.py --labels UVH-26-MV-Val.json --old250 val_sample.json \\
        --fresh250 fresh_names.json --run runA --run runB --ref iisc_bnfix --model ft_v3 --model s_iisc \\
        [--fourteen fullval_results.json --fourteen-key s_iisc=iisc ...] --out matched/
Detections are the `dets_*.npz` shards written by `m8_detector_fullval.py detect`; several --run folders are merged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

P1_FOUND, P1_LOWER, P3_PCU, P4_MAP, P5_CPU = 0.769, 0.02, 2.60, 0.560, 1.25
GRID = [round(0.50 + 0.05 * i, 2) for i in range(8)]


def main() -> None:
    from m8_detector_fullval import load_dets  # noqa: PLC0415
    from vision_service.classes import VClass, vclass_from_name  # noqa: PLC0415
    from vision_service.eval.detection import DetectionEval, paired_bootstrap  # noqa: PLC0415

    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--old250", required=True)
    ap.add_argument("--fresh250", required=True)
    ap.add_argument("--run", action="append", required=True)
    ap.add_argument("--ref", default="iisc_bnfix")
    ap.add_argument("--ref-ms-key", help="timing key of the reference measured in the SAME run as the candidate (P5: same machine)")
    ap.add_argument("--model", action="append", required=True, help="candidate (repeat); also the comparison model")
    ap.add_argument("--precision", type=float, default=0.943)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--fourteen", help="fullval_results.json holding the 14-class result")
    ap.add_argument("--fourteen-key", action="append", default=[], help="candidate=key in that file")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    dets, ms = {}, {}
    for r in a.run:
        _, d, m = load_dets(Path(r))
        for k, v in d.items():
            if k in dets:
                raise SystemExit(f"{k} appears in two runs")
            dets[k] = v
        ms.update(m)
    coco = json.loads(Path(a.labels).read_text())
    cat = {c["id"]: c["name"] for c in coco["categories"]}
    id2n = {i["id"]: i["file_name"] for i in coco["images"]}
    truth = {n: ([], []) for n in id2n.values()}
    for an in coco["annotations"]:
        x, y, w, h = an["bbox"]
        n = id2n[an["image_id"]]
        truth[n][0].append([x, y, x + w, y + h])
        truth[n][1].append(vclass_from_name(cat[an["category_id"]]))
    old = {i["file_name"] for i in json.loads(Path(a.old250).read_text())["images"]}
    fresh = {str(x) for x in json.loads(Path(a.fresh250).read_text())}
    have = set.intersection(*[set(dets[f"{m}_6"]) for m in [a.ref, *a.model]])
    dev = sorted((old | fresh) & have)
    unt = sorted(have - old - fresh)
    classes = list(VClass)
    print(f"DEV {len(dev)} frames, UNTOUCHED {len(unt)} frames")
    if len(unt) < 4000:
        print("NOTE: fewer than the 4,797 untouched frames; this is not the locked test")

    def score(model: str, names: list[str], thr: float) -> dict:
        ev = DetectionEval(op_thresh=thr)
        for n in names:
            b, s, c = dets[f"{model}_6"][n]
            ev.add(truth[n][0], truth[n][1], b, s, [classes[i] for i in c], image=n)
        s = ev.summary()
        s["per_image"] = ev.per_image
        return s

    def row(s: dict) -> dict:
        return {"found": s["vehicle_recall"], "precision": s["vehicle_precision"],
                "false_boxes_per_image": s["false_pos_per_image"], "pcu_error": s["pcu_per_image"]["mae"],
                "pcu_bias": s["pcu_per_image"]["bias"], "ap50": s["map50"],
                "found_as_type": {k: v["recall"] for k, v in s["per_class"].items()}}

    ref = score(a.ref, unt, 0.50)
    out = {"dev_frames": len(dev), "untouched_frames": len(unt), "rule": {"grid": GRID, "precision": a.precision},
           "reference": {"model": a.ref, "threshold": 0.50, **row(ref)}, "candidates": {}}
    print(f"reference {a.ref} @0.50: found {ref['vehicle_recall']:.3f} precision {ref['vehicle_precision']:.3f} "
          f"false {ref['false_pos_per_image']:.2f} PCU {ref['pcu_per_image']['mae']:.2f}")
    tk = a.ref_ms_key or a.ref
    ref_ms = float(np.median(ms[tk])) if tk in ms else None
    for m in a.model:
        sweep = {}
        pick = None
        for t in GRID:
            s = score(m, dev, t)
            sweep[t] = {"found": s["vehicle_recall"], "precision": s["vehicle_precision"],
                        "false_boxes_per_image": s["false_pos_per_image"]}
            if pick is None and s["vehicle_precision"] >= a.precision:
                pick = t
        rec = {"dev_sweep": sweep, "threshold": pick}
        if pick is None:
            rec["verdict"] = {"P1": False, "P2": False, "P3": False,
                              "note": f"no score line up to 0.85 reaches DEV precision {a.precision}"}
        else:
            s = score(m, unt, pick)
            pb = paired_bootstrap(ref["per_image"], s["per_image"], n=a.boot)
            rec.update(row(s))
            rec["vs_ref"] = {k: pb[k] for k in ("vehicle_recall", "vehicle_precision", "false_pos_per_image", "pcu_mae")}
            lo = pb["vehicle_recall"]["ci95"][0]
            rec["verdict"] = {"P1": bool(s["vehicle_recall"] >= P1_FOUND and lo > P1_LOWER),
                              "P2": bool(s["vehicle_precision"] >= a.precision),
                              "P3": bool(s["pcu_per_image"]["mae"] <= P3_PCU)}
        if m in ms and ref_ms:
            rec["cpu_ms_vs_ref"] = float(np.median(ms[m])) / ref_ms
            rec["verdict"]["P5_cpu"] = bool(rec["cpu_ms_vs_ref"] <= P5_CPU)
        if a.fourteen:
            j = json.loads(Path(a.fourteen).read_text())
            key = dict(x.split("=", 1) for x in a.fourteen_key).get(m)
            fc = j.get("fourteen_class", {}).get(key) if key else None
            if fc:
                v = fc["overall"]["13_classes"]["map50_95"]
                rec["map50_95_13"] = v
                rec["verdict"]["P4"] = bool(v >= P4_MAP)
        rec["adopt_P1_to_P4"] = all(rec["verdict"].get(k, False) for k in ("P1", "P2", "P3", "P4"))
        out["candidates"][m] = rec
        v = rec["verdict"]
        print(f"{m}: line {pick}  " + (f"found {rec['found']:.3f} [{rec['vs_ref']['vehicle_recall']['ci95'][0]:+.3f} lower "
              f"bound vs ref] precision {rec['precision']:.3f} false {rec['false_boxes_per_image']:.2f} "
              f"PCU {rec['pcu_error']:.2f}  " if pick else "no line reaches the precision  ")
              + " ".join(f"{k}={'pass' if x else 'FAIL'}" for k, x in v.items() if k.startswith("P")))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "matched.json").write_text(json.dumps(out, indent=1, default=float))
    print("wrote", Path(a.out) / "matched.json")


if __name__ == "__main__":
    main()

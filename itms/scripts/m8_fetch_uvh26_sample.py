"""Fetch what M8 needs to test an Indian-traffic detector -- without the
90 GB dataset (M8).

IISc's UVH-26 (Bengaluru Safe City CCTV, CC BY 4.0; models Apache 2.0)
ships trained detectors next to its images. This downloads:

- the YOLO11-S model trained on UVH-26 (57 MB; `--model x` adds the 342 MB
  YOLO11-X);
- the validation labels (16 MB, majority-vote consensus);
- a fixed random sample of validation images (default 250, about 3 MB
  each, ~0.8 GB) -- enough to compare detectors class by class.

Everything lands in `data/uvh26/`, which git ignores. Standard library and
`curl` only, so it runs on a stock Mac:

    cd ~/Documents/capstone/itms
    python3 scripts/m8_fetch_uvh26_sample.py            # ~0.9 GB
    python3 scripts/m8_fetch_uvh26_sample.py --n 100    # ~0.4 GB

Re-running skips files already downloaded in full, so an interrupted run
just continues. The sample is seeded: the same `--n` and `--seed` always
pick the same images.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

HF = "https://huggingface.co"
MODELS = {  # name -> (path in iisc-aim/UVH-26, size in bytes)
    "s": ("weights/YOLOv11-S/UVH-26-MV-YOLOv11-S.pt", 57_142_241),
    "x": ("weights/YOLOv11-X/UVH-26-MV-YOLOv11-X.pt", 342_462_295),
}
VAL_LABELS = "UVH-26-Val/UVH-26-MV-Val.json"
VAL_DIRS = ("UVH-26-Val/data/000", "UVH-26-Val/data/001")


def curl(url: str, dest: Path, *, headers_to: Path | None = None) -> None:
    """Download with retries and resume; raises on HTTP errors."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    cmd = ["curl", "-fsSL", "--retry", "4", "--retry-delay", "3", "-C", "-", "-o", str(tmp), url]
    if headers_to is not None:
        cmd[1:1] = ["-D", str(headers_to)]
        cmd.remove("-C")
        cmd.remove("-")
    for attempt in range(3):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            tmp.replace(dest)
            return
        if r.returncode == 33:  # server cannot resume: start over
            tmp.unlink(missing_ok=True)
        time.sleep(2 * (attempt + 1))
    raise SystemExit(f"download failed ({r.returncode}): {url}\n{r.stderr.strip()}")


def fetch(repo_kind: str, path: str, dest: Path, size: int | None = None) -> None:
    if dest.exists() and (size is None or dest.stat().st_size == size):
        return
    prefix = "datasets/" if repo_kind == "dataset" else ""
    curl(f"{HF}/{prefix}iisc-aim/UVH-26/resolve/main/{path}", dest)
    if size is not None and dest.stat().st_size != size:
        dest.unlink()
        raise SystemExit(f"{dest.name}: got a different size than the repository lists; re-run")


def list_dir(path: str, work: Path) -> dict[str, int]:
    """File name -> size for one dataset folder (the listing API pages)."""
    out: dict[str, int] = {}
    url = f"{HF}/api/datasets/iisc-aim/UVH-26/tree/main/{path}"
    page = 0
    while url:
        body, head = work / f"list_{page}.json", work / f"list_{page}.hdr"
        curl(url, body, headers_to=head)
        for e in json.loads(body.read_text()):
            if e.get("type") == "file":
                size = (e.get("lfs") or {}).get("size", e.get("size", 0))
                out[e["path"].rsplit("/", 1)[-1]] = size
        m = re.search(r'<([^>]+)>;\s*rel="next"', head.read_text(errors="replace"))
        url = m.group(1) if m else ""
        body.unlink()
        head.unlink()
        page += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=250, help="validation images to sample")
    ap.add_argument("--seed", type=int, default=26)
    ap.add_argument("--model", choices=("s", "x", "both"), default="s")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "uvh26"))
    args = ap.parse_args()
    out = Path(args.out)
    work = out / ".work"
    work.mkdir(parents=True, exist_ok=True)

    for key in ("s", "x") if args.model == "both" else (args.model,):
        path, size = MODELS[key]
        print(f"model {path.rsplit('/', 1)[-1]} ({size / 1e6:.0f} MB)...", flush=True)
        fetch("model", path, out / path.rsplit("/", 1)[-1], size)

    labels = out / "UVH-26-MV-Val.json"
    print("validation labels (16 MB)...", flush=True)
    fetch("dataset", VAL_LABELS, labels)
    coco = json.loads(labels.read_text())

    print("listing validation images...", flush=True)
    where: dict[str, tuple[str, int]] = {}
    for d in VAL_DIRS:
        for name, size in list_dir(d, work).items():
            where[name] = (f"{d}/{name}", size)
    by_name = {Path(im["file_name"]).name: im for im in coco["images"]}
    pool = sorted(set(by_name) & set(where))
    if not pool:
        raise SystemExit("no labelled image found in the listing; the repository layout changed")
    pick = sorted(random.Random(args.seed).sample(pool, min(args.n, len(pool))))
    total = sum(where[n][1] for n in pick)
    print(f"{len(pool)} labelled validation images; downloading {len(pick)} "
          f"({total / 1e9:.2f} GB)", flush=True)

    img_dir = out / "val_sample"
    for i, name in enumerate(pick, 1):
        path, size = where[name]
        fetch("dataset", path, img_dir / name, size)
        if i % 10 == 0 or i == len(pick):
            print(f"  {i}/{len(pick)}", flush=True)

    ids = {by_name[n]["id"] for n in pick}
    subset = {
        "info": {"source": f"{HF}/datasets/iisc-aim/UVH-26", "license": "CC BY 4.0",
                 "labels": VAL_LABELS, "sample": {"n": len(pick), "seed": args.seed}},
        "categories": coco["categories"],
        "images": [dict(by_name[n], file_name=n) for n in pick],
        "annotations": [a for a in coco["annotations"] if a["image_id"] in ids],
    }
    (out / "val_sample.json").write_text(json.dumps(subset))
    work.rmdir()
    print(f"\ndone: {out}\n  {len(pick)} images in val_sample/, labels in val_sample.json, "
          f"{len(subset['annotations'])} vehicles labelled", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\ninterrupted -- run the same command again to continue")

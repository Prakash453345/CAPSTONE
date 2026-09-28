# notebooks

Calibration notebooks, build guide §8.5: PCU by class, saturation flow, jam
density, free-flow speed, OD demand (with GEH validation), MFD critical
accumulation, homography reprojection error.

Empty as of M0. Arrives progressively from **M1** (OD demand, needed to build a
believable SUMO scenario) through **M8** (homography, once there's a camera).

## `m8_uvh26_finetune.ipynb` (Google Colab, GPU) — version 2

Transfer learning for M8's detector: starts from IISc's UVH-26 YOLO11-S and
fine-tunes it to the six vehicle types the controller counts, on a seeded
sample of UVH-26's training split. It keeps the 250 frames of
`baselines/2026-09-25_m8_uvh26_detector/` — the detector test set — out of
training, and any frame whose image fingerprint marks it as one of their
cameras. Open it in Colab (File → Upload notebook), pick a T4 GPU and Run
all; the result zip goes to `data/uvh26/finetune_v2/`, and
`scripts/m8_detector_eval.py` scores it against the same test frames.
Version 2's run (27 September) passed the adoption bar at 640 and 960 px
(`baselines/2026-09-27_m8_finetune_v2/`).

Version 2 (2026-09-26) trains in full precision. Version 1's training broke
because IISc's model file has BatchNorm variances larger than half
precision can hold. Version 2 repairs those statistics first, and exports
a control, `iisc_bnfix_*`, that has only that repair. It keeps
full-precision copies through training and resume, and it checks each
export against its source model. See
`baselines/2026-09-26_m8_finetune_v1_bn/`; version 1 is kept there under
`superseded/`.

`scripts/m8_notebook_dryrun.py` runs the notebook's own cells on CPU against
a small fake repository. It covers every edge case, a disconnect and resume,
and the fallbacks. It needs torch and ultralytics 8.4.163.

## `m8_fire_smoke.ipynb` (Google Colab, GPU)

A fire and smoke detector for the junction cameras. It fine-tunes
Ultralytics' COCO YOLO11-S to two classes, fire and smoke, on the public
D-Fire dataset (CC0), plus Bengaluru traffic frames with no fire as extra
negatives.
- **Where the Bengaluru frames come from.** Version 2 downloads them from
  IISc's UVH-26 on Hugging Face. It never takes a test frame or a frame from
  a test camera. If the vehicle notebook's `dataset.tar` is in Drive, it
  uses that instead.
- **It stops without them.** Version 1 carried on without them and failed
  its bars (`baselines/2026-09-28_m8_fire_v1/`).
- **Drive folder.** Version 2 works in `itms_fire_v2`.

**Getting D-Fire.** The notebook takes the dataset, in this order, from:
- a zip in the Drive folder `itms_fire_v2` (download it from
  https://github.com/gaia-solutions-on-demand/DFireDataset);
- Kaggle;
- the OneDrive link.

**What it guards against:**
- **Test leakage:** D-Fire test images, and training near-copies of them,
  are kept out of training. A download with no split is split by groups of
  near-copies.
- **Swapped class ids:** it tells which label id is fire from the boxes'
  colours and checks that against the names file.
- **Bad data:** it drops or clips broken labels, counting everything.

**Choosing and scoring:** it chooses the alarm threshold on validation and
scores the test split once.

**Results:** unzip `itms_fire_v2_results.zip` on the laptop. `scripts/m8_fire_eval.py` then
counts false alarms on the 250 Bengaluru test frames, and the bar for both
numbers is in `docs/vision_system_design.md` §3.7.

**Dry run:** `scripts/m8_fire_notebook_dryrun.py` runs the notebook's cells
on CPU against a fake D-Fire painted onto real frames. It covers every edge
case, a disconnect and resume, a changed setting, and a names file that
disagrees with the colours.


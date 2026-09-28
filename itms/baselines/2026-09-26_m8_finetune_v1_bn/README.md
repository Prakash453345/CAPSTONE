# Baseline — M8, the first fine-tune, and IISc's broken BatchNorm statistics (2026-09-26)

Builds on `baselines/2026-09-26_m8_measured_detectors/`, which set up the
fine-tuning notebook and the test that judges it. This round:

1. scores the first Colab run (notebook version 1, kept in `superseded/`)
   on the 250 test frames. It found more vehicles, missed the precision
   bar, and is **not adopted**;
2. finds that its training had broken down, and why: **IISc's model file
   has BatchNorm statistics that half precision cannot hold**;
3. measures what repairing those statistics does (a diagnostic);
4. replaces the notebook with version 2, and sets how its results will be
   judged before they exist.

## 1. The first run, on the test frames (`detector/`)

The Colab run used a T4, Ultralytics 8.4.163 and torch 2.11. It trained on
3,000 frames of UVH-26's training split, with 300 held out to decide when
to stop.
- **Frames:** 252 candidate frames were skipped as looking like a test
  camera. None was an exact copy or shared a test frame's name.
- **Boxes:** 48 "Others" boxes were dropped.
- **Training vehicles:** 16,393 two-wheelers, 7,497 cars, 6,011 autos,
  3,155 trucks, 1,299 buses and 367 bicycles.
- **Labels:** the label sheet (`colab_v1/label_check.jpg`) shows the boxes
  on the vehicles.
- **Time:** 44 min at 640 px and 65 min at 960 px.

Scored with `scripts/m8_detector_eval.py`: the 250 test frames (PNG), the
tracker's 0.5 line, and the laptop's CPU through ONNX Runtime. IISc's
numbers come from the earlier baseline.

| model | input | vehicles found | precision | false boxes / image | PCU error / image | PCU bias | AP50 | CPU / image |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IISc | 640 | 0.711 | 0.917 | 0.79 | 2.63 | −1.85 | 0.732 | 56 ms |
| **fine-tune v1** | **640** | **0.820** | **0.876** | 1.43 | **1.91** | −0.58 | 0.792 | 48 ms |
| IISc | 960 | 0.775 | 0.851 | 1.66 | 2.32 | −0.39 | 0.741 | 161 ms |
| fine-tune v1 | 960 | 0.844 | 0.842 | 1.95 | 2.11 | +0.01 | 0.735 | 114 ms |

Share found **as the right type**, by type, at 640 px (a bicycle found but called a two-wheeler does not count):

| type | IISc | fine-tune v1 |
|---|---:|---:|
| car | 0.84 | 0.91 |
| auto-rickshaw | 0.75 | 0.82 |
| two-wheeler | 0.66 | 0.78 |
| bus | 0.63 | 0.69 |
| truck | 0.55 | 0.68 |
| bicycle | 0.25 | 0.44 |

**The bar, set before the run** (`scripts/m8_detector_compare.py`, paired
by image, 10,000 resamples):

At 640 px (`cmp_uvh26_vs_ft6_640.json`):
- vehicles found +0.109, interval [+0.096, +0.122]: **passes**;
- PCU error per image −0.72, interval [−1.01, −0.44]: **passes**;
- precision 0.876 against the required 0.90: **fails**;
- CPU time 0.86×: passes.

**Not adopted.** It found one more vehicle in nine, but also 0.64 more
false boxes per image.

At 960 px (`cmp_uvh26_vs_ft6_960.json`):
- vehicles found +0.069, interval above zero: passes;
- PCU error −0.21, interval [−0.52, +0.10]: **fails**;
- precision 0.842: **fails**;
- CPU time: passes.

**Not adopted.**

## 2. The training had broken down (`colab_v1/`)

`results_ft6_640.csv` and `results_ft6_960.csv` record every epoch:
- **Every training and hold-out loss is `nan`**, in both runs.
- **The hold-out score was zero for the first epochs:** mAP 0 for
  epochs 1–7 at 640 px and 1–5 at 960 px.
- **Then the model stopped changing.** Every hold-out figure is identical
  from epoch 17 to epoch 27 at 640 px, and from 7 to 17 at 960 px.
  Early stopping (patience 10) ended both runs.

So the 640 px model last changed at epoch 17, and the 960 px one at epoch 7.
The hold-out mAP50s in `train_report.json` (0.842 and 0.763) were measured
on the saved checkpoints, which carry the damage described next.

**The cause is in IISc's model file** (`UVH-26-MV-YOLOv11-S.pt`, sha256
`12dbeb8f…`):
- **Infinite variances.** 584 of the model's 14,992 BatchNorm channels,
  in 20 layers, store an infinite running variance.
- **Many true values are too large for half precision.** Re-estimated in
  full precision at 640 px input, 327–366 channels exceed half
  precision's largest number, 65,504, and the largest reach about
  2.5 × 10⁷. The count depends on the images and how they are fed.
  That is fewer than the 584 stored as infinity; why the rest were stored
  as infinity cannot be told from the file.
- **How it happened.** IISc trained in full precision (`amp=False` in
  the checkpoint's own arguments), where such values are harmless. But
  Ultralytics saves checkpoints in half precision, which turned them into
  infinity.
- **The current save clips them instead.** Ultralytics now clips them to
  65,504. The v1 fine-tunes have 405 (640) and 417 (960) channels sitting
  at exactly that value.
- **At inference:** an infinite variance switches its channel off (the
  output is just the layer's bias). A clipped one leaves the channel's
  output up to about 20 times too large.

What that did to version 1. The logs do not allow the exact sequence to
be reconstructed. These are the mechanisms that were certainly at work,
and what they fit:
- **An infinite variance cannot heal by averaging.** A running average of
  infinity stays infinite.
  - Version 1 started from IISc's file with 584 such channels.
  - Every save clips infinities to 65,504, yet the saved fine-tunes have
    only 405 and 417 channels at that value. So some of the 584 must have
    become finite during training.
  - The one route we know of is Ultralytics' NaN recovery. It reloads the
    last half-precision checkpoint, where they had been clipped. After
    that, a running average can move them to their true value.
- **Mixed precision is the likely cause of the `nan`.**
  - Mixed-precision training (`amp=True`) runs layers in half precision.
  - This network's largest layer outputs, measured here in training
    mode, reach about 38,000. That is within a factor of two of half
    precision's limit, so an augmented batch can overflow, and an
    overflow becomes `nan`.
  - IISc trained this network in full precision without trouble, and
    version 2's full-precision dry run gives finite losses.
  - The overflow itself was not observed in Colab.
- **The frozen metrics fit skipped steps.** Mixed-precision training
  skips every step whose gradients overflow, and the identical hold-out
  figures fit every step being skipped. This too is an inference.

`UltralyticsDetector` now logs a warning when a model file has either kind
of damaged statistics (`batchnorm_health` in `detect/yolo.py`, two new
tests).

## 3. What repairing the statistics does (`diagnostics/`)

`bn_split.py` re-estimates the statistics in full precision on every
other test frame (in name order) and scores on the rest, so no frame is
used for both. The statistics use the images only. The pipeline way
writes that half's boxes as label files, because Ultralytics' loader
needs them, but they do not affect the statistics.
- **These are the same cameras, so this is a diagnostic, not a result.**
  It chooses how to repair; it is not a measurement to adopt a model on.
- The frames are JPEG copies, at 640 px and the 0.5 line.
- It compares three ways of feeding the frames:
  - **rect:** letterboxed, as the detectors see them;
  - **square:** padded to a square;
  - **pipeline:** Ultralytics' training pipeline with the model's own
    augmentation settings.

| model (125 frames) | statistics | vehicles found | precision | false boxes / image | AP50 | PCU error / image | PCU bias |
|---|---|---:|---:|---:|---:|---:|---:|
| IISc | as released | 0.706 | 0.902 | 0.94 | 0.693 | 2.48 | −1.44 |
| IISc | rect | 0.727 | 0.928 | 0.69 | 0.705 | 2.70 | −2.18 |
| IISc | square | 0.713 | 0.946 | 0.50 | 0.756 | 2.63 | −2.07 |
| IISc | **pipeline** | **0.743** | **0.928** | **0.70** | **0.755** | **2.34** | −1.72 |
| fine-tune v1 | as saved | 0.819 | 0.868 | 1.53 | 0.745 | 1.94 | −0.38 |
| fine-tune v1 | rect | 0.801 | 0.895 | 1.16 | 0.782 | 2.02 | −1.07 |
| fine-tune v1 | square | 0.833 | 0.883 | 1.36 | 0.796 | 1.90 | −0.25 |
| fine-tune v1 | **pipeline** | **0.819** | **0.892** | **1.22** | **0.790** | **1.84** | −0.67 |

Paired intervals are in `bn_split.txt`.
- **The repair helps IISc's model.** The pipeline repair found more
  vehicles (+0.037, interval [+0.028, +0.046]) and raised precision
  (+0.027, [+0.013, +0.041]). False boxes fell by a quarter and AP50 rose
  from 0.693 to 0.755. The PCU error changed by −0.15, interval
  [−0.41, +0.11], which is not significant.
- **How the frames are fed matters, and no way wins every column.**
  Letterboxed frames as seen at inference (rect) gave the lowest AP50 of
  the three for both models. The square way gave IISc's model the highest
  precision but the lowest recall of the three. The pipeline way gave
  the smallest PCU error for both models, and an AP50 within 0.006 of the
  best. It is also the principled choice: it recreates the kind of
  inputs the weights were trained with. So notebook version 2 uses it, on
  training frames.
- **The repair alone does not rescue version 1's fine-tune.** Precision
  rose from 0.868 to 0.892, recall was unchanged, and it stays under
  0.90 on this half.
- **Fine-tuning still gains when both models are repaired.** The
  fine-tune finds more vehicles (+0.076) with a smaller PCU error (−0.49),
  both significant. The cost is 0.037 lower precision (interval
  [−0.050, −0.024]) and 0.52 more false boxes per image.

## 4. Notebook version 2 (`notebooks/m8_uvh26_finetune.ipynb`)

The same data, guards, seed and class-head warm start as version 1, and
the same dataset, reused from Drive. It checks the dataset against its
settings and refuses a mismatch. Then, for each input size:

1. **Control `iisc_bnfix_{size}`.** IISc's model with only its BatchNorm
   statistics re-estimated. This is done in full precision, from 64
   batches (1,024 frames) of our training split, augmented with IISc's own
   training settings (no mosaic, scale 0.5, shifts, flips, colour jitter), at that
   input size. It is saved in full precision, exported to ONNX, and is
   also the starting point for training.
2. **Training in full precision** (`amp=False`). The batch is 16 at 640 px
   and 8 at 960, with 25 epochs and patience 8; the other settings are as
   in version 1.
   - Before the first epoch, a check refuses mixed precision or non-finite
     statistics.
   - A non-finite loss stops the run with a message. In full precision it
     would otherwise corrupt the weights until Ultralytics reloads the
     last checkpoint.
3. **Full-precision copies.**
   - `best_fp32.pt` is written whenever the hold-out score reaches a new
     best (or ties it).
   - `last_fp32.pt` is written every epoch.
   - On a resume, `last_fp32.pt` is loaded back over Ultralytics'
     half-precision `last.pt`, into both the model and its running average.
     Ultralytics resumes from the average; this loses no precision. It is
     not a bit-identical continuation of an uninterrupted run, because the
     data order's random state is not restored.
   - If no full-precision copy exists, the statistics of `best.pt` are
     re-estimated instead, and the report says so.
4. **Export and checks.** The ONNX file is exported from the
   full-precision model, never from a half-precision file. It is checked
   against that model on hold-out frames, at the letterbox the detectors
   use: box coordinates to within 0.05 px and scores to within 10⁻³.
   Then the hold-out score is recorded.
5. **A zip after each size** (`itms_uvh26_ft6v2_results.zip`), so the
   640 px results survive if the 960 px run cannot finish.

**Dry run.** `scripts/m8_notebook_dryrun.py` runs the notebook's own cells
on CPU against a fake repository built from five test-sample frames
(`notebook_dryrun.txt`). It covers:
- every dataset guard: an exact copy of a test frame, a frame named like
  one, a same-camera look-alike, a broken file, a failed download, a
  wrong size, an empty frame, an unknown label, and 'Others', crowd,
  tiny, clipped and duplicate boxes;
- the repair;
- a disconnect after epoch 1 and a resume from the full-precision copy.
  The resumed model keeps 282 variances above 65,504 and none at it;
- the exports running in the project's `OnnxDetector`;
- a session with nothing left to do;
- the fallback;
- a changed setting;
- the NaN guard.

Repeating the repair from scratch gives the same statistics to within a
relative 3 × 10⁻⁶ (float rounding).

## 5. How version 2 will be judged — set before its results exist

Every comparison uses the 250 test frames, `m8_detector_eval.py` and
`m8_detector_compare.py`, and the unchanged bar:
- more vehicles found, with the interval above zero;
- a smaller PCU error per image, with the interval below zero;
- precision at least 0.90;
- at most 1.25× the CPU time.

At each input size (640 and 960 px), three comparisons:
1. **The repair alone:** `iisc_bnfix` against IISc's model as released.
2. **The fine-tune:** `itms_six_fp32` against IISc's model as released.
3. **Is fine-tuning worth it beyond the repair:** `itms_six_fp32` against
   `iisc_bnfix`.

The deciding rule, applied to each input size on its own:
- If only one of the two candidates passes its comparison with IISc's
  model (1 or 2), it is adopted.
- If both pass, the fine-tune is adopted only if it also passes 3.
  Otherwise the repaired control is adopted.
- If neither passes, IISc's model as released stays.

Which input size a deployment runs is a separate choice: 640 px on a CPU,
960 px on a GPU (`baselines/2026-09-26_m8_measured_detectors/`).

The adopted model's SimCam preset is refitted (`m8_simcam_calibrate.py`),
and the controller is re-run on held-out seeds.

## Files

| path | what |
|---|---|
| `detector/ft6_640.json`, `ft6_960.json` | version 1's fine-tunes on the 250 test frames, per image and per box |
| `detector/cmp_uvh26_vs_ft6_*.json` | the paired comparisons and the verdicts |
| `colab_v1/` | the run's report, dataset manifest (every frame name, every skip), label sheet, per-epoch results, training arguments |
| `diagnostics/bn_split.py`, `.json`, `.txt` | §3 |
| `notebook_dryrun.txt` | §4's dry run |
| `superseded/m8_uvh26_finetune_v1.ipynb` | the notebook version 1 was run from (md5 `4747da8f…`) |

The model files are in `data/uvh26/finetune_v1/`, which git ignores. The
evaluation JSONs record them under the path they had when they were scored,
`../itms_uvh26_ft6_results/`.

## Reproducing

```bash
# the fine-tune on the test frames (laptop; data/uvh26 from scripts/m8_fetch_uvh26_sample.py)
python scripts/m8_detector_eval.py --data data/uvh26 --model ft6=data/uvh26/finetune_v1/itms_six_640.onnx --imgsz 640 --out ft6_640.json
python scripts/m8_detector_compare.py baselines/2026-09-26_m8_measured_detectors/detector/uvh26_640.json ft6_640.json
# the BatchNorm diagnostic (needs torch + ultralytics)
python baselines/2026-09-26_m8_finetune_v1_bn/diagnostics/bn_split.py --frames <test frames> \
    --labels data/uvh26/val_sample.json --iisc data/uvh26/UVH-26-MV-YOLOv11-S.pt \
    --ft6 data/uvh26/finetune_v1/itms_six_640.pt --out bn_split.json
# the notebook, dry
python scripts/m8_notebook_dryrun.py --data data/uvh26
```

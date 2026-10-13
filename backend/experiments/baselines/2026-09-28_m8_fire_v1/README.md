# Fire and smoke detector, version 1 (M8), 2026-09-28

**Result: it fails both bars that were set before training, and it is not
adopted.**

- **Bengaluru false alarms.** It alarms on **12.8 %** of the 250 Bengaluru
  traffic test frames (32 of them). The bar is at most 1 %.
- **D-Fire test recall.** It finds **79 %** of the D-Fire test images that
  show fire or smoke. The bar is at least 85 %.

The main cause is that the Bengaluru frames with no fire never reached the
training. The notebook carried on without them, and it should not have.

## The run

- **Code:** `notebooks/m8_fire_smoke.ipynb`, version 1.
- **Training:** Colab T4, 76 minutes, 30 epochs.
- **Model:** YOLO11-S from COCO weights, two classes (fire and smoke), 640 px.
- **Other details:**
  - Ultralytics 8.4.163, torch 2.11.
  - The BatchNorm statistics are healthy: no non-finite channels, and none at
    the fp16 limit.
  - The ONNX export matches the full-precision model to 1.4e-7.

**Data.** D-Fire, from the Kaggle copy `sayedgamal99/smoke-fire-detection-yolo`,
using that copy's own train/val/test split.

| split | images | with fire or smoke | neither |
|---|---:|---:|---:|
| train | 7,301 | 4,691 | 2,610 |
| val | 1,635 | 1,096 | 539 |
| test | 4,306 | 2,301 | 2,005 |

- **Test-leakage filter.** The notebook drops any training or validation
  image within 40 bits (of 256) of a test image's fingerprint. It dropped
  **6,821 training and 1,464 validation images**, about half of each. D-Fire
  is largely video frames, and this copy's split puts frames of one video on
  both sides. The filter keeps the test score honest, but it halved the
  training data.
- **Validation overlap.** 325 training images are near-copies of validation
  images. They were counted and kept, so the validation numbers are
  optimistic.
- **No Bengaluru frames.** `My Drive/itms_uvh26_finetune/dataset.tar` was not
  found. The run printed a note and carried on with D-Fire alone.

**Threshold.** With no Bengaluru frames, the fallback applied: the lowest
threshold keeping false alarms on D-Fire's *validation* negatives at or under
5 %. That gave **t = 0.29**, with validation recall 0.94 and false alarms
4.3 %.

## Scored

**D-Fire test** (in Colab, at t = 0.29):

| | |
|---|---:|
| images with fire or smoke that alarm | **0.794** (bar ≥ 0.85) |
| … with fire | 0.892 |
| … with smoke | 0.716 |
| images with neither that alarm | 0.100 |
| box mAP50 (fire / smoke) | 0.656 / 0.666 |

The missed test images (`test_misses.jpg`) are mostly **tiny, distant fires
at night and faint smoke on hillsides**. D-Fire is largely landscape and
wildfire surveillance. A fire at a junction (a burning vehicle, roadside
burning) is close and large, and this test set barely covers it.

**250 Bengaluru test frames** (`scripts/m8_fire_eval.py`, laptop CPU,
44 ms a frame; `fire_false_alarms.json`):

- **32 of 250 alarm (12.8 %)**, against a bar of at most 1 %: 22 as fire and
  10 as smoke.
- Score quantiles: median 0.07, 90th percentile 0.32, 99th 0.58, maximum
  0.67.
- **Reviewed by eye** (`bengaluru_all_alarms.jpg`): none of the 32 frames
  shows fire or smoke. The model alarmed on:
  - orange things: trucks and containers, auto-rickshaw panels, signboards,
    clothing, small orange markers;
  - washed-out, hazy stretches of road, read as smoke;
  - one corrupted grey frame;
  - street lights at night.

  These are exactly the confusions the Bengaluru negatives were meant to
  teach away.
- **What a stricter threshold would have needed.** Keeping to 1 % on these
  frames would need t ≈ 0.59. At that threshold D-Fire *validation* recall is
  0.74, so the test recall would fall further below the bar. This is
  diagnosis only: choosing a threshold on the test frames is not allowed.

## Why it failed, and what changes

1. **The Bengaluru frames were missing, and the notebook carried on.** The
   fallback, choosing the threshold on D-Fire's own negatives, was my design
   and a mistake: the bar is about Indian traffic frames.
   - The vehicle notebook's Drive folder no longer exists, so version 2
     (`notebooks/m8_fire_smoke.ipynb`, rebuilt) **downloads the Bengaluru
     frames itself** from IISc's UVH-26 on Hugging Face: 1,500 for training
     and 300 for validation.
   - It never takes one of the 250 test frames, whether by name or by
     content, nor a frame within 72 bits of one (the same camera). It keeps
     a copy in Drive for resuming.
   - It still uses the vehicle notebook's `dataset.tar` if one is in Drive.
   - It **stops** if it ends up without the frames, or if it finds a dataset
     in Drive that was built without them.
   - It works in a fresh Drive folder, `itms_fire_v2`.
   - Everything else, including both bars, is unchanged.
   - The dry run covers the download: a test frame under another name, a
     test camera, a broken file, a missing file, and reuse from Drive. It
     also covers both stops.
2. **Half the training data was dropped** as near-copies of test images.
   That is left as it is: it is the test's protection.
3. **D-Fire's recall bar measures distant wildfires.** A junction-relevant
   test of close-range fires would have to be declared before anything is
   looked at. It is not done here, and the bar stays as set.

Version 2 needs nothing extra from Drive. It downloads D-Fire from Kaggle, as
version 1 did, and the Bengaluru frames from Hugging Face.

## Files

| file | what |
|---|---|
| `fire_report.json` | the Colab report: settings, threshold curve, test scores, checksums |
| `fire_manifest.json` | exact image lists, class-id check, skip counts |
| `fire_false_alarms.json` | the laptop's score on the 250 Bengaluru frames |
| `bengaluru_all_alarms.jpg`, `bengaluru_top_scores.jpg` | the 32 alarming frames, and the top 8 |
| `test_misses.jpg`, `label_check.jpg` | D-Fire test misses; the label sanity sheet |
| `runs/fire_640/` | Ultralytics' training log and plots |
| `superseded/m8_fire_smoke_v1.ipynb` | the version-1 notebook that produced this run |
| `notebook_v2_dryrun.txt` | the version-2 notebook's CPU dry run (passed) |

The weights (`itms_fire_640.pt`, `.onnx`, 38 MB each) were never in git.
They were deleted on 2026-09-28 because the model failed and was replaced
by version 2. Their SHA-256 checksums are in `fire_report.json`.

The laptop score was made with this command, from the device's venv with
onnxruntime and opencv:

```bash
python scripts/m8_fire_eval.py --model ../itms_fire_results/itms_fire_640.onnx \
    --report ../itms_fire_results/fire_report.json --frames data/uvh26/val_sample \
    --sheet bengaluru_top_scores.jpg --out fire_false_alarms.json
```

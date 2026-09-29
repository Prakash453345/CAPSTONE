# Fire and smoke detector, version 2 (M8), 2026-09-28

**Result: it passes both bars that were set before training, and then
fails the street probe.**

- The probe's bar was also fixed before its run: fire pasted into Bengaluru
  street frames must be found at least 0.8 × as often as the same fire on
  plain grey.
- At 128 px it is found half as often in the street (0.48 against 0.94). At
  256 px the rate is 0.67 against 0.92.
- The model has partly learned that a Bengaluru CCTV picture is not a fire.
- **It is not adopted and not wired into the vision service.**

| check | result | bar |
|---|---:|---|
| D-Fire test images with fire or smoke that alarm | **93.1 %** (fire 97.9 %, smoke 89.5 %) | ≥ 85 % |
| the 250 Bengaluru traffic test frames that alarm | **0.4 %** (1 frame) | ≤ 1 % |

## The run

- **Notebook:** `notebooks/m8_fire_smoke.ipynb`, version 2.
- **Training:** Colab T4, 82 minutes, 30 epochs, seed 26.
- **Model:** YOLO11-S from COCO weights, two classes (fire and smoke), 640 px.
- **Health checks:**
  - The BatchNorm statistics are healthy.
  - The ONNX export matches the full-precision model to 1.4e-7.
  - The ONNX file's SHA-256 (6867830a…) matches the report.
- **D-Fire.** The same Kaggle copy and split as version 1: 7,301 training,
  1,635 validation and 4,306 test images. As in version 1, 6,821 training and
  1,464 validation images were dropped as near-copies of test images.
- **Bengaluru frames**, the change from version 1:
  - 1,500 in training and 300 in validation, with no fire.
  - Downloaded from IISc's UVH-26 on Hugging Face (`UVH-26-Train/data`, a
    pool of 21,349 images).
  - None of the 250 test frames, by name or by content.
  - 138 frames were skipped for being within 72 of 256 bits of a test frame,
    which marks them as the same camera.
- **Threshold.** The lowest threshold that keeps Bengaluru *validation*
  false alarms at or under 1 % is **t = 0.05**, the bottom of the search
  grid. At that threshold:
  - validation recall is 0.98;
  - 1.0 % of the Bengaluru validation frames alarm (3 of 300);
  - 17 % of D-Fire's validation images with no fire alarm.

## Scored

**D-Fire test** (in Colab, at t = 0.05):

| | |
|---|---:|
| images with fire or smoke that alarm | **0.931** (bar ≥ 0.85) |
| … with fire | 0.979 |
| … with smoke | 0.895 |
| images with neither that alarm | **0.276** |
| box mAP50 (fire / smoke) | 0.653 / 0.664 |

Version 1 scored 0.794 recall at t = 0.29, with 10 % false alarms on these
no-fire images.

**250 Bengaluru test frames** (`scripts/m8_fire_eval.py`, laptop CPU,
44 ms a frame; `fire_false_alarms.json`):

- **1 of 250 alarm (0.4 %).** Version 1 alarmed on 32.
- The one alarm is frame 686114, scored as fire at 0.26. It is an orange
  truck container at the edge of the frame with no fire in it, and it was
  version 1's second-highest alarm too.
- Score quantiles: median 0.0007, 90th percentile 0.004, 99th 0.035,
  maximum 0.26.
- `bengaluru_top_scores.jpg` shows the eight highest-scoring frames. None
  shows fire or smoke.

## Why it is not wired in yet

The pass has a feature that needs explaining.

- **The same threshold behaves very differently on the two sets.** At
  t = 0.05 the model alarms on **28 % of D-Fire's no-fire test images**.
  Yet it scores Bengaluru traffic frames almost at zero.
- **Two explanations fit.**
  - It may have learned that orange autos, trucks and haze are not fire.
    That is what the Bengaluru frames were for.
  - Or it may have learned that *a Bengaluru CCTV picture is never a fire*.
    Every Bengaluru frame it trained on was a negative, and every fire it
    saw came from D-Fire's landscapes.

  If the second is true, it would miss the junction fires it is for.
- **Neither bar can tell these apart.** No D-Fire fire is in a street, and
  there is no labelled Indian junction fire footage.

**The probe** (`scripts/m8_fire_paste_probe.py`):

- **Crops.** Flames and smoke are cut from D-Fire *test* images, which the
  model never trained on (`notebooks/m8_fire_crops.ipynb`, 400 of each
  class).
- **Pasting.** Each crop is scaled to 64, 128 or 256 px high and pasted,
  with feathered edges, into two backgrounds at the same place:
  - one of the 250 Bengaluru test frames;
  - a plain grey picture of the same size.
- **What counts as found.** A paste counts when a candidate at or above the
  threshold is centred on it. A frame that alarms by itself cannot fake a
  hit.
- **Bar, set before any result.** At 128 and 256 px, pasted **fire** must be
  found in the street at least **0.8 ×** as often as on grey. Below that,
  the detector is not trusted for junction fires, even though it passed its
  own bars. Smoke is reported but not judged: a pasted rectangle of smoke is
  a poor imitation of smoke over a street.

### The probe's result: fails (`fire_paste_probe.json`, `fire_paste_probe.jpg`)

The crops are 400 fire and 400 smoke boxes from D-Fire's test split. They
came from the same Kaggle copy the fire notebook used, with a check that it
has the same 4,306 test images and label ids. The threshold is 0.05.

| pasted | height | found in the street | found on grey | street ÷ grey |
|---|---:|---:|---:|---:|
| fire | 64 px | 0.11 | 0.83 | 0.13 |
| fire | **128 px** | **0.48** | 0.94 | **0.52** (bar ≥ 0.8) |
| fire | **256 px** | **0.67** | 0.92 | **0.73** (bar ≥ 0.8) |
| smoke | 64 px | 0.03 | 0.23 | 0.13 |
| smoke | 128 px | 0.15 | 0.35 | 0.42 |
| smoke | 256 px | 0.40 | 0.52 | 0.77 |

- **The street hides fires the model sees on grey.** At 256 px, 102 pasted
  fires were found on grey but missed in the street. Only 2 went the other
  way.
- **The misses are plain to see.** `fire_paste_probe.jpg` shows some of
  them: bright flames in the middle of a Bengaluru road, missed.
- **Pasting is only an imitation of a real junction fire.** The pasted
  patches carry their own background, and grey is an easy canvas. But the
  gap is large, it grows as the fire gets smaller, and it goes one way. That
  is what the shortcut predicts.

**Verdict:** by the probe's bar, the detector is not trusted for junction
fires, even though it passed its own bars.

**What would fix it** (not done):
- **Real street fires.** The training has no fire in a street, so "a
  street" and "no fire" always go together. It needs fires in urban or
  traffic scenes, for example a public dataset with vehicle or street fires.
- **Pasted fires in training.** Another route is pasting flames into the
  Bengaluru training frames. But this probe would then no longer be an
  independent test, so a new one would be needed: real footage, declared
  before looking.

## Other caveats

- **D-Fire false alarms.** The 28 % false-alarm rate on D-Fire's no-fire
  images matters for any camera that looks less like the Bengaluru training
  frames: other cities, night, fog, rain.
- **The threshold is at the bottom of its grid (0.05),** so the Bengaluru
  validation frames alone decided it. Only 3 of the 300 alarm there.
- **Test leakage.** Half of D-Fire's training data is still dropped by the
  test-leakage filter, as in version 1.

## Files

| file | what |
|---|---|
| `fire_report.json` | the Colab report: settings, threshold curve, test scores, checksums |
| `fire_manifest.json` | exact image lists, including the Bengaluru frames and why 138 were skipped |
| `fire_false_alarms.json`, `bengaluru_top_scores.jpg` | the laptop score on the 250 Bengaluru frames |
| `bengaluru_negatives_review.jpg` | the highest-scoring Bengaluru *validation* frames |
| `test_misses.jpg`, `label_check.jpg` | D-Fire test misses; the label sanity sheet |
| `runs/fire_640/` | Ultralytics' training log and plots |
| `fire_paste_probe.json`, `fire_paste_probe.jpg` | the street probe: every paste, the summary, examples (green found, red missed) |

The weights (`itms_fire_640.pt` and `.onnx`, 38 MB each) are not in git. They
are in `itms_fire_v2_results/` beside the repository, with SHA-256 checksums
in `fire_report.json`.

```bash
python scripts/m8_fire_eval.py --model ../itms_fire_v2_results/itms_fire_640.onnx \
    --report ../itms_fire_v2_results/fire_report.json --frames data/uvh26/val_sample \
    --sheet bengaluru_top_scores.jpg --out fire_false_alarms.json
```

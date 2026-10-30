# M8 fire and smoke detector, version 3: FAILS target B

Trained in Colab on 2026-09-29/30 with `notebooks/m8_fire_smoke_v3.ipynb` (YOLO11-S, 640 px, seed 26, T4, 97 minutes).
Targets were written before the run: `TARGETS_LOCKED.md` (md5 `26c7a964aa3b3c4be177dc07602b7f47`, unchanged).
Files here: `fire_report.json`, `fire_manifest.json` (from Colab), `false_alarms_250.json` (laptop, `scripts/m8_fire_eval.py`).
Weights: `itms_fire_v3_results/itms_fire_640.onnx` (md5 `79f0d4fcda3d2f8a9442f398b017d266`), not wired into `services/vision-service`.

## Verdict against the locked targets
| # | Target | Result | |
|---|--------|--------|---|
| A | D-Fire test recall (any fire or smoke) >= 85 % | 90.9 % (2,301 images; fire 97.1 %, smoke 85.7 %) | pass |
| B | false alarms on the 250 Bengaluru test frames <= 1 % | **7 of 250 = 2.8 %** | **FAIL** |
| C | recall on held-out FASDD street/vehicle fires (V+R) >= 80 % | 78 of 78 = 100 % (Wilson 95 %: 95.3-100 %) | pass |
| D | Inferno recall | not run: the dataset has not arrived | open |

v3 does not pass, and is not adopted. The alarm threshold, 0.12, was chosen by the notebook on validation
(false alarms on 300 Bengaluru validation frames <= 1 %); at that threshold validation showed exactly 1.0 %
(3 of 300) and the test frames showed 2.8 %.

## What the numbers do and do not show
- **B failed narrowly, and the threshold sat on the edge.** Of the 7 alarming test frames, 6 scored 0.14-0.24 (just above
  0.12); one scored 0.78 (frame 964462). I cropped the top box of each of the 7 alarming frames: 5 are privacy-blurred patches with orange or yellow in them (a number plate, including the 0.78 frame; a face; and three blurs on vehicles), 1 is an orange garment on a scooter passenger, and 1 is an overexposed night-time lamp. UVH-26 blurs plates and faces, and an orange or yellow blur is what the model mistakes for flame. Seven frames is a small count: the
  difference between pass (at most 2) and fail is five frames.
- **C is real recall on real fires, but it says little about telling fire from non-fire.** The model also alarmed on 77 of the 84
  held-out images labelled X (no visible fire, cartoon, unreadable), and on 261 of 263 non-street fires (labels B, O, F, I; the 347 in the report also counts the 84 X images). On D-Fire's negatives it
  alarms on 18.7 % of images at 0.12 (v2: 27.6 % at 0.05). C tests "does it see the fire", not "does it stay quiet without one".
  v2 was never scored on this held-out set, and the paste probe was not rerun (it is no longer an independent test), so this run gives no like-for-like street comparison with v2.
- Held-out set: 500 FASDD images, 75 dropped as near-copies of training/validation images, leaving 425 scored; V+R = 78 after
  removal. Labels are by eye (Michael and Claude); the letters were cross-checked on 50 images.
- A is the same bar as v2 (v2: 93.1 % at threshold 0.05); v3 recall is lower at a higher threshold. Smoke recall fell from v2's 89.5 % to 85.7 % (not a target).
- On D-Fire's validation negatives the false-alarm rate at 0.12 was 12.6 % against 18.7 % on the test split. 325 training images are near-copies of validation images and were kept (validation only picks the best epoch; the threshold rests on Bengaluru frames).
- The manifest records 1,992 street-like FASDD training images kept (about 2,030 was the count before the notebook's D-Fire near-copy removal).
- Validation curve (from `fire_report.json`): threshold 0.20 gave val false alarms 0.33 %, recall 97.3 %; 0.30 gave 0 %, 94.8 %.
  These are post-hoc observations made after the 250 test frames were seen, so they are a hypothesis for a next run,
  not a result. The 250 test frames are no longer untouched for any threshold chosen after this.

## Training data used (from `fire_manifest.json`)
D-Fire train + val (test kept out; 6,821 train and 1,464 val near-copies of test removed), 3,341 FASDD train and 294 val images
(77 dropped as near-copies of D-Fire test), 1,500 + 300 Bengaluru no-fire frames, 600 Bengaluru frames with pasted D-Fire-train
flames. FASDD label id 0 = fire was confirmed by colour (median flame share 0.35 vs 0.03).

## Options for a next step (not done)
1. Keep v3's data, choose the threshold with a stricter, pre-registered rule on a larger Bengaluru validation set
   (e.g. 1,000 frames), and test on a fresh, unseen 250 Bengaluru frames (from UVH-26, not the current test cameras).
2. Add more street-context negatives beyond Bengaluru CCTV, since the shortcut may now run the other way ("web-style image = fire").
3. Wait for Inferno as an independent vehicle-fire test.

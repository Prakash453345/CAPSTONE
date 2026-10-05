# Fire and smoke detector v3: pass/fail targets

Written 2026-09-29, BEFORE any v3 training run and before any v3 result exists.
Not to be changed after the run. If a target is changed, the run is reported as "targets changed after
seeing results" and does not count as a pass.

## What v3 is
YOLO11-S, 2 classes (fire, smoke), 640 px, seed 26, 30 epochs, same as v2, with these changes:
- D-Fire (as v2), plus 3,413 FASDD fire images (about 2,030 street/vehicle-like) chosen on the Mac by a vehicle
  detector (see `fasdd_selection.json`), minus black-background cut-outs and near-copies of the held-out set,
  minus near-copies of D-Fire's test images (removed inside the notebook).
- 1,500 Bengaluru no-fire frames (as v2), with flames pasted into a share of them (flame crops cut from D-Fire
  TRAIN only; the earlier `fire_crops` come from D-Fire test and are NOT used for training).
- Never used for training or threshold choice: D-Fire test, the 250 Bengaluru test frames and their cameras,
  the 500 FASDD held-out images (seed 929) and their near-copies, and Inferno (if it arrives).
- The alarm threshold is chosen on validation exactly as in v2: the lowest threshold that keeps false alarms on
  the 300 Bengaluru validation frames at or under 1 %.

## Targets (all three must pass for "v3 passes")
| # | Test | Data | Target |
|---|------|------|--------|
| A | Recall, any fire or smoke, at the chosen threshold | D-Fire test images with fire or smoke (2,301) | >= 85 % (same bar as v2) |
| B | False alarms at the same threshold | the 250 Bengaluru test frames (`scripts/m8_fire_eval.py`) | <= 1 % (at most 2 of 250) |
| C | Recall on street and vehicle fires, at the same threshold | the FASDD held-out images labelled V or R in `labels_final_seed929.tsv`, after removing any that are near-copies (<= 40 bits) of a training or validation image | >= 80 % (point estimate; the Wilson 95 % interval is reported next to it) |

"Alarm" = the image's highest fire or smoke score reaches the threshold (same rule as v2).

## Extra real test, if it arrives in time
D. Inferno (vehicle fires, 1,097 images, requested from the authors): recall at the same threshold >= 80 % on
   its fire images after removing near-copies of training data. If Inferno has not arrived when the verdict is
   written, the verdict is "provisional: A, B, C only", and Inferno is reported when it arrives. If it arrives
   before, D is a fourth required target.

## Reported, not judged
- Recall on the held-out non-street fires (labels B, O, F, I): to see the shortcut has not just moved.
- The paste probe (street vs grey ratio, bar 0.8 in v2): no longer an independent test, because v3 trains with
  pasted flames. Reported for continuity only.
- Recall by label letter, with counts.

## Known weaknesses of these tests (stated now, so they are not discovered later)
- C has about 80 images: an 80 % point estimate has a wide interval (roughly +/- 8 to 9 points).
- The held-out labels are Michael's and Claude's by-eye letters (V/R/B/O/F/I/X), cross-checked against Michael's 50
  blind labels; the overall street count held up, but single-image labels can be wrong.
- Near-copy removal uses a 256-bit fingerprint at 40 bits; re-cropped or re-encoded copies can escape it.
- FASDD reuses older datasets and web images; some held-out images may resemble training images without being
  caught. C is therefore an upper-leaning estimate of real-world street recall.
- None of A to D tests a live camera. Live behaviour (persistence, flicker/growth filter, operator confirmation)
  is tested separately after any pass.

## If it fails
Reported as a failure, with the numbers. v3 is then not wired into `services/vision-service`.

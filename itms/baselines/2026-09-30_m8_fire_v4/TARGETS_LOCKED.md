# Fire and smoke detector v4: pass/fail targets

Written 2026-09-30, BEFORE any v4 training run and before any v4 result exists. Not to be changed after the run;
if changed, the run is reported as "targets changed after seeing results" and does not count as a pass.

## Why v4
v3 failed target B: 7 of 250 Bengaluru test frames alarmed (2.8 %, bar 1 %). Five of the seven were privacy-blurred patches
with orange or yellow in them (UVH-26 blurs plates and faces); the rest an orange garment and an overexposed lamp. The
threshold (0.12) had been chosen on only 300 validation frames and landed exactly on the 1 % edge.

## What changes from v3
1. **Hard negatives.** From 2,500 extra Bengaluru frames that are not in training, validation or any test, the 800 with the
   most flame-coloured (saturated red-orange-yellow) area are added to training as no-fire images. Chosen by a colour
   score, not by the v3 model and not by looking at test frames.
2. **A larger validation set, and a stricter threshold rule.** 1,000 random Bengaluru validation frames (v3: 300). The threshold is the
   lowest one that keeps false alarms on them at or under 0.3 % (3 of 1,000). (v3: 1 % of 300.)
3. **A fresh Bengaluru test set.** 250 frames never seen by any earlier version and drawn after the run is designed. Any training,
   validation or hard-negative frame within 72 fingerprint bits of one of them (same camera) is removed from training, so the
   test cameras are unseen. The old 250 test frames are still kept out of training and are reported, not judged (they were
   scored once for v3).
Everything else as v3 (D-Fire, 3.3k FASDD images, 600 pasted-flame frames, held-out FASDD street set, seed 26, 30 epochs).

## Targets (all must pass for "v4 passes")
| # | Test | Data | Target |
|---|------|------|--------|
| A | Recall, any fire or smoke, at the chosen threshold | D-Fire test images with fire or smoke (2,301) | >= 85 % |
| B2 | False alarms at the same threshold | the 250 FRESH Bengaluru test frames (scored once, in the notebook) | <= 1 % (at most 2 of 250) |
| C | Recall on street and vehicle fires | held-out FASDD images labelled V or R (near-copies of training/validation removed) | >= 80 % (point estimate; Wilson 95 % reported) |
| D | Inferno vehicle fires, if it arrives before the verdict | recall at the same threshold | >= 80 %, else verdict "provisional" |

## Reported, not judged
- False alarms on the old 250 Bengaluru test frames (`scripts/m8_fire_eval.py`; the v3 verdict was 7 of 250).
- Recall on non-street held-out fires; false-alarm rate on D-Fire negatives; the paste probe (not independent).
- What the alarming fresh test frames show (crops).

## Known weaknesses, stated now
- 250 frames: 0, 1 or 2 alarms all pass; 3 fail. One frame changes the verdict.
- "Same camera" is a 72-bit fingerprint proxy, not a camera id; some test frames may still share a scene with training frames.
- The held-out FASDD set was scored once for v3 (its result was seen, never used for training or tuning); it is reused for C.
- Raising the threshold will cost recall: A and C may fail. That trade-off is the point of the test.
- All frames are Bengaluru CCTV with UVH-26's privacy blurs. Other cities or cameras are untested.

## If it fails
Reported as a failure, with numbers. Not wired into `services/vision-service`.

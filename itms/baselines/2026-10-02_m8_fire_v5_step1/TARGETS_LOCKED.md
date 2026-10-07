# Fire and smoke detector v5, Step 1 (two thresholds, same weights): pass/fail targets

Written 2026-10-02, BEFORE any v5 run and before any v5 result exists. Not to be changed after the run; if changed,
the run is reported as "targets changed after seeing results" and does not count as a pass.
Background and sources: `claude/m8_v5_survey_and_plan.md` in the Projects store.

## Why this step
v4 failed A (D-Fire recall 77.97 %, fire 87.0 %, smoke 67.2 %) with one global threshold (0.36). On the 250 old Bengaluru
frames every false alarm of v3 and v4 was the FIRE class; Bengaluru smoke scores stayed under about 0.01. The threshold
was also chosen on false alarms alone, and the v4 validation recall (91.5 %) was well above its test recall (78.0 %).

## What changes from v4 (nothing is trained: the v4 weights, md5 of the ONNX cb261380..., are scored again)
1. **Two thresholds.** An image alarms when its highest fire score >= t_fire OR its highest smoke score >= t_smoke.
2. **Choice rule, on validation data only** (grid 0.05 to 0.95, step 0.01, both classes):
   keep the pairs whose false alarms on the Bengaluru validation frames (frames named blr_*, split val) are at most
   floor(0.003 x n) frames; among them take the pair with the highest recall on the validation images with fire or smoke
   that are not Bengaluru frames, AFTER removing every such image within 40 fingerprint bits of a training image;
   ties: fewer alarms on validation images with no fire (not Bengaluru), then the larger t_fire + t_smoke.
   Stop (no verdict) if fewer than 60 such images remain.
3. **A new fresh Bengaluru test set (B3):** 250 frames never used by any version. A candidate is dropped when it is within
   72 fingerprint bits of any frame the model trained on or validated on, of any frame of the 250 old test frames, of
   the 250 v4 fresh test frames, or of the v4 validation/pool frames (same camera), or within 8 bits of a frame already
   kept. The notebook looks at no more than 6,000 candidates; if it finds fewer than 250 it STOPS and no verdict is made.
   B3 is scored once.

## Targets (all must pass for "v5 Step 1 passes")
| # | Test | Data | Target |
|---|------|------|--------|
| A | Recall, any fire or smoke, at the chosen pair | D-Fire test images with fire or smoke (2,301) | >= 85 % |
| B3 | False alarms at the same pair | the 250 NEW Bengaluru test frames | <= 1 % (at most 2 of 250) |
| C | Recall on street and vehicle fires | held-out FASDD images labelled V or R (near-copies of training/validation removed) | >= 80 % (point estimate; Wilson 95 % reported) |
| D | Inferno vehicle fires, if it arrives before the verdict | recall at the same pair | >= 80 %, else the verdict is "provisional" |

## Reported, not judged
- A split by label: of the D-Fire test images with fire, how many alarm; of those with smoke, how many (both under the any-alarm rule).
- False alarms on the 250 old and the 250 v4 Bengaluru test frames; false alarms on D-Fire negatives.
- The single-threshold best pair under the same rule (t_fire = t_smoke), for comparison.
- What the alarming B3 frames show (crops).

## Known weaknesses, stated now
- 250 frames: 0, 1 or 2 alarms pass; 3 fail. One frame changes the verdict.
- Two thresholds are chosen on about 950 Bengaluru validation frames (at most 2 alarms allowed): the pair may be fitted to them.
- The validation recall set is small after removing near-copies; the pair may be noisy.
- A, C and the old/v4 test frames were seen by earlier versions (never used for training or tuning).
- "Same camera" is a 72-bit fingerprint proxy, not a camera id.
- All frames are Bengaluru CCTV with UVH-26's privacy blurs. Other cities and cameras are untested.

## If it fails
Reported as a failure with numbers. Not wired into `services/vision-service`. The next step is Step 2 (second-stage crop
classifier) in the plan, with its own locked targets.

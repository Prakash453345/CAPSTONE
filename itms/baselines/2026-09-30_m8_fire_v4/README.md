# M8 fire and smoke detector, version 4: FAILS target A

Trained in Colab on 2026-10-01 with `notebooks/m8_fire_smoke_v4.ipynb` (YOLO11-S, 640 px, seed 26, T4, 136 minutes).
Targets were written before the run: `TARGETS_LOCKED.md` (md5 `d320e39ae00d27763da9c589e218fb3e`, unchanged).
Files here: `fire_report.json`, `fire_manifest.json` (from Colab), `false_alarms_250_old.json` (laptop, `scripts/m8_fire_eval.py`).
Weights: `itms_fire_v4_results/itms_fire_640.onnx` (md5 `cb261380d85330731537a0f50dd4febc`), not wired into `services/vision-service`.
The 250 fresh Bengaluru test frames are in `itms_fire_v4_results/bengaluru_test2_frames.tar`.

## Verdict against the locked targets
| # | Target | Result | |
|---|--------|--------|---|
| A | D-Fire test recall (any fire or smoke) >= 85 % | **78.0 %** (2,301 images; fire 87.0 %, smoke 67.2 %) | **FAIL** |
| B2 | false alarms on the 250 FRESH Bengaluru frames <= 1 % (at most 2) | 1 of 250 = 0.4 % | pass |
| C | recall on held-out FASDD street/vehicle fires (V+R) >= 80 % | 76 of 78 = 97.4 % (Wilson 95 %: 91.1-99.3 %) | pass |
| D | Inferno recall | not run: the dataset has not arrived | open |

v4 does not pass, and is not adopted. Threshold 0.36, chosen by the notebook on validation (false alarms on the Bengaluru validation
frames <= 0.3 %): at that threshold validation showed 0.21 % false alarms (2 of 958 frames) and 91.5 % recall.

## What the numbers show
- **The false-alarm problem that failed v3 is fixed on fresh frames, and the price is recall.** v3 (threshold 0.12): 7 of 250 old
  test frames, 90.9 % D-Fire recall. v4 (threshold 0.36): 1 of 250 fresh frames, 2 of 250 old frames (0.8 %, reported not
  judged), 78.0 % D-Fire recall. The locked targets expected this trade-off ("A and C may fail").
- **The recall lost is mostly smoke.** Smoke recall fell from 85.7 % (v3) to 67.2 %; fire recall from 97.1 % to 87.0 %.
- **The one fresh alarm** (frame 876137, score 0.64): a night infrared frame, the bright rear lights of a van. Two further fresh frames
  scored 0.33 and 0.32, just under the threshold.
- **Street recall held up** (97.4 %, v3: 100 %); 2 of 78 street fires missed. The model still alarms on many images with no visible
  fire (held-out label X: 64 of 84), and on 8.1 % of D-Fire's negative test images (v3: 18.7 %).
- Fire and smoke are judged together in A. How much a smoke miss matters for the junction cameras is a design question this
  verdict does not answer.

## Caveats
- A has been scored once per version on the same D-Fire test split (v1 to v4); nothing was trained on it or tuned on it, but it is no longer a fresh test.
- "Same camera" removal used a 72-bit fingerprint: 69 Bengaluru training frames, 29 hard negatives and 42 validation frames were dropped
  as the same camera as a fresh test frame (from `fire_manifest.json`); the fresh draw also skipped 412 frames that looked like the old test cameras.
- 250 fresh frames: the one-frame difference between 1 and 3 alarms is the whole verdict; the old frames gave 2.
- The threshold is picked only on Bengaluru validation false alarms, so it knows nothing about how much D-Fire recall it costs
  (validation recall was 91.5 %, D-Fire test recall 78.0 %).

## Training data (from `fire_manifest.json`)
As v3, plus 771 hard negatives (flame-coloured Bengaluru frames, from a pool of 2,500), 958 validation frames after camera removal
(1,000 planned), and 1,431 plain Bengaluru training negatives after camera removal (1,500 planned).

## Options for a next step (not done; any needs new locked targets)
1. **Separate thresholds for fire and smoke**, chosen on validation: smoke recall dropped most, and the v3 false alarms we looked at were
   orange or yellow things, not grey smoke-like ones (v4's one alarm is a bright night lamp). Needs fresh Bengaluru test frames again, because these 250 are now seen.
2. **Judge A on fire only** if the design says smoke need not carry the frame-level bar. That is a change of target, so it belongs to a new version, not to this verdict.
3. Accept the per-frame trade-off and rely on the downstream layers (persistence, flicker/growth check, operator confirmation, ADR-006).
   This needs a decision on what false-alarm and miss rates the operator desk can live with.

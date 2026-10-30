# M8 fire and smoke detector, v5 Step 1 (new thresholds on the v4 weights), 2026-10-02/03

**Verdict: PASS on all three judged targets (A, B3, C). D (Inferno) has not arrived, so it stays "provisional".**
Nothing was trained. The v4 weights (`itms_fire_640.pt`, sha256 `bc5c70ec...a001ca1fe`, checked in the run) were
re-used; only the alarm rule changed. Targets were locked before the run in `TARGETS_LOCKED.md`.
Run: `notebooks/m8_fire_smoke_v5_step1.ipynb`, ultralytics 8.4.163, results in `fire_report.json`.

## Alarm rule and chosen thresholds
An image alarms when max fire score >= t_fire OR max smoke score >= t_smoke.
Chosen on VALIDATION data only (rule in TARGETS_LOCKED.md): **t_fire 0.44, t_smoke 0.11**.
- Validation positives: 1,390, of which 1,236 remain after removing near-copies (<= 40 dhash bits) of training images.
- Bengaluru validation frames: 958, alarms at the chosen pair: 2 (the cap).
- Validation recall at the pair: 97.3%. D-Fire validation negatives alarming: 11.1%.
- Best single threshold under the same rule: 0.36 for both, validation recall 91.8%.

## Judged targets
| # | Test | Target | Result | |
|---|---|---|---|---|
| A | recall, any fire or smoke, D-Fire test (2,301 images with fire or smoke, of 4,306) | >= 85% | **89.27%** | PASS |
| B3 | false alarms, 250 NEW Bengaluru frames (more than 72 bits from every known camera) | <= 1% (at most 2) | **1 of 250** | PASS |
| C | recall, held-out FASDD street/vehicle fires (V+R, 78 images) | >= 80% | **76 of 78 = 97.4%**, Wilson 95% [91.1%, 99.3%] | PASS |
| D | Inferno | >= 80% | not run | provisional |

## Reported, not judged
- A by label: images with fire 95.6%, images with smoke 90.0%.
- **D-Fire negatives that alarm: 19.1%** (single 0.36 threshold on v4: 8.1%, with A recall 77.97%). Recall was bought partly with false alarms on images that do not look like Bengaluru CCTV.
- C by label: B 60/61, F 64/64, I 37/41, O 88/97, R 21/23, V 55/55; not street 315/347; **X (no visible fire) 66/84 alarm**. 75 near-copies of training images were removed from the 500 held-out images.
- B3 candidates: 624 looked at, 205 skipped (same camera), 150 skipped (duplicates).
- v4's fresh 250 frames at the new pair: 1 alarm. Old 250 test frames at the new pair: 2 alarms (`234270.png` fire 0.709, `964462.png` fire 0.632), scored by a one-off script with the ONNX export, not by the notebook.

## What the one B3 alarm is
Frame `803445.jpg`, fire 0.4673 in the notebook (0.4965 in the Mac check with the ONNX export; small export difference), smoke 0.0003. I looked at it: the box sits on the **blurred yellow-orange number plate of a truck**, not on a fire. The next-highest fire scores on B3 were 0.0723 and 0.0703, so this frame stands alone but only just clears the 0.44 threshold. Highest smoke score on B3: 0.0531 (threshold 0.11).
Indian commercial vehicles (taxis, trucks, autos) carry yellow plates, so this is a systematic look-alike, not a one-off. It is one frame in 250; it is not measured how often it recurs.

## What this does and does not show
- The three judged targets passed as locked. B3 passed with a margin of one frame.
- B3 is 250 frames: 1 alarm gives about 0.4% per frame with a wide interval (Wilson upper bound about 2.2%, my calculation). The 1% target is met by the point estimate, not proven.
- The thresholds have two free parameters and were chosen with a cap of 2 alarms in 958 validation frames; they may be fitted to those frames. Validation recall (97.3%) is still above test recall (89.3%) after near-copy removal.
- Per-frame arithmetic (mine, not measured): 0.4% of frames at 1 Hz is roughly 14 false alarms per hour per camera before any persistence. The persistence, flicker/growth and operator-confirmation layer (ADR-006) is therefore required, not optional. No street-fire video exists to test it.
- Everything is Bengaluru CCTV with UVH-26 privacy blurs; other cities, night and fog are untested. The D-Fire negative alarm rate (19.1%) is the warning sign.
- Street recall (C) is on 78 images. X-label images alarm 79%, so recall on C may partly reflect "anything bright".
- A and C were seen by earlier versions (never used to train or tune). "Same camera" is a 72-bit fingerprint proxy.

## Consequences
- `services/vision-service` needs two thresholds (fire 0.44, smoke 0.11), not one.
- Next options, not yet decided: wire into vision-service with the persistence layer; Step 2 (second-stage crop classifier, with yellow plates as a named negative) to cut look-alike alarms; Inferno when it arrives.

## Files
`fire_report.json` (md5 f9811e324f61ffb891253c0d1bdad7e7), `bengaluru_test3.tar/.json/_review.jpg`, `test_misses.jpg`, `heldout_street_misses.jpg` in `itms_fire_v5_step1_results/`.

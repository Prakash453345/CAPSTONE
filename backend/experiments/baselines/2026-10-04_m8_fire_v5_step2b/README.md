# M8 fire v5 Step 2b: result (2026-10-05). FAILED two of seven locked targets; Step 2 classifier stays

Targets: `TARGETS_LOCKED.md` (governs). Full numbers: `s2b_report.json` (`verdict_2b`). New classifier thresholds chosen on validation: p_fire 0.80, p_smoke 0.85 (Step 2: 0.80 / 0.90).

| # | Test | Target | Step 2b | Step 2 | Verdict |
|---|---|---|---|---|---|
| A | D-Fire recall | >= 85 % | 89.4 % | 85.7 % | pass |
| N | D-Fire no-fire images alarming | <= 10 % | 13.8 % | 9.5 % | **FAIL** |
| P | D-Fire precision | >= 90 % | 88.1 % | 91.2 % | **FAIL** |
| C | street fire recall (78 images) | >= 80 % | 100 % | 100 % | pass |
| B5 | clean new Bengaluru frames alarming | <= 2 of 250 | 1 | 2 | pass |
| G | degraded B5 alarms, each condition | <= 3 of 250 | max 3 (blur) | blur 5, glare 3, rain 3, jpeg 2 | pass |
| R | street recall change under degradation | >= -0.05 | worst -0.013 (noise) | n/a | pass |

Degraded B5 alarms, new / Step 2: clean 1/2, dusk 1/1, night 1/1, noise 1/1, blur 3/5, jpeg 1/2, haze 1/1, glare 1/3, rain 1/3.
Street recall, new / Step 2: glare 0.846 / 0.782, noise 0.974 / 0.987, night 0.987 / 0.987, every other condition 1.0 / 1.0. B4 alarms 0 / 1.

## Reading
Augmentation did what it was meant to on the new frames: fewer alarms under blur, glare, rain and JPEG, and better street recall in glare. But on D-Fire it
alarms on more no-fire images (13.8 % against 9.5 %) and precision falls below the bar, so by the locked rule it is not adopted.
I did not tune anything on these results. I have not established why N rose; the lower smoke threshold (0.85) chosen by the validation rule may be part of it.
Caveats: B5 has 250 frames, so 1 against 2 alarms is not a measured improvement; glare, noise, blur and dusk rows are in-family with training; the street set is 78 images and both models score about 100 % clean.

## Decision
Step 2 classifier (`itms_fire_cls_112.onnx`, thresholds 0.80 / 0.90) stays deployed. A further attempt (a different threshold rule, or an augmentation mix with fewer dim crops) would need new locked
targets and fresh D-Fire-independent test frames; A, N and P have now been looked at twice.

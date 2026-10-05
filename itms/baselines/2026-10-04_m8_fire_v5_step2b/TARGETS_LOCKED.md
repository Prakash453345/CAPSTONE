# M8 fire v5 Step 2b: classifier retrained with degradation augmentation. TARGETS LOCKED before the run (2026-10-04)

Why: the 2026-10-04 stress probe (`../2026-10-04_m8_stress.md`) showed Step 2's classifier alarming on 2 to 5 of 250 no-fire frames under night, glare
and soft focus (clean: 1), all barely over the bar, and nothing measured fire recall in those conditions. Step 2b trains the same classifier with
degradation augmentation and measures both. Nothing below may change after a run starts.

## Design (fixed, not tuned)
- Same detector (v4 weights), same crops, same classifier, recipe and seed as Step 2 (`../2026-10-03_m8_fire_v5_step2/TARGETS_LOCKED.md`). Candidate boxes are reused.
- The only change: each TRAINING crop is degraded at random before the existing augmentation. Dimming (p 0.25; gamma 1 to 2.2, times 0.5 to 1),
  headlight glare on a dimmed crop (p 0.15; 1 to 3 soft bright spots, sigma 6 to 20 px), sensor noise (p 0.30; sigma 0.02 to 0.09), blur (p 0.20; sigma 0.5 to 4 px).
  JPEG, haze and rain are NOT trained (they test transfer). Validation crops are never degraded.
- (p_fire, p_smoke) are chosen again on validation by the Step 2 rule. The last epoch is used.
- Test conditions are the stress probe's nine, verbatim, with the same seeds: clean, dusk, night, noise, blur, jpeg, haze, glare, rain.
- B5 = 250 NEW Bengaluru frames, more than 72 dhash bits from every frame any step used (B3 and B4 included). Street set = held-out FASDD V or R images, near-copies of training removed (as in C).

## Judged targets (all must pass; the Step 2 classifier is scored on the same frames for comparison)
| # | Test | Target |
|---|---|---|
| A | D-Fire test recall, any fire or smoke | >= 85 % |
| N | D-Fire test no-fire images alarming | <= 10 % |
| P | D-Fire test image-level precision | >= 90 % |
| C | held-out street and vehicle fire recall (clean) | >= 80 % |
| B5 | clean B5 frames alarming | at most 2 of 250 |
| G | degraded B5 frames alarming, each of the 8 degraded conditions | at most 3 of 250 each |
| R | street fire recall under each of the 8 degraded conditions | no more than 0.05 below the Step 2 classifier's recall in the same condition |

If any fails, the Step 2 classifier stays deployed and nothing is retuned on these frames.

## Reported, not judged
Step 2's own numbers on every judged row; B4 alarms (B4 was Step 2's test); classifier validation accuracy; alarm frames per condition; street recall in absolute terms per condition.

## Known weaknesses, stated now
- Dimming, glare, noise and blur rows are in-family with the training augmentation; only JPEG, haze and rain test transfer.
- The detector is not retrained: a fire the detector cannot propose under degradation cannot be rescued by the classifier, so recall under degradation is bounded by the detector.
- Degraded frames are darkened or noised daylight frames, not real night or CCTV footage. No real night fire footage exists here.
- A, N and C were scored for Step 2 before and are scored again for this model (never used to train or choose); B5 and its degradations are new frames.
- The street set has about 78 images, so a 0.05 change in R is about 4 images.

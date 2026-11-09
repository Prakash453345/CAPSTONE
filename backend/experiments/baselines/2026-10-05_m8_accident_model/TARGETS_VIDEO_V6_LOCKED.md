# Accident detector V6 — three-model ensemble of the V5 recipe — targets LOCKED 2026-10-15, before any V6 training or scoring

Reference (geo test, n = 1,573): V4 deployed 61.3 % detect / 5.2 % early / 56.8 % strict / 2.24 s, highway 48.2 %, window AUROC 0.799, false-alarm proxy 64.7 runs/h.
V5 (not adopted): 67.6 / 5.34 / 62.6 / 2.90 s, highway 56.8 %, AUROC 0.815, proxy 75.6 runs/h. V5 missed only the early-alarm line (by 0.34 points) and the false-alarm line.
The user asked for a better-performing model. V5 gains recall from three crops and the hard-negative stage, but one model's stray high crop score still raises early and false alarms.
Averaging independently trained models of the same recipe is the standard way to damp such isolated spikes while keeping the shared signal. No other change is made.

## What is built
Members (all geo split, same train / 20 % grouped validation partition as V4 and V5, seed 0 for the partition; K = 3 crops; recipe of V5: 4 epochs from Kinetics, hard-negative mining on TRAIN clips, 2 more epochs at lr 2e-5):
- M0 = the existing V5 geo model (weights from `accident_v5_results`; no retraining).
- M1, M2 = two fresh models trained with training seeds 1 and 2 (only data order, augmentation and dropout differ).
Each member's per-view scores for every 1-s window of the validation clips and of the full geo test are recorded ONCE (no thresholds). Window score of a member = max over its views (as V4 and V5).
Ensemble window score = mean of the three members' window scores. One recipe, no alternatives, no fusion variants.

## Selection (validation only) and scoring
(thr, k, n) is chosen on the validation clips from the existing grid (A.CFG_GRID x A.THR_GRID) by the usual rule, EXCEPT the early-alarm cap is 3 % instead of 4 %. Reason, stated honestly: in every earlier run
the test early-alarm rate came out 1.3 - 4.3 points above its validation value (V4 geo 3.0 -> 5.2, V5 geo 3.0 -> 5.3, V5 in-dist 1.9 -> 6.2); that gap was seen on the test splits, so this is a test-informed choice.
The test split is evaluated once for the chosen configuration. Per-member results (each member with its own validation-chosen configuration under the same 3 % cap) are reported for context, not judged.
Sanity check (not a selection): M0's dump with the published V5 configuration (thr 0.85, 3-of-5) must reproduce 67.6 % test detect within 0.5 points, else the dump is wrong and the whole result is void.

## Targets (judged on the geo test, once)
| # | Target |
|---|---|
| E1 | geo detect within 10 s >= 66 % |
| E2 | geo early alarm <= 5 % |
| E3 | geo strict (detect and not early) >= 61 % |
| E4 | geo false-alarm proxy <= 64.7 runs/h (not worse than V4; method of `TARGETS_VIDEO_V4_FALSE_ALARM_LOCKED.md`) |
| E5 | geo window AUROC >= 0.815 (V5's, same code) |
| B5 | nothing tuned on test (selection on validation only) |
Adoption rule: the ensemble replaces V4 only if E1-E5 all pass. Otherwise V4 stays and V6 is written up as a failed attempt.
Reported, not judged: highway / Very_Poor / night / rear-end / sideswipe slices, each member alone, validation numbers, inference cost.

## Known limits (state them whenever quoting results)
- The geo test split has now been scored for V3, V4 (twice), V5 and V6 (and member dumps); a pass by a point or two is weak evidence (SE about 1.2 points; repeated looks cannot be undone). The 3 % cap is test-informed.
- M0 and the V4 geo model share a stage-1 starting point; M1 and M2 are independent restarts, so members are correlated through the data and the recipe.
- Inference cost is three models x up to 4 views per window = 12 passes (V4: 3). On CPU that is far slower than real time; this needs a GPU or a lower view count to be usable live.
- In-distribution is not re-done (the in-dist V4 weights were deleted). All-accident clips; ordinary-traffic false alarms only proxied; ~80 % US footage; one partition.

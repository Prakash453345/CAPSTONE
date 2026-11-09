# Accident detector V7 — self-supervised VideoMAE start (V5 recipe) — targets LOCKED 2026-10-16, before any V7 training or scoring

Reference (geo test, n = 1,573): V4 deployed 61.3 % detect / 5.2 % early / 56.8 % strict / 2.24 s, highway 48.2 %, window AUROC 0.799, false-alarm proxy 64.7 runs/h.
V5 (not adopted): 67.6 / 5.34 / 62.6 / 2.90 s, highway 56.8 %, AUROC 0.815, proxy 75.6 runs/h. V6 ensemble (not adopted): 61.0 / 3.24 / 58.0 / 2.18 s, AUROC 0.835, proxy 40.3 runs/h.

## Why this change (and only this one)
Every model so far starts from `MCG-NJU/videomae-base-finetuned-kinetics`, i.e. weights that were fine-tuned on Kinetics class labels. A 2025 study of plain video transformers for
traffic-anomaly detection on dashcam benchmarks (arXiv 2507.09338) reports that masked-video (self-supervised) pretraining transfers best, that label-supervised and language-aligned
pretraining transfer less well, and that Kinetics accuracy does not predict anomaly-detection quality. That evidence is dashcam, not fixed CCTV, so it may not carry over.
V7 therefore starts from the self-supervised `MCG-NJU/videomae-base` and changes nothing else about the V5 recipe except the stage-1 length (below).

## What is built (fixed now)
- Backbone: `ACC_VID=MCG-NJU/videomae-base` (self-supervised, no Kinetics fine-tuning). Fresh classification head. Same code path as V4 / V5.
- Recipe = V5, geo split only, seed 0, same grouped 20 % validation partition: stage 1 from the backbone, then hard-negative mining on TRAIN clips, then stage 2 (2 epochs, lr 2e-5);
  K = 3 local crops (V5's measured choice, not re-chosen); alarm grid including the rise-over-baseline delta {0, 0.15, 0.30}; (thr, k, n, delta) chosen on validation with the V5 rule
  (early cap 4 %, ties prefer smaller delta). Test split scored once.
- ONE deviation from V5: stage 1 runs 6 epochs instead of 4. Reason, stated before any result: self-supervised weights have no task head start and usually need a longer schedule than a
  label-supervised start; 4 epochs would risk an under-trained model that tells us nothing about the backbone. No other schedule, learning rate or augmentation change; no search over epochs.
- Because of this deviation, V7 vs V5 is "the recipe suited to this backbone vs the recipe suited to the Kinetics backbone", not a pure backbone effect.
- Loading check before training: no encoder / embedding weight may be reported missing, and the q/v bias guard in `build_model` must pass; otherwise the run is void.

## Targets (judged on the geo test, once) — same bar as V6
| # | Target |
|---|---|
| H1 | geo detect within 10 s >= 66 % |
| H2 | geo early alarm <= 5 % |
| H3 | geo strict (detect and not early) >= 61 % |
| H4 | geo false-alarm proxy <= 64.7 runs/h (V4's; method of `TARGETS_VIDEO_V4_FALSE_ALARM_LOCKED.md`) |
| H5 | geo window AUROC >= 0.815 (V5's, same code) |
| B5 | nothing tuned on test (selection on validation only) |
Adoption rule: V7 replaces V4 only if H1-H5 all pass. Otherwise V4 stays and V7 is written up as a failed attempt.
Reported, not judged: highway / Very_Poor / night / rear-end / sideswipe slices, validation numbers, per-epoch training loss, hard negatives mined, inference cost (same as V5: 4 views per window).

## Known limits (state them whenever quoting results)
- The geo test split has been scored for V3, V4 (twice), V5, V6 and now V7; a pass by a point or two is weak evidence (SE about 1.2 points; repeated looks cannot be undone).
- One seed. Three same-recipe Kinetics-start models scored 62.6 (M0 = V5), 59.4 (M1) and 56.5 (M2) % geo test detect at the same 3 % validation early cap (V5 itself, at its own 4 %-cap
  configuration, 67.6 %), so a V7 difference of a few points from V5 cannot be credited to the backbone.
- The stage-1 length differs from V5 (6 vs 4 epochs). Validation (99 clips) cannot choose between model variants; it only sets the alarm rule.
- In-distribution is not run. All-accident clips; ordinary-traffic false alarms only proxied; ~80 % US footage; dashcam evidence for the idea, CCTV test here.

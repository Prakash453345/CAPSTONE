# Accident detector V3: fine-tuned pretrained VIDEO backbone (VideoMAE, Kinetics-400) — targets LOCKED 2026-10-12, before the run

Why: the web has no credible ready-made accident detector (the only public checkpoint found, a 112-px 3D-ResNet on HF, states no training data and no accuracy). Zero-shot VLM failed (29 % detect).
v1/v2 were ImageNet image nets with at most 2 frames of motion. What is untried is a pretrained spatio-temporal backbone fine-tuned on the benchmark's own clips.

Model: MCG-NJU/videomae-base-finetuned-kinetics, 16 frames at 4 fps (4-s window), 224 px (frame squashed, as v2), head -> 1 logit. Windows are scored every 1 s; alarm time = window END.
Labels: window end <= impact-1.0 s -> normal (this includes pre-crash traffic as hard negatives); impact+0.5 s .. impact+3 s -> accident; else ignored. Real clips only.
Protocol (unchanged from v1/v2): 20 % of each split's TRAIN clips (grouped by source video) = validation; threshold + k-of-n persistence chosen on validation (early-alarm cap 4 %), frozen;
the split's full test set (in-distribution 1,520 clips; geo-aware 1,573) scored once. Seed 0. No test-set tuning.

Targets = B1-B5 of TARGETS_LOCKED.md, unchanged: B1 detect <=10 s after impact >=70 % (in-dist); B2 alarm before impact <=5 %; B3 median delay <=5 s; B4 geo >=60 % detect and <=8 % early; B5 nothing tuned on test.
Limits: all-accident clips (no false alarms per camera-day); ~80 % US footage; 224-px squash loses small distant crashes (the known weakness); one seed; if it passes it is a candidate for an operator (ADR-006).

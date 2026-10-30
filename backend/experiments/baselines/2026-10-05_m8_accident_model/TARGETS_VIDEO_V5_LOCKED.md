# Accident detector V5 — targets LOCKED 2026-10-14, before any V5 scoring

Reference = V4 rerun (`2026-10-14_m8_accident_video_v4_rerun.md`): in-dist test 69.0 % detect / 6.3 % early / 63.3 % strict / 2.98 s;
geo test 61.3 % / 5.2 % / 56.8 % / 2.24 s; geo highway detect 48.2 %, Very_Poor 42.2 %; false-alarm proxy 64.7 runs/h (95 % CI 48.4-84.6).

## What changes (each tied to a measured weakness; nothing chosen by looking at a test split)
1. Hard-negative mining (targets early/false alarms). After V4-style training, score every TRAIN-fold clip's pre-impact windows
   (window end <= impact - 2.0 s, a wider gap than the label gap so genuine precursors are not mined); the highest-scoring (>= 0.4, at most 4 per
   clip, with the view that scored highest) become hard negatives. Stage 2 = 2 more epochs, lr 2e-5, where up to 2 of each clip's 4 normal
   windows are its hard negatives. Mined from train clips only; validation and test clips never used.
2. Local crops K = 2 or 3 (targets the 26 % of clips where no crop covers the crash). Rule fixed now: coverage of K = 2 and 3 measured on 300
   TRAIN clips; K = 3 only if clip coverage rises by >= 4 points, else K = 2.
3. Alarm rule gains a rise condition (targets scenes that stay hot): a window is hot if score >= thr AND score - baseline >= delta, baseline =
   median of the 8 scores before the last n windows (needs >= 3, else baseline 0 = V4 behaviour). delta in {0, 0.15, 0.30} added to the
   (thr, k, n) grid; chosen on the 20 % grouped validation split with the same selection rule (early cap 4 %, ties prefer smaller delta).
Geo split: stage 1 = the deployed V4 geo weights (same train/validation partition, seed 0); in-dist: stage 1 retrained (the in-dist V4 weights were deleted).
Protocol otherwise unchanged: seed 0; real clips only; test splits scored once; nothing tuned on test.

## Targets (judged on the test splits, once)
| # | Target |
|---|---|
| I1 | in-dist detect within 10 s >= 72 % |
| I2 | in-dist early alarm <= 5 % |
| I3 | in-dist strict (detect and not early) >= 66 % |
| I4 | in-dist median delay <= 5 s |
| G1 | geo detect within 10 s >= 64 % |
| G2 | geo early alarm <= 5 % |
| G3 | geo strict >= 60 % |
| G4 | geo highway detect >= 52 % |
| G5 | geo false-alarm proxy < 48 runs/h (point estimate; method of `TARGETS_VIDEO_V4_FALSE_ALARM_LOCKED.md`) |
| B5 | nothing tuned on a test split |
Reported, not judged: window-level AUROC and average precision on each test split (normal windows vs accident windows; V4 geo reference computed with the same
code), Very_Poor and night slices, the chosen K and delta, how many hard negatives were mined, proposal coverage for K = 2 and 3.

## Adoption rule (fixed now)
V5 replaces V4 in the app only if G1, G2 and G3 all pass AND window AUROC on the geo test is not lower than V4's. Otherwise V4 stays and V5 is written up as a failed attempt.

## Known limits (state them whenever quoting results)
One seed; all-accident clips, so ordinary-traffic false alarms are still only proxied; ~80 % US footage; V5 costs one extra crop per window at inference if K = 3;
the rise condition cannot act in the first seconds of a clip (no baseline yet), and most clips have the impact within a few seconds of the start; the in-dist stage 1 is a new run, so
I1-I4 compare two different trainings, not one model before and after.

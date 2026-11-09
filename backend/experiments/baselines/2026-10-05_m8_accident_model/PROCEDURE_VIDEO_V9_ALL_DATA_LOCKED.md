# Accident detector "V9": the V8 recipe trained on ALL labelled clips — procedure LOCKED 2026-10-18, before any run

This is a deployment-style retrain, not a benchmark attempt. There is NO held-out test split afterwards (the geo test clips are in the training data), so this model gets NO test number and
cannot be judged against V4 by the benchmark. It exists because more and more varied training data (all 2,027 real clips, US and non-US) is the one change likely to help on new cameras, and because
a larger validation split (about 400 clips instead of 99) gives a steadier alarm rule.

## Why this recipe
Five variants (V5-V8, V6 ensemble) were tried against the locked rule; none passed. Of the retrains that start from the Kinetics VideoMAE, V8 had the best measured geo-test profile
(63.8 % detect / 4.96 % early / 59.4 % strict / AUROC 0.812 / proxy 53.7 runs/h) against 59.4 and 56.5 % detect for the V6 members M1, M2. Seed spread is about 6 points, so V8's edge over them is NOT established;
V8 is chosen only because it is the best measured recipe of its kind, not because the crash-centred crops are proven to help.

## What is run (fixed now)
- Data: all rows of `metadata-real.csv` (expected 2,027 clips). Grouped 20 % validation split by source video (`split_train_val`, seed 0): about 80 % train, 20 % validation. Validation clips are never trained on.
- Recipe = V8: stage 1 from the Kinetics VideoMAE (4 epochs, lr 5e-5), hard-negative mining on TRAIN clips, stage 2 (2 epochs, lr 2e-5), K = 3 crops, crash-centred crops for uncovered positive windows, seed 0.
- Alarm rule (thr, k, n, delta): chosen on the validation clips by the V5 rule, with the early-alarm cap at 3 % (not 4 %), because in every earlier run the test early rate exceeded its validation value by 1.3-4.3 points (test-informed, disclosed).
- Nothing is scored on a test split. Reported: validation detect / early / strict / delay, window AUROC and AP, false-alarm proxy on the validation clips, slices.

## What may be claimed afterwards
- The held-out numbers of the same recipe family, quoted as such: V8 on the geo test 63.8 / 4.96 / 59.4 (V4 61.3 / 5.2 / 56.8); six-point seed spread; V9 itself has no measured held-out number.
- Validation numbers are optimistic by 5-20 points on detect (every earlier run) and understate early alarms; they are NOT a performance estimate.
- Swapping V4 for V9 in the app is a judgement call made without a benchmark comparison; the app keeps V4 until the user decides.

## Known limits
- No test number; one seed; one partition; ordinary-traffic false alarms unmeasured; ~80 % US footage; Indian-camera accuracy unknown.
- Validation clips share cameras/locations with training clips more than the geo test did, so the alarm rule chosen here is tuned to in-distribution behaviour and may be less conservative than a geo-chosen rule.
- Run time on a T4 x2 is estimated at 7-10 h (about 4.5 times the training clips of the earlier runs); the Kaggle limit is 12 h.

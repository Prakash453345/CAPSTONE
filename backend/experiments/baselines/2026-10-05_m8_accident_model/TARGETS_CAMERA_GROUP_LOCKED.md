# V10 camera-group test — do accident-free Indian clips as negatives cut false alarms on UNSEEN cameras? — targets LOCKED 2026-10-23, before any V10 training or scoring

Context: on the 13 accident-free Indian pole-CCTV clips (51 min) the deployed V4 raised 121 alarm runs/h and V9 75/h (`baselines/2026-10-22_m8_accident_indian_suite.md`). The training data has no ordinary Indian traffic. No new footage is available, so the only Indian negatives are these 13 clips; they can be used for training only if the effect is measured on cameras the model has not seen.

## Design (fixed now)
- Base model: `itms_accident_v9.pt` with its stored rule (thr 0.95, 3-of-5, delta 0, K = 3). The rule is NOT re-chosen anywhere in this experiment.
- Camera groups of the 13 accident-free clips (by city/camera type): airpix (normal_01), atcc (02, 03, 04), pune (05, 11), hyderabad (06), delhi (07-10), tirupati_signal (accident_27, accident_28). The 27 accident clips are never used in training (only scored).
- Fine-tune ("stage 3"), identical for every fold: 1 epoch, lr 1e-5 (the repo's `V.train`, OneCycle), data = benchmark replay of 600 clips (fixed random sample, seed 0, V8 window rules) + about 1,500 accident-free windows per epoch drawn from the TRAINING groups' clips (label 0, random view among global + 3 motion crops, windows per clip proportional to length, 16 per item). No search over lr, epochs, replay size or window counts.
- Folds: for each of the 6 groups, train with the other 5 groups' negatives, score the held-out group's clips and all 27 accident clips. Every accident-free clip is therefore scored exactly once by a model that never saw its group.
- Controls scored in the same run: BASE = V9 unchanged; CONTROL = the same fine-tune with the benchmark replay only (no Indian negatives).
- Final model V10 = same fine-tune with all 6 groups. It cannot be scored on a held-out Indian camera; its expected behaviour is whatever the folds show.

## Targets (judged once, on the pooled held-out results)
| # | Target |
|---|---|
| L1 | pooled held-out false-alarm rate <= half of BASE's pooled rate on the same clips (V9 earlier: 75.1 runs/h, so about 37.5) |
| L2a | mean accident detect (alarm in [t, t+10 s], the 27 clips) over the 6 fold models >= 70 % (V9: 81.5 %) |
| L2b | mean accident early alarm over the 6 fold models <= 25 % (V9: 18.5 %) |
| L3 | held-out false-alarm rate below BASE's in at least 4 of the 6 groups |
| B | nothing tuned on a held-out group (rule and hyper-parameters fixed above) |
Reported, not judged: CONTROL rates; per-group numbers; strict detect; median delay; confidence intervals.

## Decision rule
- L1-L3 all pass: V10 (all groups) is saved as "improved, NOT deployable": even half of 75 runs/h is one alarm every 1.6 minutes per camera, so app-side gating and ADR-006 wording stay mandatory, and V4 stays the deployed model until a separate locked plan replaces it.
- Any of L1-L3 fails: 51 minutes of accident-free footage do not transfer across cameras; V10 is written up as a failed attempt and no further model work on this recipe without new footage.
- If CONTROL alone reduces BASE's false-alarm rate by at least half of what the folds do, the gain is credited to extra fine-tuning, not to the Indian negatives (stated in the write-up).

## Known limits (state with any result)
- 13 clips, about 51 min, 6 coarse groups; groups from one vendor/city may still share look-alike scenes; Poisson CIs understate uncertainty because alarms cluster inside clips.
- One seed, one fine-tune recipe; a fail does not show that more data could not help.
- The 27 accident clips are curated; accident detection is measured with the same definitions as the suite (alarm in [t, t+10 s]; early = alarm before t); crash times hand-read.
- Normal-footage exposure per group is very uneven (airpix 22 min, delhi 2 min).

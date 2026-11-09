# Accident detector V8 — crash-centred crops for uncovered positive windows (V5 recipe, Kinetics start) — targets LOCKED 2026-10-17, before any V8 training or scoring

Reference (geo test, n = 1,573): V4 deployed 61.3 % detect / 5.2 % early / 56.8 % strict / 2.24 s, AUROC 0.799, proxy 64.7 runs/h. V5 (not adopted) 67.6 / 5.34 / 62.6, AUROC 0.815, proxy 75.6.
V6 ensemble (not adopted) 61.0 / 3.24 / 58.0, AUROC 0.835, proxy 40.3. V7 (not adopted) 56.3 / 4.45 / 52.4, AUROC 0.786, proxy 61.0.

## Why this change (and only this one)
In training (`ClipDS4` stage 1 and `ClipDS5` stage 2) a positive window is built from a motion-proposed crop only when one covers the labelled crash point; otherwise it falls back to the whole squashed frame
with label 1 (checked in the code). With K = 3 crops that is about 29 % of positive windows (window coverage 71.0 %, measured on train clips). On those windows the crash may be a few pixels wide in the 224-px view,
so the label teaches "road scene" more than "crash". V8 gives those windows a crop centred on the labelled crash point (uniform jitter +-0.08 of the frame in x and y, kept inside the frame) so the positive label always
sits on a view that shows the crash. Whether this lowers early alarms or raises recall is untested; V5's third crop (43 % -> 29 % uncovered) left early alarms unchanged, so the hypothesis is not strongly supported.
The idea comes from an outside review of our code, which we verified only for the code behaviour, not for its effect.

## What is built (fixed now)
- Everything as V5 (hard-negative stage 2, K = 3 crops, delta grid, validation-chosen alarm with the 4 % early cap, geo split, same grouped 20 % validation partition, seed 0, test scored once) EXCEPT:
  (1) stage 1 is trained from the Kinetics-finetuned VideoMAE (4 epochs, V4 recipe) with the change, rather than starting from the deployed V4 weights, because the change must apply to stage 1; and
  (2) positives with no covering motion crop use a crash-centred crop in both stage 1 and stage 2. Positives that do have a covering crop keep the V4/V5 rule (random choice among covering crops and the global view). Negatives unchanged.
- Inference is unchanged (global view + 3 motion crops, max over views). Only training windows change.

## Targets (judged on the geo test, once) — same bar as V6 and V7
| # | Target |
|---|---|
| J1 | geo detect within 10 s >= 66 % |
| J2 | geo early alarm <= 5 % |
| J3 | geo strict (detect and not early) >= 61 % |
| J4 | geo false-alarm proxy <= 64.7 runs/h |
| J5 | geo window AUROC >= 0.815 |
| B5 | nothing tuned on test |
Adoption rule: V8 replaces V4 only if J1-J5 all pass. Otherwise V4 stays and V8 is written up as a failed attempt. Reported, not judged: slices, validation numbers, chosen rule.

## Known limits (state them whenever quoting results)
- The geo test split has been scored for V3-V8; a narrow pass is weak evidence (SE about 1.2 points).
- One seed. Same-recipe Kinetics-start retrains with other seeds scored 59.4 and 56.5 % detect (V6 members M1, M2, at a 3 % cap) and V5 itself 67.6 %, so a difference of a few points cannot be attributed to the change.
  V5's stage 1 was the deployed V4 model, so V8 is not a seed-matched repeat of V5.
- Train/inference mismatch: training sees crash-centred crops for hard cases, inference sees motion-proposed crops that may miss the crash; the global view stays as a fallback.
- All-accident clips; ordinary-traffic false alarms only proxied; ~80 % US footage.

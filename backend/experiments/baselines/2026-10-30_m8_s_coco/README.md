# M8 vehicle detector: run 2 of 3 (`s_coco`, stock YOLO11-S trained on the full training split) on the untouched validation frames (2026-10-30)

Targets: `../2026-10-28_m8_full_train/TARGETS_LOCKED.md`. Same locked procedure as run 1 (`../2026-10-29_m8_s_iisc/`), run once: score line placed on the 500 DEV frames, then scored once on the 4,797 UNTOUCHED frames; reference = BatchNorm-repaired IISc at 0.50, timed in the same Kaggle CPU run. Leak check: 0 of 21,344 training names in validation.

| | repaired IISc @0.50 | s_coco @0.60 (DEV-placed) | target | verdict |
|---|---|---|---|---|
| P1 found | 0.729 | **0.755** (+0.026, paired 95 % interval +0.024 to +0.029) | >= 0.769 and lower bound > +0.02 | FAIL (0.014 short) |
| P2 precision | 0.9426 | **0.9471** (+0.0045, interval +0.0026 to +0.0064) | >= 0.943 | pass |
| P3 queue PCU error | 2.60 | **2.39** | <= 2.60 | pass |
| P4 13-class mAP50:95 (all 5,297 frames) | 0.530 | **0.608** | >= 0.560 | pass |
| P5 CPU time vs IISc, same run | 1.00 | 1.07 | <= 1.25 | pass |

Also: false boxes per frame 0.53 -> **0.50** (interval -0.044 to -0.007); AP50 (6-class) 0.790 -> 0.845; 13-class mAP50 0.640 -> 0.710. Found as the right type: car 0.794 -> 0.825, auto-rickshaw 0.767 -> 0.801, bus 0.653 -> 0.695, truck 0.646 -> 0.683, motorcycle 0.691 -> 0.714, bicycle 0.33 -> 0.545.
Compared with run 1 (`s_iisc`: found 0.751, precision 0.942, false 0.55, mAP50:95 0.577): s_coco is better on every row. Training from stock YOLO11-S weights was not worse than starting from IISc's.
Control: the repaired IISc model in this run reproduces the earlier 14-class result (13-class mAP50 0.640, mAP50:95 0.530). DEV sweep (found / precision): 0.50 0.819/0.928; 0.55 0.792/0.940; 0.60 0.764/0.950.

## Verdict, honestly
Four of five locked targets pass; P1 (found >= 0.769, i.e. +0.04) fails: 0.755. By the lock this is "not beaten", so nothing is adopted yet, and the lock is not relaxed after seeing the numbers. What is established: at the same or higher precision it finds 2.6 points more vehicles, with fewer false boxes, a better queue estimate and a much better 14-class score, at about the same speed (1.07x). It is the best candidate so far; the M run is still to come, and the choice will be made after all three are scored.
Limits: validation shares cameras with training; missing labels understate precision for every model; two candidates scored so far on one test set (three at the end: the pick carries a multiple-comparison caveat); training stopped early (283 min, best epoch 38) by the script's normal stop rule.

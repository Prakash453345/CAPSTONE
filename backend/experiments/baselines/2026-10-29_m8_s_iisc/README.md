# M8 vehicle detector: run 1 of 3 (`s_iisc`, full training split) on the untouched validation frames (2026-10-29)

Targets: `../2026-10-28_m8_full_train/TARGETS_LOCKED.md` (locked before training). Procedure run once, as locked: score line placed on the 500 DEV frames (lowest line in 0.50-0.85 with DEV precision >= 0.943), then scored once on the 4,797 UNTOUCHED validation frames; reference = BatchNorm-repaired IISc at 0.50. Detections: Kaggle CPU run, same session for both models (`results/score_s_iisc/`), leak check 0 shared frames (21,344 training names vs validation).

| | repaired IISc @0.50 | s_iisc @0.55 (DEV-placed) | target | verdict |
|---|---|---|---|---|
| P1 found | 0.729 | **0.751** (+0.022, 95 % paired interval +0.019 to +0.024) | >= 0.769 and lower bound > +0.02 | FAIL |
| P2 precision | 0.9426 | 0.9424 (difference -0.0001, interval -0.0018 to +0.0014) | >= 0.943 | FAIL by 0.0006 (a tie in practice) |
| P3 queue PCU error | 2.60 | **2.39** | <= 2.60 | pass |
| P4 13-class mAP50:95 (IISc's metric, all 5,297 frames) | 0.530 | **0.577** | >= 0.560 | pass |
| P5 CPU time vs IISc, same run | 1.00 | 0.96 | <= 1.25 | pass |

Also: false boxes per frame 0.53 -> 0.55; AP50 (6-class) 0.790 -> 0.827; 13-class mAP50 0.640 -> 0.681. Found as the right type: car 0.794 -> 0.826, auto-rickshaw 0.767 -> 0.791, bus 0.653 -> 0.679, truck 0.646 -> 0.677, motorcycle 0.691 -> 0.709, bicycle 0.33 -> 0.47.
Controls: the repaired IISc model in this run reproduces the earlier 14-class result (13-class mAP50 0.640, mAP50:95 0.530; 14-class 0.597 / 0.494), so the setup matches the earlier full-validation run. DEV sweep (found / precision): 0.50 0.787/0.936; 0.55 0.757/0.947; 0.60 0.723/0.959.

## Verdict, honestly
Under the locked rule s_iisc does NOT "beat" IISc (P1 and P2 fail), so nothing is adopted. It is a real but smaller gain than the +0.04 asked for: 2.2 points more vehicles found at the same precision, better queue estimate and better 14-class score, same speed. The P2 miss is 0.0006 and inside the noise; the lock is not relaxed. The false boxes per frame did not fall (0.55 vs 0.53): at matched precision the gain shows up as more found, not fewer false boxes, because most "false" boxes are unlabelled real vehicles (see 2026-10-28_m8_false_boxes_diagnosis.md).
Limits: validation shares cameras with training; missing labels understate precision for every model; this is candidate 1 of 3 on one test set (the other two are still to be scored, so the final choice carries a multiple-comparison caveat); hold-out numbers in the training report (mAP50 0.687) are on training-split frames and are not used.
Next: `s_coco` and `m_coco` runs, scored the same way (step 18 notebook, CAND = those names).

# M8 vehicle detector, fine-tune v3 (degradation augmentation): targets, locked before the run (2026-10-04)

**Why.** `baselines/2026-10-04_m8_stress/`: the adopted fine-tune (v2, 640 px) finds 0.790 of vehicles on clean frames but
0.697 at night, 0.687 at night with headlight glare and 0.609 under sensor noise, and its queue estimate reads low in
those cases (PCU bias -2.7 to -3.9 against -1.4 clean). Blur and rain cost nothing.

**What changes.** Only the augmentation. Same start (IISc's model, BatchNorm re-estimated), same 3,000 training frames,
same recipe (25 epochs, batch 16, 640 px, seed 26, hold-out of 300 training-split frames decides the best epoch), plus
image-only augmentation: dimming, sensor noise, blur, headlight glare. JPEG compression, haze and rain are NOT trained on,
on purpose, to see whether robustness carries over. Notebook: `notebooks/m8_uvh26_finetune_v3.ipynb`.

**The test.** 250 FRESH UVH-26 validation frames, drawn with a fixed seed (2027) from the validation split excluding the
250 old test frames (`fresh_sample.json`, `fresh_names.json`). Neither v2 nor v3 has seen them; nothing is tuned on them.
Both models are scored by the same script (`scripts/m8_detector_stress.py`) on the same frames, saved once as JPEG
quality 95, with the same seeded degradations: ONNX Runtime on CPU, 640 px, score line 0.5 (what the tracker uses).
Paired comparison v3 against v2, point estimates judged, 95 % paired-bootstrap intervals reported.

**Targets (all judged ones must pass; v2 means v2 scored on the same fresh frames).**

| # | what | target |
|---|---|---|
| C | clean frames: vehicles found, precision, AP50 | each at least v2 - 0.01 |
| N | night: vehicles found | at least v2 + 0.05 |
| G | night + glare: vehicles found | at least v2 + 0.05 |
| Z | sensor noise: vehicles found | at least v2 + 0.10 |
| H | JPEG, haze, rain (not trained on): vehicles found, each | at least v2 - 0.02 |
| P | precision, every one of the nine conditions | at least 0.88 |
| S | CPU time per image | at most 1.08 x v2 |

Basis for the margins: they ask for roughly half of the loss measured on the old test frames to be recovered (night and
glare lost about 0.10, noise 0.18). The clean and precision limits stop the gain being bought with false boxes.

**Reported, not judged:** blur and dusk, per vehicle type, PCU bias, mAP50 in every condition, the old 250 test frames on
clean (a second scoring of them), training curves.

**If it fails:** v2 stays adopted. v3 is not tuned against these frames. A second attempt needs newly drawn fresh frames.

**What a pass does and does not show.** Dimming, noise, blur and glare are trained on, and the test degradations are
the same families (made by different code, different random parameters), so those rows measure learning of the family,
not real night. Only H (JPEG, haze, rain) tests transfer. No real night or rain footage exists here, so a pass does not
show the model works at night on real cameras. It does show the weakness found in the stress probe is fixable without
losing daytime accuracy, and that the fix does not hurt conditions it was not shown.

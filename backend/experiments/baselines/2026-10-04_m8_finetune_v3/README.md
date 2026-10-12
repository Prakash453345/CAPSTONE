# M8 vehicle detector, fine-tune v3 (degradation augmentation): result (2026-10-04)

**Verdict: PASS on all seven judged targets** (`TARGETS_LOCKED.md`, written before the run). v3 is adopted as the 640 px detector alongside v2's files; nothing else was changed.

Run: notebook `m8_uvh26_finetune_v3.ipynb`, Colab, 640 px, best epoch 19; hold-out mAP50 0.854 (v2: 0.860); train and hold-out frame lists identical to v1/v2. Files: `itms_six_aug_640.onnx` sha256 `b465ec95...b823dce`, `itms_six_aug_640.pt` `42569afa...fa408d`.

Test: 250 fresh UVH-26 validation frames (never seen by either model), JPEG q95, v2 and v3 scored by `scripts/m8_detector_stress.py` (ONNX Runtime CPU, 640 px, score line 0.5), same seeded degradations.

| condition | found v2 | found v3 | diff | precision v2 | precision v3 | mAP50 v2 | mAP50 v3 | PCU bias v2 | PCU bias v3 |
|---|---|---|---|---|---|---|---|---|---|
| clean | 0.808 | 0.800 | -0.008 | 0.934 | 0.935 | 0.848 | 0.841 | -1.21 | -1.22 |
| dusk | 0.787 | 0.796 | +0.008 | 0.939 | 0.940 | 0.849 | 0.842 | -1.50 | -1.39 |
| night | 0.711 | 0.784 | +0.072 | 0.953 | 0.936 | 0.781 | 0.814 | -2.52 | -1.57 |
| noise | 0.604 | 0.771 | +0.167 | 0.966 | 0.938 | 0.717 | 0.825 | -4.13 | -1.78 |
| blur | 0.793 | 0.805 | +0.012 | 0.944 | 0.936 | 0.859 | 0.843 | -1.42 | -1.21 |
| jpeg | 0.754 | 0.761 | +0.006 | 0.943 | 0.946 | 0.822 | 0.823 | -1.91 | -1.83 |
| haze | 0.774 | 0.783 | +0.008 | 0.947 | 0.945 | 0.844 | 0.839 | -1.68 | -1.46 |
| glare | 0.706 | 0.776 | +0.070 | 0.950 | 0.935 | 0.776 | 0.812 | -2.53 | -1.74 |
| rain | 0.813 | 0.806 | -0.007 | 0.934 | 0.938 | 0.850 | 0.842 | -1.05 | -1.19 |

## Judged
| # | target | result |
|---|---|---|
| C | clean found, precision, AP50 each >= v2 - 0.01 | -0.008, +0.001, -0.007: pass |
| N | night found >= v2 + 0.05 | +0.072: pass |
| G | night+glare found >= v2 + 0.05 | +0.070: pass |
| Z | noise found >= v2 + 0.10 | +0.167: pass |
| H | jpeg, haze, rain (not trained on) >= v2 - 0.02 | +0.006, +0.008, -0.007: pass |
| P | precision >= 0.88 in all nine conditions | lowest 0.934: pass |
| S | CPU <= 1.08 x v2 | 0.94 x (86.7 vs 91.9 ms median per clean image, run one after the other): pass |

95 % paired-bootstrap intervals on type-correct recall difference (clean/night/glare/noise): -0.009 [-0.017, -0.002], +0.068 [+0.057, +0.080], +0.067 [+0.055, +0.079], +0.161 [+0.145, +0.179]. The clean loss is small but statistically real, and its interval reaches past the -0.01 allowance; the point estimate passes.

## What this does and does not show
- Night, glare and noise rows are the families trained on: it learned them. The three untrained families (jpeg, haze, rain) did not get worse, so the augmentation did not hurt what it was not shown.
- Blur and dusk (reported) moved +0.012 and +0.008.
- The gains are on synthetic degradations. No real night or rain footage was tested, so real-night recall is still unknown.
- The queue estimate bias improves (night -2.52 to -1.57, noise -4.13 to -1.78 PCU), which is the direction the controller needs; not yet run in the closed loop.
- SimCam's `itms6_640` preset is still fitted to v2; a v3 preset has not been fitted.
- Second scoring of the old 250 test frames was not done.

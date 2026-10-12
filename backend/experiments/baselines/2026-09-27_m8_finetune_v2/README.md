# Baseline — M8, the fine-tune adopted (2026-09-27)

Notebook version 2 (`notebooks/m8_uvh26_finetune.ipynb`) ran in Colab and
was judged by the rules set before its results existed
(`baselines/2026-09-26_m8_finetune_v1_bn/` §5). **The fine-tune passed at
both input sizes, and is adopted.** This baseline covers:
1. the training run;
2. the test-frame scores and the verdict;
3. SimCam fitted to the fine-tune;
4. the controller re-run on it.

## 1. The training run (`colab_v2/`)

Colab, T4, Ultralytics 8.4.163, torch 2.11, full precision throughout. The
same dataset as version 1, restored from Drive: 3,000 training frames,
300 held out, and every test frame and test-camera look-alike kept out.
Its manifest is identical to version 1's (md5 `2396bba4…`, in
`../2026-09-26_m8_finetune_v1_bn/colab_v1/`).

| | 640 px | 960 px |
|---|---|---|
| time | 61 min, 25 epochs, batch 16 | 139 min, 25 epochs, batch 8 |
| losses | finite every epoch; train box loss 0.81 → 0.66 | finite every epoch; 0.79 → 0.64 |
| best epoch (hold-out) | 17 | 19 |
| hold-out mAP50 / mAP50-95 | 0.860 / 0.732 | 0.874 / 0.743 |
| version 1, for reference | 0.842 / 0.692 (stopped learning at epoch 17) | 0.763 / 0.608 (stopped at epoch 7) |
| BatchNorm channels above 65,504, kept in full precision | 350 | 369 |
| non-finite or clipped channels | 0 | 0 |
| ONNX export against the full-precision model | boxes within 0.003 px, scores within 6 × 10⁻⁶ | 0.008 px, 2 × 10⁻⁵ |

No session was cut off, so the resume path was not needed.

The control `iisc_bnfix_*` is IISc's model with only its BatchNorm
statistics repaired:
- 584 non-finite channels went to 0;
- 371 (640 px) and 350 (960 px) channels now sit above 65,504;
- it was estimated from 1,024 training frames with IISc's own augmentation.

## 2. The test frames and the verdict (`detector/`)

**Setup:**
- all 250 PNG test frames;
- the tracker's 0.5 line;
- ONNX Runtime on the laptop, with all six models run one after another in
  one session, so their CPU times compare (`detector/environment.txt`);
- IISc's model re-run in that session reproduced its earlier scores
  exactly (recall 0.711, precision 0.917, 0.79 false boxes per image at
  640 px).

| model | input | vehicles found | precision | false boxes / image | PCU error / image | PCU bias | AP50 | CPU / image |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IISc, as released | 640 | 0.711 | 0.917 | 0.79 | 2.63 | −1.85 | 0.732 | 47 ms |
| IISc, repaired | 640 | 0.731 | 0.937 | 0.60 | 2.54 | −2.15 | 0.763 | 49 ms |
| **fine-tune v2** | **640** | **0.790** | **0.914** | 0.92 | **2.02** | −1.40 | **0.793** | 51 ms |
| IISc, as released | 960 | 0.775 | 0.851 | 1.66 | 2.32 | −0.39 | 0.741 | 146 ms |
| IISc, repaired | 960 | 0.870 | 0.838 | 2.06 | 2.03 | +0.38 | 0.800 | 152 ms |
| **fine-tune v2** | **960** | **0.823** | **0.908** | **1.03** | **1.90** | −0.97 | **0.838** | 136 ms |

**The three comparisons set in advance** (`cmp_*.json`: paired by image,
10,000 resamples, 95 % intervals; the bar requires more vehicles found, a
smaller PCU error, precision ≥ 0.90 and ≤ 1.25× the CPU time):

| comparison | input | vehicles found | PCU error | precision | CPU | passes |
|---|---:|---|---|---|---|---|
| 1. repaired vs IISc | 640 | +0.020 [+0.013, +0.027] | −0.09 [−0.27, +0.09] ✗ | 0.937 | 1.04× | no |
| 2. **fine-tune vs IISc** | 640 | **+0.080 [+0.068, +0.091]** | **−0.61 [−0.85, −0.37]** | **0.914** | 1.08× | **yes** |
| 3. fine-tune vs repaired | 640 | +0.059 [+0.049, +0.071] | −0.51 [−0.70, −0.32] | 0.914 | 1.03× | yes |
| 1. repaired vs IISc | 960 | +0.095 [+0.083, +0.107] | −0.29 [−0.57, −0.005] | 0.838 ✗ | 1.04× | no |
| 2. **fine-tune vs IISc** | 960 | **+0.048 [+0.038, +0.059]** | **−0.42 [−0.64, −0.19]** | **0.908** | 0.94× | **yes** |
| 3. fine-tune vs repaired | 960 | −0.046 [−0.057, −0.036] ✗ | −0.13 [−0.40, +0.14] ✗ | 0.908 | 0.90× | no |

**Verdict under the rule:**
- At each size only the fine-tune passes its comparison with IISc's model,
  so it is adopted at both sizes. The rule does not consult comparison 3
  when only one candidate passes.
- For the record, at 960 px the repaired model finds more vehicles than
  the fine-tune (0.870 against 0.823), at precision 0.838 and twice the
  false boxes.

**What the fine-tune gains, by type and by distance** (share found as the
right type, IISc → fine-tune, at each input size):

| | car | auto | two-wheeler | bus | truck | bicycle |
|---|---:|---:|---:|---:|---:|---:|
| 640 px | 0.84 → 0.89 | 0.75 → 0.79 | 0.66 → 0.75 | 0.63 → 0.67 | 0.55 → 0.67 | 0.25 → 0.44 |
| 960 px | 0.88 → 0.92 | 0.79 → 0.82 | 0.75 → 0.79 | 0.62 → 0.70 | 0.56 → 0.67 | 0.44 → 0.53 |

| box height | 20–40 px (63 boxes) | 40–80 px (693) | ≥ 80 px (2,307) |
|---|---:|---:|---:|
| IISc, 640 px | 0.19 | 0.50 | 0.79 |
| **fine-tune, 640 px** | **0.44** | **0.65** | **0.84** |
| IISc, 960 px | 0.60 | 0.68 | 0.81 |
| fine-tune, 960 px | 0.63 | 0.71 | 0.86 |

At 640 px the fine-tune more than doubles what IISc's model finds among the
smallest, most distant vehicles.

**Version 2 against version 1** (`cmp_ft_v1_vs_v2_*.json`; detections
only, since the two were scored on different days):
- **At 640 px:** version 2 finds slightly fewer vehicles (−0.029), but
  precision rises 0.876 → 0.914 and false boxes fall by a third. AP50 is
  the same (0.792 and 0.793), so at 640 px what changed is mostly how
  confident the model is, not how well it ranks.
- **At 960 px:** version 2 ranks far better. AP50 rose from 0.735 to
  0.838, precision from 0.842 to 0.908, and false boxes halved. But it
  finds slightly fewer vehicles (0.844 → 0.823, significant), and its PCU
  error change (−0.20) is not significant. Version 1's 960 px run had
  stopped learning at epoch 7.

## 3. SimCam fitted to the fine-tune (`simcam_fit.json`)

New presets `itms6_640` and `itms6_960` in `simcam/errors.py`, fitted as
the earlier ones were (`scripts/m8_simcam_calibrate.py`: maximum likelihood
on the 3,063 labelled boxes; bursts, false positives and person recall
kept from `finetuned_day`).

| preset | car | auto | two-wheeler | bus | truck | bicycle | half recall at (car / two-wheeler) |
|---|---:|---:|---:|---:|---:|---:|---|
| `uvh26_640` (IISc) | 0.92 | 0.86 | 0.78 | 0.73 | 0.70 | 0.46 | 53 / 59 px |
| **`itms6_640`** | 0.94 | 0.87 | 0.80 | 0.79 | 0.79 | 0.71 | **42.5 / 43 px** |
| `uvh26_1280` (IISc) | 0.88 | 0.79 | 0.76 | 0.54 | 0.61 | 0.53 | 31 / 5 px |
| **`itms6_960`** | 0.96 | 0.89 | 0.80 | 0.79 | 0.78 | 0.70 | **38.5 / 30 px** |

**The fit undershoots the smallest boxes.** For the 63 boxes 20–40 px
tall it predicts 0.26 found at 640 px where 0.44 were measured, and 0.43
where 0.63 were measured at 960 px. For distant vehicles these presets are
therefore pessimistic. SimCam's single size curve per type cannot follow
both the small-box tail and the bulk, and the bulk has far more boxes.

## 4. The controller on the fine-tune (`closed_loop.json`)

CC-A-CAMP, `failsafe`, held-out seeds 1–5, 19 cameras at 5 fps.
- The new arms are `vision:itms6_640` and `vision:itms6_960`. They took
  56 min on 2 cores.
- Webster, truth and the earlier arms are carried over from
  `baselines/2026-09-26_m8_measured_detectors/`. The only code change that
  touches them is the two new preset entries, and a fresh run of
  `vision:uvh26_640:failsafe` (medium, seed 1) reproduced its record
  (`reproducibility_check.json`).
- No arm had an interlock violation.

**medium**

| arm | person-delay | vs truth | vs Webster | p95 wait (s) | stops/veh |
|---|---:|---|---|---:|---:|
| Webster | 106,912 | | | 83.8 | 2.24 |
| truth | 73,355 | | −31.4 % SIG | 59.4 | 1.75 |
| IISc, 640 px (`uvh26_640`) | 80,141 | +9.3 % n.s. (1/5 lower) | −25.0 % SIG | 68.6 | 1.95 |
| IISc, 1280 px (`uvh26_1280`) | 75,023 | +2.3 % n.s. (2/5) | −29.8 % SIG | 64.0 | 1.81 |
| **fine-tune, 640 px (`itms6_640`)** | **76,798** | **+4.7 % SIG** [+2.0, +7.3] (0/5) | **−28.2 % SIG** | 59.8 | 1.85 |
| fine-tune, 960 px (`itms6_960`) | 76,841 | +4.8 % n.s. [−2.3, +11.8] (1/5) | −28.1 % SIG | 65.4 | 1.76 |

**heavy**

| arm | person-delay | median of 5 | vs truth | vs Webster | worst seed |
|---|---:|---:|---|---|---|
| Webster | 648,447 | 639,311 | | | |
| truth | 457,164 | 454,138 | | −29.5 % SIG | |
| IISc, 640 px | 534,132 | 518,031 | +16.8 % n.s. | −17.6 % SIG | 618,910 (the false blind alarm, `measured_detectors` §3) |
| IISc, 1280 px | 493,570 | 493,531 | +8.0 % n.s. | −23.9 % SIG | 525,870 |
| **fine-tune, 640 px** | 534,887 | **493,992** | +17.0 % n.s. [−15.7, +49.7] | −17.5 % n.s. (4/5 lower) | **728,941** (seed 5) |
| fine-tune, 960 px | 541,458 | 493,660 | +18.4 % n.s. [−15.2, +52.1] | −16.5 % SIG | **720,081** (seed 2) |

- **At medium demand, the 640 px fine-tune costs about half what IISc's
  model did at 640 px:** +4.7 % against perfect data, against +9.3 %.
  - It is also steadier: its five seeds span 74,403–78,683, while IISc's
    spanned 70,543–88,406. That steadiness is why its smaller cost is
    significant and IISc's larger one was not.
  - Against IISc's model at 640 px the difference is −4.2 %, not
    significant (3/5 seeds lower).
  - It comes within 2.4 % (n.s.) of IISc's model at 1280 px, which needs
    about five times the CPU per frame.
  - The 960 px fine-tune did no better than the 640 px one at medium
    demand.
- **At heavy demand the fine-tunes did not help, because of one jammed
  run each.**
  - **Typical runs:** on the median, both fine-tunes (494k) match IISc's
    model at 1280 px (494k) and beat it at 640 px (518k). Three of the 640
    px fine-tune's five seeds were below IISc's at 640 px.
  - **The jammed runs:** 640 px seed 5 and 960 px seed 2 each went into a
    long jam. The longest wait was 1,150 s and 973 s, against 419–557 s on
    truth. The 640 px run took 3,047 s to clear its vehicles, against
    2,476–2,691 s for the other fine-tune runs and on perfect data (Webster
    takes 2,960–3,141 s). SUMO teleported gridlocked vehicles during the
    new runs; the log does not say which runs.
  - **The means:** those two runs pull both means to +17–18 %, level with
    IISc's model at 640 px and the old assumed detector (+17.3 %), with
    intervals of ±33 %.
  - **What this suggests:** at heavy demand the camera still costs the
    controller a lot, and a better still-frame detector did not reduce
    that cost measurably. Perfect data never jammed (longest wait 557 s).
    Every camera arm was worse than perfect data on at least 4 of 5 seeds,
    including the optimistic assumed detector (+17.3 %, significant). What
    in the camera path turns a heavy run into a jam was not traced
    here.
- **Fixed-time fallback was rare.**
  - The stop-line cross-check fired for at most 18 junction-ticks in any
    fine-tune run, nothing like the 555-tick latched alarm of IISc's
    640 px model.
  - One run (640 px, medium, seed 1) fell back to fixed time for 114 of
    11,167 junction-ticks. That was because of low camera confidence, not
    the stop-line check.
  - The two jammed runs had no fallback at all.

**For a deployment:**
- **CPU:** the 640 px fine-tune is the model to run on a CPU. It is the
  first 640 px model that stays close to perfect data at medium demand
  (+4.7 %), at 51 ms a frame on the laptop.
- **GPU:** the 960 px one finds more on still frames (AP50 0.838 against
  0.793; vehicles found 0.823 against 0.790; PCU error 1.90 against 2.02)
  but was not better in the loop at either demand level. It earns its GPU
  only if Vijayawada footage says so.
- **Heavy demand:** the jams are the open problem. They appear only with
  cameras in the loop, whichever detector, so the next step is to trace
  one.

## Files

| path | what |
|---|---|
| `colab_v2/` | the run's report (models' checksums, BatchNorm health, export checks, hold-out scores), per-epoch results, training arguments |
| `detector/{uvh26,bnfix,ft}_{640,960}.json` | the six models on the 250 test frames, per image and per box |
| `detector/cmp_*.json` | the paired comparisons and their verdicts |
| `detector/environment.txt` | where and how they were scored |
| `simcam_fit.json` | §3 |
| `closed_loop.json`, `closed_loop_analysis.txt`, `reproducibility_check.json` | §4 |

The model files are in `data/uvh26/finetune_v2/` (git-ignored). The adopted
ones are `itms_six_fp32_640.onnx` and `itms_six_fp32_960.onnx`.

## Reproducing

```bash
# the test frames (laptop; data/uvh26 from scripts/m8_fetch_uvh26_sample.py)
python scripts/m8_detector_eval.py --data data/uvh26 --model ft=data/uvh26/finetune_v2/itms_six_fp32_640.onnx --imgsz 640 --out ft_640.json
python scripts/m8_detector_eval.py --data data/uvh26 --model uvh26=data/uvh26/UVH-26-MV-YOLOv11-S.onnx --imgsz 640 --out uvh26_640.json
python scripts/m8_detector_compare.py uvh26_640.json ft_640.json
# the fit, then the controller
python scripts/m8_simcam_calibrate.py ft_640.json ft_960.json --out simcam_fit.json
python scripts/m8_closed_loop_gate.py --resume --levels medium,heavy --seeds 5 --out closed_loop.json \
    --arms webster,truth,vision:itms6_640:failsafe,vision:itms6_960:failsafe
```

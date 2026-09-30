# Incident detection: normal baseline, contrast features and a trained combiner (M8 + M6), 2026-09-27/28

**Question.** The vision incident rules on their own catch about one in five
incidents a camera can see: 19 % at 1.75 false alarms/h in
`2026-09-25_m8_review` (Gate 4), and 14–17 % under this study's stricter
count. Can three additions find more? The additions are:

1. a per-place *normal* baseline;
2. upstream/downstream contrast features;
3. a trained combiner.

The measures are per-incident recall, false alarms/h and F1.

**Short answer.**

- **With lane-wide speed and halting, the approach finds about four times
  as many incidents as the re-tuned rules (3.4–4.8×), and two to three times
  as many as `quiet`.**
  - The measurements are M6's per-link features, read straight from SUMO: a
    noise-free upper bound.
  - On fresh seeds 6–10 it catches **37–43 %** of in-view incidents at
    **0.19–0.26 false alarms/h**, including **9–11 of 19 stalled vehicles**.
  - With the post-hoc re-scoring of seeds 1–5 included, the range is
    37–45 % at 0.2–0.85/h and 9–12 of 19 stalls.
  - The rules, re-tuned on the same TRAIN runs, catch **10–11 %** at about
    1.6/h and 3 of 19 stalls. At `quiet` they catch 14–17 % at about
    1.8/h.
  - F1 (in view) is **0.53–0.60** on seeds 6–10 (0.52–0.60 with seeds 1–5),
    against 0.14–0.24 for the rules at `quiet` or re-tuned to 1/h.
  - These are the numbers after correcting a simulator artefact that the
    fact-check found (see *A SUMO artefact*). Before the correction, the
    runs set in advance showed 57–64 %.
- **The normal baseline is the largest gain that was measured by removing
  it:** +29 to +30 points of recall, with the interval above zero each time.
- **With the cameras alone it beats the rules, but it failed the bar set in
  advance, twice:**
  - **Version 1** failed on false alarms: 3.1/h held-out, against a cap
    of 2.
  - **Version 2** fixed the counting and added the tracker's per-lane
    counts, and was judged on fresh seeds 6–10. It found 13 of 46 in-view
    incidents with **one** false alarm in 15.4 h. The re-tuned rules found 5
    with 26.
  - The bar asks whether the recall gain's 95 % interval lies above zero. It
    is +17 points [**0.0**, +37], so it fails.
  - At the 5 alarms/h budget, a comparison named in advance but not the bar,
    it beats the rules by **+24 points [+8.5, +40]**, with fewer false alarms
    (2.3 vs 2.9/h).
- **Decision.** The camera-only combiner is not adopted, and `quiet` stays
  the service default. The layered design is the direction for M6's fusion
  wherever lane- or link-wide speed exists.

## What was built

- **`scripts/m8_incident_gate.py --features-dir`** records three extra
  things per run, beside the rule hits:
  - M6's per-link traffic features: `graph_features.FEATURE_NAMES`, 73
    links, 1 Hz, from SUMO.
  - What the cameras report per link: `LinkEstimate` queue, approaching
    count, receiving occupancy, confidence, and the engine's `vision_score`.
  - From version 2 on, what the tracker sees on each approach lane: tracks
    in view, stopped, and moving above 1.5 m/s.

  All of it is read-only; the run itself is unchanged. The re-recorded TRAIN
  runs are bit-identical to the first recording in hits, windows and
  features.
- **`scripts/m8_harness.py`**: `run_scenario(..., runner_kwargs=)` passes M6's
  feature sink through to the runner.
- **`scripts/m8_incident_fusion.py`** is the study:
  - **Layer 1, what is normal here.** Most traffic features get a z-score
    against the same link's own mean and spread; the camera confidence and
    seen count do not.
    - The reference is the same demand level and the same 10-minute slot,
      from the incident-free twins of the TRAIN seeds.
    - A TRAIN run is normalised by the other TRAIN seeds' twins.
    - The demand level stands in for the day type; a deployment would use
      the same weekday and hour from past weeks.
  - **Layer 2, contrast.** Features that tell an incident from a red-light
    queue:
    - stopped while it has green;
    - a larger share of green spent standing;
    - slower than the sibling lanes on the same green;
    - halted while the road ahead is empty;
    - the queue never cleared, or the lane never ran free, over 90 s.

    All exist for the lane sensors. Most have a camera counterpart and, in
    version 2, a tracker counterpart.
  - **Layer 3, the combiner.** An L2 logistic regression (numpy Newton with a
    line search) gives one score per link per second. It trains on every
    positive second and 3 % of negative seconds, re-weighted.
    - A candidate is raised when the score stays over θ for K seconds, with
      the rules' own clear (20 s) and cooldown (120 s). A test checks this
      against `candidates_under` on 300 random patterns.
    - θ and K (1–60 s) are picked for each false-alarm budget on
      out-of-fold TRAIN predictions, leaving one seed out.
  - **The rules, re-tuned** (`A_rules@b`). This is `m8_incident_analysis.py`'s
    own search on the same TRAIN runs, with the strict count below and a
    wider grid.
  - **Cost.** 0.07 ms per second of traffic for all 73 links for the
    features (batch, including loading the file), plus 0.004–0.05 ms for the
    model. That is negligible next to the detector's 50 ms a frame.

**Scoring** is stricter than Gate 4's.

- A candidate *detects* an incident if it lands on one of the incident's
  links between its start and 45 s after its end.
- Every other candidate is a false alarm, wherever it is. A second
  candidate on the same incident is ignored.
- The gate's own count also forgives any candidate raised anywhere while any
  incident is on. It appears in the logs as "lenient".
- False alarms/h are counted over every run, including the incident-free
  twins.
- Precision and F1 use the incident runs only. Those have five or six
  incidents in 40–55 minutes, far denser than a real corridor, so real
  precision at the same alarms/h would be lower.

**Runs.**

- Preset `itms6_640`: the adopted fine-tune's measured error model. Webster
  control, medium and heavy demand, 5 fps.
- Six incidents are scheduled per run and five or six happen. Each is a
  stalled vehicle or a blocked lane, scheduled for 60–120 s; one TRAIN stall
  ended after 2 s.
- Each incident run has an incident-free twin.
- TRAIN: seeds 101–105, 20 runs, 15.2 h, 57 incidents, 41 in view.
- EVAL: seeds 1–5 (15.3 h, 57 incidents, 42 in view) and seeds 6–10
  (15.4 h, 57 incidents, 46 in view).

**Arms.**

| arm | what it sees |
|---|---|
| `A_quiet` | the rules at the shipped `quiet` point |
| `A_hand` | the rules at the hand-set defaults |
| `A_rules@1`, `A_rules@5` | the rules re-tuned at 1 and 5 alarms/h |
| `C_lane` | lane sensors |
| `C_lane_noz` | lane sensors, no normal baseline |
| `C_cam` | camera estimates |
| `C_cam2` | camera estimates and the tracker |
| `D_vis` | the rule evidence alone, learned |
| `E_lane` | `C_lane` plus the rule evidence |
| `E_cam` | `C_cam` plus the rule evidence |
| `E_cam2` | `C_cam2` plus the rule evidence |

## Version 1: the test set in advance, EVAL seeds 1–5 (`fusion_v1.json`)

**Bar**, set before the runs. `E_cam` (camera-only) at the point TRAIN chose
for 1 alarm/h must meet two conditions:

1. its in-view recall beats `A_rules@1` with a cluster-bootstrap 95 %
   interval above zero, the clusters being seed × level;
2. its EVAL false alarms are at most 2/h.

The lane rows are as recorded. They are inflated by the SUMO artefact below.

| arm (budget) | recall in view | stalls | lane blocks | recall, all | FA/h | precision | F1 in view | latency (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `A_quiet` | 0.14 | 4/19 | 2/23 | 0.16 | 1.77 | 0.39 | 0.21 | 64 |
| `A_rules@1` | 0.07 | 2/19 | 1/23 | 0.05 | 0.85 | 0.33 | 0.12 | 64 |
| `A_rules@5` | 0.21 | 5/19 | 4/23 | 0.21 | 3.08 | 0.33 | 0.26 | 77 |
| `E_cam@1` | 0.17 | 4/19 | 3/23 | 0.14 | **3.08** | 0.21 | 0.19 | 81 |
| `C_lane@1` † | 0.62 | 8/19 | 18/23 | 0.54 | 0.72 | 0.79 | 0.70 | 80 |
| `C_lane_noz@1` † | 0.31 | 2/19 | 11/23 | 0.26 | 1.11 | 0.65 | 0.42 | 80 |
| `E_lane@1` † | 0.64 | 9/19 | 18/23 | 0.58 | 0.59 | 0.82 | 0.72 | 79 |

† inflated by the SUMO artefact.

- **Verdict: `E_cam` fails.**
  - Its recall gain is +9.5 points [+2.3, +17.9].
  - But it raised 3.1 false alarms/h held-out, against 0.53 on TRAIN.

**Where the false alarms came from** (`v1_false_alarm_diagnosis.txt`).

- There were 47 in total.
- 30 were raised in the first 300 s of a run, while the network fills from
  empty. No incident is ever scheduled then (the warm-up is 400 s), and a
  real corridor has no such phase.
- Many came in groups of 2–4 at once, from links that share one approach
  lane. The rules raise one candidate per lane, rule and track (or
  position), not one per link.
- Counted once per lane event, 10 were left after 300 s.

These are faults of the counting, not the model. They were found by reading
held-out results, so version 2 was judged on seeds nobody had looked at.

## Version 2: fixed counting, tracker features, fresh EVAL seeds 6–10 (`fusion_v2.json`)

**Changes**, all fixed before seeds 6–10 were recorded:

- one candidate per approach lane, carrying its links' highest score;
- no candidate from any arm (the rules included) in the first 300 s;
- the tracker's per-lane counts.

The bar is the same, applied to `E_cam2`.

| arm (budget) | recall in view | stalls | lane blocks | recall, all | FA/h | precision | F1 in view | latency (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `A_quiet` | 0.17 | 6/19 | 2/27 | 0.14 | 1.82 | 0.38 | 0.24 | 60 |
| `A_hand` | 0.28 | 8/19 | 5/27 | 0.23 | 54.28 | 0.03 | 0.05 | 50 |
| `A_rules@1` | 0.11 | 3/19 | 2/27 | 0.09 | 1.69 | 0.31 | 0.16 | 44 |
| `A_rules@5` | 0.24 | 7/19 | 4/27 | 0.19 | 2.85 | 0.33 | 0.28 | 72 |
| **`E_cam2@1`** | **0.28** | 8/19 | 5/27 | 0.23 | **0.06** | 0.93 | 0.43 | 78 |
| `E_cam2@5` | 0.48 | 12/19 | 10/27 | 0.39 | 2.33 | 0.54 | 0.51 | 56 |
| `E_cam@1` | 0.33 | 9/19 | 6/27 | 0.26 | 0.19 | 0.88 | 0.48 | 78 |
| `C_cam2@1` | 0.26 | 8/19 | 4/27 | 0.21 | 0.06 | 0.92 | 0.41 | 77 |
| `C_cam@1` | 0.17 | 5/19 | 3/27 | 0.14 | 0.45 | 0.67 | 0.28 | 75 |
| `D_vis@1` | 0.09 | 2/19 | 2/27 | 0.07 | 0.65 | 0.40 | 0.14 | 76 |
| `C_lane@1` † | 0.57 | 10/19 | 16/27 | 0.56 | 0.45 | 0.94 | 0.71 | 67 |
| `C_lane_noz@1` † | 0.17 | 1/19 | 7/27 | 0.16 | 1.36 | 0.50 | 0.26 | 84 |
| `E_lane@1` † | 0.63 | 9/19 | 20/27 | 0.63 | 0.52 | 0.90 | 0.74 | 50 |
| `E_lane@5` † | 0.78 | 13/19 | 23/27 | 0.79 | 2.53 | 0.71 | 0.75 | 47 |

† inflated by the SUMO artefact; corrected numbers are below.

**Differences in in-view recall** (cluster bootstrap, 10 clusters):

| comparison | difference | 95 % interval |
|---|---:|---|
| `E_cam2@1` − `A_rules@1` (**the bar**) | +0.174 | [**+0.000**, +0.370] |
| `E_cam2@1` − `A_quiet` | +0.109 | [−0.067, +0.304] |
| `E_cam2@5` − `A_rules@5` | +0.239 | [+0.085, +0.400] |
| `E_cam@1` − `A_rules@1` | +0.217 | [+0.057, +0.395] |
| `E_cam@1` − `A_quiet` | +0.152 | [+0.020, +0.311] |
| `E_cam2@1` − `E_cam@1` (tracker features) | −0.043 | [−0.143, +0.065] |
| `E_cam@1` − `C_cam@1` (rule evidence on camera traffic) | +0.152 | [+0.023, +0.275] |

**Verdict: `E_cam2` fails.**

- The false alarms are well inside the cap: 0.06/h, one in 15.4 h.
- But the lower end of the recall interval is exactly 0, not above it. The
  fact-check found it never above 0 under 200 other bootstrap seeds.
- The bar tested recall alone at the point TRAIN chose. It did not credit the
  drop from 26 false alarms to 1.
- `E_cam`, the same model without the tracker features, would have met the
  bar on these seeds: +22 [+6, +40]. It was not the arm named in advance, so
  that is not a test.
- A later test should fix a joint criterion in advance, such as recall at no
  more false alarms than the rules, and should use more incidents.

`fusion_v2count_seeds1-5.json` applies version 2's counting to seeds 1–5.
It is post hoc: those seeds shaped version 2.

- Its bar arm is `E_cam`, since those recordings have no tracker columns.
  That arm would pass. The file marks the verdict `valid_test: false`
  because the run is post hoc.
- `E_cam@1` scored 0.21 in view at 0.98/h.
- `A_rules@1` scored 0.10 at 1.57/h; the difference is +0.119 [+0.020, +0.220].

## A SUMO artefact in the lane-sensor arms (found by the fact-check)

- **The artefact.** For an *empty* lane, SUMO reports its mean speed as the
  lane's current speed limit. The injector blocks a lane by setting that
  limit to 0.1 m/s. So a blocked lane with no vehicle on it reads as
  crawling: `mean_speed_frac` is near 0 (0.1 m/s over the lane's normal
  limit) instead of 1. That is the
  injection itself showing through, not traffic.
  - Caching the lane's normal limit, as `graph_features` does, only keeps
    the denominator right.
  - In the recordings, 4,562 of 4,839 lane-block link-seconds with no
    halted, queued or approaching vehicle read below 0.05. Outside incidents
    the rate is 0.1 %.
- **Who it affects.** It inflates every lane-sensor arm (marked †), mostly
  on lane blocks. The artefact does not arise for stalls (one stopped
  vehicle), and the camera arms do not read these features. The corrected
  models were retrained, so their stall counts can still move a little:
  `C_lane@1` on seeds 6–10 went from 10 to 11 of 19.
- **The fix.** `--empty-lane-free` reads a lane with nothing halted, queued
  or approaching as free-flowing, as a real sensor with nothing over it
  would. The lane arms were re-run with it.
  - It is a post-hoc correction of the data, not a re-tuning.
  - It is off by default, so the recorded version 1 and 2 files reproduce.

| lane arms, corrected (`--empty-lane-free`) | recall in view | stalls | lane blocks | recall, all | FA/h | precision | F1 in view | latency (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| seeds 6–10: `C_lane@1` | 0.37 | 11/19 | 6/27 | 0.40 | 0.26 | 0.96 | 0.53 | 75 |
| seeds 6–10: `E_lane@1` | 0.43 | 9/19 | 11/27 | 0.47 | 0.19 | 0.96 | 0.60 | 72 |
| seeds 6–10: `E_lane@5` | 0.57 | 13/19 | 13/27 | 0.60 | 2.53 | 0.62 | 0.59 | 51 |
| seeds 1–5: `C_lane@1` | 0.40 | 11/19 | 6/23 | 0.46 | 0.79 | 0.74 | 0.52 | 70 |
| seeds 1–5: `E_lane@1` | 0.45 | 12/19 | 7/23 | 0.51 | 0.85 | 0.74 | 0.56 | 67 |
| seeds 1–5: `E_lane@5` | 0.60 | 13/19 | 12/23 | 0.65 | 3.74 | 0.49 | 0.54 | 51 |

These use version 2's counting; the seeds 1–5 rows are post hoc. The rules
on the same counting are shown for comparison:

- seeds 6–10: `A_rules@1` 0.11, 3/19 stalls, at 1.69/h; `A_quiet` 0.17 at
  1.82/h;
- seeds 1–5: `A_rules@1` 0.10, 3/19 stalls, at 1.57/h; `A_quiet` 0.14 at
  1.77/h.

| comparison (corrected) | seeds 6–10 | seeds 1–5 (post hoc) |
|---|---|---|
| `E_lane@1` − `A_rules@1` | +0.326 [+0.136, +0.520] | +0.357 [+0.256, +0.487] |
| `C_lane@1` − `C_lane_noz@1` (normal baseline) | +0.304 [+0.111, +0.489] | +0.286 [+0.190, +0.390] |
| `E_lane@1` − `C_lane@1` (rule evidence) | +0.065 [−0.023, +0.137] | +0.048 [+0.000, +0.106] |

## What the numbers say

- **The normal baseline is the largest gain that was ablated.** The same
  lane-sensor model without it loses 29–30 points of recall (corrected),
  with the interval above zero on both seed sets.
  - With it, the strongest features are "slower than the sibling lanes on
    the same green, compared with normal", "fewer vehicles approaching than
    normal" and "slow".
  - The contrast features were not ablated on their own.
- **Lane-wide speed and halting find stalled vehicles.** At 1 alarm/h,
  corrected, they catch 9–12 of 19 stalls, against 3 for the re-tuned rules
  and 4–6 for `quiet`. They catch 6–11 lane blocks of 23–27, against 1–2.
  They also find stalls no camera sees: recall over all incidents is above
  in-view recall.
- **The cameras see less.** They cover only the approach near the junction,
  and version 1 of the camera features had no speed at all.
  - The tracker's counts made the strongest camera feature: fewer vehicles
    moving over a minute than normal. They lifted out-of-fold TRAIN recall
    from 0.27 to 0.39.
  - On seeds 6–10 they gave no measurable gain over the camera estimates
    (−4 points, n.s.).
- **The rule evidence is weak on its own.** `D_vis` matches the rules.
  - It added to camera traffic features on seeds 6–10 (+15 points
    [+2, +28]), but not in version 1 on seeds 1–5 (0).
  - It adds little to lane sensors (+5 to +7, n.s. or borderline).
- **Latency.**
  - At 1 alarm/h the learned models (corrected lane models and camera
    models) raise after 66–81 s on average; the lane model without the
    normal baseline takes 84–105 s. The rules raise after 44–64 s.
  - The corrected lane models chose K = 45 s.
  - `E_cam`, `C_cam2` and `E_cam2` raise late even at K 1–5 s. Presumably
    that is because their features are 30–90 s rolling windows, but it was
    not measured.
  - At 5/h, `E_lane` raises in 51 s and `E_cam2` in 56 s.

## Caveats

- **Lane sensors are an upper bound.** They are SUMO's whole-lane halting
  count and mean speed, with no noise; real loop or radar detectors measure
  at a point and are noisy. The artefact fix treats a lane as empty when
  nothing is halted, queued or within the approach horizon. A vehicle further
  upstream would then read as free-flowing, which errs towards missing a
  block.
- **SUMO's lane block slows the whole lane to 0.1 m/s**, so every vehicle
  on it crawls. That is still easier for whole-lane sensors than a real
  obstruction would be. The stalls are the more realistic test.
- **Small samples.** There are 42 and 46 in-view incidents per evaluation
  and 10 clusters, so intervals are wide.
- **Precision and F1 are inflated.** The incident density is far above a
  real corridor's.
- **One corridor, one control, one camera preset** (`itms6_640`).
- **Method notes.**
  - In the leave-one-seed-out picks, the training rows' normal baseline
    includes the held-out seed's twin.
  - The rules' re-tuning is scored in-sample on TRAIN, whereas the learned
    models' picks use out-of-fold predictions.
- **Changes made after a first look.**
  - The persistence grid (up to 60 s) and the rules' grid were widened
    after a TRAIN-only dry run chose values at the grid edge. EVAL was not
    looked at then.
  - Version 2 followed EVAL 1–5, hence the fresh seeds 6–10.
  - The artefact fix followed the fact-check of all results.
  - With seeds 1–10 used, this corridor's EVAL seeds are exhausted. A
    further test needs a new seed set declared before anyone looks at it.
- **M6's graph autoencoder is not compared.** No trained model exists in
  this checkout.

## Reproducibility

- `fusion_v1.json` equals the first version-1 run in every arm. Only the
  intervals moved, after the bootstrap was seeded by comparison name.
- `fusion_v2.json` was run twice and matched exactly.
- The TRAIN re-recording matched the first recording exactly.

## Files

| file | what |
|---|---|
| `fusion_v1.json`, `…_log.txt` | version 1, EVAL seeds 1–5, the test set in advance |
| `fusion_v2.json`, `…_log.txt` | version 2, fresh EVAL seeds 6–10, the test set in advance |
| `fusion_v2count_seeds1-5.json`, `…_log.txt` | version 2's counting on seeds 1–5, post hoc |
| `fusion_v2_lanefix.json`, `fusion_v2count_seeds1-5_lanefix.json`, logs | the lane arms with the artefact removed |
| `v1_false_alarm_diagnosis.txt` | where version 1's held-out false alarms came from |
| `incident_{train,eval}.json.gz` | version-1 recordings: rule hits, incident windows, run metrics |
| `incident_{train,eval}_v2.json.gz` | version-2 recordings; `eval_v2` holds seeds 1–5 (version-1 records) and 6–10 |
| `record_v1.sh`, `record_v2.sh` | the recording commands |

The per-second feature files (`.npz`, about 125 MB) are in
`itms/data/m8_fusion/features{,_v2}/`, outside git.

## Reproducing

```bash
cd itms
bash baselines/2026-09-27_m8_incident_fusion/record_v1.sh    # ~2 h on 2 cores
bash baselines/2026-09-27_m8_incident_fusion/record_v2.sh    # ~2.2 h
F=scripts/m8_incident_fusion.py; D=data/m8_fusion
.venv/bin/python $F $D/train.json $D/eval.json --v1 --out fusion_v1.json
.venv/bin/python $F $D/train_v2.json $D/eval_v2.json --eval-seeds 6,7,8,9,10 --out fusion_v2.json
.venv/bin/python $F $D/train.json $D/eval.json --post-hoc --out fusion_v2count_seeds1-5.json
.venv/bin/python $F $D/train_v2.json $D/eval_v2.json --eval-seeds 6,7,8,9,10 --empty-lane-free \
    --post-hoc --arms C_lane,C_lane_noz,E_lane --out fusion_v2_lanefix.json
.venv/bin/python $F $D/train.json $D/eval.json --empty-lane-free --post-hoc \
    --arms C_lane,C_lane_noz,E_lane --out fusion_v2count_seeds1-5_lanefix.json
```

Each analysis takes about 4–5 minutes.

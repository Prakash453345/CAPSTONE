# Baseline — gap-out enabled (2026-09-18, third baseline of the day)

Supersedes `../2026-09-18_speed_limits/`. One change: A-CA-MP now yields a
green whose own approaches have been empty for 3 s to any phase that has
demand (`AcampConfig.gap_out_grace_s`, default 3.0).

## Why this was re-tried

Under the old 7–8 s clearance interval an instant gap-out measured
+3.9% / +15.7% SIG / +3.1% — each extra phase change cost more than the empty
green it saved. Clearance is now 5.5 s, and the instrumented runs show the
controller extending an empty green on 43–65% of its extend ticks because the
pressure gap it is weighed against is 0.000 at the median tick.

Grace searched on TRAIN seeds 101–105 (0 s / 3 s / 5 s): 0 s still worse at
light and heavy, 5 s wins medium (−7.3% SIG) but costs heavy (+9.4%), 3 s
within noise everywhere and best on the wait distribution. 3 s chosen.

## Held-out result (CC-A-CAMP, seeds 1–10; seeds 11–20 added at medium/heavy)

| metric | light | medium | heavy |
|---|---|---|---|
| person-delay (10 seeds) | −1.4% n.s. | +0.1% n.s. | −7.6% n.s. |
| person-delay (20 seeds) | — | −3.1% n.s., 15/20 | −4.6% n.s., 10/20 |
| **p95 wait** | **−10.9% SIG**, 8/10 | −3.4% n.s. | −11.9% n.s. |
| **stops per vehicle** | **−6.2% SIG**, 9/10 | −0.5% n.s. | −2.9% n.s. |

**It is not a delay improvement.** The medium gain seen on the training seeds
did not reproduce, and twenty seeds leave it short of significance. What is
established: light demand's wait distribution and stop count, no metric
significantly worse anywhere, zero interlock violations.

## Full baseline — 3 arms × 3 levels × 10 held-out seeds

| level | arm | person-delay | p95 wait | stops | viol |
|---|---|---:|---:|---:|---:|
| light | webster | 45,830 | 63.3 | 1.91 | 0 |
| | ceiling | 35,117 | 48.1 | 1.46 | 0 |
| | **ccacamp** | **34,392** | **47.2** | 1.47 | 0 |
| medium | webster | 105,878 | 82.1 | 2.21 | 0 |
| | ceiling | 72,838 | 62.7 | 1.74 | 0 |
| | **ccacamp** | **72,836** | **61.7** | 1.75 | 0 |
| heavy | webster | 645,098 | 433.4 | 3.23 | 0 |
| | **ceiling** | **464,681** | 301.0 | 2.78 | 0 |
| | ccacamp | 475,779 | **288.9** | 2.80 | 0 |

### CC-A-CAMP, paired

| level | vs Webster | vs static ceiling |
|---|---|---|
| light | **−25.0% SIG**, 10/10 | −2.1% n.s. |
| medium | **−31.2% SIG**, 10/10 | −0.0% n.s. |
| heavy | **−26.2% SIG**, 10/10 | +2.4% n.s. |

## The open problem, restated

Three baselines into today, CC-A-CAMP still cannot be distinguished from the
static Webster-referenced ceiling at any demand level. Every gain recorded
today came from an input correction — occupancy units, clearance intervals,
minimum green, speed limits — and the gap-out, the first behavioural change
that survived a held-out gate, buys a smoother ride rather than less delay.

The remaining candidates in `docs/algorithm_improvement_research.md`:
lane-group pressure aggregation (53 of 73 links share a lane, so phases within
one junction are weighted 1.0–3.0× by geometry alone), and a per-phase
supervisor trigger.

## Files

`m5_baseline_results.json` (90 runs), `gapout_grace_search_train.json` (the
grace search, training seeds), `gapout_seeds_11_20.json` (the extra held-out
seeds), `benchmark_log.txt`, `pytest_full.txt` (567 passed, 6 skipped),
`environment.txt`.

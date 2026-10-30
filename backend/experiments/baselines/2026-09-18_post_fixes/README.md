# Baseline — M5 traffic coordination after the 2026-09-18 corrections

This replaces `../2026-09-16_m5_traffic_coordination/` as the reference for
future comparisons. The older baseline is **not** comparable to this one: both
the Tier-0 timing inputs and two of the metrics changed, so its numbers measure
a different corridor scored a different way. Keep it for the history, compare
against this one.

## What changed (all of it measured, see PROGRESS.md for the full write-up)

| change | where | effect |
|---|---|---|
| Lane/edge occupancy is no longer divided by 100 | `queue_state.py`, `spillback.py`, `emergency_control.py`, `adapters/sumo/*` | the spillback gate, `rho_couple` and the spillback episode counter all worked for the first time |
| `rho_jam` 0.75 → 0.85, `beta_gate` 2 → 4 | `acamp.py` | re-tune forced by the line above; searched on TRAIN seeds, −6.2% at heavy against the un-tuned pair |
| Yellow from the ITE/IRC kinematic rule, min green 10 s → 7 s | `extract_tier0_config.py` | yellow 6 s → 5 s (4.5 s at one junction); removed heavy demand's remaining interlock violations |
| `max_wait_s` re-derived when the ceiling replaces `max_green_s` | `m5_cycle_ceiling_probe.py` | I5's bound tracks the real rotation (was 5–9× too loose) |
| Throughput measured over the window actually scored | `metrics.py` | was identical for every arm by construction; now discriminates |
| Warm-up filter uses the scheduled departure | `metrics.py` | every arm now scores the same trip population |

## Results — 3 arms × 3 demand levels × 10 held-out seeds (1–10), SUMO 1.27.1

| level | arm | person-delay | p95 wait | stops | throughput | interlock violations |
|---|---|---:|---:|---:|---:|---:|
| light | webster | 60,962 | 75.8 | 1.78 | 2,348 | 0 |
| | ceiling | 51,631 | 77.9 | 1.70 | 2,377 | 0 |
| | **ccacamp** | **48,818** | **72.7** | **1.64** | **2,387** | 0 |
| medium | webster | 194,620 | 148.8 | 3.02 | 3,776 | 0 |
| | **ceiling** | **170,199** | 175.2 | 2.81 | 3,739 | 0 |
| | ccacamp | 173,710 | 175.9 | 2.86 | 3,704 | 0 |
| heavy | webster | 1,502,935 | 683.3 | 9.95 | 4,317 | 0 |
| | **ceiling** | **1,480,063** | 708.9 | 9.59 | 4,161 | 0 |
| | ccacamp | 1,478,571 | 726.2 | 9.69 | 4,186 | 0 |

### CC-A-CAMP, paired

| level | vs Webster | vs static ceiling |
|---|---|---|
| light | **−19.9% SIG**, 10/10 seeds | **−5.4% SIG**, 7/10 |
| medium | **−10.7% SIG**, 8/10 | +2.1% n.s. |
| heavy | −1.6% n.s., 7/10 | −0.1% n.s. |

**Read this honestly.** Light demand improved: the supervisor now earns a
significant win over the static ceiling (−5.4%), which it never did before.
Heavy demand did not: CC-A-CAMP's −11.6% lead over Webster is gone, because
Webster gained 6.2% from the corrected clearance intervals while CC-A-CAMP lost
4.4% once the spillback gate started working. The old lead was partly an
artifact of a gate that discounted nothing. Recovering heavy demand with a
working gate is now the open problem.

## Attribution of the heavy-demand change (10 seeds, paired)

| variant | heavy delay | vs all fixes |
|---|---:|---|
| all fixes (before the gate re-tune) | 1,533,342 | — |
| + gate disabled | 1,480,345 | −3.5% n.s. |
| + old `max_wait` | 1,533,342 | 0.0% (no effect) |
| + old yellow/min-green | 1,530,159 | −0.2% n.s., but **5 interlock violations** |
| old code, old metric (previous baseline) | 1,416,609 | −7.6% SIG |

Metric changes alone account for −0.2% to −1.0% (measured by re-scoring the old
code under the new metrics, `oldcode_newmetric_heavy.json`); the rest is the
control change. The old timing is what produced heavy's interlock violations,
so reverting it is not an option.

## Gate re-tune (TRAIN seeds 101–105, never used for the numbers above)

| rho_jam / beta | medium | heavy |
|---|---|---|
| 0.75 / 2 (shipped) | — | — |
| 0.90 / 2 | −0.7% n.s. | −3.0% n.s. |
| **0.85 / 4 (chosen)** | +0.5% n.s. | **−6.2% SIG, 5/5** |
| 0.99 / 4 | +0.5% n.s. | −3.9% n.s. |
| gate off | +0.5% n.s. | −5.7% n.s. |

## Files

- `m5_baseline_results.json` — 90 per-run records + summary
- `benchmark_log.txt`, `pytest_full.txt` (557 passed, 6 skipped), `environment.txt`
- `attrib_heavy.json`, `gate_tune.json`, `oldcode_newmetric_heavy.json` — the
  attribution, tuning and metric-isolation runs quoted above

## Reproducing

```bash
cd itms && make setup                      # eclipse-sumo stays pinned at 1.27.1
.venv/bin/pytest -q                        # 557 passed, 6 skipped
.venv/bin/python scripts/m5_baseline_benchmark.py --out /tmp/after.json
.venv/bin/python scripts/compare_m5_baseline.py \
    baselines/2026-09-18_post_fixes/m5_baseline_results.json /tmp/after.json
```

# Baseline — M5 traffic coordination (2026-09-16)

Frozen snapshot of the signal-coordination controller **before** changes made
with another AI model. Compare any later version against these numbers.

## What was tested

| | |
|---|---|
| Code | branch `komal`, HEAD `ac09e69`, plus uncommitted backend edits (diff sha256 `bfdf796b…`, 5 files under `sim-service/live` + `api-service/main.py`; none touch the M5 controller) |
| Environment | Python 3.11.15, **eclipse-sumo 1.27.1** (pinned), Linux x86_64 |
| Network | Vijayawada corridor, Webster-referenced 1.25× ceiling |
| Protocol | 3 arms × 3 demand levels × 10 held-out seeds (1–10) = 90 SUMO runs, paired per seed |
| Test suite | `pytest`: **540 passed, 6 skipped** (skips = M6 anomaly extra not installed) |

Arms: `webster` (tuned fixed-time), `ceiling` (A-CA-MP + ceiling, supervisor off),
`ccacamp` (A-CA-MP + ceiling + cycle supervisor — the current controller).

## Results (means over 10 seeds; lower is better)

| level | arm | person-delay (s) | p95 wait | max wait | stops/veh | interlock viol. |
|---|---|---:|---:|---:|---:|---:|
| light | webster | 69,573 | 102.9 | 159.0 | 1.91 | 0 |
| | ceiling | 56,472 | 93.9 | 177.7 | 1.89 | 0 |
| | **ccacamp** | **55,740** | **90.4** | **150.2** | 1.89 | 0 |
| medium | webster | 193,354 | 169.5 | 255.7 | 3.09 | 0 |
| | ceiling | 176,461 | 182.5 | 266.2 | 2.84 | 0 |
| | **ccacamp** | **171,307** | **169.0** | 266.2 | **2.77** | 0 |
| heavy | webster | 1,601,950 | 719.7 | 1148.3 | 10.42 | 0 |
| | ceiling | 1,498,307 | 776.3 | 1361.5 | 9.80 | **2** |
| | **ccacamp** | **1,416,609** | 741.3 | 1310.0 | **9.26** | **0** |

Throughput is identical across arms (2,717 / 5,203 / 10,282 persons/h) — every
trip completes, so it does not discriminate between controllers.

### CC-A-CAMP vs Webster (paired, 95% CI)

| level | person-delay | stops |
|---|---|---|
| light | **−19.9%** SIG, 10/10 seeds better | −1.1% n.s. |
| medium | **−11.4%** SIG, 8/10 | **−10.1%** SIG, 8/10 |
| heavy | **−11.6%** SIG, 10/10 | **−11.1%** SIG, 9/10 |

### CC-A-CAMP vs static ceiling

| level | person-delay | stops |
|---|---|---|
| light | −1.3% n.s. | +0.1% n.s. |
| medium | −2.9% n.s. | −2.4% n.s. |
| heavy | **−5.5%** SIG, 8/10 | **−5.5%** SIG, 8/10 |

**Reproducibility check:** these match the gate numbers recorded in
`PROGRESS.md` ("CC-A-CAMP: the supervisor, built and gated") exactly, to the
second, so the baseline is deterministic under SUMO 1.27.1.

## Files

- `m5_baseline_results.json` — all 90 per-run records + summary + provenance
- `benchmark_log.txt` — per-run console log
- `pytest_full.txt` — test-suite output
- `environment.txt` — key package versions

## How to compare after changes

From `itms/` (with the venv set up via `make setup`, SUMO **must** stay 1.27.1):

```bash
python scripts/m5_baseline_benchmark.py --out /tmp/after.json        # ~15–30 min
python scripts/compare_m5_baseline.py \
    baselines/2026-09-16_m5_traffic_coordination/m5_baseline_results.json /tmp/after.json
pytest -q                                                              # expect >= 540 passed
```

The compare script pairs runs by (arm, level, seed), prints each metric with a
95% CI, labels it BETTER / WORSE / n.s., and exits non-zero on any significant
regression or any increase in interlock violations. The `webster` rows act as a
control: if they change, the other AI touched shared code (network, harness,
metrics, safety kernel) rather than only the controller.

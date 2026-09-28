# Baseline — corrected corridor speed limits (2026-09-18, later the same day)

This supersedes `../2026-09-18_post_fixes/`. One input changed: the network's
speed limits, from the OSM typemap's inter-urban 80–100 km/h to an
urban-arterial 50 km/h (`scenarios/networks/vijayawada/cap_speeds.py`, step 4
of `build.sh`). The kinematic yellow follows it down, 5.0 s → **3.5 s** at
every junction.

## Reading these numbers

**Person-delay is not comparable across the speed change.** SUMO scores
`timeLoss` against each vehicle's own free-flow speed, so lowering the limit
lowers the reference every delay figure is measured from. Compare arms *within*
this table, and use the reference-free measures below to compare against the
previous configuration.

## Results — 3 arms × 3 levels × 10 held-out seeds, zero interlock violations

| level | arm | person-delay | p95 wait | stops/veh | throughput |
|---|---|---:|---:|---:|---:|
| light | webster | 45,830 | 63.3 | 1.91 | 2,043 |
| | **ceiling** | **34,860** | 52.4 | 1.53 | 2,100 |
| | ccacamp | 34,894 | 53.0 | 1.56 | 2,091 |
| medium | webster | 105,878 | 82.1 | 2.21 | 3,287 |
| | **ceiling** | **71,371** | 64.4 | 1.72 | 3,343 |
| | ccacamp | 72,757 | 63.9 | 1.76 | 3,341 |
| heavy | webster | 645,098 | 433.4 | 3.23 | 4,885 |
| | ceiling | 539,175 | 354.4 | 3.02 | 5,737 |
| | **ccacamp** | **515,141** | **328.0** | **2.88** | **5,885** |

### CC-A-CAMP, paired

| level | vs Webster | vs static ceiling |
|---|---|---|
| light | **−23.9% SIG**, 10/10 | +0.1% n.s. |
| medium | **−31.3% SIG**, 10/10 | +1.9% n.s. |
| heavy | **−20.1% SIG**, 9/10 | −4.5% n.s., 6/10 |

Throughput now separates the arms (it could not before the metric fix): at
heavy demand CC-A-CAMP clears 5,885 persons/h against Webster's 4,885, **+20%**.

## What actually improved, in reference-free terms

p95 wait and stops per vehicle do not depend on the free-flow reference, so
these *are* comparable with the previous configuration:

| level | arm | p95 wait (s) | stops per vehicle |
|---|---|---|---|
| light | webster | 75.8 → 63.3 | 1.78 → 1.91 |
| | ccacamp | 72.7 → **53.0** | 1.64 → **1.56** |
| medium | webster | 148.8 → 82.1 | 3.02 → 2.21 |
| | ccacamp | 175.9 → **63.9** | 2.86 → **1.76** |
| heavy | webster | 683.3 → 433.4 | 9.95 → 3.23 |
| | ccacamp | 726.2 → **328.0** | 9.69 → **2.88** |

Heavy demand is the striking one: p95 wait more than halves and stops fall by
two thirds. The mechanism is not subtle — a 3.5 s yellow instead of 5–6 s
returns 1.5–2.5 s of usable green to every phase change, and at heavy demand
this corridor was change-interval-bound.

## What did not improve: the adaptive layer

Against the static ceiling — the arm that isolates what A-CA-MP's own logic
contributes — CC-A-CAMP is +0.1% (light), +1.9% (medium) and −4.5% n.s.
(heavy). The −5.4% light-demand win the supervisor had in the previous
configuration is gone: with clearance this cheap, the static ceiling captures
essentially all of the available gain. **The corridor's binding constraint was
never the control policy.**

That is the open problem, and `docs/algorithm_improvement_research.md` still
lists the candidates: lane-group pressure aggregation, an extension/gap-out
rule now that switching is cheap (a naive gap-out was +15.7% worse under the
old 7–8 s clearance and deserves a re-test at 5.5 s), and a per-phase
supervisor trigger.

## Caveats

- `sat_flow_calibration.json` was measured under the old speed limits and has
  not been re-measured; saturation flow depends on approach speed, so the
  per-movement values are now slightly off.
- 50 km/h is IRC:86's urban-arterial design speed, not a survey of this
  corridor. A measured 85th-percentile speed would be better evidence.
- The Webster baseline still computes its cycle with a textbook 4 s lost time
  per phase while the junctions now display 3.5 + 2 = 5.5 s.

## Files

`m5_baseline_results.json` (90 runs), `benchmark_log.txt`, `pytest_full.txt`
(560 passed, 6 skipped), `environment.txt`.

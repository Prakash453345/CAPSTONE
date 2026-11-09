# M7 routing: time-based cost, rerouting rule, hex band (2026-10-17)

**Status: simulation result. 5 of 6 targets pass; H1 fails narrowly. Not committed. Update 2026-10-27: the time-based router is now the default (`ITMS_ROUTE_COST=weighted` restores the old weighted cost); see `baselines/2026-10-27_m7_signal_research`.**

## Why
The 14 Oct M7 gate used a single corridor, which offers only one route, so route choice could not matter there. This test uses networks that have many routes.

## What changed (code)
- `routing/eta_cost.py`, `EtaCostModel`: route cost is in seconds of EV time. It adds travel at the EV's speed (limit × 1.2, adjusted by how freely traffic can move aside on that road's lanes), the junction cost, a turn penalty (the crossing turn is right for left-hand traffic), anomaly delay, and 0.5 × σ. The junction cost uses preemption: once the queue clears inside the 15 s lead, only the crossing time (1.5 s) remains. A* uses an admissible straight-line heuristic. `should_reroute` switches only if the saving is greater than max(15 s, 10 %) + 5 s.
- `routing/hexgrid.py`, `HexIndex`: hex cells, each about one block across (the median junction spacing, 150–600 m). A cell-level Dijkstra finds a corridor of cells, which is widened by rings (the benchmark uses 2 via `HEX_RINGS`; the code default is 1) and then searched exactly. The A* heuristic is scaled by 0.9 as a safety margin. Cells with live anomalies cost 10×. Between full sweeps (every 60 s), the monitor reads live data only for edges inside the band.
- `graph.py`: stores the turn direction and driving side. `cost.py` adds a `halting` field (queue length) to `EdgeConditions`. `planner.py` gains an optional `cost_model`, the A* heuristic, `allowed_edges` (the hex band), and `static_prior` (off by default; it did not help on dev). In `emergency_control.py`, `ITMS_ROUTE_COST=eta` switches the live service to the new cost and rule and samples queue length.
- Tests: `tests/routing/test_eta_cost.py` (7). The full suite has 767 passing and 5 skipped.

## Benchmark
`scripts/m7_route_benchmark.py` and `scripts/m7_route_summarise.py`.
- The EV is dispatched at t = 600 s between a random O-D pair at least 45 % of the network diagonal apart.
- The incident is placed on the free-flow path 20 s after dispatch, at 2 m/s for 900 s. It is reported to the router 10 s later as high severity, impact 0.8.
- All arms use the same simple reactive preemption: EV links turn green within 150 m of the signal. Background signals run fixed programs.
- Arms:
  - `dist`: free-flow path, fixed.
  - `weighted`: the current production router and rule.
  - `eta_rr`: the new cost and rule.
  - `eta_hex`: the new cost and rule plus the hex band.
- Seeds and networks: dev seeds 1–10 (random_lh, amaravati_plan). Held-out seeds 300–329 on random_lh, amaravati_plan and vijayawada_district, medium demand, with and without the incident: 720 runs.
- TARGETS.md was written at 15:45Z, before any held-out run.

## Held-out results (EV travel time, mean of per-seed % difference, bootstrap 95 % CI, n = 90 pairs)

| id | comparison | condition | result | target | verdict |
|---|---|---|---|---|---|
| H1 | eta_rr vs weighted | incident | **-4.6 % [-7.9, -0.2]** (-27 s) | <= -5 %, CI < 0 | **FAIL** (CI excludes 0, mean misses -5 %) |
| H2 | eta_rr vs weighted | no incident | **-6.4 % [-8.9, -3.8]** (-29 s) | CI upper <= +3 % | PASS |
| H3 | eta_rr vs dist | incident | **-19.0 % [-24.6, -12.5]** (-130 s) | <= -15 %, CI < 0 | PASS |
| H4 | eta_rr vs dist | no incident | **-2.1 % [-4.8, +1.1]** | CI upper <= +3 % | PASS |
| H5 | eta_hex vs eta_rr (Vijayawada, 3757 edges) | both | +0.3 % [-0.6, +1.4] / +0.2 % [-0.7, +1.2]; 1548 vs 3757 edges sampled per tick (2.4x fewer); plan 60 vs 93 ms | CI within ±5 %, >= 2x fewer, faster | PASS |
| H6 | all | all | 0 DNF in 720 runs | no DNF | PASS |

Also observed:
- The current production router is **worse than the plain shortest route when nothing goes wrong**: +5.6 % [+2.3, +9.4]. It counts congestion three times and length twice, so it detours on noise. Its rerouting still saves 12.8 % when an incident happens.
- Per network, eta_rr vs weighted: random_lh -3.2 % (incident) and -3.4 % (none); amaravati_plan -3.4 % and -1.3 % (n.s.); vijayawada_district -7.2 % [-14.9, +4.6] and -14.5 % [-17.6, -11.1].

## Caveats
- Vijayawada ran **without the SUMO bluelight device** (other cars do not form a rescue lane). SUMO 1.27.1 crashed with it from seed 303 onward. This is recorded as an amendment in TARGETS.md, applies to all arms, and the partial runs are kept but not used.
- Heavy demand was dropped: under fixed-time signals the networks gridlock. The EV teleported in 3 random_lh medium seeds (314, 318, 327; 4 seed-and-condition cells), in every arm alike: 16 of 720 runs.
- Background signals are fixed-time, not CC-A-CAMP, and preemption is a simple reactive rule. The test isolates route choice; it does not test the corridor engine.
- Predicted ETAs are roughly half of the actual times on dev, because the model does not see spillback at bottlenecks. The router ranks routes well, but its seconds are not yet calibrated ETAs.
- The hex band is not yet wired into the live service. The live service still samples every edge.

## Files
TARGETS.md, summary.md (all tables), results/*.jsonl (720 runs), results/vij_bluelight_crashed/ (unused), copies of the two scripts as they were at target time, plus code_md5.txt. The script that actually ran (`scripts/m7_route_benchmark.py`, md5 in code_md5_run.txt) adds only the `EV_BLUELIGHT` switch after the amendment (a debug `--error-log` flag was on during the Vijayawada re-run and has since been removed; it only writes SUMO errors to a file).

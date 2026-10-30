# Green corridor (M7) and signal algorithm: research round 17–27 Oct 2026

**Status: two changes applied (the time-based router as the default; the standard all-red as an option, off by default). Everything else was tried and is not adopted. Simulation results (SUMO 1.27.1), not field results. Not committed.**

## 1. What changed in the code

| change | where | default | evidence |
|---|---|---|---|
| Time-based emergency router (`EtaCostModel` + `should_reroute`) is now the default; `ITMS_ROUTE_COST=weighted` restores the old weighted cost | `services/sim-service/sim_service/live/emergency_control.py` | **on** | held-out, 720 runs (`baselines/2026-10-17_m7_routing`): -4.6 % [-7.9, -0.2] EV time vs the weighted cost with an incident, -6.4 % [-8.9, -3.8] without; -19.0 % [-24.6, -12.5] vs a fixed route with an incident. 5 of 6 pre-written targets passed (H1 missed its -5 % bar by 0.4 points). |
| Standard (ITE) all-red per junction, `r = (W + 6 m) / v`, rounded up to 0.5 s, 1–4 s; `SIGNAL_ALL_RED=ite` | `scenarios/networks/vijayawada/extract_tier0_config.py` (`ite_all_red_s`) | off (flat 2.0 s) | section 4 |
| Test fakes give `getLastStepHaltingNumber` (the time-based router reads queue length); one monitoring test strengthened for the 15 s reroute bar, plus a weighted-cost copy of it | `tests/live/*`, `tests/control/strategies/test_tier0_clearance_intervals.py` | – | 819 passed, 5 skipped (818 + 1 new all-red test) |

## 2. Ambulance routing (M7): every further idea tested, none adopted

Practice (training) seeds only. Base = the round-1 time-based router (`eta_rr`). Numbers are EV travel time, mean of per-seed % change.

| idea | result | verdict |
|---|---|---|
| Cost constants learned from ~10,500 recorded EV edge traversals (with and without driver yield) | route ranking offline (leave-one-network-out, with driver yield) 0.83/0.73/0.93 → 0.92/0.78/0.95, but trips +4.1 % with incident, +4.0 % without; Vijayawada +13.4 % with incident, +7.8 % without | no |
| Reroute check when the EV stands still 15 s | +0.1 % | no |
| Router that knows the incident and its location at dispatch (upper bound) | -0.1 % | routing is at its limit |
| Incident detected with zero delay | 0.0 % | – |
| Hindsight best of 3–4 driven routes for the same trip | chosen route 4.7–5.6 % slower on average, median 0 % | the gap is unforeseeable stuck events |
| Gap-acceptance (Adams) delay at give-way junctions, Vijayawada, 30 seeds | +1.1 % [-3.9, +7.2] | no |
| EV ignores right of way everywhere (upper bound, 3 EV collisions) | +0.8 % Vijayawada | no headroom |
| ITMS holds cross traffic when the EV must give way | +0.4 % Vijayawada | no |

Where the EV loses time (no incident): 13–16 % of trip time on random_lh / amaravati_plan, 40 % on Vijayawada (no driver yield). Signalised junctions under 4 % of the loss everywhere (preemption works). The rest is following slower traffic and slowing for turns, which the upper-bound tests show no routing or junction-priority scheme recovers in this simulator.

## 3. Signal controller (CC-A-CAMP): green waves, not adopted

- Diagnosis on the real Amaravati map (medium, training seed 102): of signal-stop waiting, 13.7 % is a green cut off just before an unimpeded arrival and 24.2 % is a long red. That pool is about 5 % of person-delay at most. Phase ends: max green 62 %, gap-out 23 %, pressure 15 %.
- Built the controller's planned "Layer 2" neighbour exchange (an upstream green tells the next signal what it is releasing; off by default; code in the 2026-10-18 backup, not in this repo).
- Practice seeds 101–103, person-delay vs the current controller: hold-for-platoon 25 s: light +7.0 %, medium +0.2 %; all phases 25 s: +9.1 % / +1.3 %; 12 s: +0.7 % / +1.0 %. No gain.
- Option (a), rest in green all day: already tested on 14 Oct (`2026-10-14_exit_gap_test`, `2026-10-14_rest_medium`): held-out -3.0 % [-6.1, +0.1], narrow fail. Not re-run.

## 4. All-red clearance: a safety gap, and what closing it costs

The controller uses a flat 2.0 s all-red at every junction. The ITE standard gives:

| network | signals | mean ITE all-red (s) | range | junctions below / above 2.0 s |
|---|---|---|---|---|
| amaravati_v2 | 120 | 2.15 | 1.5–4.0 | 21 / 32 |
| arterial_lh | 6 | 2.50 | 2.5 | 0 / 6 |
| berlin_adlershof | 15 | 2.27 | 1.0–4.0 | 6 / 9 |
| grid4_rh_turns | 16 | 2.50 | 2.5 | 0 / 16 |
| random_lh | 28 | 2.68 | 2.0–3.5 | 0 / 25 |
| vijayawada_district | 37 | 2.45 | 1.5–4.0 | 9 / 15 |

W is taken as the length of the straight-through path across the junction, which is approximate. (The 19 Oct estimate in the project log used the longest path of any kind and is superseded.)

Cost of switching to it (`truth` arm, practice seeds 101–103, person-delay ITE vs flat 2.0 s):

| network | light | medium |
|---|---|---|
| amaravati_v2 | +9.9 % | +10.0 % |
| arterial_lh | +19.7 % | +16.7 % |
| berlin_adlershof | +7.5 % | +13.2 % |
| grid4_rh_turns | +13.5 % | +10.1 % |
| random_lh | +5.2 % | +11.9 % |
| vijayawada_district | +5.5 % | +15.4 % (one seed +45.1 %) |
| **mean of networks** | **+10.2 %** | **+12.9 %** |

- Check: a flat 2.0 s through the new code path gives exactly the old result (0.0 % on all six arterial runs). A flat 2.5 s gives the same as ITE on the arterial (where ITE is 2.5 s everywhere). So the cost is real, not a code side effect.
- Why so large: the all-red value also feeds the controller's tuning (Webster-based max-green ceilings, switching cost, head-of-line timing), and the controller changes phase often (about every 16–18 s per junction on the arterial, per the 13 Oct checkup). Each extra half second is paid on every change.
- **Open issue:** the ITE runs had 4 interlock violations (amaravati_v2 light seed 103: 1, medium seed 102: 2; berlin_adlershof medium seed 103: 1). The flat 2.0 s runs had 0. Not investigated. Longer clearances may conflict with another timing bound (for example `max_wait_s` or the transition planner). This must be fixed before ITE all-red can be used.
- Teleports: 4 → 8 over the 36 run pairs. The extra ones are on amaravati_v2 (light 0 → 1, medium 2 → 3) and vijayawada_district (medium 2 → 4), networks that already teleport.
- In SUMO, drivers never run a red, so the sim cannot show the safety benefit of a longer all-red. That argument rests on the engineering standard.

Reading: the current results use a clearance shorter than the ITE standard at 27–100 % of junctions, depending on the network. A fair comparison (Webster and CC-A-CAMP both on ITE all-red) has not been run. Deciding which all-red to report is a project decision.

## Files
- `results/*.json` (each network × {fixed, ite}, and the flat 2.0/2.5 check)
- `run_allred.sh`, `summarise_allred.py`
- Round-2 routing, green-wave and diagnostic code and data: Mac backups `.claude_staging_20261018*/` (not in this repo)
- Project doc `claude/m7_routing_round2_handoff.md` (full log)

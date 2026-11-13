# Why the green corridor does not beat reactive preemption, and a shared-lane fix (12 Nov 2026)

**Status: simulation result (SUMO 1.27.1, Vijayawada corridor, medium demand). 4 of 5 pre-written targets pass; H3 fails. The fix is off by default. Not committed.**

## Question
On 14 Oct the corridor engine came out level with reactive preemption (each junction switches when the EV is within 300 m). This round asks why, re-tested on the current code.

## Method
- The benchmark is unchanged (`m7_corridor_benchmark.run_one`: 4 EVs per 1800 s run on the dispatched trauma route through 7 junctions) and runs on the current controller inputs (`m8_harness.ccacamp_inputs("medium")`).
- A wrapper (`experiments/m7_corridor_why.py`) records, every second:
  - every EV stop: the light it faced, the cars ahead of it and what the car at the front of the lane was waiting for, and whether the junction was claimed for the EV and in what state;
  - every junction claim: when it was made, how far away the EV was, and when the EV crossed.
- Diagnosis: training seeds 101–110. Held-out: seeds 500–519 (never used before). `TARGETS.md` was written at 04:31Z, before the held-out run.

## Findings
1. **The corridor claims each junction at about the same moment as reactive: slightly later, never earlier.**
   - Held-out medians: claim distance 241 m (corridor) vs 277 m (reactive), 242 / 278 m with the fix. Time from claim to crossing 20 s vs 21 s (20 / 22 s with the fix).
   - The corridor's computed lead time (switch time + queue discharge + latency) seems almost always to be below its 20 s floor (`base_lead_s`). This is inferred from claim timing, because lead time is not logged: only 5 of 469 corridor claims had distance ÷ speed above 20.5 s.
   - At this corridor's EV speed, a 20 s floor is about the same as reactive's 300 m range. So for the EV, the two arms behave as the same trigger, and EV time comes out the same.
   - Note: the wrapper keeps the last claim when a junction is claimed again (42 reactive and 30 corridor claims in the arms without the fix). That skews these medians a little, but no H1–H5 result.
2. **Most of the EV's stopped time was at one junction, on a green, behind a car waiting at its own red.**
   - At `2833253632`, the EV turns left from lane `350502993#7_0` (link L2) onto `-343269496`. The same lane also carries straight-through traffic (L3).
   - L2 is protected in both phases there: P0 (side street L0, L1 + L2) and P1 (L2–L5, the EV's whole approach). Preemption takes the first phase in ring order (`protected_phase_for`), which is P0. P0 holds L3 on red.
   - A straight-going car at the front of the lane therefore waits at its red, and the EV waits about 25 s behind it on a green it cannot use.
   - Held-out, without the fix: 41 such stops, 986 s (reactive), and 39 stops, 995 s (corridor), summed over 20 seeds. That is 80 % and 74 % of the EV stopped time counted by the wrapper.
   - Reactive is a subclass of the corridor engine and uses the same function, so both lose this time equally.
   - On this corridor, 2 of the 53 preemptable movements are set up like this, at `2833253632` and `1880441505`. At `1880441505` the EV goes straight (L3–L5), not through the affected turn, so for this route the fix changes the phase only at `2833253632`.
3. Smaller remaining causes (held-out, per arm, summed over 20 seeds):
   - a red at a junction that was not claimed for the EV, 60–155 s. All but 1 of these 45 stops are at `7871074777`, the one of the 7 signals on the route that is never claimed;
   - mid-block stops, 100–200 s;
   - red while the switch was still running, 0–60 s.

## The fix
`protected_phase_for(cfg, movement, lane_mates)`: among the phases that protect the EV's movement, prefer one that also shows green to every other movement leaving the EV's lane. If no phase does, ring order decides, as before. `CorridorEngine(lane_mates=...)` passes this in; the default is none (old behaviour). Lane mates come from the network's link-to-lane map. The experiment set the same attribute after construction (`m7_corridor_why.py`), so the constructor parameter itself is not yet exercised. Test: `test_a_shared_lane_prefers_the_phase_that_clears_the_whole_lane`, which covers `protected_phase_for` only (corridor tests: 52 passed).

## Held-out results (seeds 500–519, n = 20; per-seed % change, bootstrap 95 % CI)
| arm | EV time (4 EVs) | time lost | stops | stopped | non-EV person-delay | violations | EVs done |
|---|---|---|---|---|---|---|---|
| reactive | 1187 s | 129 s | 4.0 | 60 s | 49,577 | 0 | 80/80 |
| reactive + fix | 1129 s | 71 s | 1.9 | 13 s | 50,739 | 0 | 80/80 |
| corridor | 1192 s | 134 s | 5.0 | 67 s | 50,989 | 0 | 80/80 |
| corridor + fix | 1137 s | 79 s | 2.5 | 18 s | 48,907 | 0 | 80/80 |

| id | comparison | result | target | verdict |
|---|---|---|---|---|
| H1 | reactive + fix vs reactive, EV time | **−4.9 % [−6.1, −3.7]** | ≤ −3 %, CI < 0 | PASS |
| H2 | corridor + fix vs corridor, EV time | **−4.6 % [−5.8, −3.4]** | ≤ −3 %, CI < 0 | PASS |
| H3 | reactive + fix vs reactive, non-EV person-delay (whole network) | +2.6 % [−0.4, +5.7] | CI upper ≤ +3 % | **FAIL** |
| H4 | corridor + fix vs corridor, non-EV person-delay | −3.7 % [−6.9, −0.1] | CI upper ≤ +3 % | PASS |
| H5 | fix arms: violations, EVs complete | 0, 80/80 each | 0, all | PASS |
| D1 | corridor + fix vs reactive + fix, EV time | +0.7 % [−0.0, +1.5] | descriptive | – |
| D1b | same, non-EV person-delay | −3.5 % [−5.8, −1.1] | descriptive | – |
| – | corridor vs reactive (no fix), EV time | +0.5 % [−1.0, +1.8] | descriptive | – |

What this shows:
- **The fix cuts the EV's time lost by about 40–45 %** (129 → 71 s reactive, 134 → 79 s corridor) and its stopped time by about 75 %. Stops behind a car held at a red on a green fell from 41 and 39 to **0**. The 3–4 green-queued stops left are mostly at `7871074777`, with no car at a red in front.
- Delay to all other traffic (non-EV person-delay, whole network): +2.6 % under reactive (CI reaches +5.7 %, so H3 fails) and −3.7 % under the corridor. **The cause is unknown, and the signal looks noisy.**
  - The fix changes the phase the same way in both arms.
  - On the dev seeds, reactive was −2.7 %, the opposite sign to held-out.
  - Without the fix, corridor vs reactive is already +3.1 % [−0.6, +6.7].
  - The arms also differ in pressure terms: the corridor uses anticipation and debt, reactive has both zeroed.
- **The corridor still does not beat reactive for the EV**, with or without the fix (+0.7 % and +0.5 %, CIs reaching 0). The corridor's own idea (claim earlier, by computed lead time) does not engage here, because its 20 s floor makes it claim at about the same time as reactive. With the fix, its non-EV person-delay is 3.5 % lower than reactive with the fix (D1b), but given the noise above, that is not claimed as a corridor benefit.
- Protocol note: `summarise.py` and the new test were written while the held-out run was going. The engine change and the wrapper were written before it. `summarise.py` scores exactly as TARGETS.md specifies. TARGETS.md calls H3 "cross-street"; the metric is actually all non-EV traffic.

## Not done / limits
- **The live path has the same rule.** `live/green_corridor.py` `_phase_serving` breaks ties by the current phase, then ring order. It was not changed or tested here.
- One corridor and medium demand only. 2 of 53 movements are affected here; how common shared-lane turns are on other maps was not checked.
- Why `7871074777` is never claimed (the source of nearly all "red, not claimed" stops) was not investigated.

## Files
`TARGETS.md`, `summarise.py`, `results/` (held-out, 80 runs), `dev/` (training seeds 101–110, 40 runs); `experiments/m7_corridor_why.py`, `experiments/m7_corridor_why_summary.py`; code: `sim_service/control/corridor/junction.py`, `engine.py`; test in `tests/control/corridor/test_corridor_junction.py`.

---

# Round 2 (12 Nov, afternoon): making the fixes default, and what is left to improve

## Changes
| change | where | default |
|---|---|---|
| Both preempting arms choose the phase that clears the EV's whole lane. `reactive_ringorder` / `corridor_ringorder` keep the old ring-order choice. | `experiments/m7_corridor_benchmark.py` (`lane_mates()`, `build_arm`) | **on** in the benchmark |
| The benchmark trip ends at the hospital (`arrivalPos` = the facility's `edge_offset_m`, 212 m), not at the far end of edge `343269496` (424 m). 212 m is the facility extractor's default (half the edge); the hospital itself projects to about 217 m. EVs were driving 212 m past the trauma centre and queuing for the next signal there. This changes every arm's absolute times, so pre-12-Nov EV durations are not comparable. | same file, `_Injector` | **on** |
| Live corridor: among phases that protect the EV's movement equally, prefer one that also greens those other movements leaving the EV's lane(s) **that have cars queued** (`ctx.queue_pcu > 0`), before the "keep the current phase" tie-break. Protection still comes first. | `live/green_corridor.py` (`_phase_serving`, `preemption_plan`), `routing/graph.py` (`RoadGraph.link_lane_mates`, built from `fromLane`) | **on** |
| Tests: 4 live tests (`tests/live/test_green_corridor_protected.py`, including the queue-conditional wiring in `preemption_plan`) and the junction test from round 1. Simulation-service suite: 1682 passed, 4 failed. The same 4 fail on the untouched 12 Nov snapshot: three `test_live_service` tests and `test_snap::test_every_depot_and_facility_resolves_to_a_district_road`. | | |

## The ambulance now hardly stops on the corridor
Training seeds 101–110, both fixes on, 4 EVs per run:

| arm | EV time | time lost | stops | stopped | non-EV person-delay |
|---|---|---|---|---|---|
| reactive | 1048 s | 62 s | 0.9 | 6 s | 48,725 |
| corridor | 1054 s | 68 s | 1.4 | 8 s | 50,352 |

That is 15–17 s lost per trip, and 0.9 (reactive) or 1.4 (corridor) stops per 4 trips. Stopped time is only about 1.5–2 s per trip. The rest of the time lost (slowing for turns, following traffic) was not broken down, and no free-flow reference run was made, so this is not shown to be a floor. Nearly all the stopped time is at the final U-turn into the hospital road: 60 of 61 s (reactive) and 82 of 83 s (corridor) are at `7871074777`.
- At `7871074777`, the U-turn L4 is only *permitted* (yield-on-green) in its one green phase: it merges with L0 into lane `343269496_0`.
- The movement index therefore drops it, and that junction is never claimed. This is by the safety rule against preempting onto a permissive movement (hazard D3).
- Removing this would need a preemption-only signal state (L2–L4 green, L0 red). Not built: it costs about 1–2 s per trip.

## Tried and rejected: claim later to lower the cost to other traffic
The EV has little left to gain, so the remaining lever is preempting later. Corridor arm, training seeds 101–110, vs reactive:

| corridor lead floor `base_lead_s` | EV time | stops (4 EVs) | non-EV person-delay |
|---|---|---|---|
| 20 s (default) | +0.5 % | 1.4 | +3.4 % (sd 4.1) |
| 15 s | +2.3 % | 3.9 | −1.2 % (sd 5.6) |
| 12 s | +3.2 % | 4.8 | +2.3 % (sd 8.4) |
| 8 s | +5.0 % | 6.8 | +2.3 % (sd 4.0) |

A later claim makes the EV stop more.
- Paired against the 20 s default, 15 s may save about 4 % of non-EV delay (−4.3 %, sd 6.4, p ≈ 0.06, 10 seeds), at a cost of +18 s EV time per run. It is rejected on that EV cost.
- 12 s and 8 s show no saving.
- In the same data, the default corridor costs other traffic +3.4 % against reactive (t ≈ 2.6).

The default (20 s) stays. No held-out run was made, because nothing was adopted.

## Live corridor, district map: no measurable effect
Audit test B (`green_corridor_audit_2026-11-09/b_lane.py`: 4 EVs per run on random O-D pairs, live `CorridorController`), training seeds 101–110, light and medium traffic.

First version: always prefer the phase that clears the EV's lane.
- EV time vs no fix: light −0.1 % (39 paired EVs), medium +0.1 % (38 paired); median 0.0 %.
- Single trips swung from −25 % to +32 % in medium traffic (10 of 38 changed). In light traffic 4 of 39 changed, from −7 % to +3 %.
- The fact-check found the reason: in all 18 affected district cases, the live phase already protects the EV, so this version forced a phase switch even when no car was blocking the lane.

**Kept version (`fix2`):** a lane mate counts only if cars are queued on it (`ctx.queue_pcu > 0`). Otherwise the live phase keeps the tie.
- Light traffic: no trip changed at all.
- Medium traffic: 5 of 38 trips changed, mean +0.35 %, median 0.0 %, signal stops 381 → 398 s.
- The change is dominated by one trip, medium seed 109, EV 2: 344 → 453 s. It rerouted 5 times instead of 3, so traffic had diverged. Three of the five changed trips got faster, the largest being seed 109 EV 3 (420 → 378 s, −10 %) and seed 107 EV 1 (571 → 524 s). Whether 109's loss comes from the fix itself was not traced.
- EVs not arrived: 1 (light) and 2 (medium) in every variant; they were still driving when the run ended.

How much the change can matter here: on the district map, it alters the choice in 18 of the 305 (turn × live phase) cases a corridor can preempt at all (525 including unprotected ones). 16 of the 80 initial routes cross such a turn.

Reading: on the live map the fix is a correctness fix with no measured benefit (10 seeds, underpowered). The large gain is on the corridor benchmark, where an EV route crosses the affected turn every trip.

## Where improvement is still possible (not done)
- **Live path, district map.** EVs still spend about 6–10 s per trip at signals. The 9 Nov audit attributes this to 31 % of signal movements having no protected phase, and to EVs being ordinary car types queued behind traffic. Both are bigger changes: adding protected or preemption-only phases, and an EV vehicle type that can use a rescue lane.
- **The corridor engine vs reactive.** No setting tried makes the corridor's earlier, computed claim pay off on this corridor. Its value over reactive would have to come from multi-EV arbitration (with two EVs on crossing routes) or from coordination across junctions, which these tests do not exercise.

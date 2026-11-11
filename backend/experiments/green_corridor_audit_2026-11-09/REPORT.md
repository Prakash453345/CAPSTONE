# Green corridor, rerouting, race and fire/ambulance audit — expanded district map

9 Nov 2026 · branch `komal` working tree · SUMO 1.27.1 · map `vijayawada_district` (362 roads, 28 signals)
Targets were written before any run (`TARGETS.md`). Nothing in your source code was changed; everything is in this folder.

## Verdict

| Question | Answer |
|---|---|
| Is it just picking a straight line? | **No.** Routes are real road paths, traffic-aware, never loop, and all 362 roads are mutually reachable. Circuity misses my numeric target, but pure shortest-by-length paths score the same, so that is the map, not the router. |
| Does the green corridor work? | **It is safe, but it barely helps.** 0 conflicting greens, 0 skipped yellows, 0 collisions in every run. But EV travel time vs a fixed route is only −0.9 % (light) and −2.3 % (medium), both with confidence intervals spanning zero, and EV time stopped at signals falls by only 13–28 %. Target was ≥ 50 %. |
| Does rerouting work? | **Yes, the reaction is fast and correct** (24/24 blocks: EV off the blocked road in 3 s, corridor re-armed). **But** it reroutes 1–9 times per trip even with no incident, and 10 SUMO route updates were silently rejected. |
| Race conditions? | **Two real bugs** in command handling (vehicle double-booking, second CANCEL throws) and **stuck EVs with no watchdog**. Signals stayed safe under every concurrent test. |
| Fire got no ambulance? | **Confirmed, and it is two bugs.** A FIRE incident pages fire truck + police only (no ambulance), and no fire-truck units exist at all. 0 of 20 fires got an ambulance; 20 of 20 accidents did. A fix is validated in simulation (below). |

## Results against the pre-set targets

| # | Target | Result | |
|---|---|---|---|
| A1 | every road pair routable | 362/362 roads in one strongly-connected set; 0 of 600 random pairs unroutable | PASS |
| A3 | no loops / broken routes | 0 loops, 0 disconnected, 600 pairs | PASS |
| A4 | circuity median ≤ 1.5, p95 ≤ 2.5 | median 1.60, p95 4.39. Shortest-by-length: 1.60 / 4.35. Planner within 2.3 % of shortest length at p95; differs from it in 22 % of pairs | FAIL (map property) |
| B1 | corridor vs fixed route: CI upper < +3 %, mean ≤ −5 % (light, medium) | light −0.9 % [−5.4, +3.5]; medium −2.3 % [−7.3, +2.5] (9 seeds, 34 and 33 paired EVs) | FAIL |
| B2 | signal-stop time ≤ 50 % of fixed route | 0.72 light, 0.87 medium, 0.84 heavy | FAIL |
| B3 | 0 EV not arrived (light, medium) | corridor arm: 1/36 light, 3/36 medium. Fixed route: 2/36 and 2/36 | FAIL |
| B4 | corridor armed on every trip with a signal | 36/36, 36/36, 12/12 | PASS |
| B5 | no corridor left after trip | 0 left at light and medium | PASS |
| B6 | reroute alone not worse | light +2.0 % [−0.8, +5.8]; medium −1.2 % [−5.2, +2.7] | FAIL at light (inconclusive), PASS medium |
| C1 | 0 conflicting greens | 0 in all ~150 runs, all 28 signals checked | PASS |
| C2 | 0 green→red without yellow | 0 | PASS |
| C3 | no extra collisions | 0 with corridor. 2 in heavy `route_only` arm (no corridor) | PASS |
| C4 | max red on any link ≤ 1.5× fixed route | 1.29× light, **1.46× medium**, 1.0× heavy | PASS (medium close) |
| C5 | signals recover ≤ 60 s | not timed directly. Proxy: 0 corridors left at light and medium | proxy PASS |
| D1 | EV leaves a newly blocked road ≤ 10 s | **24/24 in 3.0 s**, 0 entered the blocked road | PASS |
| D2 | corridor re-armed on new route | 24/24 | PASS |
| D3 | no way round: no crash/loop | no crash or exception. EV drove on to the closed road. Completed 2/2 light, 1/2 medium, 1/2 heavy | PASS |
| D4 | flapping block: ≤ 6 reroutes | 5.0 / 5.5 / 7.0 per trip vs 3.0 / 5.0 / 9.0 with no block at all, so flapping adds no churn | PASS |
| D5 | never re-enter a re-blocked road | ≤ 1 s once | PASS |
| E1 | two EVs crossing one signal, offsets 0…±10 s | light, medium: 56/56 trials both arrived, 0 conflicts, 0 collisions. Heavy: 14/28 (gridlock, ~140 teleports per run) | PASS (light, medium) |
| E2 | 2/4/6/10 EVs in the same second | light 44/44 arrived; **medium 41/44**; heavy 22/44. Never a conflicting green | FAIL (medium) |
| E3 | command races | double-booking a vehicle: 6/6 runs. Second CANCEL raises: 6/6 runs | **FAIL** |
| E4 | dispatch invariants R1–R12 on this map, 2 seeds × 1–2 units | 3 of 4 runs clean. 1 run: R6 ×2 (a trip sat in "corridor active" 61 s without departing) | FAIL |
| F1 | fire pages an ambulance | **0/20** (accident control 20/20) | **FAIL** |
| F2 | fire truck sent | **0/20, no units exist** | **FAIL** |
| F3 | ambulance ≤ 10 min from anywhere | all roads reachable, worst 524 s, 8 roads over 300 s | PASS |

Heavy demand gridlocks this map even with the fixed route (about 300 teleports per 3 runs), so heavy results say little about the algorithm.
The seeds went from 3 to 9 at light and medium after the first 3 gave wide intervals. That extension was not in the original plan.

## What is wrong, ranked

**1. Fire never pages an ambulance, and there are no fire trucks.** (`live/incident_response.py`)
`_RESPONSE_MAP[FIRE] = (FIRE_TRUCK, POLICE)`, and `_units[FIRE_TRUCK] = []`. So a fire dispatches police only, and ACCIDENT's fire-truck page goes nowhere too.
Test: 20 fires and 20 accidents at the same 20 places. Fire: 0 ambulances, 0 fire trucks, police 15/20 (4 police units, the rest queued). Accident: 20 ambulances, 0 fire trucks.
Fix tried in the test harness only (not in your code): add `AMBULANCE` to the FIRE entry, and base fire trucks at the police depots (what `service.py` already assumes for crew home edges). Result: fire gets an ambulance 20/20 and a fire truck 15/20 (the other 5 wait because only 4 units exist). Real fire-station locations for the expanded map would fix the unit count.

**2. The corridor is mostly not open when the EV arrives.** In corridor runs the EV spent about 300 s at red lights, and a reservation was open at that signal for only 3–12 % of it.
- Windows are computed once from free-flow ETAs and never re-timed. 61 % (light) and 68 % (medium) of junction passes came after the window had closed. The lag compounds: 0–3 s late at the first junction, 40–60 s late further along (from the 2nd junction at medium, the 3rd at light).
- 31 % of non-U-turn signal movements (65/209) have no protected phase, so the corridor cannot preempt them. 51 % of random routes with a signal (619/1222) cross at least one such junction; 17 % of all crossings. Worst: `1880441581`, `cluster_1880441740_4393296791` (about half their crossings).
- Just under half of red-light stops are the EV queued behind other cars (light 162/343, medium 165/372); the rest are the EV first in line, which a working corridor should remove. The EV is a plain `DEFAULT_VEHTYPE` car, so it cannot pass a queue.
- I tried re-timing windows every 3 s from the EV's measured progress. **It did not help** (light, 5 seeds: signal-stop time 564 s vs 590 s for the fixed route; current corridor 465 s). So stale windows are real but not the whole story, and my prototype may not be the right fix.

**3. Command races** (`live/emergency_control.py`)
- Two requests for the same vehicle id in the same second are both accepted. The second spawn fails ("could not spawn"), yet the request ends COMPLETED. Two live trips for one vehicle for 390–650 s. The dispatcher protects against this with a busy flag; the operator/console path does not.
- A second CANCEL on a cancelled request throws `IllegalRequestTransition` (RECALCULATE and ACTIVATE are guarded; CANCEL is not).
- Handled correctly: duplicate request id, double ACTIVATE, cancel in the same tick as create, source equal to destination, unknown roads, destination blocked at creation, duplicate/unknown anomaly ids, create+clear in the same tick.

**4. Stuck EVs go unnoticed.** At medium traffic 3 of 44 EVs in the mass-dispatch test never arrived (one sat 1021 s motionless inside a junction, another two ~600 s on a road). Nothing flags or reacts to an EV that has not moved for minutes away from a signal.

**5. Silent route-update failures.** 10 times in 89 SUMO runs (and again in the dispatch stress runs) SUMO rejected `setRoute` ("on junction-internal edge", "no connection between edge X and edge X"). The error is logged and swallowed, so the request's route and the vehicle's real route disagree.

**6. Reroute churn with no incident.** On long test trips with nothing blocked: 3.0 / 5.0 / 9.0 reroutes per trip at light / medium / heavy (2 seeds). Ordinary 4-trip runs average 1.1–1.4 per trip.

**7. Data coverage on the expanded map.** Hospitals sit only in the old corridor area; there are 4 police depots. Worst ambulance ETA 524 s and police 556 s, both on the far north-east on-ramp roads (`374226425#2`, `-305817523`, `177626311#…`).

## What works

- Signals stayed safe under every test: concurrent EVs, flapping blocks, 10 EVs at once.
- Reroute reaction is fast and the corridor follows the new route.
- Dispatch queue/priority logic is clean in 3 of 4 stress runs on the new map.
- Routes are valid, loop-free and traffic-aware. The result is deterministic: Mac and cloud runs gave identical EV times.

## Limits of this audit

- 9 seeds × 4 EVs per cell at light and medium (3 seeds at heavy). Confidence intervals are wide; "FAIL" on B1 means the pre-set bar was not met, not that the corridor is harmful.
- The live wiring uses the Webster strategy under the corridor, not A-CA-MP.
- Static checks A and F3 ran on a Python 3.10 shim; all SUMO runs on Python 3.13 with SUMO 1.27.1 (your pin).
- The stress script `m7_dispatch_stress.py` is stale after the restructure (old `sim-service` path, raw facility edges). I ran a corrected copy (`e4_dispatch_stress.py`).
- C5 (signal recovery time) was not measured directly.
- Facility and depot data come from the old corridor extract, snapped onto the new map.

## Files (all new, in `backend/experiments/green_corridor_audit_2026-11-09/`)

`TARGETS.md` (written first) · `audit_lib.py`, `audit_run.py`, `audit_run2.py`, `audit_tests2.py` (harness) · `e4_dispatch_stress.py` · `analyze_B.py`, `analyze_D.py` · `results/` (one JSON per run, `B_summary.txt`, `D_E_summary.txt`) · `results_diag/` (stop-reason diagnostics) · `stage/backend_subset.tgz` (the copy I used to run in the cloud; delete it).

---

# After the fixes (same harness, same seeds, 9 seeds × 4 EVs)

## What I changed (working tree only, nothing committed)

| Fix | File |
|---|---|
| **Corridor windows now follow the EV's measured position**, not the free-flow clock fixed at activation. A junction is held once the EV is within 260 m of the stop line, released when it passes, and never held more than 60 s for one EV (new config `corridor_lookahead_m`, `corridor_max_hold_s`). Root cause found by tracing preemption: 99.5 % of ticks returned "no plan" because the window was closed or not yet open, while the EV was actually there. Interlocks were not the problem (291 of 291 plans accepted). | `live/green_corridor.py`, `itms_domain/routing.py` |
| Fire now pages an ambulance, and fire trucks are based at the police depots until real fire stations exist | `live/incident_response.py` |
| A second request for a busy vehicle is refused (ROUTE_FAILED) instead of double-booked | `live/emergency_control.py` |
| A second CANCEL on a finished request is ignored instead of raising | `live/emergency_control.py` |
| A SUMO route change that is refused is retried for 20 s, then warned about, instead of silently lost | `live/emergency_control.py` |
| Tests added/updated for all of the above (4 new, 3 updated) | `tests/live/*` |

Tests: live + routing + signal_controller = 1200 passed (plus 2 new corridor tests).

## Results vs the pre-set targets (corridor arm, before → after)

| Target | Before | After |
|---|---|---|
| B1 EV travel time vs fixed route, light | −0.9 % [−5.4, +3.5] FAIL | **−6.6 % [−10.9, −2.1]** PASS |
| B1 medium | −2.3 % [−7.3, +2.5] FAIL | **−6.9 % [−12.0, −0.5]** PASS |
| B2 signal-stop time vs fixed route (≤ 0.5) | 0.72 light / 0.87 medium | **0.48 light / 0.37 medium** PASS |
| B3 EVs not arrived | 1 light, 3 medium | 1 light, 2 medium (fixed route: 2 and 2) still not 0 |
| C1/C2 conflicting greens, skipped yellows | 0 | 0 |
| Collisions | 0 | 0 |
| C4 longest red on any link vs fixed route (≤ 1.5×) | 1.29× light, 1.46× medium | **2.1× light (80 s), 1.8× medium (66 s)** FAIL |
| F1 fire gets an ambulance | 0/20 | 20/20 (simulation of the patched dispatcher) |

Cost: the corridor now actually takes green, so cross-traffic waits longer: worst red went from 38 s to 80 s at light. Still no conflicting greens. If that is too long, lower `corridor_max_hold_s`.
Heavy demand still gridlocks on this map (3 seeds, 279 teleports); not improved or judged.

## Not done
- Stuck-EV watchdog (an EV motionless for minutes away from a signal is still not flagged).
- Reroute churn without incidents (1.1–1.5 per trip) not reduced.
- 31 % of signal movements still have no protected phase; those junctions are still skipped.
- Re-run after the fixes covered the B test only (corridor arm, light and medium); D, E and F were not repeated end to end.
- Pre-fix numbers are the first pass; I did not tune the new constants on a separate set of seeds, so 260 m and 60 s were chosen once and the same 9 seeds measured them.

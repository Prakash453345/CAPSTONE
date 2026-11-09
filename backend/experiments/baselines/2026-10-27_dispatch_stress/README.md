# Dispatch queue, reassignment and reroute: stress test and bug fixes (27–28 Oct 2026)

**Status: 9 bugs found and fixed, plus 3 more issues from the independent fact-check. Every fix has a test that fails without it. Simulation (SUMO 1.27.1) and unit tests, not field results. Not committed.**

## How it was tested
1. **Code review plus small probes** using the existing test fakes (no SUMO), one per suspected bug.
2. **Randomised stress test in real SUMO** (`scripts/m7_dispatch_stress.py`). It runs the live anomaly, incident-response, emergency-routing and green-corridor code for 3600 s of simulated time per run.
   - Calls arrive every 60–200 s (random place; 70 % accidents, half medium and half high; 15 % blockages; 15 % low severity) for 1 or 2 police units and ambulances (no fire trucks). The fleet is overloaded on purpose.
   - When a vehicle sets off, there is a 35 % chance that a road 2–5 roads ahead of it is blocked (if its route is long enough and that road is free). In practice this happened on 66 of 263 trips.
   - The "operator" clears anomalies early now and then, cancels random trips, and accepts about half of the reassignment suggestions.
   - Thirteen rules are checked after every simulated second (listed in the script's docstring). Examples:
     - no vehicle has two live trips;
     - a unit is busy exactly when it has a trip;
     - no unit is idle while a call of its kind waits;
     - the queue is served in priority order;
     - no call is silently dropped;
     - a driving vehicle with a signal ahead has a corridor;
     - a vehicle reroutes off a blocked road within 10 s if there is a way round;
     - no suggestion stays open after it stops applying.
   - Maps: random_lh (generated; stand-in hospitals), amaravati_v2 (real map, 120 signals; stand-in hospitals) and the Vijayawada corridor (real hospitals and police stations).

## Bugs found
| # | bug | effect | found by |
|---|---|---|---|
| 1 | A unit that came free went to a call reported in that same second, ahead of an older call of equal or higher priority that was already waiting | priority inversion | probe; also seen once in a stress run (rule R4), but that run was stopped early and its log not kept, so the sighting cannot be verified |
| 2 | Two new calls in the same second were served in list order, not by severity | a medium call could take the only unit from a high one | review |
| 3 | A reassignment suggestion stayed open after it stopped applying (the unit's trip ended, or the waiting call was served or cleared) | that unit got **no further suggestions** for the rest of the run | probe; **all 10 old-code stress runs** (20 times, rule R11) |
| 4 | Each additional unit heading to a less severe call produced another suggestion for the same waiting call, one per second | duplicate prompts to the operator | probe |
| 5 | A waiting call that no unit could reach was retried every second | one failed trip created per second for as long as the call stayed active (8 in 8 s in the probe) | probe |
| 6 | A unit beyond the hex search radius (about 10 km) was never sent, even when it was the only free one | the call waited while a unit stood idle | review |
| 7 | A cancelled ambulance trip, or a failed reassignment, left its "go to hospital after the scene" flag set | the ambulance's next trip, even an operator's non-incident trip, was chained to a hospital | probe |
| 8 | A reroute onto a road with signals armed no green corridor if the first route had crossed no signal | no signal preemption on the new route | probe (not seen in the stress runs: rule R7 never fired on the old code) |
| 9 | Monitoring of new severe anomalies: (a) a new high-severity anomaly triggered an immediate reroute only for the first vehicle that saw it, because the "already seen" record was shared across trips; (b) an anomaly already known when the route was planned still triggered a reroute, which re-armed the corridor for nothing | (a) other vehicles drove on toward it until the 30 s cooldown and progress check let the normal re-plan run; (b) wasted replanning and corridor churn | probe |

Found by the fact-check of the first round of fixes, and fixed:
- A reassignment that could not route from where the unit was marked the unit as unable to reach the call at all. That could drop a call reachable from the unit's depot.
- The beyond-radius fallback sent the first free unit in list order. It now sends the nearest in a straight line.
- After a replan that left the route unchanged, the minimum-progress check measured from an old baseline.

Found by the final stress round, and fixed: moving a unit off a call whose anomaly had just been resolved put that call back in the queue for one second.

Other changes:
- A reassigned unit now restarts where it is on its road, instead of at the beginning of that road (up to one road length back).
- Most per-trip monitoring state is cleared when a trip ends.
- When a monitor trigger's replan gives the same route, the vehicle is no longer re-pointed and the corridor is not re-armed. The exception is a route that now runs knowingly through a new blockage: that is still applied, so the route records it.

## Results
Old code = `pre`, final code = `final`. Each final-code run made different dispatch decisions, so the random script played out differently. Compare violation counts, not trip numbers.

| map | units per kind | runs | violations, old code | violations, final |
|---|---|---|---|---|
| random_lh | 1 | 3 | R11 × 5 | none |
| random_lh | 2 | 3 | R11 × 8 | none |
| amaravati_v2 | 1 | 1 | R11 × 1 | none |
| amaravati_v2 | 2 | 1 | R11 × 2 | none |
| Vijayawada | 1 | 1 | R11 × 1 | none |
| Vijayawada | 2 | 1 | R11 × 3 | none |
| **all** | | **10 + 10** | **20, in all 10 runs** | **0** |

Across the 10 final-code runs:
- 263 trips, 219 dispatches, 153 of them served from the queue (this count includes new calls queued and served in the same second);
- 81 reassignment suggestions, 33 accepted (48 suggestions on the old code; the runs diverge, so this is not a like-for-like comparison);
- 145 reroutes, 66 blocks ahead of a moving vehicle, 27 operator cancels.

No crashes. No vehicle with two trips, no corridor left behind after its trip, no call dropped, no trip stuck before departure, and no vehicle kept on a blocked road with a way round.

How the rules were adjusted along the way:
- **R4b added.** Since the bug 1 fix, a new call joins the queue whenever a call of its kind is waiting, so R4 can no longer fire on the final code. R4b checks the serving order.
- **One R4b hit traced to the rule itself.** It first fired twice in one run. Both times the cause was the one-second requeue fixed above, which the rule counted as a waiting call. The rule now looks only at calls that were waiting before the tick. That run was repeated with the final code: no violations.

Tests: 14 new (`services/sim-service/tests/live/test_dispatch_edge_cases.py`). The first 11 fail on the old code. The last 3 fail on the first round of fixes, which had only bugs 1–9 fixed. Whole repo: 1111 passed, 12 skipped.

## Files changed
- `services/sim-service/sim_service/live/incident_response.py` (bugs 1–7, the fact-check items, the restart position)
- `services/sim-service/sim_service/live/emergency_control.py` (bugs 8–9, the restart position, cleanup)
- `services/sim-service/tests/live/test_dispatch_edge_cases.py` (new)
- `scripts/m7_dispatch_stress.py` (new)
- `results/{pre,final}_<map>_u<units>_s<seed>.json`

## Not fixed: design decisions and known limits
- **New: unreachable calls are dropped for good.** A call that no unit of its kind can route to from its depot is dropped, with one alert. It is not retried later, even if a unit is added, because the anomaly is already marked as seen.
- **One open suggestion per waiting call.** If the operator ignores a suggestion, no other unit is suggested for that call until the first suggestion stops applying.
- **Withdrawn suggestions are not announced.** A suggestion that stops applying is removed internally but no event says so. A future console button would show it until clicked, and then the click returns "no longer applies".
- **An operator cancel drops the call.** If the operator stands a unit down while the anomaly is still active, nobody else is sent. This may be intended, or the call should go back in the queue. This is a project decision.
- **Units return to base instantly.** A unit that finishes a job is free at once and its next trip starts at its depot, wherever it actually is. Queue waiting times are therefore optimistic.
- **Real crew accounts:** a call that every crew declines (`exhausted`) is still dropped, not queued.
- **Anomaly ids are remembered for the whole run.** An id that is cleared and later reused is never dispatched again. Camera and operator ids are unique today.
- **Coverage is limited:** 10 runs per code version, 1 seed for each real map. The rules are checks, not proofs.

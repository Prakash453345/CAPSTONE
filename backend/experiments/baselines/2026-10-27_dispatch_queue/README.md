# Dispatch queue, reassignment and faster rerouting (2026-10-27)

**Status: built and tested; not committed. A behaviour change, not a tuning: no held-out benchmark applies.**

## Problems found in the code
1. **Calls with no free unit were forgotten.** `incident_response._dispatch` logged "no available unit … skipping" and marked the anomaly seen, so when the unit came free nothing went back for that call.
2. **No priority:** first detected, first served, whatever the severity.
3. **A newly blocked road ahead waited out the 30 s reroute cooldown.**
4. **Repeated forced reroutes:** with no way around a blockage, the monitor "rerouted" onto the same forced route every cooldown period.

## Changes
- `live/incident_response.py`:
  - **Waiting queue.** A call (one unit kind for one anomaly) whose kind has units but none free waits. Each tick, free units serve waiting calls, highest priority first. Priority is severity (high/blocked 3, medium 2) plus 1 per 10 min waited (`QUEUE_AGING_S`), so medium calls are not starved. A call whose anomaly is resolved or cancelled is dropped. Kinds with no units at all (fire trucks today) are still skipped.
  - **Reassignment suggestions.** For a waiting call, a unit of the same kind still on its way to a *lower-severity* call is suggested, nearest by road time. There is at most one open suggestion per unit, and each (unit, call) pair is suggested once. Never automatic.
  - `accept_reassignment(suggestion_id)` cancels the unit's trip, puts that call back in the queue with its original waiting time, and sends the unit from where it is now.
  - `waiting` lists the queue for the console.
- `live/service.py`: `EmergencyCommand` with action `REASSIGN` (`request_id` = suggestion id) calls `accept_reassignment`.
- `live/emergency_control.py`:
  - A road ahead that has just become blocked, or a new severe anomaly on it, skips the cooldown and progress gates, once per anomaly for each trip.
  - The vehicle's own road and its destination are not "ahead".
  - A blockage the current route already crosses knowingly (`forced_through`) no longer re-triggers.
  - `current_edge(request_id)` added.
- Contracts (backward compatible, all new fields have defaults): `EmergencyDispatched` gains `queued_kinds`, `waited_s`, `reassigned_from` and `reassign_suggestions`. `EmergencyCommandAction` gains `REASSIGN` (appended).

## Tests
- sim-service + packages: 826 passed, 5 skipped. New tests:
  - waiting call served when the unit frees;
  - higher severity first;
  - resolved anomaly leaves the queue;
  - suggest + accept reassignment (old call requeued, original time kept, suggestion single-use);
  - equal severity never suggests;
  - new blockage skips the cooldown once;
  - blocked destination does not trigger;
  - a forced-through blockage is not retried (this one fails without the fix).
- api-service: 92 passed, 4 skipped.

## Simulation check (real SUMO, `scripts/m7_dispatch_queue_check.py`, one ambulance)
Accident an-A (medium) at t = 300 s; an-B and an-C (high) at t = 310 s; the "operator" accepts the suggestion; a road ahead of the ambulance is blocked 5 s after it sets off for an-B.

| | random_lh (stand-in hospital, metres mapped to lat/lon) | Vijayawada corridor (real hospital) |
|---|---|---|
| an-A medium | sent 300 s; moved to an-B at 311 s; served again at 2270 s | sent 300 s; moved at 311 s; served again at 955 s |
| an-B high | 311 s (reassigned ambulance) | 311 s (reassigned ambulance) |
| an-C high | 1346 s, after an-B and its hospital trip | 544 s |
| blocked road ahead | rerouted **1 s** after the block, 6 s after the route was set; new corridor armed; 1 reroute in total | not run (the corridor network has no road with a way round) |
| left waiting | none | none |

Before these changes, an-B and an-C would never have received the ambulance, and the reroute would have waited until the 30 s cooldown ended.

## Not done
- **Console / web-app:** the suggestion arrives on the existing `EmergencyDispatched` alert stream, but there is no button yet that sends `REASSIGN`.
- **Real crew accounts** (`crew_dispatch.CrewDispatcher`): when every crew declines (`exhausted`), the call is still dropped, not queued.
- The queue lives in memory: a sim-service restart empties it.

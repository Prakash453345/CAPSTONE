# Green-corridor / rerouting / dispatch audit — targets (written 2026-11-09, BEFORE any run)

Map: Vijayawada **district** network (SIM_NETWORK=district), branch `komal` working tree.
Stack under test: live wiring of `sim_service.live.service.run_live` minus Redis — Webster strategy + arbiter
+ `CorridorController.preemption_plan` + `EmergencyController` + `IncidentResponseOrchestrator`, in real SUMO 1.27.1.
Demand: light / medium / heavy (the district's own three levels). Not tuned on anything; no test frames involved.

## A. Map and routing sanity (no SUMO)
- A1 every ordered pair of edges inside the largest strongly-connected component is routable by the planner: 100 %.
- A2 edges outside that component are listed (data finding, no pass/fail).
- A3 planner route is a valid connected edge sequence, no repeated edge (no loop): 100 % of sampled pairs.
- A4 "not a straight line" = route is traffic-aware: with live congestion the planner's route differs from the free-flow
  path on a non-trivial share of pairs AND is not slower. Static circuity (route length / straight-line distance):
  median <= 1.5, p95 <= 2.5.

## B. Green corridor, single EV, 3 traffic levels (paired on seed and O-D, 3 arms)
Arms: `plain` (free-flow route fixed, no corridor, no reroute) / `route_only` (planner + reroute, no corridor) /
`full` (planner + reroute + corridor).
- B1 `full` vs `plain` EV travel time, per level: mean paired % change, bootstrap 95 % CI upper bound < +3 %
  (must not be worse), and mean <= -5 % at light and medium (the corridor has to earn something).
- B2 `full` signal stop time (EV speed < 0.5 m/s within 40 m before a signal) per run <= 50 % of `plain`'s, at each level.
- B3 0 DNF (EV not arrived by 900 s after spawn) in `full` at light and medium; at heavy any DNF is reported, not hidden.
- B4 corridor armed (>=1 reservation) for 100 % of `full` trips that cross >=1 signal (rule R7).
- B5 no corridor left after its trip ends (R8): 0 violations.
- B6 `route_only` vs `plain` : mean paired change CI upper bound < +3 % (rerouting alone must not hurt).

## C. Signal safety while corridors run (every tick, every signal, every arm)
- C1 0 conflicting greens (two 'G' links that are foes at the same node).
- C2 0 direct green->red jumps without yellow, in `full` beyond the count in `plain`.
- C3 0 collisions beyond `plain`'s count; 0 vehicle teleports caused by the EV beyond `plain`'s.
- C4 cross-street starvation: max continuous red on any link in `full` <= 1.5 x the max in `plain`.
- C5 every signal back on its normal program within 60 s after the EV has passed it.

## D. Rerouting
- D1 block placed on the EV's route 2-5 roads ahead (every level): EV leaves the blocked road within 10 s of the block
  becoming known whenever a way round exists: 100 %.
- D2 new route re-arms a corridor (R7) when it has signals: 100 %.
- D3 no way round (both alternatives blocked): EV holds, does not crash, does not teleport; event says so. Pass = no crash, no loop.
- D4 block flapping (set / clear every 5 s for 120 s): reroutes <= 6 in that window (no oscillation), EV arrives.
- D5 unblocking later: EV never driven INTO a cleared-then-reblocked road twice.

## E. Race conditions
- E1 two EVs, crossing routes through one signal, arrival offsets {0, +-2, +-5, +-10} s: both arrive, 0 conflicting greens, 0 deadlock (neither stuck > 120 s).
- E2 N = 2, 4, 6, 10 EVs dispatched in the same second at random pairs: all routed or cleanly refused; none stuck; 0 safety violations.
- E3 command races: duplicate create id, double ACTIVATE, CANCEL same tick as create, src == dst, unreachable pair, unknown edge:
  no exception escapes the tick, no vehicle with two live trips, no corridor leak.
- E4 dispatch invariants R1-R12 (existing `m7_dispatch_stress.py`) on the district: 0 violations, 2 seeds x units {1,2}.

## F. Fire / ambulance
- F1 a FIRE anomaly (MEDIUM/HIGH/BLOCKED) at 20 locations pages an AMBULANCE: expected 100 % (a fire with casualties needs one).
  The ACCIDENT type is the control (it already pages all three).
- F2 a FIRE_TRUCK is dispatched for FIRE and for ACCIDENT: 100 % where units exist.
- F3 coverage: every edge of the largest component has an ambulance within 10 min free-flow travel of some hospital depot; list the rest.

Results are reported as measured. Failures stay failures.

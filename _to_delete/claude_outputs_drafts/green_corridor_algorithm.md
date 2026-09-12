# The Green Corridor Algorithm

Emergency-vehicle preemption for the Vijayawada corridor, specified
against a catalogue of 85 documented hazards drawn from MUTCD 11th
Edition Part 4, NTCIP 1211, NEMA TS2, NCHRP Synthesis 507, ITE RP-025D,
TTI reports 1439-9 and 0-4657-1, FHWA-JPO-05-010 and FHWA-HOP-24-019,
NTSB HAR-96/02 (Fox River Grove), and the EVP/EVTSP research literature.

Two things this document is careful about. Every mechanism below names
the hazard it answers, so the design can be checked against the
catalogue rather than admired. And every hazard the design does *not*
answer is listed as such in §6, because a traceability matrix with no
gaps in it is a matrix nobody checked.

---

## 1. What the algorithm is for

A "green corridor" here is not a green wave. It is emergency-vehicle
preemption coordinated across a *route* rather than decided
independently at each junction — the sense the codebase has used since
M2, where `signal_controller/arbiter.py` reserved rung 3 of the
arbitration ladder for "green corridor preemption" and left it
deliberately empty.

The per-junction design is what the field deploys, and it fails in two
structural ways that no amount of per-junction cleverness fixes.

**G2 — the emergency vehicle is blocked by the traffic its own
preemption released.** A junction that reacts when the vehicle enters
detector range gives a green to an approach whose queue then has to
discharge with the vehicle behind it. The remedy is not a longer green;
it is an earlier one, and how much earlier is a route-level quantity.

**D11 — adjacent junctions grant conflicting vehicles.** One unit on the
arterial, another on a cross street, arriving at neighbouring junctions
seconds apart: junction *n* grants A, junction *n+1* grants B, and A is
released into a junction being held against it. Neither controller is
wrong on its own information. Arbitration has to happen where both
requests are visible.

---

## 2. The authority model, which decides everything else

The engine **proposes**; it never commands. Every plan it produces is
checked by `interlocks.check` unchanged, and the safety kernel can
refuse it. NTCIP 1211 draws the same line for the same reason: the
Priority Request Generator asks, the Priority Request Server decides,
and the Coordinator retains authority — "a CO cannot be commanded to
service a priority request".

From that follows the single rule the implementation is built around:

> **Never propose a plan the interlocks will reject.**

This is forced, not stylistic. `arbiter.tick` answers a failing
`interlocks.check` by commanding all-red. For a fixed-time plan that is
correct — nothing sits below it. For a preemption plan it is the worst
available outcome: the emergency vehicle arrives at a junction in solid
all-red, with the cross street stopped too, and the adaptive controller
that could have run the junction perfectly well is never asked.

So rung 3 treats a rejected preemption as a **denial, not a fault**: the
arbiter raises a `preempt_denied` event, calls back into the requester,
and falls through to the strategy below as if no request had been made
(H1 requires that a denied emergency request never be silent). And the
engine pre-computes every rejection reachable from its own proposals —
minimum green (I3), pedestrian clearance (I4), maximum wait (I5), the
preemption-hour budget — holding or releasing rather than proposing
something that would bounce.

```
                         ┌──────────────────────────────┐
   detector / CV feed ──▶│ 1  hardware & cabinet faults │──▶ failsafe
                         ├──────────────────────────────┤
                         │ 2  manual override  (absent) │
                         ├──────────────────────────────┤
                         │ 3  GREEN CORRIDOR ENGINE     │──▶ interlocks
                         │      propose() -> plan|None  │      │
                         └──────────────┬───────────────┘   pass│fail
                                        │                       │
                                  None  │                    DENIAL
                                        ▼                       │
                         ┌──────────────────────────────┐◀──────┘
                         │ 4  A-CA-MP adaptive control  │
                         ├──────────────────────────────┤
                         │ 5  fixed-time fallback       │
                         └──────────────────────────────┘
```

---

## 3. The algorithm

### 3.1 Ingestion — every request is untrusted (E13, H2)

A request asserts identity, position, speed, intended movement and
observation time. It **does not** assert its own class, and it does not
assert an ETA.

```
submit(report):
    priority ← authorization_table[report.vehicle_id]      # E13
    if priority is None: count(unauthorized); reject       # H2 audit trail
    track ← tracks[vehicle_id] or new
    track.smoothed_speed ← EWMA(report.speed, half_life)
    track.previous_route ← track.report.route              # passage vs reroute
    track.report ← report
```

Class comes from an authorization table because a homemade infrared
transmitter reproducing a vendor's pulse protocol is demonstrated, not
hypothetical — an Arduino Nano and an LED array — and SAFETEA's criminal
penalty is deterrence, not prevention.

ETA is derived, never asserted, and always from the freshest report.
That is the whole of E10: a corridor system commits to junctions ahead of
the vehicle, so an ETA computed from a report that stopped arriving is
the specific way route-based preemption fails *worse* than the
point-detection kind it improves on.

### 3.2 Per-tick corridor arbitration (D1, D6, D7, D11, G5)

Once per simulation step, before any junction is arbitrated:

```
begin_tick(now):
    decay debt ledger to now
    drop tracks where age > report_ttl_s  or  stopped(now)   # E4, E7, E9, E10
    winners ← arbitrate(now)
    for each junction holding a reservation whose holder is no longer its winner:
        release with the reason that actually applies:
            PASSED         if the junction left the route from the front
            ROUTE_CHANGED  if it left from anywhere else            # G4
            STALE_REPORT   if the track is gone                     # E10
            SUPERSEDED     if another vehicle won it                # D4

arbitrate(now):
    for each junction:
        contenders ← accepted tracks routed through it             # E8 dwell
        coalesce contenders sharing a response_id, nearest represents  # G5
        winner ← min by (priority, first_seen, vehicle_id)         # D1, D7
```

The comparison key is total, and each element earns its place. `priority`
is MUTCD's controllability ordering — *a vehicle that is more difficult
to control supersedes one that is easier*, which is not an urgency
ranking. `first_seen` is NEMA TS2's rule for equal-priority calls.
`vehicle_id` breaks exact ties, because a tie-break that falls through to
dictionary ordering can differ between two runs of the same input, and
D1 is the scenario that produced the 1972 St. Paul fatality.

D6's starvation — a continuously asserted call permanently blocking an
equal-priority one — cannot arise, because arbitration is retaken every
tick and no call is permanent: tracks expire on `report_ttl_s`, dwells on
`max_dwell_s`.

### 3.3 Claiming a junction — lead time, not detection range (E1, E2, G2, G3, G4)

```
should_claim(junction, track):
    eta ← distance / smoothed_speed                  # ∞ if stopped
    lead ← max(base_lead_s,
               transfer_time(junction, target_phase)          # E1
             + queue_ahead / saturation_flow                  # G2
             + (receiving_queue / saturation_flow
                if receiving_occupancy > ρ_couple else 0)     # G3
             + latency_margin)                                # E2
    return eta ≤ min(lead, max_lead_s × confidence_scale)     # G4, E14
```

`transfer_time` is the decomposition E1 is about — right-of-way transfer
is not a constant, it depends where in the cycle the call lands:

```
transfer = max(remaining_min_green, remaining_pedestrian_clearance)
         + yellow + all_red
```

The `max`, not a sum: a pedestrian phase's clearance and its vehicular
minimum green run concurrently, and overstating transfer time is not the
conservative error it sounds like — it makes the engine trigger earlier
and hold longer, spending cross-street service on margin that does not
exist.

**`base_lead_s` is a floor, and leaving it out was a measured mistake.**
The computed sum is a *lower bound on sufficiency* — the least advance at
which the junction could be ready — and triggering on a lower bound
leaves no margin for ETA error. §5 has the measurement.

Low detection confidence scales the commitment down but never refuses
it: degraded detection is the normal condition of a real corridor (E14
GPS in urban canyons, E11 rain and sun on an optical receiver, E4 a truck
breaking line of sight), and a system that only works on clean data does
not work.

### 3.4 The per-junction state machine

```
IDLE ──claim──▶ ENTRY_HOLD ──min green & ped clear──▶ ENTRY_CLEAR ──▶ DWELL
  ▲                  │                                    │            │
  └──────────────────┴────────── release ─────────────────┴────────────┘
```

| state | plan proposed | why |
|---|---|---|
| `ENTRY_HOLD` | hold current phase, `green_s` = remaining pedestrian clearance | I3/I4 forbid leaving yet; **E1 made visible instead of surprising** |
| `ENTRY_CLEAR` | 2-step: current phase + full `yellow_s`/`all_red_s`, then target | A7 — clearance carried verbatim, never shortened |
| `DWELL` | hold target phase, one tick | re-decided every tick, so D6 cannot latch |

The target phase must serve the requested movement **protected**. A
movement served only permissively is refused and counted (A5/D3):
pairing a green the driver must yield on with a confirmation indication
asserting the junction is theirs is worse than no preemption at all.

### 3.5 Release — seven bounded exits (E3, E7, E9, E10, F9, H1)

| reason | trigger | hazard |
|---|---|---|
| `PASSED` | vehicle observed past the junction | E3 — geometric release, not a timeout |
| `ROUTE_CHANGED` | junction dropped from mid-route | G4 |
| `STALE_REPORT` | no report within TTL | E4, E9, E10 |
| `MAX_DWELL` | hard bound reached | E7, F9 |
| `BUDGET` | hour cap would be exceeded | H1 |
| `MAX_WAIT_HEADROOM` | a cross movement nears I5's bound | *(no counterpart in the literature — see below)* |
| `SUPERSEDED` | higher priority took the junction | D4 |

`MAX_WAIT_HEADROOM` has no counterpart in the EVP literature, which is a
comment on the literature rather than on the hazard. This build has a
hard per-movement maximum-wait interlock, so an unbounded hold does not
degrade the cross street gradually — it hits a wall and the junction
fails safe into all-red with the vehicle still approaching.

### 3.6 The cheap half — anticipation and debt

Preemption is expensive at a price fixed by physics: a full right-of-way
transfer, a hold, and a recovery, all paid by the cross street. So the
engine spends as little of it as possible, and hands most of the work to
ordinary adaptive control through two pressure terms:

```
𝒫(p) = P_press(p) + F(p) + A(p) + D(p)

A(p) = λ_A · Σ_m s_m · u_m · q̂_m           u_m ∈ [0,1], arrival imminence
D(p) = λ_D · Σ_m s_m · min(1, d_m / T)     d_m = decayed seconds held on red
```

`A(p)` biases a junction on an active route toward clearing the vehicle's
path *before* it arrives — G2's requirement, achieved with no preemption
budget spent and no cross street held on red. It is a **multiplier on
discharge benefit**, not an additive bonus, so a movement with nothing
waiting scores zero however imminent the arrival.

`D(p)` records what preemption did spend, per movement, and repays it.
Unlike Reno's five exit strategies — all one-shot choices of which phase
to return to, after which the controller forgets the preemption happened
— repayment is continuous, proportional and self-terminating. The
saturating ratio is not decoration; §5 has what happened without it.

Both terms are identically zero when nothing is responding, so the
controller is bit-for-bit its M5 self on every ordinary tick.

---

## 4. What is structurally impossible here

Some hazards are not handled; they cannot occur.

**A1/A2, the yellow trap** — the highest-severity hazard in the
catalogue. It needs one direction's through movement carried green across
a transition while another terminates. `TraCICabinet` builds every
phase's state from that phase's movements alone with every other index
red, shows the departing phase's greens as yellow with everything else
red, then a full all-red. That is exactly WisDOT's prescribed mitigation
("exit all phases … before initiating the track clearance phase"), applied
unconditionally to every transition. Checked directly over every ordered
phase pair at all seven junctions.

**A6, yellow-to-green revert** — the runner's transition sequencer has no
path from yellow back to the phase it is leaving.

**A7, truncated clearance** — the entry plan carries `cfg.yellow_s` and
`cfg.all_red_s` verbatim, and `clearance_intervals_present` would reject
anything less.

**B2, pedestrian change-interval truncation** — MUTCD *permits* it and
NCHRP 507 found 75% of agencies do it. Interlock I4 has refused it for
any requester "including preemption" since M2, so the permission was
never available here. What M7 adds is that the deferral is now
*deliberate and counted* rather than incidental.

**A12, preempt request during startup** — MUTCD enumerates five permitted
responses and requires the design to pick one. `arbiter.tick` returns on
`readback.booting` before rung 3 is consulted, which is "run normal
startup first". Chosen, not defaulted.

---

## 5. What the benchmark measured, including two failures

Five arms, paired on the ten evaluation seeds, medium demand. `reactive`
is per-junction preemption on a fixed 300 m range — what the field
deploys, and the arm that actually has to be beaten. Beating
no-preemption only shows that preemption works, which has been known
since the 1970s.

| arm | EV travel (s) | EV time loss (s) | EV stops | person-delay | interlock violations |
|---|---|---|---|---|---|
| none | 1034.2 | 420.7 | 11.7 | 250,516 | 0 |
| reactive | 711.4 | 97.5 | 5.5 | 245,242 | 1 |
| corridor *(v1)* | 837.1 | 223.0 | 11.8 | 313,992 | 0 |
| corridor_noAD | 822.9 | 209.4 | 11.6 | 248,882 | 0 |
| corridor_noD | 798.3 | 184.1 | 10.2 | 245,958 | 0 |

The first corridor arm **lost to plain reactive preemption on both axes
at once** — the emergency vehicle slower and the cross street paying
more. The ablation arms exist to attribute that, and they separate it
cleanly into two independent failures.

**Failure 1 — `D(p)` was not scale-free.** Paired against `reactive`:
`corridor` costs **+68,750 person-delay [+44,892, +92,607]**, significant;
`corridor_noD` costs **+716 [−12,422, +13,853]**, not significant. The
entire cross-street blow-up is the debt term.

The cause, confirmed analytically before the ablation finished: debt
accrued one second per tick for *every* movement a preemption held, so
after a 20-second preemption at `cluster_11608007559_1880441514` — ten
movements, `Σ s_m` = 4.49 — `D(P0)` reached `0.5 × 4.49 × 20 = 44.9`,
against a `pressure_scale` whose median at decision ticks is 0.21 and
whose p90 is 9.8. Three to two-hundred times the entire pressure signal,
at every junction on the route, for the two minutes its half-life takes
to decay.

This is the **third** time this project has hit the same shape: M4's
constant `S(p)`, M5's `lost_time_weight` sized against the full cycle
instead of a phase's share, and now this. A term whose magnitude is set
by something other than traffic, deciding a comparison whose magnitude is
set by traffic. The original docstring even argued from dimensional
analysis — debt in seconds times PCU/s is PCU, the same unit as `s·q` —
which is true and irrelevant: dimensional agreement is not magnitude
agreement.

Fixed by clipping `d_m / T` the way `fairness` clips `wait / max_wait`,
which bounds `D(p)` by `λ_D · Σ_m s_m` regardless of how long anything has
been held. `T` is one phase's share of the nominal cycle: **debt saturates
once a movement has lost a full green's worth of service.**

**Failure 2 — the lead-time trigger under-claimed.** With both pressure
terms zeroed so only the trigger differed, `corridor_noAD` cost the
emergency vehicle **+111.5 s of travel time [+93.5, +129.5]** against a
plain 300 m fixed range.

The computed sum is a lower bound on sufficiency, and it is small in the
common case because its dominant term collapses to yellow plus all-red
once the current phase has served its minimum green — about 8 s, roughly
180 m at emergency speed, well inside the 300 m baseline and far inside
the 1,600–2,300 ft real installations use. Fixed with `base_lead_s` as a
floor under the computed terms, which still *raise* the lead where a
queue must be dissipated or a short downstream link cleared.

**After both fixes**, paired against `reactive` (n=10, 95% CI):

| | mean diff | 95% CI | |
|---|---|---|---|
| EV travel time | **−28.2 s (−4.0%)** | [−53.3, −3.1] | significant |
| EV time loss | **−28.3 s (−29.0%)** | [−53.4, −3.1] | significant |
| EV stops | −1.8 (−32.7%) | [−3.7, +0.1] | marginal |
| person-delay | +2,493 (+1.0%) | [−17,439, +22,426] | not significant |

The corridor engine beats field-standard reactive preemption on
emergency-vehicle travel time, and the cross street pays no measurable
price. Zero interlock violations across all 30 corridor runs (the
reactive arm had one), and zero denied-by-interlock — the "never propose
a plan that will be rejected" invariant held in the simulator as well as
in the property test. Of 280 reservations, **239 released on `PASSED`**,
40 on `STALE_REPORT`, 1 on `MAX_DWELL`.

**And the negative result.** `corridor` against `corridor_noAD` — same
preemption policy, `A(p)` and `D(p)` on versus off — gives +8.4 s EV
travel [−6.8, +23.6], +0.5 stops [−1.1, +2.1], −3,360 person-delay
[−27,054, +20,334]. **Every interval contains zero.** The entire measured
win comes from the lead-time trigger; the two pressure terms contribute
nothing detectable here in either direction.

That is stated rather than tuned away. Three readings fit the data and
this experiment cannot separate them: the terms are worthless here;
`λ_A` and `λ_D` are simply untuned, being the only parameters in
`AcampConfig` that never went through CMA-ES; or medium demand is too
easy for them, since `A(p)`'s job of dissipating the queue ahead is
largely already done by 20 s of lead time. The honest claim for this
milestone is the lead-time trigger and the safety machinery, not the
pressure terms.

---

## 6. Traceability, honestly

**Legend** — `STRUCT` cannot occur by construction · `HANDLED` mechanism
in code, tested · `PARTIAL` mechanism exists, incompletely ·
`UNEXERCISED` implemented but this network cannot test it · `N/A` not
applicable to this build · **`GAP` not addressed**

### A — signal display and driver expectancy

| | status | mechanism |
|---|---|---|
| A1 yellow trap, entry | STRUCT | clean all-red break; every phase pair checked |
| A2 yellow trap, exit | STRUCT | same |
| A3 lagging prot/perm left | N/A | no lagging left phasing in this network |
| A4 trailing overlaps | N/A | no overlaps; phases are disjoint movement sets |
| A5 permissive left not dropped | **FIXED** | cabinet emitted `'G'` for SUMO `'g'`; see §7 |
| A6 yellow→green revert | STRUCT | transition sequencer has no such path |
| A7 truncated clearance | STRUCT | plan carries config values; I2 enforces |
| A8 dilemma zone | **GAP** | min green honoured; no advance detection |
| A9 red clearance omitted on revert | N/A | the MUTCD option is not taken |
| A10 confirmation misread | UNEXERCISED | `Confirmation` SOLID/FLASHING/NONE; no display in SUMO |
| A11 preemption-induced red running | PARTIAL | frequency capped, prompt release; unmeasurable here |
| A12 request during startup | HANDLED | boot branch precedes rung 3 — "normal startup first" |

### B — pedestrians

| | status | mechanism |
|---|---|---|
| B1 call mid-WALK | UNEXERCISED | defer via I4; unit-tested, no ped phases in this net |
| B2 call mid-clearance | UNEXERCISED | never truncated — stricter than MUTCD |
| B3 countdown truncation | N/A | follows from B2 |
| B4 APS output during preempt | **GAP** | no pedestrian signal outputs in this build |
| B5 ped call lost across preemption | **GAP** | no call latching |
| B6 pushbutton during dwell | N/A | no pushbuttons modelled |
| B7 long crossing dominates transfer | HANDLED | ped clearance enters `transfer_time` |
| B8 exit ped service into a second EV | **GAP** | no ped service decisions |

### C — railroad and light rail

All twelve are **N/A**: this corridor has no grade crossing. This is the
most mature failure-mode literature in the field and this build touches
none of it. The architecture accommodates it — `PreemptionClass.RAIL` is
the highest class and wins every arbitration — but advance preempt time,
track clearance greens and the interconnect are absent.

### D — arbitration

| | status | mechanism |
|---|---|---|
| D1 two EVs, conflicting approaches | HANDLED | total-order key; loser gets flashing confirmation |
| D2 two EVs, opposing, same phase | PARTIAL | permissives now yield; EV-to-EV conflict still possible |
| D3 same approach, divergent turns | HANDLED | movement-level requests; protected phase required |
| D4 higher priority mid-sequence | HANDLED | `SUPERSEDED`, re-entry through full clearance |
| D5 second call during exit | HANDLED | re-arbitration every tick; no latched call |
| D6 equal-priority starvation | HANDLED | bounded dwell + TTL + per-tick re-arbitration |
| D7 precedence ambiguity | HANDLED | all 30 ordered class pairs bench-tested |
| D8 class assignment | HANDLED | explicit ordering with gaps for local classes |
| D9 transit priority vs EVP | STRUCT | one total order; no separate input numbering to misconfigure |
| D10 bus re-serve timer | N/A | no NEMA bus preemptor inputs; every denial counted |
| D11 corridor cross-conflict | HANDLED | one arbitration per corridor per tick |
| D12 confirmation with 3+ EVs | **GAP** | one-bit confirmation; no directional heads |

### E — detection and request integrity

| | status | mechanism |
|---|---|---|
| E1 outrunning the preemption | HANDLED | transfer time in lead; `ENTRY_HOLD`; flashing confirmation |
| E2 request latency | HANDLED | `latency_margin_s` |
| E3 release latency | HANDLED | geometric release on passage |
| E4 detection dropout | HANDLED | `report_ttl_s` rides through short gaps |
| E5 "first light" | PARTIAL | engine responds correctly; detection is perfect here |
| E6 light trespass | N/A | exact detection; movement-level requests would mitigate |
| E7 stuck emitter | HANDLED | `max_dwell_s` + stopped-vehicle release |
| E8 spurious turning call | HANDLED | `acceptance_dwell_s` |
| E9 requests, never arrives | HANDLED | `ROUTE_CHANGED` / `STALE_REPORT` |
| E10 stale ETA | HANDLED | ETA re-derived; no coasting |
| E11 weather false triggers | PARTIAL | `confidence` scales commitment; not exercised |
| E12 acoustic false triggers | N/A | not a detection channel here |
| E13 spoofing | HANDLED | authorization table; counted for audit |
| E14 GPS urban canyon | HANDLED | `confidence` scales lead and dwell, with a floor |
| E15 detector degradation | **GAP** | no observed-range trending |
| E16 receding detection | STRUCT | route is directional; a passed junction leaves it |

### F — recovery and transition

F1, F4, F5, F7 are **N/A**: they concern coordinated fixed-cycle
controllers re-acquiring an offset, and A-CA-MP runs free. F2's
recommended exit strategy for queue-bound intersections is "return to
free operations", which is what happens here by construction — with
`D(p)` making the return targeted rather than uniform. F3 is **MEASURED**
(debt ledger, per movement). F6 is **PARTIAL** — `A(p)` is corridor-aware
but ripple is not measured. F8 is **HANDLED** and F9 **HANDLED**
(`max_dwell_s`).

### G — network effects

| | status | mechanism |
|---|---|---|
| G1 spillback from over-long green | HANDLED | `max_dwell_s`; `gate(ρ)` in pressure |
| G2 preemption blocks the EV's own path | HANDLED | queue discharge in lead time; `A(p)` |
| G3 short-link coupling | HANDLED | downstream clearance in lead time |
| G4 junctions never traversed | HANDLED | route-aware; `max_lead_s`; `ROUTE_CHANGED` |
| G5 multi-unit response | HANDLED | coalescing by `response_id` |
| G6 diversion to parallel routes | PARTIAL | motivates `D(p)`; not measured |

### H — operational and policy

| | status | mechanism |
|---|---|---|
| H1 frequency caps | HANDLED | rolling-hour ledger makes a dormant interlock live |
| H2 non-emergency use | HANDLED | authorization table + audit counters |
| H3 logging | PARTIAL | reasons and counters; not the full per-interval record |
| H4 change management | N/A | organisational |
| H5 maintenance regime | N/A | organisational |
| H6 bench acceptance testing | PARTIAL | D7's pairwise matrix is automated; the rest is not |
| H7 multi-agency governance | N/A | organisational |
| H8 driver training | N/A | `Confirmation` exists to support it |
| H9 equity — who bears the cost | HANDLED | per-movement debt distribution, never a mean |
| H10 backup power | N/A | no power model |

**Count:** 32 handled, 7 structural, 6 partial, 3 unexercised, 8 gaps,
29 not applicable.

---

## 7. Limitations, stated rather than buried

- **Detection is perfect.** TraCI gives exact position, speed and route,
  so the benchmark exercises the engine's control behaviour and not its
  detection robustness. Every mechanism for E4, E5, E6, E11, E12, E14 and
  E15 is present and untested against real degradation. Injecting
  degraded reports is the obvious next experiment; it was not done here
  so the numbers are not flattered by a noise model chosen by whoever
  also wrote the controller.
- **No pedestrian phases** exist in this network, so all of category B is
  unit-tested against synthetic junctions and unexercised by any corridor
  run.
- **No railroad crossing**, so all of category C is out of reach.
- **Six of seven junctions have two phases**, so multi-phase arbitration
  is thinly exercised.
- **A safety bug was found in the existing build on the way in.**
  `TraCICabinet` wrote `'G'` for every green movement including the ones
  SUMO's network marks `'g'`, which removed the yield obligation from
  nine permissive movements across four junctions, every one of which
  conflicts with a protected movement in its own phase. Measured on
  identical net, demand and seeds: 5 junction collisions across three
  seeds under the old string, 0 under SUMO's own program, 1 after the
  fix. The M3/M4/M5 numbers in `PROGRESS.md` were all measured under the
  old behaviour and have not been re-run; that is a caveat on those
  tables, not a correction to them.

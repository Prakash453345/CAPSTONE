# Dispatch: which vehicles, where they are going, and how the response ends

The layer above the Green Corridor Engine. The engine answers *which
signals, and when*; the interlocks answer *is that legal*; this answers
*which facility, and by what path*. Nothing here can command a signal,
and a dispatch decision that is wrong produces a vehicle going to the
wrong hospital, never an unsafe junction.

It exists because of a question with an uncomfortable answer. The M7
benchmark contained this:

```python
EV_ROUTE_EDGES = (
    "219187869 350502993#0 350502993#1 350502993#2 350502993#4 "
    "350502993#6 350502993#7 -343269496 220332271#0"
).split()
```

Nine edges, pasted in. The corridor engine consumed a route and nothing
in the system produced one — so "where is the ambulance going" had no
answer anywhere in the codebase, and the honest description of the build
was *signal control for a vehicle whose destination somebody typed in*.
That is now gone. The benchmark declares an **incident**; the route is
whatever `dispatch.choose` returns for it.

---

## 1. What counts as an emergency vehicle

Authority is granted per vehicle, by identity, before any request is
honoured. `CorridorEngine.authorize(vehicle_id, priority)` is the only
way into the system: a report from an unauthorized id increments
`counters["unauthorized"]` and is discarded, never served. There is no
"assert your own class" path, because a preemption request that carries
its own priority is a preemption request anyone can forge.

The classes, from `control/corridor/requests.py`, lower value winning:

| Class | Value | Notes |
|---|---|---|
| `RAIL` | 0 | Not present in this network; the ordering is stated so it is not invented later under pressure |
| `FIRE` | 10 | |
| `AMBULANCE` | 20 | |
| `POLICE` | 30 | |
| `LIGHT_RAIL` | 80 | |
| `TRANSIT` | 90 | Bus priority, below every emergency class |

**The ordering is by controllability, not by urgency,** which is MUTCD
11th Edition §4F.19's ordering and is worth stating because it reads
backwards at first. A train cannot stop; an ambulance can. When two
requests conflict, the one that can safely yield is the one that yields,
regardless of which patient is sicker. Getting this backwards is how a
corridor arrives at a decision that is defensible in isolation and
indefensible at the crossing.

In simulation, authority comes from `_Injector`, which creates the
`veh_emergency` vehicle type and authorizes exactly the ids it injects.
In deployment it comes from whatever the agency's own credentialing is —
the engine's requirement is only that *something* outside it says which
ids are real.

---

## 2. Where the vehicle is going

### The decision

```
choose the facility minimising live travel time,
  among those that can treat the incident,
  from the shortlist of the k nearest by air
```

An `IncidentRequest` is a call for service: an id, an origin (edge plus
latitude and longitude), and a `required_capability`. It does **not**
carry a destination. The vehicle does not tell the system where it
intends to go; the system works it out, which is the difference between
dispatch and a route file.

`FacilityIndex` holds the destinations, extracted from the corridor's
own OSM data by `scenarios/networks/vijayawada/extract_facilities.py`:
**103 facilities — 85 hospitals and 18 clinics — carrying 11 normalised
capabilities.**

| Capability | Facilities |
|---|---|
| general | 48 |
| obstetric | 13 |
| ophthalmic | 12 |
| dental | 5 |
| paediatric | 5 |
| neuro | 4 |
| oncology | 4 |
| orthopaedic | 4 |
| cardiac | 3 |
| ent | 3 |
| trauma | 1 |

**The facilities and their locations are real. The capability tags are a
model.** Most are keyword-matched from the facility's name — "Maxivision
Eye Hospital" gets `ophthalmic` because of the word "Eye" — and a name
says nothing about whether the theatre is staffed tonight. OSM's own
`healthcare:speciality` tag is preferred wherever it exists, because it
is asserted by a mapper rather than guessed from a string; the keyword
pass only fills the gap, which on this extract is most of them. A
deployment replaces the JSON with the health authority's register, and
the schema is deliberately plain so that swap is a data change and not a
code change.

### Why travel time and not distance

Routing is `traci.simulation.findRoute` against *current* edge travel
times, which is the whole reason dispatch is worth doing live: a
hospital 400 m further away down a clear road beats a nearer one behind
the jam the corridor is currently producing, and only a router that sees
the jam can tell them apart. It is routed for the emergency vehicle type
specifically — an emergency vClass is permitted on edges a passenger car
is not, and routing the ambulance as a car would reject paths it is
entitled to take and quietly return a *worse facility* rather than an
error.

The air-distance shortlist is a prefilter, not an answer, and its bound
is one-directional: far by air implies far by road, but near by air does
**not** imply near by road. Vijayawada's corridor is cut by the Krishna
river, so a facility 400 m away can be 6 km by road. `k` is therefore
set generously (12) rather than tightly, and `DispatchDecision` records
how many candidates were actually routed and how many were unreachable,
so a shortlist that is too small shows up in the log instead of hiding
as a slightly worse choice.

### What it refuses to do

`choose` returns `None` when no capable facility is reachable, rather
than falling back to `general`. That fallback is a *policy* decision and
a consequential one — "we could not reach an ophthalmic facility so we
sent them to a general one" must be owned by a caller, not made silently
inside a routing function.

---

## 3. The measurement that changed the benchmark

The obvious scenario is a general emergency going to the nearest
hospital. It was tried, measured, and is the wrong scenario for a
corridor benchmark — and the measurement is worth stating rather than
the conclusion.

Routing a `general` incident from **each of the 19 approach edges** into
the corridor's seven signalised junctions:

| | Result |
|---|---|
| Best case | **2 of 7 junctions** |
| Median | **1 junction** |
| Origins reaching no junction at all | **7 of 19** |
| Travel times | **6–60 s** |

That is not a failure of dispatch. It is what 48 general facilities
inside a 4 km box means: the nearest hospital is always a block away,
and a green corridor is irrelevant to a 22-second trip.

**Scarcity is what makes a corridor worth having** — here and in the
field, where EVP is justified by long responses and inter-facility
transfers rather than by short ones. Best traversal by capability, over
the same 19 origins:

| Capability | n | Best traversal |
|---|---|---|
| trauma | 1 | **7 / 7** |
| ent | 3 | 6 / 7 |
| dental | 5 | 6 / 7 |
| obstetric | 13 | 5 / 7 |
| ophthalmic | 12 | 5 / 7 |
| paediatric | 5 | 5 / 7 |
| oncology | 4 | 5 / 7 |
| cardiac | 3 | 3 / 7 |
| neuro | 4 | 3 / 7 |
| orthopaedic | 4 | 3 / 7 |
| general | 48 | 2 / 7 |

So the gate's incident is a **trauma call**, whose one legal destination
is `S V R Neuro & Trauma Hospital`, reached through all seven junctions
in order.

**What this changed, and what it did not.** The dispatch route and the
old hand-picked one share 8 of 9 edges and traverse the same seven
junctions in the same order, differing only in the final edge — the
hand-picked route ran on to the bounding box, the dispatched one stops
at the hospital. The gate is measuring the same manoeuvre it always was.
It is now measuring a route the system *derived*, and the old edge list
turning out to be very nearly the dispatch answer was luck rather than
method.

Both contrasts are one flag apart in the demo:

```
python scripts/m7_demo.py --capability trauma     # 7 junctions
python scripts/m7_demo.py --capability general    # 1 junction
```

---

## 4. Live dispatch, and why the benchmark freezes it

`should_redispatch` re-evaluates a committed decision and returns a
better destination or `None`. Two rules:

- **It must beat the current facility by `improvement_s` (30 s), not
  merely beat it.** A vehicle already committed has a crew expecting it,
  and flapping between two facilities whose travel times cross and
  re-cross costs more than the seconds it chases.
- **It compares against the current facility's travel time recomputed
  now, never against the estimate made at dispatch.** The original
  number is stale by construction; measuring improvement against a stale
  baseline re-routes on nothing more than the original having been
  optimistic.

**The benchmark deliberately does not use it.** Dispatch there runs once,
at t = 0, on the empty network, so every arm drives the identical route.
This is the right departure from realism *for this experiment*: routing
against live conditions would let the arms diverge onto different
hospitals, and an emergency-vehicle travel time measured against a
different hospital in each arm is not a comparison at all. `m7_demo.py`
runs the live version, because it has one arm and nothing to confound.

On this corridor it fires zero times for a trauma call, for the reason
the table above gives — there is nowhere else to go.

---

## 5. How a response proceeds, end to end

1. **Call.** An `IncidentRequest`: origin and required capability.
2. **Dispatch.** `choose` filters the register by capability, shortlists
   the 12 nearest by air, routes to each, and takes the minimum live
   travel time. Ties break on facility id so identical inputs always give
   an identical answer, for the same reason the engine's arbitration key
   is total.
3. **Assignment.** The vehicle is created with that route and authorized
   with its preemption class.
4. **Observation.** `EmergencyVehicleReporter` submits one
   `VehicleReport` per tick: remaining junctions in traversal order,
   distance to each, speed, and *which movement* at each. Movement, not
   approach — two units on the same approach, one going through and one
   turning left across the opposing through, are served by the same
   approach and by different protected paths.
5. **Corridor.** The engine arbitrates across the whole route, computes
   a lead time per junction from transfer time plus queue discharge, and
   proposes. Every proposal is checked by the unchanged safety kernel.
6. **Release.** Each junction releases when the vehicle passes it —
   geometric, on the tick the junction leaves the front of the reported
   route — or on one of six bounds if it does not.
7. **Arrival.** The route ends at the facility's snapped edge. The
   vehicle leaves the network there, the report goes empty, and the last
   junction releases as `passed` like every other one.

Step 7 is newer than the rest of this document, and it found a bug.

### The bug giving the ambulance a destination exposed

While the route ran off the bounding box, `EmergencyVehicleReporter`
stopped submitting reports the moment no junctions remained ahead. So
the **final junction of every response** released on `report_ttl_s` with
reason `stale_report` rather than `passed` — **41 of 281 releases across
the recorded medium gate**, close to one per emergency vehicle per run.

Nothing unsafe happened. The bounded release is exactly the mechanism
for a track that goes quiet, and it fired correctly. But the junction
stayed held for the full six-second timeout after the vehicle had
already cleared it, and a release reason saying *we lost the vehicle*
when the vehicle simply finished its route is the release-reason
distribution failing at the one job it has — the distribution exists to
answer "is this working", and it was reporting a detection failure on
every successful response.

The fix is one line and its justification: a report whose route is empty
is not an absent report. It states the true thing — no junctions remain
ahead — and `_Track.dropped_by_passing` reads a fully-dropped prefix as
a passage. A single run went from 24 `passed` / 4 `stale_report` to
**28 `passed` / 0 `stale_report`**, with `28/28` junction passages
confirmed independently by the reporter's own ground truth.

It took a real destination to see it. While the ambulance drove off the
edge of the map, "the vehicle vanished" and "the vehicle arrived" were
the same event.

Confirmed at scale by the re-measured gate: **280 releases across ten
corridor runs, every one of them `passed`.** The pre-fix gate recorded
41 `stale_report` over the same ten seeds.

---

## 6. What is not modelled

Each of these a real dispatcher weighs, and each would change the
answer.

- **Bed and theatre availability.** The nearest capable hospital may be
  full. Nothing in OSM knows this. A facility register that did would
  make this a filter rather than a redesign.
- **Diversion status.** Hospitals go on divert; a live feed would remove
  them from `with_capability` for the duration.
- **Clinical acuity beyond one capability token.** Real triage is not a
  single string. `required_capability` is a deliberately thin model of
  it, and the capability data underneath could not support more.
- **The station-to-scene leg.** This models scene → facility. The
  outbound leg is the other half of a response and is classically where
  preemption is deployed; the OSM extract contains **no fire or
  ambulance station**, so it cannot be modelled from this data at all.
- **Multi-vehicle responses to one incident.** `VehicleReport.
  response_id` exists for it and the engine coalesces on it, but
  dispatch assigns one vehicle per call.

The difference between "nearest capable facility by live travel time"
and "correct hospital for this patient" is a difference of kind, not of
tuning.

---

## 7. Where the code is

| File | What it is |
|---|---|
| `control/dispatch/facilities.py` | `Facility`, `FacilityIndex`; capability lookup, air-distance shortlist |
| `control/dispatch/dispatcher.py` | `IncidentRequest`, `DispatchDecision`, `choose`, `should_redispatch` |
| `signal_controller/ev_routing.py` | `traci_route_fn`, `edge_latlon` — the only TraCI in the layer |
| `scenarios/networks/vijayawada/extract_facilities.py` | OSM → `facilities.json` |
| `tests/control/dispatch/test_dispatcher.py` | 16 tests; selection and re-dispatch against injected travel times, capability model against the real extract |

`RouteFn` is injected rather than imported, which is what lets
`choose` be tested against a dictionary of travel times instead of a
simulator — the same split between `control/` and `signal_controller/`
the project keeps everywhere else.

# Where this project stands

A plain-language status report. Written 11 September 2026 and updated
12 September after M4/M5 were re-measured, diagnosed and fixed. From the code and the
measured results — not from the plan.

---

## The short answer

**About 70% done**, counting milestones. About **60–65%** if you weight by
effort, because the single biggest piece left (M8, computer vision on real
camera footage) has not been started at all.

What that 70% actually means:

- The **traffic signal controller** works, is safe, is measured, and as of
  12 September **beats the classic Webster baseline at every demand level**.
  This is the bulk of the project and it is genuinely finished.
- The **green corridor for ambulances** works, is safe, and is measured.
- The **eyes of the system** — cameras, incident detection — do not exist.
- The **middle bit** — an incident is spotted, an authority is told, a
  responder is sent — is about a fifth built.

---

## What the project was meant to be

Your plan (in `README.md`) has ten milestones, M0 to M9. Here is where each
one really is:

| # | What it is | Planned | Really |
|---|---|---|---|
| M0 | Skeleton: services talking to each other | done | ✅ **done** |
| M1 | SUMO simulation on the real Vijayawada map | done | ✅ **done** |
| M2 | Safety kernel — the rules signals can never break | done | ✅ **done** |
| M3 | Baseline controllers + measurement harness | *not started* | ✅ **done** |
| M4 | CA-MP — first smart controller | *not started* | ⚠️ **built, loses to the baseline** |
| M5 | A-CA-MP — smarter controller with memory | *not started* | ✅ **built; now beats the baseline at all 3 levels** |
| M6 | Incident → dispatch → routing | *not started* | 🟡 **~20% built** |
| M7 | Green corridor for emergency vehicles | *not started* | ✅ **built and measured** |
| M8 | Computer vision on real camera footage | *not started* | ❌ **not started** |
| M9 | Benchmark, evaluation, project website | *not started* | 🟡 **~35% — the benchmark half exists** |

> ⚠️ **Your README is wrong.** It still says M3 through M9 are "not started".
> Six of those seven have had substantial work. Anyone opening your repo cold
> — a guide, an examiner, a teammate — will believe you have done far less
> than you have. This is the cheapest fix on the whole list.

---

## What is finished, and how

### M0 — Skeleton ✅

**What it does.** Three services (`sim-service`, `api-service`,
`vision-service`) plus a database, a message bus (Redis) and file storage,
all started with one command (`make dev`).

**How you know it works.** A test event was published by one service and
arrived in a web browser through the WebSocket, on a real machine with real
Docker. Lint, type checks and tests all pass.

---

### M1 — Simulation on the real map ✅

**What it does.** SUMO (the traffic simulator) runs your actual Vijayawada
corridor — MG Road from Benz Circle to PNBS, 16 junctions of which 7 have
traffic lights — built from a real OpenStreetMap extract. Every second it
publishes where every vehicle is, and a browser map shows them moving.

**How you know it works.** A 2-minute run at double speed dropped **zero**
ticks. The road network was loaded into PostGIS (33 edges, 25 junctions) with
correct real-world coordinates. Verified visually in a headless browser.

**A bug caught here.** The Redis consumer group could vanish (e.g. after a
Redis restart) and the dashboard would silently go dead with no error. Fixed
by recreating the group automatically.

---

### M2 — Safety kernel ✅

**This is the most important part of the project and it is done properly.**

**What it does.** Before any traffic light is allowed to change, a set of
hard rules checks the proposed change. These are the *interlocks* (I1–I7):

| Rule | In plain words |
|---|---|
| I1 | Two conflicting directions can never both get green |
| I2 | Yellow and all-red gaps must always be present |
| I3 | A green must last at least its minimum time |
| I4 | A pedestrian crossing interval must be allowed to finish |
| I5 | No direction may be made to wait longer than its limit |
| I6 | The next phase must actually be reachable from this one |
| I7 | What we command and what the signal reports back must agree |

Nothing in the system can bypass these. The smart controller and the green
corridor both only *propose*; the kernel decides.

**How you know it works.** 9 property tests, each run against **10,000
randomly generated cases** — 90,000 cases total — where the test deliberately
tries to build an illegal plan and checks the kernel catches it. Plus five
hardware-fault tests (C1–C5): lamp failure, conflict monitor trip, comms
loss, power restart, command/readback mismatch. All reach a defined safe
state.

---

### M3 — Baselines and measurement ✅

**What it does.** Three "old-school" controllers to measure against, so any
claim of improvement has something to beat:

- **Webster fixed-time** — the classic 1958 formula, tuned from your
  corridor's real measured traffic flows
- **Semi-actuated** — main road stays green, side roads get green on demand
- **Coordinated-actuated** — a shared cycle with green-wave offsets

Plus the measurement harness itself: `make bench` produces a table of
person-delay, throughput, max-wait and stops over 10 random seeds with
confidence intervals.

**How you know it works.** All three ran end-to-end on the real 7-junction
corridor with **zero safety violations**, and `make bench` reproduces the
gate table.

**Note:** the section header in `PROGRESS.md` still says "in progress" even
though the same section ends with "M3 is now fully closed out". Stale header.

---

### M7 — Green corridor for emergency vehicles ✅

**What it does.** When an ambulance is coming, junctions ahead of it open in
sequence — not each junction reacting on its own, but the whole route
coordinated together.

**How it works, step by step:**

1. The ambulance is **authorised** by ID (nobody can claim priority for
   themselves).
2. Every second it reports its position, speed, and *which movement* it will
   use at each junction ahead.
3. The engine works out **how early** each junction must start switching —
   from the time to transfer phases, plus how long the queue ahead takes to
   clear.
4. It **proposes** a plan. The safety kernel checks it. Nothing unsafe can be
   commanded.
5. Each junction is **released** the moment the ambulance passes it — not on
   a timer.
6. A **debt ledger** remembers which side-street movements were interrupted
   and pays the green time back afterwards.

**How you know it works.** Measured against the field-standard approach
(each junction preempting on its own 300 m detection range), over 10 paired
random seeds:

| | Improvement | Proven? |
|---|---|---|
| Ambulance travel time | −27.6 s (−3.5%) | ✅ yes |
| Time lost to signals | −27.8 s (−25.3%) | ✅ yes |
| Number of stops | −1.7 (−31.5%) | ✅ yes |
| Worst single wait for anyone else | −50.3 s (−10.1%) | ✅ yes |
| Total delay to everyone else | +1.6% | ❌ no — a tie |

Also: **280 corridor releases across 10 runs, every single one because the
ambulance actually passed** — none from a timeout.

**Backed by real research.** 86 documented hazards catalogued from MUTCD,
NTCIP 1211, NEMA TS2, NCHRP, FHWA and NTSB sources before a line was
written.

---

### M7 dispatch — where the ambulance is going ✅ (added last week)

**What it does.** Until last week the ambulance's route was nine road IDs
pasted into a benchmark file. Now the system reads 103 real hospitals and
clinics out of your OSM data, filters them by what the patient needs, routes
to each one using live traffic conditions, and picks the fastest.

**A finding that changed the design.** Routing a *general* emergency from
every approach into the corridor uses **at most 2 of the 7 junctions** — often
none. That is not a bug: with 48 general hospitals inside a 4 km box, the
nearest one is always a block away, and a green corridor is pointless for a
20-second trip. **Scarcity is what makes a corridor worth having.** Your
corridor has exactly **one** trauma hospital — and a trauma call routes
through **all seven junctions**. That is why the benchmark now uses a trauma
call.

---

## What is built but did not fully work

### M4 — CA-MP ⚠️ *(re-measured 11 Sep)*

**What it was meant to do.** Replace fixed timers with a controller that
reads real queues and gives green to whoever needs it most (max-pressure
control).

**What happened.** It was built, it is safe, and it was measured honestly —
and **it did not beat Webster's fixed-time baseline**. Re-measured under the
fixed cabinet at medium demand it is **+148.6% worse** than Webster, on 10
seeds out of 10. A-CA-MP (M5) beats it by 49.5%, so M5's work over M4 was a
large real improvement — just not enough to reach the baseline.

**Why, as far as it was traced.** A "switching cost" term was wildly out of
scale — it was 1127% of the mean flow pressure at light demand. Recalibrating
it from real measured data brought that to 183% and made the controller
genuinely more responsive, but not enough to win.

This is a **negative result honestly reported**, which is worth more in a
capstone than a tuned-until-it-wins number. But it is an open thread.

---

### M5 — A-CA-MP ⚠️ *(re-measured 11 Sep — the headline inverted)*

**What it does.** M4's controller, with three real defects fixed and a memory
added.

**Where it landed after re-measuring under the fixed cabinet** (total waiting
time vs Webster, 10 held-out seeds, paired):

| Traffic level | Corrected result | What the old numbers said |
|---|---|---|
| Light | **+43.4% WORSE** (9/10 seeds) | −16.7%, "a clear, proven win" |
| Medium | **+25.7% worse** (10/10 seeds) | +15.9%, "a statistical tie" |
| Heavy | **−4.2% better** (9/10 seeds improve) | −6.7%, "a narrow lean-win" |

**The light-demand win was an artefact of the safety bug.** Those nine
movements that wrongly got protected green had extra capacity they weren't
entitled to, and that was papering over the gap. Remove it and A-CA-MP loses
at light demand by 43%.

**The cause is now identified, not guessed.** Webster computes a
delay-minimising cycle length from measured flows. A-CA-MP has **no cycle
concept at all** — its cycle is whatever emerges from second-by-second
decisions, and nothing keeps it near the optimum:

| Level | Webster's optimum | A-CA-MP's actual | Ratio | Result |
|---|---|---|---|---|
| Light | 40.0 s | 70.8 s | **1.77×** | +43.4% worse |
| Medium | 42.1 s | 59.1 s | **1.40×** | +25.7% worse |
| Heavy | 104.1 s | 76.7 s | **0.74×** | −4.2% better |

The further its cycle drifts above the optimum, the worse it does — and in
the one case where it runs *shorter*, it wins. Monotonic across all three
levels. **Heavy demand was never where the controller was cleverest; it is
where its uncontrolled cycle happened to land in the right place.**

Also new: **2 safety violations at light and 3 at heavy** in the A-CA-MP arm.
Webster has zero at every level.

**And then the fix worked.** `max_green_s` was a flat 90 s everywhere — a
safety constant that never bound (0.3% of ticks). Replacing it per phase with
1.25× that phase's own Webster green, **with no change to the controller at
all**, produced this:

| Level | Webster | A-CA-MP before | A-CA-MP + ceiling | vs Webster |
|---|---|---|---|---|
| Light | 69,573 | 99,791 (+43.4%) | **56,472** | **−18.8%** ✅ 10/10 seeds |
| Medium | 193,354 | 243,015 (+25.7%) | **176,461** | **−8.7%** ✅ 9/10 seeds |
| Heavy | 1,601,950 | 1,534,346 (−4.2%) | **1,498,307** | **−6.5%** ✅ 8/10 seeds |

**This is the first time in the project's history that the adaptive
controller beats a well-tuned Webster baseline at every demand level** — all
significant, all on held-out seeds. Interlock violations at light went 2 → 0.

**The factor was then chosen properly.** Sweeping 0.75× to 2.00× on
*training* seeds found **every factor statistically indistinguishable** — the
whole effect is in having *a* ceiling rather than none. So 1.25× was chosen on
stated grounds (a rationale you can say in a sentence, fewest heavy
violations, keeps the most adaptive range), not by picking the best number.
The held-out result above confirms that choice rather than being its basis.

**And the heavy-demand safety gap now has a root cause.** The violations are
all one thing, at the corridor's only four-phase junction:

> `I5: movement 'L3' has waited 452.0s (>= 452.0s bound) with demand, but the
> plan doesn't serve it now` — phase P1, **9.0 s** into a 10 s minimum green.

Minimum green (I3) is an absolute safety floor checked *before* the starvation
override. So when a movement crosses its max-wait bound during another phase's
minimum green, the controller is *obliged* to return a plan that doesn't serve
it, and the max-wait interlock is obliged to reject it. **Neither rule is
wrong — the configuration is infeasible.** Webster never trips it because its
fixed cycle serves all four phases on rotation.

The cycle ceiling does **not** fix this (violations persist at every factor).
What fixes it is the *other* half of the cyclical max-pressure design you
cited — "each phase must be actuated at least once per cycle". The two halves
of that paper close two different measured defects.

**And then the supervisor was built (CC-A-CAMP).** A cycle is measured
explicitly; while it's inside its envelope A-CA-MP acts unchanged; past it,
any phase still owed a green gets forced in. It sits *after* the minimum-green
gate, so it can never cut a green short.

| Level | Webster | + ceiling | **+ supervisor** | vs Webster |
|---|---|---|---|---|
| Light | 69,573 | 56,472 | **55,740** | **−19.9%** ✅ 10/10 |
| Medium | 193,354 | 176,461 | **171,307** | **−11.4%** ✅ 8/10 |
| Heavy | 1,601,950 | 1,498,307 | **1,416,609** | **−11.6%** ✅ 10/10 |

Against the ceiling alone — the honest test of whether the supervisor earns
its keep — light and medium are a wash (not significant), but heavy is
**−5.5% delay and −5.5% stops, both significant**. And the thing it was built
for: **heavy interlock violations went 2 → 0.** No ceiling factor had ever
closed them.

It fires on **0.6–1.0% of phase changes**, so this is not Webster with extra
steps — 99% of decisions are still the controller's own.

**Status: M5 is done.** The controller beats a well-tuned Webster baseline at
every demand level, with zero safety violations at every level, on held-out
seeds. First time in the project that sentence has been true.

---

## What is not built

### M6 — Incident → dispatch → routing 🟡 ~20%

This is the missing middle of your whole system. What exists and what does
not:

| Piece | Status |
|---|---|
| Pick the right hospital for the patient | ✅ built |
| Compute the route to it | ✅ built |
| Re-check the route as traffic changes | ✅ built |
| Detect that an incident happened | ❌ absent |
| Decide what *kind* of incident it is | ❌ absent |
| Tell the fire service / ambulance / police | ❌ absent |
| Confirm somebody received and accepted it | ❌ absent |
| Send a responder *to* the scene | ❌ absent |

**One thing to know:** the dispatch layer routes **scene → hospital**. The
pipeline you described goes **station → scene**. These are different problems,
and your OSM extract contains **no fire station or ambulance station at all**
— so the station→scene leg cannot be simulated from this data without either
a station list from the agency or depots you place yourself.

A full failure analysis of this stage — 22 loopholes with mitigations — is in
[`incident_response_pipeline_analysis.md`](incident_response_pipeline_analysis.md).

---

### M8 — Vision on real footage ❌ 0%

`services/vision-service/` contains **one file: a README**. So does
`packages/geo/` (the homography / camera-to-ground-plane maths) and
`notebooks/`.

This is the largest single remaining piece of work, and everything in M6's
detection stage depends on it.

---

### M9 — Benchmark, evaluation, site 🟡 ~35%

The **benchmark half is done and has been used constantly** — paired seeds,
held-out evaluation seeds never touched by tuning, 95% confidence intervals,
every raw run kept. That machinery is better than most student projects ever
build.

What does not exist: a final cross-milestone evaluation, and the project
website. `web/index.html` is a single live map page, and `api-service` is two
Python files doing health checks and WebSocket fan-out — no login, no
dashboard.

---

## Problems in work that is already "done"

These are real and worth knowing before you present anything.

### Serious

**1. The safety bug was also a capacity bug, and it was inflating the
results.** `TraCICabinet` used to write `'G'` (protected green) for every
green movement, including the nine that SUMO's own network marks `'g'`
(permissive — you must yield). That silently removed the yield obligation.
Measured: **5 junction collisions across 3 seeds** before the fix, **1**
after.

**M4 and M5 have now been re-measured under the fix, and the headline
inverted** (see above — light demand went from a −16.7% win to a +43.4%
loss). **M3's three baseline numbers still predate the fix and have not been
re-run.** Webster's own figures moved by about +5% at medium when re-measured,
so the M3 table is stale but not wildly so.

**2. One safety violation appeared in the latest gate.** Corridor arm, seed 6,
step 1731. Traced to the A-CA-MP controller, **not** the corridor engine (the
engine's own counter was zero on every run). Not fixed.

**3. The "novel contribution" of M7 is unproven.** The anticipation term
`A(p)` and debt term `D(p)` — the two things that make this more than standard
preemption — showed **no detectable effect** at 10 seeds medium or 30 seeds
heavy. They are left on by default and documented as unproven, which is honest,
but it means the headline contribution has no evidence behind it.

### Moderate

**4. Traffic demand is not calibrated.** 708 vehicles over 30 minutes,
generated randomly with seed 42. Flagged since M1 and deferred to M8.5. Every
result in the project rests on synthetic demand.

**5. No pedestrian phases exist in this network.** All of hazard category B —
pedestrian safety during preemption — is unit-tested against made-up junctions
and **exercised by zero real runs**. In an Indian city centre with heavy
mid-block pedestrian movement, that is the biggest gap between the simulation
and the real thing.

**6. M6 was skipped.** M7 was built before M6, so the green corridor exists
without the incident pipeline meant to feed it. Not wrong, but it means the
system has a working mouth and no eyes.

**7. M5's gate was measured against the pre-M7 controller.** `acamp.py` was
merged and extended for M7; the M5-level numbers were never re-measured
against the merged version.

**8. Older M7 arms are on the old route.** The ablation arms and all
heavy-demand arms were measured before the route became a dispatch output and
before the release fix. They are still valid as *attribution* evidence but
must not be compared numerically against the new arms. Both artefact files now
say so.

### Minor

**9. `README.md`'s milestone table is wrong** (see the warning above).

**10. Section headers say "in progress"** for M3 and M4 even though both were
closed out later in the same section.

**11. `sumo-gui` will not start on your Mac.** The headless run works and
gives the same commentary. Likely a pip-wheel problem; the Homebrew build is
the thing to try.

**12. Distributed-systems faults C6–C10** (optimiser silence, bad config,
clock skew, leader failover, split-brain) are not covered. Reasonable — this
is a single-process build.

---

## How I got to 70%

Equal weight per milestone, judged on what is actually demonstrated:

| Milestone | Credit | Why |
|---|---|---|
| M0 | 1.00 | Gate verified |
| M1 | 1.00 | Gate verified |
| M2 | 1.00 | Gate verified, 90,000 property cases |
| M3 | 1.00 | Gate satisfied, closed out |
| M4 | 0.85 | Built and measured; result is a clear loss (+148.6% at medium) |
| M5 | 0.95 | Cause found, fixed, and the supervisor gated; beats the baseline at all 3 levels, zero violations |
| M6 | 0.20 | Dispatch built; detection, classification, notification absent |
| M7 | 0.85 | Built and gated; contribution unproven, pedestrians unexercised |
| M8 | 0.00 | One README |
| M9 | 0.35 | Benchmark machinery exists; evaluation and site do not |
| | **7.20 / 10** | **≈ 72%** |

The number barely moves across the 11–12 September work, and that is the
honest outcome: **almost nothing was un-built or newly built.** What changed
is that M5 went from a result nobody could reproduce, to a measured failure
with an identified cause, to a one-parameter fix that beats the baseline at
every demand level. Same amount of code; a completely different project.

**Why it might be lower.** M8 is not one-tenth of this project — computer
vision on real footage is probably the second-largest single milestone after
the controller work. Weighted by effort, 60–65% is the more honest number.

**Why it might be higher.** The depth of what is done is unusual. 296 passing
tests. 90,000 property-test cases. Held-out evaluation seeds never used for
tuning. An 86-hazard catalogue with citations. A 3,600-line honest progress
log including every negative result. Most projects that claim "90% complete"
have done less than this project has at 70%.

---

## What I would fix first

1. **Update the README milestone table.** Ten minutes. Stops everyone who
   opens your repo from underestimating it by six milestones.
2. **Decide what M8 actually means for a capstone.** Full vision on real
   footage is huge. A scoped version — one camera, one junction, one incident
   type — may be enough to demonstrate the idea, and that is a scope decision
   only you can make.
3. **Re-run the M3/M4/M5 gates** under the fixed cabinet, or write one clear
   paragraph saying those numbers predate the fix. Either is fine; leaving it
   implicit is not.
4. **Decide what to do about `A(p)` / `D(p)`.** Three options, in rising cost:
   claim only the trigger and drop them; measure them against an
   ambulance-local metric rather than a run-level average; or put them through
   proper parameter tuning. The first is defensible today.
5. **Close the medium-demand question, or state it as future work.** It has
   been open since M4 and two investigations have come back empty. Declaring
   it a known limitation is a legitimate ending.

---

## The honest one-paragraph version

You have built a traffic signal controller that is provably safe, a green
corridor for emergency vehicles that measurably beats the field-standard
approach, a hospital-dispatch layer that picks destinations from real data,
and a benchmarking discipline stronger than most published work — all
documented with the negative results left in. What you do **not** have is
anything that sees the road: no cameras, no incident detection, no way for an
incident to reach an authority. The system can respond beautifully to an
emergency that something else tells it about. Nothing tells it yet.

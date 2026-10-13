# Where this project stands

A plain-language status report. Written 11 September 2026, updated
12 September after M4/M5 were re-measured, diagnosed and fixed, and updated
again 23 September after the 18 September measurement fixes and the
23 September merge, 24 September after M8 (vision) was built and
measured, and 25 September after M8 was reviewed for bugs, every M8 test
re-run, and the controller's handling of camera doubt fixed. From the code and the measured results — not from the plan.

---

## The short answer

**About 81% done**, counting milestones. About **75%** if you weight by
effort: M8 (vision) now exists and is measured on a digital twin, but has
not seen Vijayawada footage or an Indian-traffic detector.

What that means as of 24 September:

- The **traffic signal controller** works, is safe, and cuts person-delay by
  **25–31% against a tuned Webster baseline** at every demand level, with
  zero safety violations. The caveat: since the 18 September fixes, the last
  piece M5 added — the cycle supervisor — shows no measurable benefit over
  the same controller without it, and every gain recorded that day came from
  correcting timing inputs rather than from new control logic. Know both
  halves before presenting M5.
- The **green corridor for ambulances** works, is safe, and was measured —
  but before the 18 September fixes, so its numbers need one re-run.
- **Incident detection (M6)** is built end to end, but the model is not
  accurate yet: it caught 1 of 2 test incidents and raises too many false
  alarms.
- **The response chain** — anomaly → alert → police and ambulance sent from
  real stations → green corridor → hospital — now exists in the interactive
  mode. An operator has to mark the anomaly; the detector does not trigger it
  yet.
- The **eyes of the system** — cameras (M8) — now exist as a full pipeline,
  measured against a digital twin of 19 junction cameras. With a good
  detector the signal controller keeps its win over Webster when it runs on
  camera data instead of the simulator's ground truth, and a camera that
  fails is handled. What is missing is a detector trained on Indian traffic
  and real Vijayawada footage; incident spotting from cameras is weak.
- There is now a real **operator dashboard** (the TRAFFIX Command Center) and
  a **test lab** for running scenarios by hand.

---

## What the project was meant to be

Your plan (in `README.md`) has ten milestones, M0 to M9. Here is where each
one really is:

| # | What it is | Really (23 Sep) |
|---|---|---|
| M0 | Skeleton: services talking to each other | ✅ **done** |
| M1 | SUMO simulation on the real Vijayawada map | ✅ **done** |
| M2 | Safety kernel — the rules signals can never break | ✅ **done** |
| M3 | Baseline controllers + measurement harness | ✅ **done** |
| M4 | CA-MP — first smart controller | ⚠️ **built, loses to the baseline** (superseded by M5) |
| M5 | A-CA-MP — smarter controller with memory | ✅ **built; beats Webster by 25–31% at all 3 levels** · ⚠️ **the cycle supervisor adds nothing measurable** |
| M6 | Anomaly detection + incident response | 🟡 **detector built but undertrained; response chain built; the two not connected** |
| M7 | Green corridor for emergency vehicles | ✅ **built and measured** (numbers need a re-run on current code) |
| M8 | Computer vision on real camera footage | 🟡 **built and measured on a digital twin; smoke-tested on real clips; no Indian-traffic detector or Vijayawada footage yet** |
| M9 | Benchmark, evaluation, project website | 🟡 **~55% — benchmarks, Command Center and test lab exist** |

`README.md`'s milestone table and "Current milestone" section were updated on
23 September to match this.

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

> **Needs a re-run.** These numbers were measured before the 18 September
> fixes (see M5): the occupancy bug reached the corridor engine's
> `rho_couple` test, and clearance intervals, minimum green and speed limits
> all changed underneath it. Re-run `scripts/m7_corridor_benchmark.py` on
> current code before quoting them as current. (The 16 September safety
> change — preempt only onto phases that *protect* the ambulance's movement —
> was to the live corridor the interactive mode uses; the benchmarked engine
> already worked that way. On the benchmarked route it picks the same phase
> at every junction, so it changes nothing there.)

**Backed by real research.** 86 documented hazards catalogued from MUTCD,
NTCIP 1211, NEMA TS2, NCHRP, FHWA and NTSB sources before a line was
written.

---

### M7 dispatch — where the ambulance is going ✅ (added early September)

**What it does.** Until early September the ambulance's route was nine road IDs
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

**Since then, the other direction too.** The last version of this report
said the station→scene leg could not be simulated because the OSM extract has
no fire or ambulance stations. The interactive mode now sends police from real
OSM police stations and ambulances from hospitals (assumed to be their base),
then takes the ambulance on to the nearest hospital. Fire trucks still have no
station data, so they are never sent.

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

### M5 — A-CA-MP ✅ built · ⚠️ supervisor unproven *(re-measured 11 Sep and again 18 Sep — the headline moved both times)*

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

**Where it stood on 12 September:** beating Webster at every demand level
(−19.9% / −11.4% / −11.6%) with zero violations. **That is no longer the
current result** — read on.

#### 18 September: four measurement bugs, and the headline moved again

A review of the whole control path
([`algorithm_improvement_research.md`](algorithm_improvement_research.md),
690 scratch SUMO runs) found four things that had each been quietly
invalidating results:

1. **The spillback gate had never run.** Occupancy was divided by 100 twice,
   so the gate always returned about 1.0. Every tuning of it had been tuning
   nothing.
2. **Clearance times and minimum green were guesses.** Yellow was whatever
   netconvert had invented (5–6 s); it now comes from the ITE/IRC kinematic
   rule. Minimum green went from 10 s to 7 s.
3. **Two metrics didn't measure what they claimed.** Throughput divided by a
   fixed 1,800 s, so every controller scored the same; the warm-up filter
   compared different sets of trips between arms.
4. **The starvation limit didn't follow the ceiling**, so it sat 5–9× above
   the cycle the corridor actually ran.

The same day, the corridor's speed limits were capped at 50 km/h (the OSM
extract said 80–100 km/h — road-type defaults, not a survey), and a 3-second
gap-out was added. The gap-out is kept because it makes light-demand waits and
stops significantly better — **not** because it cuts delay; on held-out seeds
it doesn't, measurably.

**Current result** (`baselines/2026-09-18_gap_out/`, 10 held-out seeds,
paired, zero interlock violations in every arm):

| Traffic level | vs Webster | vs `ceiling` arm (same controller, supervisor off) |
|---|---|---|
| Light | **−25.0%** ✅ 10/10 seeds | −2.1%, not significant |
| Medium | **−31.2%** ✅ 10/10 seeds | 0.0%, not significant |
| Heavy | **−26.2%** ✅ 10/10 seeds | +2.4%, not significant |

At heavy demand the controller also cleared about 20% more people per hour
than Webster (5,885 vs 4,885, measured in the speed-limits baseline just
before gap-out). **Person-delay from before and after 18 September cannot be
compared**: lowering the speed limit lowers the free-flow reference SUMO
measures delay against.

**What this means.** Both columns matter. The first is a real, large win:
adaptive control beats tuned fixed-time timing by a quarter to a third,
measured on corrected inputs that helped Webster too. The second is the
caveat. The `ceiling` arm is the same A-CA-MP with the same Webster-referenced
ceiling, just without the cycle supervisor — and the supervisor no longer
makes a measurable difference (on 12 September it was −5.5% at heavy demand).
The ceiling arm now has zero violations too, so the supervisor's safety job
isn't being demonstrated on this corridor either. The gap-out smooths waits
but doesn't cut delay. So every improvement recorded on 18 September came from
correcting an input, not from new control logic. And A-CA-MP still leans on
the Webster-referenced ceiling: without it, on 11 September, it lost to
Webster at light and medium demand (before these fixes, and not re-measured
since).

> **A wording trap in `PROGRESS.md`.** Its 18 September section calls the
> `ceiling` arm a "static ceiling" that "isolates what A-CA-MP's own logic
> contributes". According to `scripts/m5_baseline_benchmark.py`, that arm is
> A-CA-MP + ceiling with the supervisor off, so what it isolates is the
> supervisor. The CC-A-CAMP section earlier in the same log describes it
> correctly.

The honest claim for M5 today: *a safe adaptive controller that beats tuned
Webster by 25–31% at every demand level; the cycle supervisor and gap-out
added on top of it have no measured effect on delay.*

Two ideas are left to try: **lane-group pressure aggregation** (53 of the
corridor's 73 links share a physical lane, so phases inside one junction are
weighted 1–3× by geometry alone) and a **per-phase supervisor trigger**.

---

## What is partly built, and what is not

### M6 — Anomaly detection and incident response 🟡

Two halves, built by different routes, not yet joined.

**The detector** (`control/anomaly/`, about 2,300 lines, ~105 tests). A graph
neural network that watches all 73 signal-controlled links every second, a
calibrated alert threshold, an incident state machine with a tamper-evident
audit trail, and an injector that stages stalled vehicles and blocked lanes so
accuracy can be measured exactly. The plumbing works. The model doesn't yet —
it has only had a tiny proof-of-training run (2 scenarios, 12 epochs):

| Metric | Now | Target |
|---|---|---|
| Incidents caught | 1 of 2 (0.50) | ≥ 0.90 |
| Time to detect | 40 s | < 30 s |
| False alarms | ~0.19 per tick | ≤ 0.10 |
| Right link named | 1 of 1 | high |

That is one evaluation seed, so read it as indicative only. No trained model
ships in the repo. The plan to fix it is in
`ITMS_M6_Anomaly_Detection_Status_and_Accuracy_Plan.docx`: record the full
30-scenario dataset and train for 50–80 epochs.

A second M6, built separately on the `VIVEK` branch, is not merged; its event
fields are incompatible with the ones this branch's API and dashboard read.
[`m6_branch_decision.md`](m6_branch_decision.md) has the details.

**The response chain** (`live/`, run with `SIM_MODE=live`) — new since the
last version of this report:

| Piece | Status |
|---|---|
| Operator marks an anomaly, and it really affects the simulation | ✅ built |
| Decide which authorities respond | ✅ built — accident → police, ambulance and fire; other road blockages → police; congestion → no one |
| Alert with type and GPS | ✅ built |
| Send a responder to the scene | ✅ police from real OSM police stations; ambulances based at hospitals · ❌ fire: no station data, so never sent |
| Take the ambulance on to the nearest hospital | ✅ built |
| Green corridor and continuous re-routing on the way | ✅ built |
| Operator confirms or rejects a detected incident | ✅ built (API-key protected) |
| Responder acknowledges the job | ❌ not built |
| The detector triggers the chain by itself | ❌ not connected |

It is covered by 68 tests but has never been benchmarked. The green corridor
it uses is a separate live implementation, not the benchmarked M7 engine.

One document is now out of date because of this:
[`incident_response_pipeline_analysis.md`](incident_response_pipeline_analysis.md)
still lists notification and dispatch as "absent". It was written before this
was built, so read its status table as a snapshot. Its 22 loopholes and
mitigations are still worth reading.

---

### M8 — Vision on real footage 🟡 ~55%

**Built** (`services/vision-service/`, `packages/geo/`, 168 tests): a
camera is treated as one more sensor. It reports the same per-link queue
numbers the controller already reads from the simulator, plus a
**confidence** value, so the controller runs on cameras unchanged. The
pieces: camera geometry and calibration (including calibration from the
lane markings a camera can already see, no survey needed), a YOLO11
detector adapter, a tracker written from scratch, tracking on the road
surface in metres, the queue estimator, five incident rules that know
whether the light is green or red, camera health checks, and privacy
redaction of stored evidence. It runs as a service next to `make dev`,
and the live signal controller can now run on it (`CONTROL_SENSOR=vision`;
`make m8-live` checks the two services end to end over the message bus).

**Reviewed for bugs (24–25 September).** A pass over every module found and
fixed a dozen defects, each with a test. The serious ones: the live wiring
crashed on its first message (a timestamp arrived as a date object; the
test with the real message bus found it); a camera coming back from an
outage re-attached old vehicles to new ones; and the incident scoring
under-counted false alarms. A new feature was built, measured and switched
off because it made the estimate better and the controller worse. Every
M8 measurement was then re-run; the numbers below are the new ones.

**Measured** on a digital twin — the simulator filmed through each of 19
planned cameras with realistic detector errors:

- **With an in-domain detector the controller keeps its win over Webster
  on camera data**: −31.0 % person-delay at medium, −20.3 % at heavy (both
  significant), against −31.4 % / −29.5 % on the simulator's own truth. At
  medium the cameras cost nothing measurable (+0.6 %). Zero safety
  violations.
- **Camera doubt used to hurt the controller.** When a camera was unsure,
  the controller's fallback cut green lights short, and with a stock
  (untrained-for-India) detector that cost 28 %. The fallback is fixed
  (25 September): an unsure reading is still used as the best estimate
  available, and only a camera that has really failed sends a junction to
  fixed timings. The stock detector now costs +5 % against the simulator's
  own truth.
- **When a junction's cameras fail for half an hour**, trusting them costs
  +12.6 % (significant); telling the controller recovers about half of it
  (the first measurement said three quarters). A camera that goes *blind*
  instead — still sending pictures, recognising nothing — looks healthy
  to every check inside the camera system; the controller now catches it
  by comparing with the stop-line loop detectors, and recovers about a
  third of the cost.
- **Incident spotting from cameras is weak**: counted correctly, the rules
  catch about a fifth (19 %) of the injected incidents a camera can see at
  under two false alarms an hour for the whole corridor, or 37 % at 37 an
  hour. Useful as one input to the M6 detector, not on its own. Along the
  way the M8 tests found that M6's incident injector let "broken-down" cars
  keep changing lanes; fixed.
  - **A trained combiner was tested.** It uses each link's normal
    behaviour, contrast features and the rules' evidence
    (`baselines/2026-09-27_m8_incident_fusion/`).
  - **With whole-lane speed and halting** (SUMO's, noise-free: an upper
    bound) it catches 37–43 % on fresh test seeds at under 0.3 false alarms
    an hour. That is about four times what the re-tuned rules catch, and
    two to three times the shipped setting.
  - **With the cameras alone** it catches 28 % with 1 false alarm in 15
    hours, where the rules catch 11 % with 26. That did not meet the bar set
    in advance, so it was not adopted.
- **Real footage** (short public clips, CPU only): the stock detector and
  the whole pipeline run end to end at ~14 frames per second; camera health
  raised no false alarm and caught every injected fault; evidence is
  pixelated. On an overhead view, stock weights find almost no vehicles.
- **A real Indian-traffic detector, measured** (250 labelled Bengaluru
  CCTV frames): IISc's UVH-26 model finds 71 % of vehicles at the
  tracker's confidence line against 32 % for the stock model, recognises
  three quarters of auto-rickshaws (the stock model has no such class), and
  runs as fast (58 ms a frame on a laptop CPU). Getting there found a bug:
  the model splits a car into five types, and a car it was unsure between
  "sedan" and "hatchback" was thrown away; fixed. The digital twin's
  detector settings turned out optimistic about motorbikes and
  auto-rickshaws, the "stock" one badly.
- **The controller on real detectors** (26 September). The digital twin's
  cameras now detect the way the measured models do. With IISc's model
  reading images at 1280 pixels wide, the controller costs +2 % (medium
  traffic) and +8 % (heavy) against perfect data, neither significant, and
  still beats Webster by 30 % and 24 %. At 640 pixels, the setting a
  laptop runs at about 18 frames a second (enough for three or four
  cameras, not 19), it loses more (+9 % and +17 %). With the stock model it costs
  +17 %, three times the old estimate. So a deployment needs IISc's model
  run on a GPU. A Colab notebook to fine-tune it on more Bengaluru frames
  is ready, with the test that will judge the result.
- **The first fine-tuning run** (26 September). At 640 pixels it found
  more vehicles than IISc's model (82 % against 71 %), with a smaller
  error in the per-image vehicle count (in car units),
  but more of its boxes were wrong (precision 0.876). That misses the 0.90
  bar set in advance, so it was not adopted. Its training had in fact
  broken down. IISc's model file stores some internal normalisation
  numbers (BatchNorm variances) that are too large for the compact number
  format used to save and to speed up training. Some are stored as
  infinity, and the training stopped learning part-way through. A second
  version of the notebook keeps these numbers in full precision throughout.
  It also makes a copy of IISc's model with only those numbers repaired,
  which is itself a candidate: on a diagnostic split of the test frames,
  the repair alone raised precision from 0.90 to 0.93.
- **The corrected fine-tune, adopted** (27 September). It passed the bar
  set in advance at both image sizes. At 640 pixels, the laptop setting,
  it finds 79 % of vehicles against IISc's 71 %, with about the same share
  of boxes right (91 % against 92 %), and more than twice as many of the
  smallest, most distant ones. With the digital twin's cameras fitted to it, the
  controller at medium traffic costs +4.7 % against perfect data, half of
  what IISc's model cost at that setting. The difference between the two
  is not yet statistically certain. That is close to IISc's model at 1280
  pixels, which needs a GPU. In heavy traffic one run in five went into a
  long jam with either fine-tune, so the heavy-traffic average did not
  improve. Runs on perfect data never jammed, so something in the camera
  path causes these jams; finding what is the next job.

**Not done:** testing
on Vijayawada footage (the real detector has only been measured on
Bengaluru's cameras), a fix for a standing jam that can look like a blind
camera, and incident rules good enough to use on their own.

---

### M9 — Benchmark, evaluation, site 🟡 ~55%

**Built:**

- **The benchmark machinery**, used constantly: paired seeds, held-out
  evaluation seeds never touched by tuning, 95% confidence intervals, every
  raw run kept — and now frozen, dated snapshots in `baselines/` with the
  test log and environment beside each one.
- **The TRAFFIX Command Center** (`web-app/`): React and TypeScript, a
  landing page plus six workspaces (overview, anomalies, traffic, emergency,
  analytics, settings). It opens on in-browser simulated data and switches
  to live when the backend answers. 139 unit tests plus Playwright browser
  tests.
- **The test lab** (`testing_site/`): run light, medium or heavy traffic, or
  your own origin-to-destination scenarios, against the real code; compare
  runs and export the KPIs.

**Not built:** the final cross-milestone evaluation write-up.

---

## Problems worth knowing before you present

### Serious

**1. The cycle supervisor — the "CC" in CC-A-CAMP — no longer has a
measured benefit.** See M5 above. The 25–31% win over Webster is solid;
claims about the supervisor aren't, right now. Either the per-phase trigger
makes it earn its place, or it gets presented as a safety backstop with no
measured delay effect.

**2. M7's numbers predate the 18 September fixes.** Re-run the corridor
benchmark on current code so M5 and M7 are measured on the same code.

**3. The "novel contribution" of M7 is unproven.** The anticipation term
`A(p)` and debt term `D(p)` — the two things that make this more than standard
preemption — showed **no detectable effect** at 10 seeds medium or 30 seeds
heavy. They are left on by default and documented as unproven, which is honest,
but it means the headline contribution has no evidence behind it.

**4. M6's model isn't accurate yet, and it isn't connected to the response
chain.** Until both are fixed, every incident in a demo has to be marked by
hand.

### Moderate

**5. Traffic demand is not calibrated.** Light, medium and heavy demand are
generated, not taken from traffic counts. Flagged since M1 and deferred to
M8.5. Every result in the project rests on synthetic demand.

**6. Several inputs are standards, not measurements.** The 50 km/h speed cap
is a design standard, not this corridor's measured speeds. Saturation flow was
calibrated under the old speed limits and hasn't been re-measured. Webster
still assumes 4 s of lost time per phase change against the 5.5 s now
displayed.

**7. No pedestrian phases exist in this network.** All of hazard category B —
pedestrian safety during preemption — is unit-tested against made-up junctions
and **exercised by zero real runs**. In an Indian city centre with heavy
mid-block pedestrian movement, that is the biggest gap between the simulation
and the real thing.

**8. Older M7 arms are on the old route.** The ablation arms and all
heavy-demand arms were measured before the route became a dispatch output and
before the release fix. They are still valid as *attribution* evidence but
must not be compared numerically against the new arms.

**8b. M8's numbers come from a simulated camera.** The detector error
presets are assumptions, not measurements of a real model on Vijayawada
video, and the closed-loop runs keep the safety kernel's stop-bar inputs
(`has_demand`, waits) on ground truth. Present M8 as "the controller keeps
its win on camera-grade data, under these assumptions", not as a field
result. The incident stream found the M6 injector's stalled vehicles
changing lanes while stopped (fixed in `injector.py`; the M6 gate results
predate the fix).

### Minor

**9. CI never runs.** `ci.yml` sits in `itms/`, not `.github/workflows/`,
and it only triggers on `main` — which hasn't moved since 22 August.

**10. `POST /v1/commands` has no authentication.** It can create anomalies
and send emergency vehicles. Fine on a laptop, not beyond it.

**11. Incidents are held in memory only.** Restarting `api-service` loses
them.

**12. `PROGRESS.md`'s M4 header still says "in progress"** even though the
section closes it out.

**13. `sumo-gui` will not start on your Mac.** The headless run works and
gives the same commentary. Likely a pip-wheel problem; the Homebrew build is
the thing to try.

**14. Distributed-systems faults C6–C10** (optimiser silence, bad config,
clock skew, leader failover, split-brain) are not covered. Reasonable — this
is a single-process build.

### Resolved since the 12 September version

- **README milestone table** — updated 23 September.
- **M5 measured against the pre-M7 controller** — the 16 and 18 September
  baselines run on the merged code.
- **Webster numbers predating the cabinet fix** — Webster is re-measured
  inside every baseline. (`make bench`'s own M3 table, from 30 August, still
  hasn't been re-run.)
- **The heavy-demand and seed-6 interlock violations** — every arm of the
  18 September baselines has zero violations on every seed. The M7 gate itself
  hasn't been re-run, so for the corridor arm this is expected, not confirmed.
- **"M6 was skipped"** — it has been built (see above).
- **M3's "in progress" header** — fixed.

---

## How I got to 75%

Equal weight per milestone, judged on what is actually demonstrated:

| Milestone | Credit | Why |
|---|---|---|
| M0 | 1.00 | Gate verified |
| M1 | 1.00 | Gate verified |
| M2 | 1.00 | Gate verified, 90,000 property cases |
| M3 | 1.00 | Gate satisfied, closed out |
| M4 | 0.85 | Built and measured; result is a clear loss |
| M5 | 0.90 | Beats Webster by 25–31% at every level with zero violations; supervisor and gap-out have no measured delay benefit *(was 0.95)* |
| M6 | 0.50 | Detector built but undertrained; response chain built but not benchmarked; the two not connected *(was 0.20)* |
| M7 | 0.80 | Built and gated; numbers need a re-run on current code; contribution unproven; pedestrians unexercised *(was 0.85)* |
| M8 | 0.55 | Full pipeline built and measured on a digital twin; controller keeps its win on cameras; wired into the live controller; real-footage smoke test. No Indian-traffic detector, no Vijayawada footage; incident rules weak *(was 0.00)* |
| M9 | 0.55 | Benchmarks, Command Center and test lab exist; final evaluation doesn't *(was 0.35)* |
| | **8.15 / 10** | **≈ 81%** |

The number went up, but mostly from **breadth** — the response chain and the
Command Center — while **M5's own claim got narrower**. That trade is worth
being clear-eyed about.

**Why it might be lower.** M8 is not one-tenth of this project — computer
vision on real footage is probably the second-largest single milestone after
the controller work, and what exists is measured on a simulated camera, not
on real Vijayawada video. Weighted by effort, about 75% is the more honest
number.

**Why it might be higher.** The depth of what is done is unusual: 621 Python
tests and 139 web-app tests (as recorded at the 23 September merge), 90,000
property-test cases, held-out evaluation seeds never used for tuning, an
86-hazard catalogue with citations, four frozen baselines, and a 4,400-line
progress log with every negative result — including four bugs that were
flattering your own headline, found and reported rather than left alone.

---

## What I would fix first

1. **Decide M5's story.** The 25–31% win over Webster is solid. For the
   supervisor, try the per-phase trigger; if it still doesn't separate from
   the `ceiling` arm on held-out seeds, present it as a safety backstop with
   no measured delay effect. Lane-group pressure aggregation, the other
   remaining idea, targets the controller itself. Either ending is
   defensible; leaving it ambiguous isn't.
2. **Re-run the M7 corridor gate on current code**, so M5 and M7 numbers come
   from the same code.
3. **Train M6 properly** — the 30-scenario dataset and 50–80 epochs from the
   accuracy plan. Only then connect the detector to the response chain.
4. **Give M8 real eyes.** The pipeline is built and measured; what it lacks
   is a detector trained on Indian traffic (IISc's UVH-26 model is
   measured; its corrected fine-tune is ready to run in Colab) and some real Vijayawada
   junction footage to calibrate
   one camera (`itms_geo.lanecal`) and check the twin's numbers against.
   One camera at one junction is enough to demonstrate it.
5. **Decide what to do about `A(p)` / `D(p)`.** Three options, in rising cost:
   claim only the trigger and drop them; measure them against an
   ambulance-local metric rather than a run-level average; or put them through
   proper parameter tuning. The first is defensible today.
6. **Housekeeping:** move `ci.yml` into `.github/workflows/` and point it at
   `traffic`; delete `Makefile_1` (an identical copy of `Makefile`).

---

## The honest one-paragraph version

You have built a traffic signal controller that is provably safe and cuts
delay by a quarter to a third against a tuned classic baseline — though the
extras added on top of it last (the cycle supervisor, the gap-out) haven't
shown a measured effect on delay. A green corridor that measurably
beats the field-standard approach. An incident pipeline that can take a marked
anomaly all the way to police and ambulances sent from real stations, a green
corridor, and a hospital. A working operator dashboard. And a benchmarking
discipline stronger than most published work, with the negative results left
in. What you still don't have is reliable sight: the detection model is
undertrained and not connected to the response chain, and the camera
pipeline, now built and shown to keep the controller's win on camera data,
has only seen simulated cameras and short public clips. The system responds
well to an emergency once someone tells it about one. It can't yet reliably
spot one for itself.

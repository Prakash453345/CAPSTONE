# The incident-response pipeline: failure analysis and design review

    anomaly detected  →  classified  →  authority notified  →  corridor computed  →  responder arrives

This document analyses the three stages of that pipeline that this
project has **not** built, and the one stage it has. It is a design
review, not a specification: every item is a way the pipeline can be
wrong, what that costs, and what closing it would take.

---

## How to read this

**Scope.** Anomaly detection itself is out of scope by instruction. It
appears here only as an *upstream source* — the properties its output
must carry for everything downstream to behave correctly. Nothing here
concerns CV architectures, sensor selection, or model training.

**Relationship to the hazard catalogue.**
[`green_corridor_hazard_catalogue.md`](green_corridor_hazard_catalogue.md)
already holds 86 hazards (categories A–H) covering the corridor and
preemption stage. This document does **not** restate them. Where an item
here is already catalogued, it is cited by its existing ID (`D11`,
`E14`, `H9`…) and only the *new* upstream aspect is analysed. Read the
two together.

**Item format.** Each loophole gets an ID (`L-<stage><n>`), then:

> **Loophole** — the specific way it breaks.
> **Risk** — what that costs, and to whom.
> **Mitigation** — what to do, concretely.
> **Tradeoff** — what the mitigation costs.
> **In this build** — the honest status today.

**Status vocabulary** used in "In this build":

| Marker | Meaning |
|---|---|
| **built** | Implemented and exercised by a test or a gate run |
| **partial** | Mechanism exists, trigger or coverage missing |
| **absent** | No code. The stage does not exist |
| **n/a in sim** | Cannot arise in simulation; matters only in deployment |

---

## 0. What exists today, stated plainly

Three of the four stages are not built. That is not a criticism — the
project scoped to signal control and did signal control — but a design
review that blurs "designed" and "implemented" is useless, so:

| Stage | Status | Where |
|---|---|---|
| Detection | **absent** | — (out of scope by instruction) |
| Classification | **absent** | — |
| Notification / dispatch to an authority | **absent** | — |
| Facility selection + route computation | **built** | `control/dispatch/` |
| Corridor arbitration + preemption | **built** | `control/corridor/` |
| Safety kernel | **built** | `control/safety/interlocks.py` |

Two mismatches between the described pipeline and the code, worth
naming before anything else:

1. **The cost function described is not the cost function implemented.**
   The design says "route safety (avoiding other active anomalies),
   current traffic congestion, and shortest travel time". `dispatcher.
   choose` minimises *live travel time alone*, from a capability-filtered
   shortlist. There is no safety term and no explicit congestion term
   (congestion enters only implicitly, through live edge travel times).
   §4 argues the implemented version is closer to correct than the
   described one, and that adding the missing terms as a weighted sum
   would be a mistake this project has already made three times.

2. **The direction of travel is reversed.** The dispatch layer routes
   *scene → facility*. The pipeline described here is *station → scene*:
   an anomaly is detected somewhere and a responder must reach it. These
   are different problems — the scene is a computed destination in one
   and a given origin in the other — and the OSM extract contains no fire
   or ambulance station at all, so the station→scene leg cannot currently
   be modelled from this data.

---

## 1. What the field actually does

### 1.1 The architecture question is already settled by standard

**NTCIP 1211** splits signal priority into three roles: a **Priority
Request Generator** on the vehicle that asks, a **Priority Request
Server** that arbitrates among requests, and the **Coordinator** — the
signal controller — that decides. The standard is explicit that
"requests for priority service can be sent to a CO, but **a CO cannot be
commanded to service a priority request** by the SCP system", and the
PRS prioritises "based on the requests' vehicle class level and time of
service desired".([ntcip.org](https://www.ntcip.org/file/2018/11/NTCIP1211-v0224j.pdf))

This is the propose/decide split the corridor engine already implements,
and it is worth noting that the standard reaches it for the same reason:
a priority system that can *command* a controller can command it into an
unsafe state.

### 1.2 The standards define rejection — the pipeline should too

**SAE J2735**'s Signal Status Message carries a priority request status
drawn from an eight-value enumeration: `unknown`, `requested`,
`processing`, `watchOtherTraffic`, `granted`, `rejected`, `maxPresence`,
`reserviceLocked`.([hexdocs](https://kitt.hexdocs.pm/Kitt.Message.SSM.html))

Three of those deserve attention:

- **`rejected`** — the standard assumes requests get denied and defines
  how the requester is told. A pipeline whose only outcome is "corridor
  granted" is less expressive than a 2016 message set.
- **`maxPresence`** — a bound on how long a preemption may persist.
- **`reserviceLocked`** — a lockout preventing the same requester being
  served again within a window.

The last two are *conditional priority* primitives. The corridor engine
has their equivalents (`max_dwell_s`, the rolling-hour budget). The
notification and dispatch stages have nothing of the kind, which is
exactly where §3 finds its worst failure modes.

### 1.3 Preemption's cost on the cross street is measured, and it is real

Xu, Tian and Wang (2023) tested **five** EVP exit strategies in
hardware-in-the-loop simulation across four scenarios in Reno, Nevada,
and found EVP "tends to worsen arterial and intersection operations for
**all five** EVP exit strategies by increasing the arterial travel times
and the total vehicle movement delay" at preempted
intersections.([TRID](https://trid.trb.org/view/2236919))

The USDOT **MMITSS** impacts assessment quantifies the same tradeoff for
priority rather than preemption: connected transit saw **46.4–51.4%**
delay reduction, but system-wide delay rose by up to **10.6%**; connected
trucks saw 25–53% reductions with system-wide delay increasing
substantially at high truck volumes. The report's conclusion is that
priority applications "improve vehicle travel time, delay, and travel
time reliability for equipped" vehicles but "may produce overall
system-wide negative impacts", concentrated on unequipped side-street
traffic.([USDOT](https://rosap.ntl.bts.gov/view/dot/3557/dot_3557_DS1.pdf))

**A gap worth knowing about:** MMITSS's own emergency-vehicle preemption
application (PREEMPT) "was not ready for testing" during the study, so
the flagship US connected-vehicle signal-priority programme produced *no
measured EVP impact data at all*. That makes this project's M7 gate a
genuine contribution rather than a re-derivation — and it also means
there is little published work to check it against.

### 1.4 Automatic incident notification already exists at scale, and its false-alarm rate is known

This is the single most important number in this document.

**eCall** is a mandatory, regulated, purpose-built automatic crash
notification system: on airbag deployment the vehicle calls the
emergency number and transmits a Minimum Set of Data. It is the closest
deployed analogue to "sensor detects incident, authority is notified
automatically". A 2025 RAC Foundation study by Reed Mobility found that
in 2024, **two-thirds of all eCall activations in the UK were false
alarms**; of the *automatic* activations specifically, **around one third
were false**.([RAC
Foundation](https://www.racfoundation.org/media-centre/two-thirds-of-ecall-activations-are-false-alarms))
Finland's Emergency Response Centre Agency has separately reported false
eCalls burdening emergency
services.([112.fi](https://112.fi/en/-/ecall-emergency-call-system-prevents-road-deaths-false-calls-burden-emergency-services))

A physical airbag sensor — an unambiguous, high-signal, purpose-built
trigger — is wrong a third of the time when it fires automatically. A CV
model inferring "accident" from pixels will not beat it. **Design the
pipeline to be correct when detection is wrong**, because it will be.

### 1.5 Alert fatigue is quantified, and the numbers are brutal

The Joint Commission's Sentinel Event Alert 50 states that "between **85
and 99 percent** of alarm signals do not require clinical intervention",
and records 98 alarm-related events between January 2009 and June 2012 of
which **80 resulted in death** — deaths caused not by alarms failing to
fire but by staff having learned to ignore
them.([Joint Commission SEA
50](https://www.kff.org/wp-content/uploads/sites/2/2013/04/sea_50_alarms_4_5_13_final1.pdf))

The evidence-based mitigations it recommends are structural, not
technical: leadership-owned alarm-management policy, tiering by risk,
per-context threshold customisation, and cross-disciplinary review of
alarm data. None of them is "improve the detector".

### 1.6 India already runs green corridors — manually

In Indian practice a "green corridor" is usually a **police-escorted,
manually cleared route**, most often for organ transport. Documented
performance is extraordinary: 12.5 km Stanley → Kauvery in Chennai in
**6 minutes**, and — directly relevant here — 15.2 km in **7 minutes** in
**Vijayawada**, from Capital Hospital to the airport. The same account
notes that "the process of setting up a green corridor is complex, since
it requires coordination of multiple
stakeholders".([Kauvery
Hospital](https://www.kauveryhospital.com/kauverian-scientific-journal/ready-steady-go-a-brief-on-green-corridor-activation-in-organ-transplantation/))

Two implications. First, the *performance target* is already
demonstrated on the user's own corridor city — the automated system is
competing with something that works. Second, what automation actually
replaces is not the clearing but the **coordination burden**: manual
corridors are pre-planned hours ahead for scheduled transports, which is
precisely why they cannot serve an unscheduled emergency. That is the
gap this project fills, and it is a better framing for a viva than "we
make ambulances faster".

### 1.7 Base rates, for calibration

MoRTH's *Road Accidents in India 2023*: **480,583** accidents, **172,890**
deaths, 462,825 injuries — about 55 accidents and 20 deaths per hour
nationally; 31.5% of deaths urban; over two-thirds of victims aged
18–45.([Business
Standard](https://www.business-standard.com/india-news/india-road-accidents-deaths-injuries-report-road-highway-ministry-nitin-gadkari-125082801527_1.html))

108 (GVK EMRI) ambulance response times in Tamil Nadu, July 2023: metro
**7.13 min**, urban 11.41 min, rural 13.41 min — with metro times having
*risen* 20 seconds year-on-year, attributed partly to construction
traffic.([DT
Next](https://www.dtnext.in/news/tamilnadu/overall-response-time-of-108-ambulances-drops-in-last-one-year-727237))

Divide the national figure across urban India and a seven-junction
corridor sees a genuine reportable incident perhaps a few times a *year*.
Hold that number in mind for every threshold in §2 and §3.

---

## 2. Stage A — Detection, as an upstream source only

Not analysed: how detection works. Analysed: what its output must carry
for the rest of the pipeline to be correct.

### L-A1 — Confidence is destroyed at the first stage boundary

> **Loophole.** The detector emits `(accident, p=0.62)`. The classifier
> consumes it, applies a threshold, and emits `accident`. From that point
> the pipeline cannot distinguish a near-certain fire from a coin-flip,
> and every downstream decision — which authority, how many units, whether
> to preempt seven junctions — is taken as if the observation were fact.
>
> **Risk.** The whole pipeline's error behaviour becomes a step function
> of one threshold nobody owns. Set it low and you get §1.4's false-alarm
> economics with §1.5's consequences. Set it high and you miss incidents.
> There is no setting that is right, because the correct action genuinely
> differs between p=0.6 and p=0.95 — and thresholding erases the
> difference.
>
> **Mitigation.** Carry confidence as a first-class field on the incident
> record end-to-end, and make each stage's *action* graded rather than
> its *input* thresholded. Concretely: p≥0.9 → dispatch and preempt;
> 0.6≤p<0.9 → dispatch, no preemption until a responder or a second
> source confirms; p<0.6 → queue for operator review, no automatic
> action. The corridor engine already models exactly this
> (`VehicleReport.confidence` shortens the commitment horizon rather than
> refusing the request) — the same discipline needs to run three stages
> higher.
>
> **Tradeoff.** Graded response means the system is slowest precisely
> when it is least sure, which is when a real incident is hardest to see
> — fog, night, occlusion. You are trading tail latency on ambiguous true
> positives against not preempting a corridor for a plastic bag.
>
> **In this build: absent** upstream, **built** inside the corridor
> engine. The pattern to copy is already in `engine.py`.

### L-A2 — There is no latency budget, so nobody knows what "real time" means

> **Loophole.** "Detected" is not an instant. It is frame capture →
> inference → post-processing → aggregation across frames to suppress
> flicker → message → classification → dispatch decision. Each step has a
> latency and the temporal-smoothing step is often the largest, because
> suppressing single-frame false positives means waiting for
> corroborating frames.
>
> **Risk.** The corridor's lead-time computation assumes a bounded
> observation age; `CorridorConfig.latency_margin_s` is 1.0 s and
> `report_ttl_s` is 6.0 s. If detection-to-dispatch runs to 30 s, the
> corridor is computed against a world 30 s stale and the responder is
> dispatched to a scene whose state has moved on. Worse, the number is
> invisible: nothing measures it, so it degrades silently as models grow.
>
> **Mitigation.** Timestamp at *capture*, not at message emission, and
> carry `observed_at` through every stage — the pattern
> `VehicleReport.observed_at_s` already uses. Then publish an end-to-end
> latency budget with a per-stage allocation, and alarm on breach. Reject
> or downgrade any incident record older than its TTL rather than acting
> on it.
>
> **Tradeoff.** Aggressive TTLs discard genuine detections during network
> hiccups. The alternative — acting on stale data — is worse, but the
> discard rate has to be monitored or you have built a system that
> silently stops working under load.
>
> **In this build: partial.** The corridor stage is rigorous about
> observation age. Nothing upstream of it exists to be rigorous.

### L-A3 — The prior is ignored, so precision on a test set says nothing

> **Loophole.** A detector reported at "95% accuracy" is almost always
> measured on a class-balanced evaluation set. The deployed prior is
> nothing like balanced: §1.7's base rates put a genuine incident on a
> seven-junction corridor at a handful per year against continuous
> observation.
>
> **Risk.** At realistic priors, even a very good detector's positive
> predictive value can fall below 10% — meaning nine out of ten
> automatic dispatches are to nothing. That is the eCall number (§1.4)
> made worse, and it produces §1.5's outcome: an ICCC operator who
> learns to dismiss the alert, at which point the real one is dismissed
> too.
>
> **Mitigation.** Specify the system against **PPV at the deployed
> prior**, not accuracy. Require corroboration before automatic action —
> a second sensor modality, a second camera, a 112/108 call, or an
> operator — with single-source detections permitted to *prepare* a
> response (compute the route, warm the corridor) but not to *commit*
> one. Publish the expected false-dispatch rate per corridor per month
> as a design output, and get the responding agency to agree it is
> tolerable *before* deployment, not after.
>
> **Tradeoff.** Corroboration costs time, and for a fire the seconds are
> real. The honest framing is that this is not accuracy-versus-latency
> but *whose* latency: corroboration adds seconds to true positives to
> avoid destroying the system's credibility on false ones.
>
> **In this build: absent**, and it is the item most likely to decide
> whether the pipeline would work in reality.

---

## 3. Stage B — Classification

### L-B1 — Misclassification routes to the wrong authority, and the clock does not reset

> **Loophole.** "Fire" and "accident" and "breakdown" are not disjoint,
> and a classifier that must pick one will sometimes pick wrong. The cost
> is asymmetric and the pipeline treats it as symmetric.
>
> **Risk.** A fire classified as a breakdown dispatches a tow truck. The
> error is not discovered until a human sees the scene, by which point
> the response clock has been running for minutes with the wrong resource
> committed — and, if a corridor was granted, the cross street has paid
> for it too.
>
> **Mitigation.** Do not model classification as a single label. Model it
> as a **capability requirement vector** with independent probabilities —
> `P(needs_fire_suppression)`, `P(needs_medical)`, `P(needs_traffic_
> control)` — and dispatch on each independently where it clears
> threshold. This is a strictly better fit to reality (a road traffic
> accident with entrapment genuinely needs all three) and it removes the
> forced-choice error entirely. Note that `IncidentRequest.required_
> capability` in the dispatch layer is currently a **single string**, and
> its own docstring already concedes this is "a deliberately thin model"
> of triage.
>
> **Tradeoff.** Independent thresholds mean over-dispatch when several
> clear at once. Mitigate with a cap on simultaneous corridors per
> incident (see L-D3), not by forcing the choice back into one label.
>
> **In this build: absent** as a stage; the single-string capability
> model in `dispatcher.py` is the artefact that would need widening.

### L-B2 — A multi-type incident produces multiple corridors that fight each other

> **Loophole.** Accident-plus-fire dispatches fire, ambulance and police
> from three different bases. Three responders, three routes, three
> corridor requests, converging on one point.
>
> **Risk.** The engine's arbitration handles the *junction-level*
> conflict correctly (this is catalogued `D11`, and the priority ordering
> in `PreemptionClass` resolves it). But arbitration is a last resort: by
> the time two units are contending for one junction, the system has
> already committed both routes and one of them is going to lose. Worse,
> converging routes means the *last* junction before the scene is on all
> three routes and gets preempted three times in succession — `F8`
> (preemption during transition) three deep.
>
> **Mitigation.** Solve it upstream as an **assignment** problem rather
> than downstream as an arbitration problem. When dispatching N units to
> one incident, choose the assignment of units to approach directions
> that minimises route overlap, then coalesce the shared tail into **one**
> reservation held until the last unit passes. `VehicleReport.response_id`
> and the engine's coalescing already implement the second half — units
> sharing a `response_id` are one interruption per junction, not N. The
> missing half is that nothing upstream *sets* `response_id`, because
> nothing upstream exists.
>
> **Tradeoff.** Overlap-minimising assignment can send a unit on a longer
> route than its own optimum, trading one responder's arrival time for
> the corridor's total disruption. Whether that trade is acceptable is a
> policy question for the responding agency, not a tuning parameter.
>
> **In this build: partial** — coalescing is built and tested
> (`test_a_multi_unit_response_is_one_interruption_per_junction`); the
> producer of `response_id` is absent.

### L-B3 — The confidence threshold is a policy decision disguised as a constant

> **Loophole.** Somewhere a number decides whether an ambulance rolls.
> If it lives in a config file, it was chosen by whoever wrote the
> config.
>
> **Risk.** Nobody owns the false-dispatch rate. When it turns out to be
> too high, the fix applied under pressure is to raise the threshold —
> which trades false dispatches for missed incidents, silently, with no
> record that the trade was made.
>
> **Mitigation.** Express the threshold as an **operating point on a
> published ROC curve**, with the resulting expected false-dispatch and
> missed-incident rates written next to it, and require the operating
> agency to sign off the point rather than the number. Log every
> threshold change with who made it and what the projected rates became.
> This is `H`-category governance, and it is cheap to build and
> impossible to retrofit.
>
> **Tradeoff.** None worth the name; it is process cost against
> accountability. The real cost is that it makes an uncomfortable number
> visible.
>
> **In this build: absent.**

---

## 4. Stage C — Notification and dispatch

This is the stage with **no representation at all** in the existing
hazard catalogue, and the one where the described design is thinnest.

### L-C1 — "Notify the authority" is not one event, and treating it as one loses the response

> **Loophole.** The design says the authority "is automatically notified".
> That collapses at least five distinct states: *sent*, *delivered*,
> *acknowledged by a dispatcher*, *unit assigned*, *unit en route*. Only
> the last justifies computing a corridor.
>
> **Risk.** A corridor computed on *sent* preempts junctions for a
> vehicle that does not exist. That is `G4` — preemption of intersections
> no emergency vehicle traverses — at pipeline scale, and it is pure cost
> with no benefit. It is also the failure mode most corrosive to public
> tolerance, because the delay is visible and the ambulance never arrives
> to justify it.
>
> **Mitigation.** Model the notification as a state machine with explicit
> transitions and require *unit assigned* before any corridor
> computation, *unit en route with position* before any preemption.
> J2735's status enumeration (§1.2) is the right vocabulary. NENA's
> **Emergency Incident Data Object (EIDO)** is the right data structure:
> an ANSI-approved JSON format for exchanging incident information "from
> call handling to Computer-Aided-Dispatch (CAD), from CAD to CAD, to
> field responders", released 25 October
> 2021.([NENA](https://www.nena.org/news/584569/NENA-Releases-ANSI-Approved-Emergency-Incident-Data-Object-EIDO-Standard.htm))
> It is the current form of a line of work that runs back through the
> NENA/APCO **EIDD** (2.105.1-2017), whose information document is still
> the clearest description of what an incident record must carry:
> globally unique incident identifiers, location in PIDF-LO, incident
> type and status, dispatching agencies and dispatched
> units.([NENA/APCO
> INF-005.1](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/nena_apco-inf-005.1_eidd_201.pdf))
> Adopting that field structure costs nothing and makes eventual
> integration with a real CAD a mapping exercise rather than a redesign.
> **Cite EIDO, not EIDD, in any report** — EIDD is the predecessor.
>
> **Tradeoff.** Waiting for assignment adds the dispatcher's decision
> time before the corridor starts warming. Recover most of it by
> *computing* the route on *acknowledged* and only *committing*
> preemption on *en route* — the expensive part is the computation, the
> harmful part is the preemption, and they can be separated.
>
> **In this build: absent.** The corridor engine's `authorize()` is a
> Python dict populated by the injector; there is no notification
> protocol at all.

### L-C2 — Nothing happens when nobody acknowledges

> **Loophole.** The alert is sent. The channel is up. No dispatcher
> answers — busy, understaffed, mid-shift-change, or the alert landed in
> a queue nobody watches.
>
> **Risk.** Silent total failure, which is the worst class: the system
> reports success, the incident is unattended, and no component is in an
> error state. Automated senders are particularly prone to this because
> a human caller who gets no answer escalates on their own initiative and
> an API client does not.
>
> **Mitigation.** An **escalation ladder with timers**, defined per
> incident severity: no ACK in T₁ → re-send on the same channel; T₂ →
> alternate channel; T₃ → alternate agency or supervisor; T₄ → human
> operator paged, incident flagged as unacknowledged in the ICCC. Treat
> non-acknowledgment as an incident in its own right and record it. The
> J2735 pattern applies again — `requested` and `processing` are
> distinct states precisely so a requester can tell "you have it" from
> "nothing came back".
>
> *(Public-safety practice does define call-answering time standards —
> the NFPA 1225 / NENA family — but I could not verify their current
> numeric requirements against a primary source in this pass. Treat any
> specific figure as unconfirmed until checked.)*
>
> **Tradeoff.** Escalation ladders generate their own alert volume and
> feed L-C4. Bound them: cap escalations per incident, and make T₁…T₄
> severity-dependent rather than uniform.
>
> **In this build: absent.**

### L-C3 — Duplicate alerts for one incident produce duplicate responses

> **Loophole.** One crash is seen by two cameras, a roadside sensor, and
> three phone calls to 112. Six reports, one incident.
>
> **Risk.** Six dispatches, six corridors, six preemption sequences on
> overlapping routes — the L-B2 failure multiplied, and a corridor
> budget consumed by one event. It also corrupts every downstream count:
> incident rates, response times, and the corridor's own rolling-hour
> preemption budget all inflate.
>
> **Mitigation.** Spatio-temporal correlation before dispatch: cluster
> reports within a distance and time window into one incident record with
> one identifier, and treat later reports as *updates* to it rather than
> new incidents. The EIDD/EIDO answer is instructive — it does not
> deduplicate but **links**, carrying explicit `REPLACED` / `REPLACING` /
> `Split` indicators and hierarchical relationships between
> incidents.([NENA/APCO
> INF-005.1](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/nena_apco-inf-005.1_eidd_201.pdf))
> Linking is the better primitive: merging is lossy and sometimes wrong
> (two vehicles crashing 50 m apart within a minute *are* two incidents),
> and a link can be undone.
>
> **Tradeoff.** The clustering window is a direct accuracy tradeoff —
> too wide merges genuinely separate incidents, too narrow lets
> duplicates through. Err narrow and link rather than merge, because an
> under-merged pair costs an extra dispatch and an over-merged pair
> costs an unattended incident.
>
> **In this build: absent.** Note the precedent from the facility
> extractor, where a grid-cell deduplication *looked* sufficient and
> merged nothing because the duplicate pairs sat 90–95 m apart and a
> 100 m cell separates points that close about as often as it groups
> them. The same trap is waiting here: a cell whose size merely exceeds
> the distance does not co-locate anything.

### L-C4 — Over-alerting destroys the system's credibility before it destroys anything else

> **Loophole.** Every detection reaches a human. At §1.4's false-alarm
> rates and §1.7's base rates, most of what reaches them is noise.
>
> **Risk.** §1.5's finding, transplanted: operators become desensitised,
> and the deaths that follow are caused not by alarms failing to fire but
> by having been ignored. For an ICCC operator watching many feeds this
> is the *expected* outcome, not a tail risk. Once credibility is lost it
> does not come back by fixing the detector.
>
> **Mitigation.** The Joint Commission's evidence-based measures
> translate directly: **tier** alerts by severity with different
> annunciation for each; **delay** annunciation of low-tier alerts to let
> transients self-resolve; **customise** thresholds per site rather than
> globally; and establish a standing review of alert data with authority
> to change thresholds. Add one that is specific to this pipeline:
> **separate the machine-to-machine path from the human path** — an alert
> that triggers automatic route preparation need not ring a bell, and
> most should not.
>
> **Tradeoff.** Tiering means low-tier alerts get less attention by
> design, and occasionally one of them is real. That is a deliberate,
> reviewable choice; the alternative is the same outcome arrived at
> accidentally.
>
> **In this build: absent.**

### L-C5 — One channel, one failure

> **Loophole.** A single API to a single CAD endpoint over a single
> network path.
>
> **Risk.** Any of them fails and the pipeline is decorative. Emergency
> systems fail exactly when load is highest, which is when they matter.
>
> **Mitigation.** Two independent paths with genuinely different failure
> modes — not two cloud regions on the same carrier. Heartbeat both and
> alarm on either failing, so a dead standby is discovered before it is
> needed. Persist outbound incident records to a durable queue so that a
> channel outage delays notification rather than losing it, and make the
> replay idempotent using the incident identifier from L-C3.
>
> **Tradeoff.** Real redundancy roughly doubles integration cost and adds
> a split-brain problem (both channels deliver, agency sees two
> incidents) — solved by the same identifier that solves L-C3.
>
> **In this build: n/a in sim**, but worth stating in the design because
> it is an architectural commitment, not a deployment detail.

---

## 5. Stage D — Corridor computation and the cost function

Corridor *internals* are catalogued. This section covers the layer that
*invokes* the corridor and the cost function that chooses the route.

### L-D1 — A weighted-sum cost function is the trap this project has fallen into three times

> **Loophole.** The described cost is
> `w₁·travel_time + w₂·congestion + w₃·route_safety`. Travel time is in
> seconds. Congestion is dimensionless or in vehicles. Route safety is in
> "anomalies near the path". Summing them requires weights that convert
> between incommensurable units, and those weights get chosen by hand.
>
> **Risk.** This project's own history is the argument. `PROGRESS.md`
> records three separate defects of exactly this shape: M4's `S(p)`, M5's
> `lost_time_weight`, and M7's `D(p)` — the last reaching a magnitude of
> 44.9 against a pressure-scale median of 0.21 and costing **+68,750
> person-delay** before it was caught. The lesson recorded at the time
> was *"dimensional agreement is not magnitude agreement"*. A fourth
> weighted sum, with a term whose units are even less well-defined than
> the previous three, is the same defect scheduled in advance.
>
> **Mitigation.** Reformulate as a **constrained shortest path**:
> minimise travel time **subject to** hard safety constraints — never
> route through an edge closed by an incident, never within X metres of
> an active fire, never through a flooded segment. Constraints are
> auditable ("we did not route past the fire") in a way weights are not
> ("we assigned fire a weight of 3.2"). This is the settled position in
> the HAZMAT routing literature, which spent two decades on exactly this
> question and largely moved from scalarised risk-cost sums to
> constrained and Pareto formulations
> ([Erkut & Verter, *Modeling of Transport Risk for Hazardous
> Materials*, Operations Research 46(5),
> 1998](https://pubsonline.informs.org/doi/10.1287/opre.46.5.625)). Where
> a genuine tradeoff must be exposed, compute the **Pareto front** over
> (time, risk) and let a human or an explicit policy pick a point —
> never a hand-tuned scalar.
>
> **Tradeoff.** Constrained shortest path is more expensive than Dijkstra
> and can be infeasible (see L-D2). Pareto enumeration is more expensive
> still. Both are affordable at this network's size; neither is at
> city scale without preprocessing.
>
> **In this build: partial and, as it happens, better than the design.**
> `dispatcher.choose` minimises travel time alone with capability as a
> **hard filter** — which is already the constrained formulation, applied
> to capability rather than safety. Extending the same pattern to safety
> is a smaller change than adding a weighted term, and a safer one.

### L-D2 — Every route passes near an anomaly

> **Loophole.** Hard constraints can be infeasible. On a corridor cut by
> a river with limited crossings, one incident on a bridge approach can
> make every capable facility unreachable under the constraint.
>
> **Risk.** Two bad outcomes and one good one. Bad: the router returns
> nothing and the responder is not dispatched. Worse: the implementation
> silently relaxes the constraint and routes past the fire *without
> saying so*, which is the same as not having the constraint except that
> now it is invisible.
>
> **Mitigation.** Make infeasibility an explicit, typed outcome that a
> caller must handle, and define the relaxation ladder in advance:
> (1) tighten to the least-violating path, (2) surface it to a human with
> the specific violated constraint named, (3) record the override and who
> owns it. `dispatcher.choose` already sets this precedent by returning
> `None` rather than falling back to `general`, with the reasoning stated
> in its docstring: *"we could not reach an ophthalmic facility so we sent
> them to a general one" must be a decision someone owns*. The same
> sentence applies verbatim to safety constraints.
>
> **Tradeoff.** Requiring a human on infeasibility adds latency exactly
> when the network is most disrupted. The alternative is an automated
> system quietly deciding how close to a fire is close enough.
>
> **In this build: built for capability, absent for safety.**

### L-D3 — Stale traffic data, and the objective that hides it

> **Loophole.** Congestion state is sampled, and by the time the route is
> computed it describes the past. Separately: `findRoute` returns
> *expected* travel time, and the corridor is chosen to minimise it.
>
> **Risk.** The stale-data problem is well understood and bounded by TTL.
> The objective problem is not, and it is bigger. **Minimising expected
> travel time is the wrong objective for an emergency vehicle.** A route
> with mean 8 min and sd 1 min beats one with mean 7 min and sd 5 min for
> any patient with a deadline, and expected-time routing picks the second
> one every time. The right objective is Nie & Wu's **stochastic on-time
> arrival**: maximise P(arrive ≤ T) ([Nie & Wu, *Shortest path problem
> considering on-time arrival probability*, Transportation Research Part
> B 43(6):597–613,
> 2009](https://www.sciencedirect.com/science/article/abs/pii/S0191261509000174)).
>
> **Mitigation.** Timestamp every edge-cost sample and refuse to route on
> samples older than a TTL, degrading to historical profiles rather than
> using stale live data — historical is *known* to be approximate, stale
> live data is approximate while claiming to be current. Then, for the
> objective: estimate per-edge travel-time *variance* alongside the mean
> and adopt an on-time-arrival objective, or as a cheap approximation
> minimise a reliability-weighted cost `mean + k·sd`. Note that a green
> corridor's whole effect is to *reduce variance* — signals stop being a
> random draw — so a variance-blind objective cannot see the benefit of
> the thing this project builds.
>
> **Tradeoff.** Variance estimation needs history and more computation,
> and SOTA routing is substantially more expensive than Dijkstra. The
> `mean + k·sd` approximation captures most of the benefit at almost no
> cost and is the sensible first step.
>
> **In this build: absent** — `traci_route_fn` returns
> `result.travelTime`, an expected value, and this is arguably the single
> most defensible upgrade available to the dispatch layer.

### L-D4 — A new anomaly appears on a committed route

> **Loophole.** The corridor is granted, the responder is moving, and a
> second incident opens on an edge ahead of it.
>
> **Risk.** The responder is driven into the new incident, or the
> corridor holds junctions for a route that is no longer passable.
>
> **Mitigation.** The engine half of this is **built**:
> `ReleaseReason.ROUTE_CHANGED` exists, the engine treats the route as a
> live quantity it is *told*, and a re-route needs no cooperation from it
> beyond the next position report. What is missing is the *trigger* —
> nothing subscribes the dispatch layer to new incidents on committed
> routes. That is a publish-subscribe wiring job, not a redesign: index
> committed routes by edge, and on a new incident, look up which
> committed routes touch its edges and re-evaluate only those.
> `should_redispatch` then applies its existing hysteresis so a marginal
> re-route does not flap.
>
> **Tradeoff.** Re-routing mid-transit confuses a crew who were told
> where they were going. Mitigate by requiring a *material* improvement
> (the existing 30 s threshold) and by pushing the change to the vehicle
> rather than silently changing the corridor under it.
>
> **In this build: partial** — release mechanism built, invalidation
> trigger absent.

### L-D5 — Corridor authority is a Python dictionary

> **Loophole.** `CorridorEngine.authorize(vehicle_id, priority)` is the
> only gate. In simulation the injector populates it. In deployment,
> nothing described establishes that a vehicle claiming to be an
> ambulance is one.
>
> **Risk.** Anyone who can forge a request gets a green corridor. The
> deployed precedent is not encouraging: Ghena, Beyer, Hillaker, Pevarnek
> and Halderman (USENIX WOOT 2014) examined a Michigan deployment of just
> under a hundred signals with the road agency's cooperation —
> demonstrating in the field at a single intersection — and found the
> network unencrypted, devices on default credentials that on some
> hardware *could not be changed*, and a controller exposing a known
> VxWorks debug port. The malfunction management unit prevented
> conflicting greens but did not prevent denial of service via "safe
> configurations" such as all-way
> red.([USENIX](https://www.usenix.org/system/files/conference/woot14/woot14-ghena.pdf))
>
> **Mitigation.** Authenticate the *request*, not the *vehicle type*:
> signed messages under a certificate hierarchy with per-vehicle
> credentials and revocation (IEEE 1609.2 / SCMS is the standardised
> answer). Then — and this is the part usually skipped — recognise that
> **signatures do not solve position falsification**. A genuine
> certificate on a spoofed position is valid and wrong. Add plausibility
> checking: is the claimed position on a drivable edge, consistent with
> the previous report, at a feasible speed, and corroborated by
> infrastructure detection? This is the misbehaviour-detection literature
> ([VeReMi and its extension, van der Heijden et al.](https://veremi-dataset.github.io/))
> and it is the layer that catches what cryptography cannot.
>
> Two cheap architectural defences worth more than they cost: the
> **safety kernel already cannot be bypassed** — a forged request can at
> worst obtain a *legal* phase change, never an unsafe one — and the
> rolling-hour **budget** bounds how much damage a forged identity can do
> before it runs out of credit.
>
> **Tradeoff.** Certificate infrastructure is a real operational burden
> (issuance, rotation, revocation latency, offline vehicles). Plausibility
> checks add false rejections of genuine vehicles in GPS-poor
> environments — which, in a dense Indian city centre, is `E14`'s urban
> canyon, and common.
>
> **In this build: n/a in sim** for the cryptography; the budget and the
> kernel are **built** and are the reason a forged request is bounded
> rather than unlimited.

### L-D6 — Clearing one corridor jams the network around it

> **Loophole.** Preemption does not create capacity. It moves green time
> from the cross street to the corridor, and the cross street's queue
> does not evaporate.
>
> **Risk.** Measured, not hypothetical: §1.3's Reno result (worse on
> *all five* exit strategies) and MMITSS's system-wide delay increases of
> up to 10.6% for transit priority alone. This is catalogued `H9`, whose
> argument is that reporting EVP as a mean is the operation that makes
> its cost invisible.
>
> **Mitigation.** Three, in increasing order of ambition. (1) **Bound
> it** — the rolling-hour budget and per-junction dwell caps already do
> this, and J2735's `maxPresence` / `reserviceLocked` are the standard's
> vocabulary for the same. (2) **Repay it** — the debt ledger exists to
> return green time to the movements a preemption stopped. (3) **Measure
> the distribution, never the mean** — the M7 gate already reports
> person-delay, p95 and max wait separately for exactly this reason, and
> the re-measured gate found the corridor arm *reduces* worst individual
> wait by 10.1% against reactive while cross-street person-delay stays
> indistinguishable.
>
> **The scaling caveat that matters.** Those M7 numbers are four
> emergency vehicles in thirty minutes on one corridor. An
> auto-dispatching city-wide pipeline changes the preemption *rate* by
> orders of magnitude, and none of the measured results transfer. Before
> claiming the pipeline is affordable, re-run the gate at the preemption
> rate the pipeline would actually generate — which requires an incident
> arrival model, which requires §1.7's base rates.
>
> **In this build: built and measured** at one scale, **unvalidated** at
> the scale the pipeline implies.

### L-D7 — Pedestrians and cross traffic during preemption

> Catalogued in full as **category B** (pedestrian hazards) and
> **category A** (signal display and driver expectancy). Not restated.
>
> Two things the *pipeline* adds that the catalogue does not cover.
> First, **frequency**: category B's mitigations are correct per event,
> and an auto-dispatching pipeline raises the event rate — which converts
> a rare hazard into a routine one without changing any single event's
> analysis. Second, **this network has no pedestrian phases at all**, so
> every category B mitigation is unit-tested against synthetic junctions
> and unexercised by any corridor run. In a tier-1 Indian city with heavy
> mid-block pedestrian movement that is the largest single gap between
> the simulation and the thing being simulated.
>
> **In this build: built and unexercised.** See
> `green_corridor_algorithm.md` §7.

---

## 6. System level

### L-S1 — Many simultaneous incidents

> **Loophole.** The design implicitly assumes incidents are rare enough
> to handle one at a time. Monsoon flooding, a festival, a multi-vehicle
> pile-up in fog: incidents arrive correlated, not independently.
>
> **Risk.** Correlated arrivals defeat capacity planning done on average
> rates. Every corridor competes with every other, the budget is
> exhausted, and the system's behaviour under the load it was built for
> is untested — which is the load that matters.
>
> **Mitigation.** Define and test a **saturation policy** explicitly:
> when demand exceeds what the network can grant, what gets refused, in
> what order, and who is told. Priority-ordered admission control at the
> dispatch layer, not at the junction. Load-test at 10× and 100× the
> nominal incident rate and publish where it breaks — a documented
> breaking point is an engineering result; an undocumented one is an
> outage.
>
> **In this build: absent** at the pipeline level; arbitration exists at
> the junction level for the vehicles that are already committed.

### L-S2 — Camera feeds and location tracking under Indian law

> **Loophole.** The pipeline processes continuous video of public space
> and tracks vehicle locations. Both are personal data when individuals
> are identifiable.
>
> **Risk — and it runs the opposite way to intuition.** India's **DPDP
> Act 2023 s.17(1)(c)** exempts processing "in the interest of
> prevention, detection, investigation or prosecution of any offence"
> from Chapters II and III, and **s.17(2)(a)** disapplies the Act in
> respect of processing "by such instrumentality of the State as the
> Central Government may notify, in the interests of sovereignty and
> integrity of India, security of the State, friendly relations with
> foreign States, maintenance of public
> order".([DPDP Act s.17, Indian Kanoon](https://indiankanoon.org/doc/180784190/))
> The **DPDP Rules 2025** were notified on **14 November 2025** with an
> eighteen-month phased compliance
> period.([PIB](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf))
>
> So the risk is *not* non-compliance. A police-operated traffic system
> will very likely fall inside the exemption. The risk is that **the law
> will not force the design to be accountable, so the design has to
> choose to be** — and a system that retains identifiable video
> indefinitely, with no purpose limitation and no audit trail, is one
> disclosure away from being a surveillance programme that happened to
> start as a traffic project. This has been the substance of Indian
> criticism of the Act's State exemptions.([Scroll](https://scroll.in/article/1054722/indias-data-protection-law-does-little-for-privacy-while-bolstering-the-states-surveillance-powers))
>
> **Mitigation.** Design to the exemption you *don't* need: process at
> the edge and emit events rather than shipping raw frames; retain video
> only as long as an open incident requires and delete on a timer;
> separate the incident-detection pipeline from any identity-resolving
> capability (ANPR, face) by an access-controlled boundary with logging;
> and publish a retention schedule. Note that none of this costs
> detection accuracy — it costs storage convenience.
>
> *I am not a lawyer and this is not legal advice. The statutory text is
> cited so it can be checked; the Puttaswamy proportionality standard and
> current ANPR/facial-recognition case law were not researched in this
> pass and should be before any claim is made in a report.*
>
> **In this build: n/a in sim.**

### L-S3 — Liability when the automation is wrong

> **Loophole.** A corridor is granted on a false detection, a cross-street
> vehicle collides during the phase change, and the question is who
> decided.
>
> **Risk.** Catalogued in outline as category `H`. The pipeline sharpens
> it: with a human dispatcher in the loop, the human decided. With
> automatic detection→notification→corridor, *nobody* decided, and the
> chain of reasoning that produced the preemption exists only in logs.
>
> **Mitigation.** Make every automated decision reconstructible after the
> fact: log the detection with its confidence and source, the
> classification with its alternatives, the dispatch with what else was
> considered, and the corridor grant with which interlocks passed. The
> corridor engine already does the last part well —
> `DispatchDecision.considered` / `unreachable` / `runners_up` exist
> specifically so a decision can be told apart from a lack of choice,
> and the release-reason distribution records *why* each junction was
> given back. Extend that discipline upstream. Separately, keep a human
> in the loop for the *irreversible* step: preemption is reversible,
> dispatching a unit is expensive but recoverable, and the design should
> be explicit about which step it will not take without a person.
>
> **In this build: built** for the corridor and dispatch stages,
> **absent** above them.

### L-S4 — Graceful degradation

> **Loophole.** Detection offline, CAD unreachable, TraCI/controller link
> down, ICCC down. Four independent components, and the design describes
> behaviour only when all four work.
>
> **Risk.** Undefined behaviour on partial failure is how a traffic
> system ends up in an unsafe or absurd state — holding a corridor for a
> vehicle it can no longer see, or refusing all preemption because one
> subsystem is quiet.
>
> **Mitigation.** Define the fallback per component *before* it fails,
> and make each fallback a state the system can be tested in:
>
> | Component down | Required behaviour |
> |---|---|
> | Detection | Pipeline idle; signals run adaptive control unchanged |
> | Classification | Route to a default multi-agency response, flagged |
> | Notification | Queue durably, escalate to operator, no corridor |
> | Corridor engine | Signals fall back to A-CA-MP, then fixed-time |
> | Central link | Junctions run locally on last-known plan |
>
> The bottom two are **built** and this is the project's strongest
> existing property: the arbitration ladder degrades through adaptive to
> fixed-time to the cabinet's own failsafe, and the interlocks sit below
> all of it. The top three do not exist. The principle to carry upward is
> the one the corridor engine already follows — *never propose a plan the
> interlocks will reject*, because rejection commands all-red — whose
> generalisation is that **every layer's failure must land in a state the
> layer below can handle**, not in an exception.
>
> **In this build: built** below the corridor, **absent** above it.

---

## 7. If it were up to me, in this order

Ranked by risk reduced per unit of work, not by interest.

1. **L-A1 / L-B3 — confidence end-to-end and a published operating
   point.** Cheap, and every other mitigation depends on the incident
   record carrying uncertainty. Without it the rest is decoration.
2. **L-C1 — the notification state machine.** Adopting EIDD's field
   structure and J2735's status vocabulary costs a week and turns
   eventual CAD integration into a mapping exercise.
3. **L-D3 — on-time-arrival objective.** `mean + k·sd` is a small change
   to `dispatcher.choose`, and it is the change that makes the corridor's
   own benefit *visible to the router*, since variance reduction is
   precisely what a green corridor produces.
4. **L-D1 / L-D2 — safety as a hard constraint with an explicit
   infeasibility path.** Extends the existing capability-filter pattern
   rather than adding a fourth weighted term.
5. **L-D4 — the invalidation trigger.** The expensive half is already
   built; this is pub-sub wiring.
6. **L-D6 scaling caveat — re-run the gate at pipeline-realistic
   preemption rates.** Until this is done, "the corridor is affordable"
   is a claim about four vehicles in half an hour.
7. **L-C3 / L-C4 — deduplication and alert tiering.** Matter enormously
   in deployment, not at all in simulation. Worth designing, not worth
   building yet.

---

## 8. Cross-reference to the hazard catalogue

Items here that are the *upstream* face of an existing hazard:

| This document | Existing hazard | Relationship |
|---|---|---|
| L-B2 (converging responders) | `D11`, `F8` | Solve by assignment upstream; catalogue handles arbitration downstream |
| L-C1 (corridor before a vehicle exists) | `G4` | Same waste, one stage earlier |
| L-D4 (route invalidated mid-transit) | `ReleaseReason.ROUTE_CHANGED` | Mechanism catalogued and built; trigger is new |
| L-D5 (authentication) | category `E` (request integrity), `E14` | Catalogue covers degraded detection; forged identity is new |
| L-D6 (cascading jams) | `H9` | Catalogue's argument, applied at pipeline scale |
| L-D7 (pedestrians) | category `B`, category `A` | Wholly catalogued; only the frequency change is new |
| L-S3 (liability) | category `H` | Sharpened by removing the human decision-maker |

Genuinely new categories, with no catalogue representation: **all of
§3 (classification)** and **all of §4 (notification and dispatch)**.

---

## 9. Decisions I have not taken

Per your instruction, these are flagged rather than settled. Each changes
what gets built.

1. **Is route safety a hard constraint or a weighted term?** I argue hard
   (L-D1) on the evidence of this project's own three scale-mismatch
   defects, but a hard constraint makes infeasibility a real operational
   state you then have to handle.
2. **Does the dispatch objective change from expected travel time to
   on-time-arrival probability?** This changes what the gate measures and
   would invalidate direct comparison with the recorded M7 numbers.
3. **Who owns the false-dispatch rate, and what number is acceptable?**
   Everything in §2 and §3 is downstream of this, and it is a policy
   answer, not a technical one.
4. **Is the notification stage modelled in simulation at all,** or
   stipulated as an interface with a latency distribution? Modelling it
   is weeks; stipulating it is a paragraph and an assumption to defend.
5. **Do privacy and liability belong in the capstone's scope,** or are
   they a "future work" section? They are real, and they are also a large
   amount of writing that is not engineering.
6. **Is the station→scene leg in scope?** It is the leg this pipeline
   actually describes, and the OSM extract has no fire or ambulance
   station in it — so it needs either an agency station list or
   deliberately placed synthetic depots.

---

## Sources

- [NTCIP 1211 v02, *Object Definitions for Signal Control and Prioritization*](https://www.ntcip.org/file/2018/11/NTCIP1211-v0224j.pdf) — PRG/PRS/CO split; "a CO cannot be commanded to service a priority request"
- [SAE J2735 SSM message structure and `prioritization_response_status` enumeration](https://kitt.hexdocs.pm/Kitt.Message.SSM.html) — `granted` / `rejected` / `maxPresence` / `reserviceLocked`
- [Xu, Tian & Wang (2023), *Evaluating the Impacts of Different Exit Strategies of Emergency Vehicle Preemption on Arterial Signal Coordination: A Case Study in Reno, Nevada*, J. Transportation Engineering Part A 149(11)](https://trid.trb.org/view/2236919)
- [USDOT, *Multi-Modal Intelligent Traffic Signal Systems (MMITSS) Impacts Assessment*](https://rosap.ntl.bts.gov/view/dot/3557/dot_3557_DS1.pdf) — TSP/FSP delay results, system-wide increases, PREEMPT not tested
- [RAC Foundation / Reed Mobility (2025), *Spoiler Alert: Is the eCall emergency alerting system fulfilling its road safety promise?*](https://www.racfoundation.org/media-centre/two-thirds-of-ecall-activations-are-false-alarms) — two-thirds of activations false; ~one third of automatic activations false
- [Emergency Response Centre Agency (Finland), *eCall … false calls burden emergency services*](https://112.fi/en/-/ecall-emergency-call-system-prevents-road-deaths-false-calls-burden-emergency-services)
- [The Joint Commission, *Sentinel Event Alert 50: Medical device alarm safety in hospitals* (2013)](https://www.kff.org/wp-content/uploads/sites/2/2013/04/sea_50_alarms_4_5_13_final1.pdf) — 85–99% of alarms need no intervention; 98 events, 80 deaths
- [NENA, *ANSI-Approved Emergency Incident Data Object (EIDO) Standard*, released 25 October 2021](https://www.nena.org/news/584569/NENA-Releases-ANSI-Approved-Emergency-Incident-Data-Object-EIDO-Standard.htm) — the **current** standard; JSON; supersedes the EIDD line of work
- [NENA/APCO INF-005.1, *Emergency Incident Data Document (EIDD) Information Document*](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/nena_apco-inf-005.1_eidd_201.pdf) — predecessor (APCO/NENA 2.105.1-2017); incident structure, REPLACED/REPLACING/Split linking
- [Ghena, Beyer, Hillaker, Pevarnek & Halderman, *Green Lights Forever: Analyzing the Security of Traffic Infrastructure*, USENIX WOOT 2014](https://www.usenix.org/system/files/conference/woot14/woot14-ghena.pdf)
- [van der Heijden et al., VeReMi misbehaviour-detection dataset](https://veremi-dataset.github.io/)
- [Nie & Wu (2009), *Shortest path problem considering on-time arrival probability*, Transportation Research Part B 43(6):597–613](https://www.sciencedirect.com/science/article/abs/pii/S0191261509000174)
- [Erkut & Verter (1998), *Modeling of Transport Risk for Hazardous Materials*, Operations Research 46(5):625–642](https://pubsonline.informs.org/doi/10.1287/opre.46.5.625)
- [Kauvery Hospital, *Ready, Steady, Go!!! A brief on Green Corridor activation in Organ Transplantation*](https://www.kauveryhospital.com/kauverian-scientific-journal/ready-steady-go-a-brief-on-green-corridor-activation-in-organ-transplantation/) — Chennai 12.5 km / 6 min; Vijayawada 15.2 km / 7 min
- [MoRTH, *Road Accidents in India 2023* — reported figures](https://www.business-standard.com/india-news/india-road-accidents-deaths-injuries-report-road-highway-ministry-nitin-gadkari-125082801527_1.html) — 480,583 accidents; 172,890 deaths
- [DT Next, 108 ambulance response times, Tamil Nadu, July 2023](https://www.dtnext.in/news/tamilnadu/overall-response-time-of-108-ambulances-drops-in-last-one-year-727237)
- [Digital Personal Data Protection Act 2023, Section 17 (exemptions) — statutory text](https://indiankanoon.org/doc/180784190/)
- [PIB, *DPDP Rules, 2025 Notified* (14 November 2025)](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf)
- [Scroll.in, on the DPDP Act's State exemptions and surveillance powers](https://scroll.in/article/1054722/indias-data-protection-law-does-little-for-privacy-while-bolstering-the-states-surveillance-powers)

**Verification.** Every numeric and citation claim above was re-checked
against its primary source by a separate pass that had not seen this
document written. It found four errors, all now corrected and recorded
here so the correction is auditable rather than invisible: the Ghena et
al. field demonstration was at **one** intersection, not the ~100-signal
deployment it examined; the DPDP State-instrumentality exemption is
**s.17(2)(a)**, not 17(2)(b); **EIDO supersedes EIDD** and is what a
report should cite; and a claim that EIDD tracks incident state changes
by sequence number could not be corroborated and has been removed rather
than defended.

**Unverified in this pass, flagged rather than asserted:** NFPA 1225 /
NENA call-answering time requirements (L-C2); the Puttaswamy
proportionality standard as applied to ANPR and facial recognition
(L-S2); quantitative AID detection-rate / false-alarm-rate / mean-time-to-detect
figures for specific algorithms — PIARC's overview confirms AID has "had
mixed success, primarily because of their relatively high false-alarm
rates" but publishes no numbers.

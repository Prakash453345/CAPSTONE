I've completed the research across FHWA, MUTCD, NCHRP, NEMA/NTCIP, ITE, state DOT manuals, NTSB reports, and the academic literature. Here is the catalogue.

---

# Emergency Vehicle Preemption / Green Corridor Control: Exhaustive Hazard & Edge-Case Catalogue

## 0. Normative baseline (what the standards actually require)

These constrain every mitigation below. From MUTCD 11th Edition §4F.18–4F.19 (identical text in 2009 MUTCD §4D.27, verified via CA MUTCD 2026 Ch. 4F and Delaware's adoption):

- **Entry:** "During the transition into preemption control, the yellow change interval, and any red clearance interval that follows, shall not be shortened or omitted." (Standard)
- **Pedestrian:** "Any pedestrian walk interval and/or pedestrian change interval may be shortened or omitted." (Option) — note this permits omitting the *flashing DON'T WALK* too, which is the root of several hazards below.
- **During and exit:** "Any yellow change interval, and any red clearance interval that follows, shall not be shortened or omitted." (Standard)
- **Prohibited sequence:** "A signal indication sequence from a steady yellow signal indication to a green signal indication shall not be permitted." (Standard)
- **Permitted exception:** red clearance may be omitted where the display returns to the *previous* green after a steady yellow.
- **Priority order (Guidance):** train → boat → heavy vehicle (fire apparatus / ambulance) → light vehicle (law enforcement) → light rail transit → rubber-tired transit. Rationale: "a vehicle that is more difficult to control supersedes" one easier to control.
- **Priority control (as distinct from preemption):** pedestrian walk interval **shall not** be shortened below the minimum and **shall not** be omitted unless the vehicular phase is also omitted. This is stricter than preemption.

NEMA TS2 controller behaviour (Montgomery County MD TS2 specification): six railroad/fire/emergency preemptor sequences plus four bus preemptors; "Priority preemptor calls shall override non-priority preemptor calls. **Low-numbered priority preemptors shall override higher-numbered** priority preemptor calls"; non-priority calls served in order received; bus preemptors lowest and overridden by all EV/rail preempts; bus preemptors have a **re-serve timer** that blocks re-service if a call arrives too soon.

Scale of the safety problem: >25% of all emergency-vehicle crashes occur at signalized intersections (FHWA cross-cutting study). St. Paul reported a 71% reduction in EV crashes post-EVP; Plano went from 7 signalized-intersection crashes (1981–83) to 4 in the following 20+ years.

---

## A. Signal-display and driver-expectancy hazards

**A1. Yellow trap on preemption entry (the canonical case).**
*Trigger:* Arterial is running concurrent through movements with permissive or protected/permissive left turns (circular green or FYA). A preempt call arrives; the controller terminates **one** direction's through movement to reach the preempt phase while **retaining** the opposing through green (because the opposing through is part of the preempt/track-clearance phase, or because the phase pair is asymmetric).
*Mechanism:* The waiting left-turner sees his own display go circular-green → yellow. Drivers' learned model is "yellow on my head means yellow on theirs." He commits to the left turn during yellow/early red. Opposing through traffic still has green and does not slow. Result is a left-turn-across-path/opposite-direction collision at full closing speed — the highest-severity conflict at a signalized intersection.
*Mitigation:* WisDOT's rule is the cleanest statement of the fix: **"exit all phases (ensuring min green as well as full yellow and all red clearance are displayed) before initiating the track clearance phase"** — i.e. force a clean all-red break so no through movement is carried across the transition. Alternatives: FYA overlaps programmed to drop with the opposing through; Dallas/Arlington phasing; protected-only lefts during preemption.

**A2. Yellow trap on preemption exit.**
*Trigger:* Same asymmetry re-created on the way out, when the controller jumps to an exit phase that reintroduces one direction's green while the other terminates.
*Hazard:* Identical LTAP/OD crash, but with worse expectancy — cross traffic that has been sitting on red for 25+ seconds is impatient and launches early.
*Mitigation:* Constrain exit phases to full phase-pair transitions with all-red separation; never exit directly into a half-served concurrency. Note the MUTCD prohibits yellow→green, but that alone does **not** prevent yellow trap.

**A3. Lagging protected/permissive left turn phasing.**
*Trigger:* Any lagging prot/perm left, preemption or not; preemption makes it worse because the sequence is irregular.
*Hazard:* WisDOT: "Lagging protected/permissive left turn phasing **shall not** be utilized as it creates a dangerous situation often referred to as a 'left turn trap' or 'yellow trap'." Exceptions: T-intersections, ramp terminals without opposing lefts, and when FYA is used.

**A4. Asymmetric termination via trailing overlaps / pre-signals.**
*Trigger:* Track-clearance or preemption phases implemented as overlaps, where the overlap runs 3–4 seconds longer than the parent phase.
*Hazard:* Purdue: drivers turning left "may misjudge opposing traffic phase duration, assuming it ends when the pre-signal phase ends, but it continues 3–4 seconds longer."
*Mitigation:* Use **dummy phases** (never displayed) on trailing overlaps so all heads terminate together.

**A5. FYA permissive left not dropped at preempt entry.**
*Trigger:* FYA overlap logic tied to opposing through; preempt sequence retains the opposing through green.
*Hazard:* The left-turn driver keeps a *flashing yellow arrow* (an explicit "proceed with caution" invitation) while the intersection is being cleared for an emergency vehicle that is about to enter at speed on a conflicting path.
*Mitigation:* Force FYA overlaps to red (not dark, not yellow-arrow-then-green) at preempt entry; verify overlap output states in every preempt phase, entry, dwell and exit.

**A6. Yellow-to-green revert.**
*Trigger:* Controller programmed to abandon a preempt sequence mid-yellow and return to green.
*Hazard:* Explicitly prohibited by MUTCD; a driver who committed to stopping is now facing green with a vehicle behind him decelerating — rear-end conflict, plus complete loss of display credibility.
*Mitigation:* Standard prohibition; verify firmware cannot do this on preempt-call-drop.

**A7. Truncated yellow or red clearance at preempt entry.**
*Trigger:* Designer shortens clearance intervals to reduce right-of-way transfer time (a real temptation when RTT must fit inside a 20-second railroad minimum warning time).
*Hazard:* Vehicles still in the intersection when the conflicting green starts — right-angle crash with the emergency vehicle itself.
*Mitigation:* Prohibited by MUTCD Standard, entry and exit. The permitted lever is pedestrian time and minimum green, never vehicle clearance.

**A8. Green truncation into the dilemma zone.**
*Trigger:* Preempt call arrives while a high-speed approach (≥45 mph) has a platoon in the 2.5–5.5 second travel-time band from the stop line. Preemption applies a hard force-off; it does not consult advance detection or dilemma-zone gap-out logic.
*Hazard:* Drivers in the indecision zone can neither stop comfortably nor clear on yellow — rear-end and red-light-running crashes, aggravated because the conflicting movement is an emergency vehicle entering immediately.
*Mitigation:* Not addressed by MUTCD. Practical measures: honour a minimum green (NCHRP 507 found 55% of agencies time a minimum green of 1–7 s during preemption right-of-way transfer); allow dilemma-zone protection logic to run to a bounded max before force-off; consider advance warning flashers on high-speed EVP approaches. **Flagging this as a genuine standards gap** — the literature on dilemma zone and the literature on preemption barely intersect.

**A9. Return-to-previous-green with red clearance omitted.**
*Trigger:* MUTCD Option permits omitting red clearance where the display returns to the previously displayed green after a steady yellow (i.e., the preempt was abandoned).
*Hazard:* Cross-street drivers who began creeping on the assumption the phase was ending are now exposed.
*Mitigation:* Use sparingly; some agencies disable it.

**A10. Confirmation-light misinterpretation.**
*Trigger:* Confirmation ("notifier") indications tell EV drivers whether they hold the preempt. St. Paul convention: **solid** = you have it; **flashing** = another approach has precedence and you must yield.
*Hazard:* An EV driver who misreads flashing-as-solid enters against a conflicting emergency vehicle. This is the exact configuration behind the 1972 St. Paul fatal police-car/fire-truck collision at an EVP-equipped intersection, which prompted the city to mandate confirmation coverage on **all** approaches rather than just the two main ones.
*Mitigation:* Confirmation indications on every equipped approach; unambiguous solid/flash semantics; mandatory recurrent driver training.

**A11. Preemption-induced red-light running by the general public.**
*Trigger:* High preemption frequency on a corridor; long red holds; drivers see no vehicle arrive.
*Hazard:* WSDOT explicitly warns frequent preemptions may "encourage drivers to disobey red lights," which degrades safety for every subsequent cycle — including the next genuine preemption.
*Mitigation:* Cap preemption frequency; release preemption promptly on EV clearance rather than on a fixed timeout (see F10, H1).

**A12. Preempt request during startup / flash-to-steady transition.**
*Trigger:* Power restoration, cabinet exiting flash, or MMU reset while a preempt call is asserted.
*Hazard:* Undefined display state, or a jump into a preempt phase without a valid known prior state.
*Mitigation:* MUTCD 11th Ed. §4F.18 explicitly enumerates the permitted responses: remain dark, stay in flash, alter the flash mode, run normal startup first, or respond directly to the preempt initial/dwell period. **The design must pick one deliberately** — a system that hasn't decided has an undefined safety-critical state.

---

## B. Pedestrian hazards

**B1. Preempt call arrives mid-WALK.**
*Trigger:* Preempt asserted while a pedestrian phase is displaying WALK.
*Hazard:* If walk is omitted immediately, pedestrians who have just stepped off are in the roadway when the conflicting preempt phase turns green.
*Standard position:* MUTCD **permits** shortening or omitting the walk interval under preemption. St. Paul takes the conservative line: "the only condition for request approval is that the signal is not in a pedestrian phase" — the preempt is deferred until the ped phase completes.
*Mitigation:* Either defer preempt service until the walk interval completes (St. Paul), or truncate walk but preserve full pedestrian change interval.

**B2. Preempt call arrives mid-pedestrian-change-interval (FDW).**
*Trigger:* Preempt during flashing DON'T WALK.
*Hazard:* This is the sharp one. Pedestrians already committed mid-crossing lose their clearance time. TTI is blunt: "by shortening these intervals, some pedestrians may be trapped in the intersection facing oncoming vehicles." TTI adds: "The effect of pedestrian clearance times on preemption cannot be over emphasized!"
*Prevalence:* NCHRP Synthesis 507 found **75% of agencies routinely truncate the pedestrian interval** at rail-preempted signals.
*Mitigation:* INDOT Design Memo 25-19 (2025) moved the other way, clarifying "the pedestrian clearance interval at an intersection with railroad crossing preemption **should not be omitted or truncated** during a preemption event." Under *priority* control (not preemption) MUTCD already forbids it. Recommended: never truncate the pedestrian change interval for EVP; reserve truncation for rail preemption only where the timing analysis proves it is unavoidable, and document it.

**B3. Countdown display truncation.**
*Trigger:* Countdown pedestrian signal is displaying "12…11…10" when the interval is cut short.
*Hazard:* Display and reality diverge. Pedestrians calibrate their walking speed to the count; a count that jumps to zero or freezes destroys the one cue they trust, and it does so precisely when an emergency vehicle is arriving. NCHRP 507 records agencies declining to truncate specifically because of "accessibility and countdown display concerns."
*Mitigation:* Either don't truncate, or drive the countdown from actual remaining time and accept the visible jump — but never let it continue counting a time that no longer exists.

**B4. Blind / low-vision pedestrians and APS.**
*Trigger:* Preemption removes or alters accessible pedestrian signal audible and vibrotactile cues mid-crossing.
*Hazard:* A pedestrian relying on the audible walk indication or a locator tone loses their orientation reference mid-street, with conflicting traffic about to be released. NEMA TS2 allows ped indications during preempt to be "solid DON'T WALK, OFF, or fully operational" — the "OFF" option is the dangerous one.
*Mitigation:* Never select OFF for pedestrian outputs during preemption; maintain the pedestrian change indication and APS output through the full clearance time.

**B5. Pedestrian call lost across preemption.**
*Trigger:* A pedestrian pushbutton call is registered, then a preempt event runs, and the exit phase does not include that pedestrian movement.
*Hazard:* The call is dropped or deferred by another full cycle. In back-to-back preemption (D5) a crossing can be starved indefinitely, driving pedestrians to cross against the signal.
*Mitigation:* Ensure ped calls latch across preempt entry/dwell/exit and that exit-phase selection considers outstanding pedestrian calls.

**B6. Pedestrian pushbutton actuation during preempt dwell.**
*Trigger:* Pedestrians press repeatedly during a long hold with no feedback.
*Hazard:* No safety hazard directly, but it degrades trust in the pushbutton and produces crossing against DON'T WALK during the dwell — into the path of the emergency vehicle.
*Mitigation:* Pushbutton feedback indication that acknowledges the call even when it cannot yet be served.

**B7. Long crossings where pedestrian clearance dominates right-of-way transfer time.**
*Trigger:* Wide multi-lane crossings; pedestrian clearance can exceed 20 seconds.
*Hazard:* On rail-preempted signals, RTT = yellow + red + max(pedestrian clearance, minimum green). If pedestrian clearance is honoured in full, RTT may exceed available warning time and vehicles remain on the tracks. TTI notes full clearance "can exceed 20 seconds on large intersections."
*Mitigation:* This is a **design-time geometry problem, not a runtime one.** ITE RP-025D and NCHRP 507 mitigations: request advance preemption time from the railroad, relocate or remove the pedestrian crossing, use pre-signals or queue cutters — rather than solving it by truncating pedestrians at runtime.

**B8. Exit-phase pedestrian service released into a still-approaching second EV.**
*Trigger:* Preempt drops (EV cleared), exit phase serves a pedestrian movement, and a second EV is inbound but its call has not yet been detected.
*Hazard:* Pedestrians in the crosswalk when the second preempt hits, now facing B2 with no walk time already banked.
*Mitigation:* Inhibit pedestrian service during a configurable post-preempt guard interval on high-preemption corridors; or make the exit ped decision conditional on no active or recently-dropped calls.

---

## C. Railroad and light-rail grade crossing interaction

This is the most mature failure-mode literature in the field; treat it as the reference model.

**C9 numbering note:** all timing terms below are per TTI Report 1439-9 and TxDOT's Rail-Highway Operations Manual.

**C1. Advance preempt trap.**
*Trigger:* Advance preemption gives the signal controller a head start (e.g. 15 s) before the crossing warning devices activate. The actual advance preemption time varies (train decelerates after detection). If the preempt call arrives while the controller is *already* in the track-clearance phase, right-of-way transfer time is effectively zero.
*Mechanism:* Track clearance green expires **before** the gates start descending. Drivers, seeing no warning devices active, drive onto the crossing. Preemption hold then displays red and they are trapped on the tracks.
*Hazard:* Vehicle struck on the crossing — this negates the preemption entirely and is worse than not preempting.
*Mitigation (NCHRP 507, TTI, Purdue, TxDOT):* (a) **gate-down confirmation circuit** — hold track clearance green until the gates are horizontal, then time a final clearance; (b) two preempt inputs per train arrival (early preempt to run vehicle/pedestrian clearance, later simultaneous preempt to time the track clearance phase); (c) increase track-clearance green by the full advance preemption time; (d) "not-to-exceed" timer forcing warning-device activation; (e) a dedicated track clearance phase that bounds minimum RTT.

**C2. Failed preempt trap (interconnect failure).**
*Trigger:* Interconnect wire between crossing and controller breaks or is cut. Normally-closed (fail-safe) design de-energises the preempt input.
*Mechanism:* The signal preempts and clears vehicles across the crossing while the **railroad warning devices remain inoperative**. Purdue: this "creates a false sense of security — worse than no preemption."
*Mitigation:* **Three-wire supervised circuits** requiring 2-of-3 wires live; a cut blows a fuse and triggers a distinct failed-preempt sequence (all-red flash) rather than normal operation. TxDOT: "supervised circuit... can send the traffic signal into flash if the connection is broken." Also a maximum-preempt-duration timer that assumes circuit failure and reverts to flashing red. **Note the two-wire vulnerability:** NCHRP 507 found 55% of agencies use unsupervised two-wire circuits, which "can be compromised if the two wires are shorted together."

**C3. Second train trap.**
*Trigger:* First train clears, gates begin to rise, drivers begin crossing; a second train's preempt is still asserted or re-asserts.
*Mechanism:* Signal remains in preemption hold displaying red; vehicles that entered the crossing during the gate-rise are trapped as the second train arrives. Variant: gates begin rising then reverse mid-travel, which drivers do not expect.
*Mitigation:* Second-train-coming logic — the controller must recognise a subsequent preempt call and **restart the full sequence** (RTT + track clearance green), not resume hold. NCHRP 507: only **20% of agencies use second-train logic** on new or upgraded systems.

**C4. Second preempt call ignored during exit/transition.**
*Trigger:* A new preempt arrives while the controller is executing its exit sequence or coordination transition.
*Hazard:* TTI: some controllers "will ignore this second preemption input if it occurs during the return to normal operations, **which could lead to skipping the clear track interval**." Direct analogue exists for EVP (see D5).
*Mitigation:* Firmware verification; explicit test case; a call-latching design that guarantees re-entry from any state.

**C5. Train stopped at a station / switching operations.**
*Trigger:* Train stops within the approach circuit (station adjacent to the crossing, or yard switching).
*Hazard:* Indefinite preemption hold; corridor gridlock; drivers eventually drive around gates.
*Prevalence:* NCHRP 507: 45% of agencies have stations near crossings; only 32% make special provisions. Portland case: railroad design value 77 s vs crossing order value 67 s because of switching variability.
*Mitigation:* Timeout/restart procedures; some agencies hold gates down deliberately; limited-service cycling during hold.

**C6. Constant-warning-time prediction error.**
*Trigger:* CWT devices predict arrival from speed at detection; trains accelerate or decelerate afterwards.
*Hazard:* TTI cites a study where CWT provided "as much as 5 seconds less than the preselected minimum time." The whole preemption timing design is built on an assumption that is not guaranteed.
*Mitigation:* Buffer time (railroad-determined, typically 5 s per TxDOT) plus equipment response time (~5 s); design for **both** worst case (RTT maximum) and best case (RTT = 0).

**C7. EV preemption pulls traffic onto the tracks.**
*Trigger:* An EVP preempt at a signal near a grade crossing gives an extended green to a movement that discharges toward the crossing, or holds red on the crossing-side approach so a queue forms across the rails.
*Hazard:* The EVP system actively creates the condition rail preemption exists to prevent.
*Prevalence:* NCHRP 507: **67% of agencies allow fire preemption at rail-preemption intersections.**
*Mitigation:* Rail preempt at highest priority (TxDOT: "Railroad preemption always overrides emergency vehicle preemption"); EVP phase selection at crossing-adjacent signals must never hold a queue over the tracks; queue-cutter signals (only 34% of agencies use them).

**C8. EV preempt truncating an active track-clearance green.**
*Trigger:* Misconfigured precedence lets an EV preempt interrupt a track clearance interval.
*Hazard:* Vehicles left on the crossing. TTI's rationale for the hierarchy: "a train represents a much more serious hazard than an emergency vehicle, which would have the ability to stop quickly and/or swerve."
*Mitigation:* NEMA TS2 preempt inputs 1–2 reserved for rail; verify precedence empirically on the bench, not from the manual.

**C9. Queue spillback onto the tracks from a downstream signal (Fox River Grove).**
*Trigger:* Insufficient clear storage distance between the crossing and the downstream signalized intersection.
*Hazard:* NTSB HAR-96/02: the 1989 road widening cut storage from ~80 ft to **45 ft**; a school bus waiting for the signal had ~3 ft over the rails. Preemption gave only **6–18 seconds** of northbound green after railroad activation, "depending on whether pedestrian clearance was triggered."
*Mitigation:* ITE RP-025D reframes the trigger: "the critical factor for determining the need for preemption is **not the distance to the crossing, but the likelihood that a traffic queue will extend onto the tracks**." Pre-signals, queue cutters, storage-length verification for design vehicles including buses. NCHRP 507: 67% of agencies preempt signals beyond the MUTCD 200 ft threshold because of queue overage.

**C10. Undocumented change to railroad warning time.**
*Trigger:* Railroad adjusts a warning-time thumbwheel; highway agency is not notified.
*Hazard:* Fox River Grove: warning time was changed from 30 s to 25 s on 11 October 1995 — two weeks before the crash — with no apparent notification to IDOT. IDOT could not document how the 1990 preemption timing had been programmed.
*Mitigation:* NTSB recommended documented coordination, written specification of warning times and preemption sequences, and mandatory change-notification protocols. 49 CFR 234.261 requires monthly interconnection testing; NCHRP 507 found only **8% of agencies coordinate with the railroad's monthly testing.**

**C11. Multiple tracks / multiple clearance intervals exceeding the warning-time budget.**
*Trigger:* Tracks crossing more than one intersection approach requiring sequential clearing.
*Hazard:* TTI: total sequence "potentially exceeding 60 seconds with full pedestrian clearance," against an AREMA 3.1.10 maximum preemption warning time of **50 seconds.**
*Mitigation:* Trim timing (including pedestrian intervals), relocate pedestrian crossings, queue cutters, or request additional railroad warning time.

**C12. Light rail preemption gaps and the LRT-operator expectancy failure.**
*Trigger:* LRT shares the corridor; an EV preempts a signal at an LRT crossing.
*Hazard:* Hillsboro, Oregon, 2 January 2005: a fire engine's Opticom changed the signal at the tracks to green two blocks out and "once the light was changed, it held." A MAX light rail train collided with it. The LRT operator "was viewing right-of-way indications from **downstream** signals and failed to realize that preemption had occurred." A 55-ton train at 10–15 mph needs ~50 ft to stop. Signal records confirmed the preemption system "was functioning properly" — this was an expectancy/human-factors failure, not an equipment failure.
*Mitigation:* LRT-specific indications per MUTCD §8D.15; ensure LRT operators receive an in-cab or wayside indication tied to the *governing* signal, not a downstream one; explicit conflict resolution between LRT and EVP.
*Prevalence:* NCHRP 507: only 27% of agencies have LRT preemption; 31% have written LRT preemption practices.

---

## D. Multi-request arbitration

**D1. Two EVs, conflicting approaches, near-simultaneous.**
*Trigger:* Fire apparatus northbound and ambulance eastbound both assert within a second or two of each other.
*Hazard:* The single most dangerous EVP scenario. Both crews believe they hold the intersection; both enter against the general public who have also stopped. EMS World states the operational reality: "when two or more emergency vehicles reach the intersection at one time, **preemption is only given to one vehicle**." This produced the 1972 St. Paul fatality.
*Mitigation:* (a) Deterministic arbitration — NEMA TS2: low-numbered priority preemptor overrides higher-numbered; non-priority calls served in the order received. (b) **Confirmation indications on every approach**, solid = you have it, flashing = you must yield. (c) Training rule: absent a solid confirmation, come to a complete stop. (d) Coverage on all approaches, not just the two main ones (the explicit St. Paul lesson).

**D2. Two EVs, opposite directions, same corridor.**
*Trigger:* Both request the same phase pair from opposing approaches.
*Mechanism:* Not a phase conflict — both are served by the same green. But if the phase includes a **permissive left**, the two EVs are on a head-on/left-turn conflict path with each other, and each has a green.
*Hazard:* EV-to-EV LTAP/OD, exactly the A1 geometry but with both vehicles moving at emergency speed. Also: preempt hold is extended by the second call, so the corridor is held far longer than either EV needs.
*Mitigation:* Protected-only left turns (or lefts prohibited) during EVP dwell; per-approach confirmation so each crew knows another EV holds the opposing approach; log dual-approach events and review.

**D3. Two EVs, same approach, divergent turns.**
*Trigger:* Two units on the same approach, one continuing through, one turning left across the opposing through.
*Hazard:* The preempt phase serves the through movement; the turning unit has no protected path but has been given a green and a confirmation.
*Mitigation:* Route-aware preemption (request specifies desired movement, not just approach); otherwise treat all preempt phases as through-only and train crews accordingly.

**D4. Higher-priority preempt arrives mid-sequence.**
*Trigger:* Rail preempt asserts during an active EV preempt (or fire during police).
*Hazard:* If the controller aborts the current sequence abruptly, it can produce a yellow-trap-shaped transition (A1) or truncate a clearance interval. If it *cannot* interrupt, C8 results.
*Mitigation:* NEMA TS2 supports **preemptor linking** — a lower-priority sequence can call a higher-priority preemptor upon its termination. The spec notably does **not** define mid-sequence replacement; NEMA TS2 documentation "does not explicitly detail mid-sequence preemption replacement scenarios." **This is an under-specified area: your design must define it explicitly and test it.**

**D5. Back-to-back preemption — second call during exit/recovery.**
*Trigger:* Second EV call arrives while the controller is in exit phases or coordination transition.
*Hazard:* Documented for rail (C4): some controllers **ignore** the second call during return-to-normal. For EVP, the failure is silent — the second EV gets no green, no confirmation light, and arrives at a red it expected to be green. Compounding hazard: the cross street, already starved by the first preemption, is starved again with no intervening service, producing split failures and spillback.
*Mitigation:* Guarantee call latching and re-entry from *any* controller state including transition; instrument "preempt call received but not served" as a first-class logged event; consider forcing a minimum cross-street service between consecutive preemptions on the same approach.

**D6. Equal-priority tie / first-come-first-served starvation.**
*Trigger:* Two calls at the same priority level; the controller serves in order received and latches.
*Hazard:* A continuously-asserted call (stuck emitter, E7) at a given priority permanently starves an equal-priority call from a conflicting approach.
*Mitigation:* Maximum hold/dwell timers; forced arbitration re-evaluation at fixed intervals rather than only at call drop.

**D7. Precedence-convention ambiguity across sources and vendors.**
*Trigger:* Configuring preempt input numbering.
*Hazard:* **The sources disagree.** NEMA TS2 (Montgomery County spec): "**Low-numbered** priority preemptors shall override higher-numbered priority preemptor calls." The Florida LTAP *Traffic Signal Timing 201* handout states "**Higher-numbered** inputs always override lower-numbered ones." Whichever is true for a given controller, a designer who assumes the wrong one inverts the entire safety hierarchy — e.g. giving transit priority precedence over fire.
*Mitigation:* Never take precedence from documentation. Bench-test every pairwise combination of preempt inputs before deployment. This is exactly the failure ITS lessons-learned recorded: "Traffic signal software can inadvertently grant transit priority requests **equal precedence** to emergency preemption. This requires careful verification before deployment."

**D8. Priority class assignment in practice.**
*How it is actually decided:* Three layers, and they can disagree.
- **MUTCD guidance (policy layer):** train → boat → heavy vehicle (fire/ambulance) → light vehicle (police) → light rail → rubber-tired transit. Rationale is *controllability*, not urgency — a heavier/less manoeuvrable vehicle wins.
- **Controller layer (NEMA TS2):** 6 rail/fire/emergency preemptors + 4 bus preemptors; priority > non-priority; bus lowest.
- **Detection layer (optical):** frequency-coded — **14 Hz = high priority** (emergency), **10 Hz = low priority** (transit/bus). NTCIP/controller input convention: PR1–PR2 rail, PR3–PR6 rail or high-priority emergency, PR7–PR10 low-priority emergency or transit priority.
*Hazard:* Fire-vs-ambulance-vs-police is generally **not** resolved by the standards — MUTCD lumps fire and ambulance together as "heavy vehicle" and puts police below them. Agencies must decide locally and encode it in input numbering. NCHRP 507: **71% prioritize preempts, 12% do not, 17% are unsure**; 93% make rail highest, with exceptions (one agency gives bridge lift precedence).
*Mitigation:* Written inter-agency policy signed by fire, EMS, police and the signal agency; per-vehicle ID codes so the class is verifiable in logs, not inferred.

**D9. Transit priority colliding with EV preemption.**
*Trigger:* TSP green extension in progress when an EV preempt arrives, or TSP mapped to a preempt input.
*Hazard:* TSP holds a green that the preempt needs to terminate, or (documented) TSP is granted equal precedence to EVP. Note the standards treat these differently: under *priority* control MUTCD forbids shortening the walk interval below minimum, whereas under *preemption* it permits omission — so a request routed to the wrong mechanism silently changes the pedestrian safety rules.
*Mitigation:* Route TSP through priority logic, never through preempt inputs; verify TSP yields immediately and completely.

**D10. Bus re-serve timer blocking a legitimate call.**
*Trigger:* NEMA TS2 bus re-serve timer: "If a call is received before the re-serve time has elapsed, the bus preemptor shall not be re-serviced."
*Hazard:* Benign for buses (its purpose is to cap frequency), but if EVP is ever mapped onto a bus preemptor input — a plausible integration shortcut — a genuine emergency call is silently dropped.
*Mitigation:* Never map emergency requests to bus preemptors; alarm on any suppressed call.

**D11. Corridor-level cross-conflict at adjacent junctions.**
*Trigger:* EV-A on the arterial, EV-B on a cross street, arriving at adjacent junctions within a few seconds.
*Hazard:* Junction *n* grants A, junction *n+1* grants B. A is released into a downstream junction being held for B; the corridor pumps A's platoon (and A) into a stopped condition.
*Mitigation:* Corridor-level arbitration, not per-intersection — this is the argument for route-based preemption (UMN dynamic route clearance, 10–16% EV travel-time reduction on long/complex routes) rather than independent per-junction decisions.

**D12. Confirmation ambiguity with three or more EVs.**
*Trigger:* Multi-alarm response; three units converge.
*Hazard:* Solid/flashing is a one-bit encoding. It tells a crew "someone else has it" but not *who* or *from where*.
*Mitigation:* Directional confirmation heads per approach; the Wikipedia-documented convention (solid = EV approaching from behind you; flashing = EV approaching laterally or oncoming) is more informative and should be specified explicitly.

---

## E. Detection, estimation and request-integrity failures

**E1. Outrunning the preemption.**
*Trigger:* EV arrives at the stop line before the entry sequence (minimum green + yellow + all-red + any pedestrian time) has completed. Explicitly listed as a caution in the Florida LTAP signal timing course.
*Mechanism:* Right-of-way transfer time is not a constant — it depends on where in the cycle the call lands. Worst case (phase just started, pedestrian clearance running) can be 20+ seconds; best case is zero. The EV driver, having seen the green appear at every previous intersection, does not expect the exception.
*Hazard:* EV enters against a red it assumes will turn green, into cross traffic that has a legitimate green.
*Mitigation:* Detection range sized for approach speed — Fairfax County ~1,600 ft; St. Paul uses maximum range **~2,300 ft** specifically "to accommodate police vehicles, which accelerate quickly." Plus the non-negotiable training rule: FHWA — "**A green light is not guaranteed.** Emergency vehicle drivers need to use caution not to over-rely on the system and to be prepared to stop if provision of the preemption phase is delayed." St. Paul crews reported "the main lesson learned was not to over-rely on the system and to proceed as if preemption would not be granted."

**E2. Request latency in connected-vehicle / cellular EVP.**
*Trigger:* V2X or cellular request path; end-to-end delay from EV request to controller action.
*Hazard:* The EV arrives before the signal has transitioned — E1 by a different route, but invisible to the crew because the system reports "request sent."
*Mitigation:* Li et al. propose an end-to-end delay decomposition model and a **compensated distance strategy** — trigger at a distance upstream that absorbs the expected latency. Any CV-based design must budget latency explicitly and degrade gracefully.

**E3. Release latency holding the preempt after the EV has cleared.**
*Trigger:* Cellular-based EVP.
*Hazard:* "It can sometimes take cellular based preemption systems **10 seconds or more** to release the preemption of a traffic signal, even though the emergency vehicle has already cleared the intersection." Ten wasted seconds per junction on a corridor is a large cumulative cross-street cost, and it trains drivers that preemption reds are meaningless (A11).
*Mitigation:* Prefer geometric/on-board release (drop within ~30 ft of passage per practitioner guidance) over timeouts; cross-check with local detection.

**E4. Detection dropout mid-approach.**
*Trigger:* Line-of-sight broken by a large truck, a bus, a curve, a hill, building geometry, or heavy rain/snow; direct sun into the receiver.
*Hazard:* Preempt call drops mid-entry. If the controller abandons the sequence, the EV arrives at a signal reverting to normal — and the abandonment path is where illegal yellow→green reverts and truncated clearances hide.
*Mitigation:* Call **extension/hold timers** that ride through short dropouts; radio (900 MHz FHSS) or GPS-based detection to avoid LOS dependence; dead-reckoning (IMU) backup for GPS. Define the drop-out behaviour explicitly and prove it never produces a prohibited sequence.

**E5. "First light" problem.**
*Trigger:* Building on a curving road, or a freight truck, blocks LOS until the EV is very close.
*Hazard:* Insufficient time to serve the preempt — the EV stops at the first intersection, which is often the one nearest the station.
*Mitigation:* Non-LOS technologies; supplementary detectors; station-departure preemption on a hardwired input.

**E6. Light trespass / cross-detection.**
*Trigger:* Optical emitter detected by a receiver on an approach the EV is not using, or at an adjacent parallel intersection.
*Hazard:* Wrong approach gets the green; conflicting movement released toward the EV's actual path. FHWA lists "possible preemption of other approaches" as an inherent limitation of light and infrared systems.
*Mitigation:* Detector aiming, range limiting, shields. INDOT Design Memo 25-19 added Indiana Design Manual criteria "to minimize light trespass outside the right-of-way."

**E7. Stuck emitter / EV stopped near an intersection with the emitter live.**
*Trigger:* EV parks at a scene within detection range with the emitter still transmitting.
*Hazard:* FHWA's stated design requirement is unambiguous: "When EVs stop in the vicinity of an intersection, a continuously running emitter will **hold the signal in the preemption phase indefinitely**, causing significant traffic problems." At an incident scene this is exactly when you least want the surrounding network frozen.
*Mitigation:* "Wire the vehicle emitter into the EV parking brake or transmission lever to turn the emitter off while the EV is stopped." Fairfax County and Plano had to build custom power-interrupt solutions for locally-installed emitters. Controller side: **maximum preempt duration timer** with defined revert behaviour.

**E8. Spurious call from a turning EV at closely spaced parallel streets.**
*Trigger:* EV turns, sweeping its emitter across a detector it never intends to use.
*Hazard:* Unnecessary preemption of an intersection the EV does not traverse; cumulative cross-street cost with zero benefit.
*Mitigation:* St. Paul's **2-second dwell requirement for call acceptance** — the call must persist before it is honoured. Explicitly adopted "to reduce the number of inadvertent preemptions triggered when preemption equipped vehicles make turns in areas with closely spaced parallel streets."

**E9. EV requests, then does not arrive (route change, cancelled call, diverted).**
*Trigger:* Dispatch cancels; EV turns off the corridor; EV rerouted.
*Hazard:* Signal holds for a vehicle that never comes. Cross street pays the full 25-second average preemption cost plus recovery, for nothing. With optical detection the call simply stops and the controller exits; with GPS/cellular the request may persist until an explicit cancel.
*Mitigation:* Bounded max-presence/hold timers on every preempt; explicit cancellation message in CV/GPS systems with a timeout fallback; downstream verification (did the EV actually pass?) via local detection, logged as a mismatch.

**E10. EV stopped or delayed en route — stale ETA.**
*Trigger:* GPS/CV systems that preempt a chain of downstream signals based on projected arrival. EV stops in traffic, at a scene, or is blocked.
*Hazard:* A whole corridor is held for an ETA that has expired. This is a **systemic** version of E7 and is specific to route-based/green-corridor designs; conventional point-detection EVP cannot exhibit it because it never commits ahead.
*Mitigation:* Continuously re-estimate; require positive position updates with a staleness timeout; release downstream preempts on stale data rather than persisting; cap how far ahead the corridor commits. **Note that WSDOT identifies the converse limitation of legacy systems: "Point detection systems cannot recognize speed changes or stops before intersection arrival" and "Zone detection gaps: zone systems cannot determine actual vehicle location or speed within the detection range."**

**E11. Weather, sunlight and reflection false triggers (optical).**
*Trigger:* Direct sun into the receiver; reflections off glass buildings; heavy rain/snow attenuating a genuine signal.
*Hazard:* Both false positives (spurious preemption) and false negatives (E4).
*Mitigation:* Coded/encrypted pulse trains; range limiting; radio/GPS alternatives.

**E12. Acoustic false triggers.**
*Trigger:* Siren-detection systems. "Sound waves can easily be reflected by buildings or other large vehicles" causing misdirected activation; sensitivity triggering from distant sources or unauthorized horns exceeding 120 dB.
*Hazard:* Preemption of the wrong approach — worse than a spurious call, because a green is given to a direction with no EV while another direction is stopped.
*Mitigation:* MnDOT publishes specific siren-activated EVP guidelines; generally, acoustic detection is not recommended as a primary channel for safety-critical corridors.

**E13. Unauthorized activation / spoofing.**
*Trigger:* Homemade mobile infrared transmitters (MIRT) — "a timer circuit connected to an infrared LED array" strobing at 14 Hz. A 2026 demonstration reproduced Tomar Strobecom's pulse-length-modulated protocol with "an Arduino Nano and an infrared LED."
*Hazard:* A member of the public can seize an intersection. Legally addressed (SAFETEA, August 2005: minimum six months imprisonment for illegal use, up to one year for sellers) but that is deterrence, not prevention.
*Mitigation:* Encoded/encrypted pulse sequences; **per-vehicle ID codes** — the demonstration noted "in at least some systems, a valid vehicle ID would be needed." MUTCD 11th Ed. guidance: EVP equipment "should encode vehicle IDs." FHWA: codes "provide a record of which operator drove the vehicle, as well as protect against unauthorized use." Treat every request as untrusted input; authenticate, rate-limit, and log.

**E14. GPS degradation in urban canyons.**
*Trigger:* "Dense buildings prevent signal reception"; heavy cloud cover; systems needing four satellites.
*Hazard:* Position/ETA errors precisely where intersections are densest.
*Mitigation:* IMU/dead-reckoning backup; hybrid detection; explicit confidence thresholds below which the system falls back to conservative behaviour.

**E15. Detector degradation over time.**
*Trigger:* Dirty lenses, tree overgrowth, ageing receivers.
*Hazard:* Silent, gradual range reduction converging on E1/E5. No alarm — it just fails more often on marginal approaches.
*Mitigation:* St. Paul performs "regular preventive maintenance on EVP detectors, including lens cleaning and removal of tree overgrowth," with "detector lens condition inspection... in conjunction with signal lamp replacement." Instrument observed detection distance and trend it.

**E16. Wrong-direction / receding detection.**
*Trigger:* EV departing the intersection still within detector range and within the acceptance cone.
*Hazard:* Preempt re-asserted after the EV has cleared.
*Mitigation:* Directional detection; drop the call on confirmed passage rather than on loss of signal alone.

---

## F. Recovery and transition back to normal

**F1. Named transition (coordination-recovery) strategies and their tradeoffs.**
Verified against TTI Report 0-4657-1 (controller firmware behaviour):

| Method | Mechanism | Tradeoff |
|---|---|---|
| **Dwell** | Rest in the coordinated phase until the offset correction is complete | "Causes the most disruption to the cross-street without any noticeable benefits to either the arterial approaches or the overall intersection." Delay std. dev. 6.7 s vs 0.3–0.4 s for alternatives; NB/SB delay 63.8/57.4 s vs 48.2/45.1 s under Shortway |
| **Max Dwell** | Dwell, but capped | "Less disruption to the non-coordinated phases than the Dwell mode" |
| **Shortway (Short)** | Reach the target offset by the fastest route — shorten *or* lengthen. Corrections capped at ≤50%; cycle-length variation ≤18.75% (Naztec: shorten 0–24%) | Fastest recovery; risk of repeated split failures if splits are already tight |
| **Shortway+ / Longway (Long)** | Add time only to the coordinated phase (Naztec Long: lengthen 0–99%) | Protects cross-street minimums but recovers slower; starves the cross street differently |
| **Shortway-2** | Distribute added time proportionally across all phases | Fairer distribution, slower |
| **No Short Phases** | Exempt up to four phases from shortening | Protects phases with minimal splits from dropping below minimums |

TTI's empirical finding is important and counterintuitive: under typical conditions, average intersection delay across all modes was 21.0–24.0 s and "no noticeable difference" in travel time. **The choice matters mainly in the tails** — Dwell's variance is an order of magnitude larger. For a safety-critical system, minimising variance is the point.

**F2. Exit-strategy (which phase to return to) — a separate decision from F1.**
Five strategies compared for EVP on a coordinated arterial (Reno, Nevada case study):
1. Return to defined phases
2. Return to coordinated operations
3. Return to free operations
4. Return to first skipped phase
5. Return to the most delayed phase

*Finding:* "EVP tends to worsen arterial and intersection operations for **all five** EVP exit strategies." Strategy effectiveness depends on the EV's route and activation point. Recommendation: **"return to coordinated operations"** when prioritising arterial progression recovery; **"return to free operations"** to prevent queue spillover and phase split failures at the intersection level. A separate hardware-in-the-loop study found fixed exit-phase control reduced network-wide delay 2.8% and dynamic exit-phase control 4.5% versus no exit-phase control.

**F3. Cross-street starvation and recovery duration.**
*Trigger:* Preemption holds the cross street on red for the full entry + dwell + exit.
*Quantities:* Average preemption event duration **25 seconds**. In the well-behaved case, "side street backups normally cleared during the first signal cycle following the preemption event," and a Route 7 (Virginia) hardware-in-the-loop evaluation of three coordinated intersections found only a **1.6% increase in average travel time** — but explicitly attributed that to wide intersection spacing, platoon dispersion, and long cycle lengths, and cautioned the result "may not generalize to corridors with closer intersection spacing, shorter cycles."
*Worst case:* Plano, near hospitals, during peak periods with repeated calls: **"it can take 10 to 20 minutes for the traffic flow to return to normal."**

**F4. Coordination recovery lag.**
*Trigger:* Any preemption on a coordinated corridor.
*Hazard:* "On a signal preemptive system in the Washington, DC, metropolitan area, once a signal was preempted, the coordinated systems took anywhere between **30 seconds to 7 minutes** to recover to base time coordination," producing "less-than-optimum timing splits, offsets, and corridor progression" throughout.
*Mitigation:* Choose the transition method deliberately (F1); NCHRP 507's finding is sobering — **90% of agencies either do not use, or are unaware of, "smart recovery strategies" for preemption exit.**

**F5. Split failure during transition.**
*Trigger:* Shortway correction shortens splits at the same time the cross street is discharging an accumulated queue.
*Hazard:* The cross street cannot clear, the queue grows across successive cycles, and recovery becomes divergent rather than convergent.
*Mitigation:* Minimum-phase-time protection ("No Short Phases"); "return to free" exit strategy when queues are the binding constraint.

**F6. Transition ripple to adjacent intersections.**
*Trigger:* One junction is preempted; its offset shifts; downstream junctions receive platoons at the wrong time.
*Hazard:* The disturbance propagates beyond the preempted junction; a corridor of eight signals can be de-coordinated by one preemption at one of them.
*Mitigation:* Corridor-scope recovery decisions rather than per-controller; consider deliberately transitioning neighbours.

**F7. Failure to re-enter coordination at all.**
*Trigger:* Controller drops coordination on preempt entry and does not re-acquire.
*Hazard:* Sebago: "the controller will commonly **drop out of any active coordination programing**" and requires re-entry. If re-entry fails silently, the corridor runs free indefinitely — often unnoticed until complaints arrive.
*Mitigation:* Alarm on "in transition longer than N cycles" and "not in coordination" as monitored states.

**F8. Preemption during transition.**
*Trigger:* A new preempt arrives while a previous transition is still running.
*Hazard:* Compounding — the controller never reaches steady state. On a corridor with frequent EVP near a station or hospital, the signal can spend most of the peak in transition, which is a state nobody times or optimises for.
*Mitigation:* Measure "total interruption time" (preemption duration + transition duration) as the real performance metric, per the high-resolution event-data method (Chou & Nichols).

**F9. Indefinite hold — no max dwell configured.**
*Trigger:* Preempt call remains asserted (E7 stuck emitter, C5 stopped train, interconnect failure).
*Hazard:* Signal held in preemption indefinitely.
*Mitigation:* Controllers "feature a timer that can be set to specify the maximum time a signal can remain in preemption before it assumes that the circuit has failed," reverting to flashing red. Set it; choose the revert state deliberately (flash vs normal — flash is safer for rail, arguably not for EVP).

---

## G. Network and corridor-level effects

**G1. Spillback from an over-long green.**
*Trigger:* Preempt green held longer than the downstream link can absorb.
*Hazard:* The discharging platoon fills the downstream link and blocks the downstream intersection, which then blocks *its* cross street. The preemption's cost is exported to junctions that were never preempted.
*Mitigation:* Chen et al. (2024) is the direct treatment: conventional EVTSP has "underreported" spillback impacts; their system adds (1) a queue-management algorithm preventing queues from blocking the EV at route start, (2) preemption that works even when approaches are already spilled back, (3) a traffic-recovery strategy, and (4) controlled signal normalisation.

**G2. Preemption blocking the EV's own path.**
*Trigger:* Green given to the EV's approach, but the queue *ahead* of the EV has nowhere to go.
*Hazard:* The EV is stuck behind the very traffic the preemption released. Practitioner framing: legacy systems "only activate when vehicles approach, leaving congestion ahead unaddressed."
*Mitigation:* Preempt far enough ahead to *dissipate* the queue before arrival, not merely to hold a green — this is the core argument for route-based/green-corridor preemption over per-junction reaction.

**G3. Closely-spaced junctions where clearing one blocks the next.**
*Trigger:* Signals within a queue-length of each other (downtown grids, diamond interchanges, signals adjacent to grade crossings).
*Hazard:* The clearance movement at junction *n* discharges into the short link to *n+1*, which is still red. The link fills; junction *n*'s clearance is now useless and the intersection is gridlocked with the EV inside it. This is structurally the same failure as Fox River Grove (C9) but with a signal instead of a railroad.
*Mitigation:* Simultaneous/coordinated preemption of the pair (not independent decisions); clear-storage-distance analysis at design time; pre-signals and queue cutters where a critical link is short.

**G4. Preemption of intersections the EV never traverses.**
*Trigger:* Corridor-wide or generous-range preemption; EV turns off early.
*Hazard:* Pure cost, no benefit. Multiplied across every call, this is where public tolerance for EVP is spent.
*Mitigation:* Route-aware preemption; the UMN dynamic route clearance work showed 10–16% EV travel-time reduction on long/complex routes with "compatible network-wide performance," i.e. targeting rather than blanketing.

**G5. Multi-unit response saturating a corridor.**
*Trigger:* Multi-alarm fire; several units on the same or converging routes over several minutes.
*Hazard:* Sequential preemptions with no recovery between them (F8). Corridor effectively fails for the duration.
*Mitigation:* Fleet-level coordination — treat a multi-unit response as one corridor reservation rather than N independent preemptions.

**G6. Diversion to parallel routes.**
*Trigger:* Repeated preemption on an arterial.
*Hazard:* Drivers learn and divert to parallel local streets, exporting traffic (and crash risk) into residential streets that were never designed for it.
*Mitigation:* Monitor parallel-route volumes as an EVP performance measure, not just corridor travel time.

---

## H. Operational, institutional and policy

**H1. Preemption frequency caps — why they exist.**
*Rationale, three distinct mechanisms:* (a) **Capacity** — each event costs ~25 s of cross-street service plus 30 s–7 min of degraded coordination; at high frequency the corridor never recovers (Plano's 10–20 minutes near hospitals). (b) **Compliance** — WSDOT: frequent preemptions "encourage drivers to disobey red lights." (c) **Equity of burden** — the cost lands entirely on non-preempted movements.
*Existing mechanisms in the standards:* NEMA TS2's bus **re-serve timer** is the only explicit frequency cap in the controller standard, and it applies only to bus preemptors. For EVP, caps are policy, not firmware — which means they must be designed in.
*Mitigation:* Minimum inter-preemption interval per approach; per-vehicle-class daily budgets with alarming rather than hard blocking (never silently deny a genuine emergency request — alarm and log instead).

**H2. Non-emergency use.**
*Trigger:* Return trips, non-urgent transport, staff convenience, unauthorized personnel.
*Hazard:* Consumes the corridor budget and the public's tolerance; the biggest driver of programme cancellation.
*Mitigation:* Per-vehicle and per-operator ID coding — FHWA: codes "provide a record of which operator drove the vehicle, as well as protect against unauthorized use." Routine audit of logs against dispatch records.

**H3. Logging and accountability.**
*What must be logged:* Controllers and MMUs record "signal conflicts, field circuit failures, cabinet door openings, preemption calls, coordination faults, and voltage anomalies." Railroad recorders capture track occupancy, gate position, warning light operation, preemption circuit activation, power and temperature; capacity "over 100,000 events."
*The gap:* FHWA is explicit — "The data recorded, however, are **not always either easily retrieved or of much use for effective analysis**." Manufacturer-specific software prevents unified retrieval; "electrical isolation that exists between the two systems" complicates exchange; often the only shared channel "is a single preemption call circuit." NCHRP 507: only **16% of agencies record detailed railway warning-system events** beyond the controller preempt log, despite FRA Safety Advisory 2010-02 recommending event recorders.
*Minimum recommended log record per event:* preempt input number and priority; requesting vehicle ID and class; request assert and drop timestamps (synchronised clock); controller state at assert (phase, interval, time-in-phase, ped state); each interval entered with duration; pedestrian intervals truncated or omitted, with the amount; arbitration outcome when multiple calls were present, including **calls received but not served**; exit phase selected; transition method and time to re-coordination; any max-timer expiry; MMU/conflict events.
*Analysis method:* Chou & Nichols demonstrate high-resolution signal event data with phase-spectrum plots yielding preemption duration, transition duration and **total interruption time** per intersection, plus EV trajectory reconstruction across the network — and advocate this specifically for "troubleshooting field preemption operations."
*Time synchronisation is load-bearing:* without synchronised clocks across controller, detection system and CAD/dispatch, none of the above can be correlated after an incident. Fox River Grove turned in part on the absence of documentation of what had been programmed.

**H4. Change management.**
*Trigger:* Timing changes, geometry changes, warning-time changes, firmware updates.
*Hazard:* Fox River Grove is the archetype: undocumented 1990 programming, a 1989 widening that cut storage from ~80 ft to 45 ft, and a railroad warning-time change from 30 s to 25 s two weeks before the crash without notification. TxDOT requires timing changes to be "documented in logbook in traffic signal controller," with the preemption form (Form 2304) and signal layout kept in the cabinet, and a warning label prohibiting tampering with the interconnect.
*Mitigation:* Formal notification protocol between all parties; re-verify preemption timing on **any** geometry or timing change; NCHRP 507 found 87% restrict timing changes to pre-approved staff, but only **61% perform routine inspections**, most commonly yearly.

**H5. Maintenance and inspection regime.**
*Findings:* NCHRP 507: 74% shop-test cabinets before installation; only 39% have training for maintenance staff; only 37% of those using contract maintenance have railway coordination procedures; inspection intervals range from monthly to **every five years.** 49 CFR 234.261 requires monthly testing of preemption interconnections.
*Mitigation:* ITS lessons learned: identify **a single agency** responsible for scheduling, coordinating and funding maintenance; a formal problem-reporting channel; a documented troubleshooting process ("will reduce the repeat/recur rate as well as the maintenance call false alarm rate"); integrate EVP maintenance into routine signal maintenance.

**H6. Bench and field acceptance testing.**
*Mitigation:* "Traffic controllers should be set up in the shop the same way as in the field to replicate any issues that may occur." Field acceptance testing with all stakeholders before system-wide rollout. Given D7 (precedence ambiguity) and D4 (undefined mid-sequence replacement), **pairwise preempt-interaction testing on the bench is not optional.**

**H7. Multi-agency governance.**
*Hazard:* Fire, EMS, police, transit and the signal agency have different objectives and no single one owns the outcome. FHWA recommends a memorandum of agreement documenting "service call precedence, cabinet access procedures, service log requirements." WSDOT: "Agencies must agree about overall system goals, as well as **when and under what conditions** priority and preemption will apply."

**H8. Driver training and over-reliance.**
*Hazard:* The single most-repeated finding in the practitioner literature. FHWA: "Emergency vehicle preemption operation and limitations **must** be a part of initial and recurring emergency vehicle driver training." Fire Engineering warns of "a false sense of security that everyone will yield the right of way." The doctrine that survives every failure mode above: proceed as if preemption will not be granted; without a solid confirmation indication, stop.

**H9. Equity — who bears the cost.**
*What the literature actually establishes:* The delay burden is systematically allocated, and it is allocated to the same parties every time. (a) **Cross streets** absorb the full event plus recovery — Reno found *all five* exit strategies worsen operations for non-priority movements. (b) **Pedestrians** are the first thing sacrificed: MUTCD permits omitting both walk and pedestrian change intervals under preemption, and 75% of agencies routinely truncate. (c) **Geographic concentration** — preemption density is highest near fire stations and hospitals, so a small set of corridors and their cross streets carry nearly all the burden (Plano's 10–20 minute peak recovery is a hospital-adjacent effect).
*Honest caveat:* I did not find a formal equity/disparate-impact analysis of EVP in the literature. The distributional facts above are well documented; the equity framing of them is inference. **This is a genuine research gap** and worth stating as such rather than citing something that doesn't exist.
*Mitigation:* Report EVP performance as a distribution, not a mean — cross-street delay percentiles, pedestrian intervals truncated per week by location, preemption counts per intersection — so the burden is visible rather than averaged away into a "1.6% travel time increase."

**H10. Backup power.**
*Standard:* MUTCD 11th Ed. §4F.19 Guidance: signals "with railroad preemption or coordinated with flashing-light signal systems **should** be provided with a back-up power supply." NCHRP 507: 75% use battery backup at new installations, but the survey provides no data on failure rates, testing frequency, or recovery procedures — an unmeasured dependency.

---

## Highest-priority items for a safety-critical implementation

If I had to rank by (severity × likelihood × how often it's actually gotten wrong):

1. **A1/A2 — yellow trap on preempt entry and exit.** Highest-severity crash type, routinely present in the field, and the fix (all-red clean break before the preempt phase, per WisDOT) is cheap and unambiguous.
2. **D1/D7 — conflicting-approach arbitration and precedence-convention ambiguity.** Two EVs is the scenario the whole system exists to handle and the one least specified by standards; the sources actively disagree on input precedence direction.
3. **B2 — pedestrian change interval truncation.** Permitted by MUTCD, done by 75% of agencies, and the one hazard where the standard is *more* permissive than the risk warrants. INDOT has already moved against it.
4. **E7/F9 — stuck call with no bounded hold.** Trivially preventable, catastrophic to the network, explicitly documented by FHWA as requiring a vehicle-side interlock.
5. **D5 — second preempt during exit being silently dropped.** Documented for rail; the EVP analogue is unverified in most deployments and fails silently.
6. **C7 — EVP queuing traffic onto railroad tracks.** 67% of agencies allow fire preemption at rail-preempted intersections; this is where two independently-correct systems combine into an incorrect one.

---

## Sources

- [FHWA, *Traffic Signal Preemption for Emergency Vehicles: A Cross-Cutting Study* (FHWA-JPO-05-010)](https://rosap.ntl.bts.gov/view/dot/3655/dot_3655_DS1.pdf)
- [FHWA, *Emergency Vehicle Preemption (EVP)*, FHWA-HOP-24-019](https://ops.fhwa.dot.gov/publications/fhwahop24019/fhwahop24019.pdf) · [ROSAP record](https://rosap.ntl.bts.gov/view/dot/88240)
- [FHWA, *Traffic Signal Timing Manual*, Chapter 9 — Preemption and Priority](https://ops.fhwa.dot.gov/publications/fhwahop08024/chapter9.htm)
- [FHWA, *Recording Devices for Interconnected Grade Crossing and Intersection Signal Systems*](https://highways.dot.gov/safety/hsip/xings/recording-devices-interconnected-grade-crossing-and-intersection-signal-systems-6)
- [MUTCD 11th Edition, Part 4](https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part4.pdf) · [Part 8](https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part8.pdf) · [2009 Edition Part 4D](https://mutcd.fhwa.dot.gov/HTM/2009/part4/part4d.htm)
- [CA MUTCD 2026 Chapter 4F — §4F.18/4F.19 preemption and priority text](https://dot.ca.gov/-/media/dot-media/programs/safety-programs/documents/ca-mutcd/2026/2026-camutcd-2026-4f-a11y.pdf)
- [Delaware adoption of MUTCD §4D.27](https://regulations.justia.com/states/delaware/title-2/2000/2400/2402/part-4/chapter-4d/section-4d-27/)
- [NCHRP Synthesis 507, *Traffic Signal Preemption at Intersections Near Highway–Rail Grade Crossings*](https://transops.s3.amazonaws.com/uploaded_files/NCHRP%20Synthesis%20507%20Traffic%20Signal%20Preemption%20at%20Intersections%20Near%20Highway%E2%80%93Rail%20Grade%20Crossings.pdf) · [NAP catalog](https://nap.nationalacademies.org/catalog/24769/)
- [TTI Report 1439-9, *Guide for Traffic Signal Preemption Near Railroad Grade Crossings*](https://static.tti.tamu.edu/tti.tamu.edu/documents/1439-9.pdf)
- [TTI Report 0-4657-1, *Evaluation of Advance Coordination Features in Traffic Signal Controllers*](https://static.tti.tamu.edu/tti.tamu.edu/documents/0-4657-1.pdf)
- [Purdue Road School, *Traffic Signal Pre-emption Near Active Railroad Crossings — Revisited*](https://docs.lib.purdue.edu/cgi/viewcontent.cgi?article=4662&context=roadschool)
- [ITE Recommended Practice RP-025D, *Preemption of Traffic Signals Near Railroad Grade Crossings*](https://www.ite.org/technical-resources/topics/standards/recommended-practices/traffic-signal-preemption-near-railroad-grade-crossings-mutcd-update/)
- [NTSB HAR-96/02, Fox River Grove bus–train collision](https://www.ntsb.gov/investigations/AccidentReports/Reports/HAR9602.pdf)
- [NEMA TS2 specification (Montgomery County MD)](https://atms.montgomerycountymd.gov/specs/ts2spec.htm)
- [NTCIP 1202 v03A](https://www.ntcip.org/file/2019/07/NTCIP-1202v0328A.pdf)
- [Florida LTAP, *Traffic Signal Timing 201 — Advanced Intersection Control, Day 2*](https://floridaltap.org/wp-content/uploads/2021/04/HANDOUT-TST-201-Part2.pdf)
- [Sebago Technics, *Basics of a Preemption Event at a Traffic Signal Controller*](https://www.sebagotechnics.com/wp-content/uploads/Preemption.pdf)
- [WisDOT TEOpS Chapter 4-7 (left-turn trap, FYA, preemption)](https://wisconsindot.gov/dtsdManuals/traffic-ops/manuals-and-standards/teops/04-07.pdf)
- [TxDOT, *Preemption by Emergency Vehicles*](https://www.txdot.gov/manuals/trf/tff/operational_considerations/preemption-i999302/preemption_by_emergency_vehicles-i999343.html) · [Rail-Highway Ops: Traffic Signal Preemption](https://www.txdot.gov/manuals/rrd/rho/exhibit_a_and_pse_design/traffic_signal_preemption-i1005274.html) · [Maintenance of Preempted Traffic Signals](https://www.txdot.gov/manuals/rrd/rho/maintenance/preempted_traffic_signals-i999534.html)
- [WSDOT TSMO, Emergency vehicle preemption](https://tsmowa.org/category/intelligent-transportation-systems/emergency-vehicle-preemption) · [Signal priority & preemption](https://tsmowa.org/category/intelligent-transportation-systems/traffic-signal-priority-preemption)
- [INDOT Design Memo 25-19, Traffic Signal Preemption / Light Trespass](https://secure.in.gov/dot/div/contracts/standards/memos/2025/DM%2025-19%20Traffic%20Signal%20Preemption_Light%20Trespass.pdf)
- [MnDOT, Siren-Activated EVP Guidelines](https://www.dot.state.mn.us/trafficeng/signals/news/EVPSirenGuidelines20021015.doc) · [MnDOT EVP approved products](https://www.dot.state.mn.us/products/signals/evp.html)
- [ITE Wisconsin, *Signal Preemption, Confirmation & RR Preemption* issue paper](https://itewisconsin.org/images/downloads/Traffic_Engineering_Council_Issue_Papers/signal_preemption___confirmation__rr_preemption.pdf)
- [Obenberger & Collura, *Transition Strategies to Exit Preemption Control* (TRR 1748)](https://journals.sagepub.com/doi/10.3141/1748-09)
- [*Evaluating the Impacts of Different Exit Strategies of EVP on Arterial Signal Coordination: Reno, Nevada* (ASCE JTEPBS 149:11)](https://trid.trb.org/view/2236919)
- [*Investigation on the exit phase controls for emergency vehicle preemption* (KSCE JCE)](https://link.springer.com/article/10.1007/s12205-011-1326-2)
- [Chou & Nichols, *Characterizing EVP Operation with High-Resolution Traffic Signal Event Data* (TRR 2557)](https://journals.sagepub.com/doi/10.3141/2557-11)
- [Li et al., *Signal Priority Request Delay Modeling and Mitigation for Emergency Vehicles in Connected Vehicle Environment* (TRR)](https://journals.sagepub.com/doi/10.1177/0361198118774184)
- [Chen et al. (2024), *An EVP system considering queue spillbacks and negative impacts on non-priority traffic* (IET ITS)](https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/itr2.12518)
- [FHWA, *Evaluation of Emergency Vehicle Signal Preemption on the Route 7 Virginia Corridor*](https://rosap.ntl.bts.gov/view/dot/35851)
- [UMN CTS, *Development of Dynamic Route Clearance Strategies for Emergency Vehicle Operations, Phase I*](https://www.cts.umn.edu/research/project/development-of-dynamic-route-clearance-strategies-for-emergency-vehicle-operations-phase-i)
- [ITS Lessons Learned: EVP maintenance](https://www.itskrs.its.dot.gov/2006-l00230) · [EVP institutional coordination](https://www.itskrs.its.dot.gov/2006-l00231)
- [Wikipedia, *Yellow trap*](https://en.wikipedia.org/wiki/Yellow_trap) · [*Traffic signal preemption*](https://en.wikipedia.org/wiki/Traffic_signal_preemption) · [*Mobile infrared transmitter*](https://en.wikipedia.org/wiki/Mobile_infrared_transmitter)
- [MidiMagic, *Yellow Trap and Preemptions*](https://midimagic.sgc-hosting.com/premtrap.htm)
- [Hackaday (2026), *Spoofing an Emergency Traffic Preemption Signal*](https://hackaday.com/2026/03/08/spoofing-an-emergency-traffic-preemption-signal/)
- [EMS World, *Emergency Vehicle Driving and Traffic Preemption*](https://www.hmpgloballearningnetwork.com/site/emsworld/article/10324699/emergency-vehicle-driving-and-traffic-preemption)
- [Fire Engineering, *Running the Red: Emergency Vehicle Operations Pitfalls*](https://www.fireengineering.com/fire-apparatus/running-the-red-emergency-vehicle-operations-pitfalls/)
- [Firefighter Close Calls, Hillsboro OR fire engine / MAX light rail collision (2005)](https://www.firefighterclosecalls.com/update-oregon-firetruck-changed-signal-to-green-test-determines/)
- [App-Info, *Common Problems with Preemption Systems*](https://appinfoinc.com/preemption-systems-problems-solved/)

---

**Summary of what was done:** Researched EVP/green-corridor signal control across FHWA (cross-cutting study, Signal Timing Manual Ch. 9, EVP guide, grade-crossing handbook), MUTCD 11th Edition §4F.18–4F.19 (verified verbatim via the CA MUTCD 2026 adoption after the FHWA PDFs proved unfetchable at that depth), NCHRP Synthesis 507, ITE RP-025D, NEMA TS2 and NTCIP 1202, TTI/TxDOT/WisDOT/INDOT/MnDOT/WSDOT/ODOT guidance, NTSB HAR-96/02, and ~15 peer-reviewed papers. Catalogued **~75 distinct edge cases** across eight categories.

**Three findings worth flagging above the rest:** (1) the preempt-input **precedence convention is contradicted between authoritative sources** — NEMA TS2 says low-numbered overrides higher-numbered, the FHWA-sponsored Florida LTAP course says the opposite — so precedence must be established by bench test, never by documentation; (2) **mid-sequence preempt replacement is genuinely under-specified** in NEMA TS2, and the rail literature documents controllers silently *ignoring* a second call arriving during exit, which for EVP means a second emergency vehicle can be dropped with no indication to anyone; (3) **the dilemma-zone and preemption literatures barely intersect** — preemption applies a hard force-off with no consultation of advance detection, and I found no standard addressing it. Items (2) and (3) are gaps rather than solved problems, and I've marked them as such rather than inventing mitigations.
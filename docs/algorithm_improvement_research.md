# CC-A-CAMP: where the algorithm actually stands, and what would improve it

**Scope:** an evidence-based review of the ITMS traffic-coordination algorithm at
`komal` / `a87e845`, run on 2026-09-17. Every number below was measured in this
review unless it is explicitly labelled as quoted from `PROGRESS.md`.
Nothing under `itms/` was modified: all experiments ran from a scratch harness
outside the repo, against the shipped code.

**Method:** Python 3.11.15, eclipse-sumo 1.27.1 (the pinned version), Linux
x86_64. `pytest -q` at this commit: 549 passed, 6 skipped. The frozen benchmark
(`scripts/m5_baseline_benchmark.py`, 3 arms × 3 demand levels × 10 held-out
seeds) reproduced the saved baseline exactly. **690 further SUMO runs** were
executed for the ablations, parameter sweeps and candidate fixes reported here
(780 including the baseline reproduction);
every comparison is paired per (arm, level, seed) with a 95% CI, and "SIG" means
the CI excludes zero.

---

## 1. Executive summary

The headline result — CC-A-CAMP beats a tuned Webster by 19.9% / 11.4% / 11.6%
of person-delay at light / medium / heavy demand — is real and reproducible.
**But almost all of it comes from one line of configuration, not from the
adaptive algorithm.** Ablating the 1.25× Webster green ceiling costs +86% at
light and +42% at medium; ablating the cycle supervisor costs nothing outside
heavy demand. The parts of A-CA-MP that the project's write-ups treat as its
contribution are, on this corridor, either inert or unmeasurable.

Five findings drive everything else:

1. **The spillback gate has never been active.** `queue_state.py` divides
   `traci.lane.getLastStepOccupancy` by 100, but that call already returns a
   fraction. Measured maximum receiving occupancy over a heavy run: **0.0067**,
   so `gate()` never falls below **0.99992**. Turning the gate fully off
   (`rho_jam = 1e9`) or hardening it (`rho_jam = 0.30`) both reproduce the
   shipped results **bit-for-bit on every seed and demand level**. A-CA-MP's
   "Defect 1 fix", `rho_jam`, `beta_gate`, and whatever the tuner learned for
   them, have all been scoring a term that is identically 1.
2. **The controller is boxed in.** 62–64% of all decision ticks at light and
   medium demand are inside minimum green (10 s), while the 1.25× ceiling at
   most junctions is 12.5 s. The adaptive band is about **2.5 seconds wide**,
   which is why CC-A-CAMP and the static-ceiling arm are statistically
   indistinguishable there (−1.3% and −2.9%, both n.s.).
3. **Clearance time, not control policy, is this corridor's dominant cost.**
   `yellow_s` is inherited from netconvert's guessed program (5–6 s) and 2 s of
   all-red is added on top, so every phase change costs 7–8 s. Cutting yellow to
   a conventional 3 s gives CC-A-CAMP **−18.9% / −21.0% / −3.7%** (light and
   medium significant, 10/10 and 9/10 seeds); with minimum green at 7 s as well,
   **−21.7% / −23.5% / −5.2%, all three significant, zero interlock violations.**
   That is larger than every algorithmic change this project has landed.
4. **The pressure contest rarely decides anything.** The best-vs-current
   pressure gap is **0.000 at the median decision tick**; all phase pressures are
   simultaneously ≤ 0 on 12–89% of ticks depending on junction; and the
   controller extends a green whose own approaches are empty on **43–65%** of its
   extend ticks. Max-green timeouts still account for **35–41% of all switches**
   — M4's disease, reduced but not cured.
5. **Two of three "memories" never run in any benchmark.** `DemandMemory`,
   `OnlineCalibration` and `LoadBaseline` are all `None` in every gate arm, and
   the confidence ladder never leaves `camp_full` (confidence defaults to 1.0),
   so `use_memory_blend` and the `profile_actuated` rung are dead code in every
   measured result.

Highest-value work, in order: fix the occupancy unit bug and re-tune the gate;
re-derive clearance intervals and minimum greens from the network instead of
inheriting them (largest measured win by far); replace the min/max-green box
with a real gap-out/extension rule so the controller has room to act; and
rebuild the evaluation (throughput metric is constant by construction, the
Webster baseline is mistimed, 10 seeds is thin).

Things that sound promising and are **not** worth doing, each tested here: a
naive gap-out rule (+15.7% at medium, SIG), de-duplicating per-lane saturation
flows (+6.6% at heavy, SIG), correcting Webster's lost time inside the baseline
(+22% at medium, SIG), and tightening `cycle_target_factor` to 0.70 (looked
−10.5% on 3 training seeds, came back +5.7% SIG worse on the held-out set).

---

## 2. What the algorithm actually is, as it runs in the benchmark

Per junction, per 1 s tick, `AdaptiveCamp.__call__`:

```
                    ┌─ confidence < 0.8 → blended / fixed-time rung
ctx ──► calibration ┤   (never taken: ctx.confidence is empty → min() = 1.0)
        + load EWMA └─ camp_full
          │
          ▼
   pressures[p] = Σ_m s_m·(q̂_m·gate(ρ_m) − r_m)      ← gate ≡ 1.0 (bug B1)
                + λ_f·Σ_m s_m·(wait/max_wait)^γ       ← no measurable effect
                + A(p) + D(p)                          ← 0 unless an EV is inbound
          │
          ▼
   elapsed < min_green?  ──yes──► extend                (62% of ticks, light)
          │no
   any phase within 15 s of max_wait_s? ──yes──► switch (2 firings in 30 heavy runs)
          │no
   cycle > Σ(max_green+y+ar)·ctf and phases owed? ──yes──► supervisor switch (0.6–1.0%)
          │no
   elapsed < max_green?
          ├─ protect_allocated_green (needs congestion ≥ 0.5) ──► extend
          ├─ pressures[cur] + hold_bias ≥ best ──► extend
          └─ else ──► switch_pressure
          │
   else ──► switch_max_green                              (35–41% of all switches)
          │
          ▼
   next = argmax pressure over ring lookahead k=2, skipping empty phases
   allocate_green = nominal_cycle · (P_next − min P)/Σ(P − min P), clamped
          │
          ▼
   interlocks.check (I1–I6) ──► arbiter ──► runner (yellow → all-red → green)
```

Measured decision mix (10 seeds × 7 junctions, share of all decision ticks):

| branch | light | medium | heavy |
|---|---:|---:|---:|
| extend, inside min green | 61.8% | 64.4% | 41.3% |
| extend, pressure contest | 32.0% | 26.3% | 29.1% |
| extend, allocation protected | 0% | 2.9% | 25.5% |
| switch on pressure | 3.6% | 4.1% | 2.5% |
| switch on max green | 2.5% | 2.3% | 1.5% |
| switch by cycle supervisor | 0.04% | 0.05% | 0.04% |
| switch on starvation | 0 | 0 | 0.001% |

### Which components pay for themselves

Each row turns one component off; delta is against CC-A-CAMP, paired per seed,
positive = worse. n=10 unless noted (n=6 for the rows marked †, n=3 ‡).

| component removed | light | medium | heavy | verdict |
|---|---|---|---|---|
| 1.25× ceiling (`max_green` back to 90 s) † | **+86.3% SIG** | **+41.7% SIG** | **+7.6% SIG** | the algorithm's entire win |
| arrival term (`eta_arrival = 0`) † | **+18.7% SIG** | **+30.1% SIG** | +7.6% n.s. | second most valuable |
| `protect_allocated_green` | 0.0% (identical) | +0.3% n.s. | **+21.2% SIG** | heavy only, large |
| hold bias (κ=0, lost-time weight=0) † | +5.0% n.s. | +5.7% n.s. | **+8.2% SIG** | heavy only |
| cycle supervisor | +1.3% n.s. | +3.0% n.s. | **+5.8% SIG** | heavy only, small |
| fairness (`lambda_f = 0`) † | +5.2% n.s. | +5.2% n.s. | −2.2% n.s. | no measurable value |
| lost-time term (`lost_time_weight = 0`) † | −1.3% n.s. | +2.2% n.s. | +0.9% n.s. | inert (its congestion gate is ~0) |
| spillback gate (`rho_jam = 1e9`) † | **0.0% identical** | **0.0% identical** | **0.0% identical** | inert (bug B1) |
| harder gate (`rho_jam = 0.30`) | **0.0% identical** | **0.0% identical** | **0.0% identical** | inert (bug B1) |
| ring lookahead k=2 → 4 † | −5.0% n.s. | +5.9% n.s. | **+9.6% SIG** | k=2 is right |
| `eta_arrival` 0.5 → 1.0 | −3.5% n.s. (8/10) | −4.4% n.s. (6/10) | +0.5% n.s. | worth re-tuning |
| `eta_arrival` 0.5 → 0.25 | +4.2% n.s. | +3.0% n.s. | +2.7% n.s. | 0.5 beats 0.25 |
| ceiling factor 1.00 / 1.50 / 2.00 ‡ | +2.5 / +2.5 / +11.2% | −1.8 / −0.3 / −4.1% | −3.9 / −4.8 / +7.6% | 1.00–1.50 indistinguishable, 2.00 worse |

Read together: **ceiling + arrival term + (at heavy) allocation protection and
the hold bias** are the algorithm. Fairness, the spillback gate, the lost-time
economic term, the demand memory, the online calibration, the relative-congestion
gate and the confidence ladder contribute nothing measurable on this corridor as
configured.

---

## 3. Bugs and defects

### B1 — Receiving-lane occupancy is divided by 100 twice; the spillback gate is dead
**Severity: High (silently disables a headline mechanism).**
`services/sim-service/sim_service/signal_controller/queue_state.py:227` and `:257`

```python
receiving_occupancy[link_id] = traci.lane.getLastStepOccupancy(lane_id) / 100.0
```

`getLastStepOccupancy` returns the occupied fraction of the lane (0–1), not a
percentage. **Evidence:** instrumented heavy run, 194,233 samples — max
occupancy **0.00669**, p99 0.00607, median non-zero 0.00027. With
`rho_jam = 0.75, beta_gate = 2`, `gate()` at that maximum is **0.99992**.
Both ablations (`rho_jam = 1e9` and `rho_jam = 0.30`) reproduce the shipped
delay **to the last digit on all 30 runs**, and per-junction decision counters
are identical, which is only possible if the term never changes a decision.

**Consequence:** A-CA-MP's Defect-1 fix (the bounded `gate` replacing M4's `θ`),
`rho_jam`, `beta_gate`, and any tuner effort spent on them, have never had any
effect. The controller has no working spillback protection; only the `− r_m`
receiving-queue term carries downstream state.

**Proposed fix:** drop the `/ 100.0` (both call sites), then **re-tune**
`rho_jam` / `beta_gate` on training seeds — the fix alone is not a win (measured:
gate active at ρ=0.75 gives −0.4% / +2.4% / +1.8%, all n.s.; at ρ=0.90,
+5.4% SIG worse at heavy). Add a unit test asserting `gate() < 0.9` for a lane
that is 60% occupied, and a property test that occupancy read from a jammed lane
exceeds 0.5.
**Interlock risk:** none — the gate only scales pressure.

### B2 — `person_throughput_per_hour` is a constant, and its divisor is wrong
**Severity: Medium (a reported KPI that cannot discriminate).**
`control/metrics.py:152,163–166`; `scenario_duration_s: float = 1800.0` is never
overridden by `m5_harness.run_one`.

Every arm completes all 14,400 vehicles, so the numerator is fixed; the
denominator is a hard-coded 1,800 s while the runs actually last 2,070–3,540 s.
The metric therefore reads **2,717 / 5,203 / 10,282 persons/h identically for
every arm at every demand level** (measured) and its absolute value is inflated
by roughly 1.2–2×. **Fix:** divide by the real scored window
(`max(depart+duration) − warmup`), or report vehicles-cleared-by-time-T.

### B3 — Warm-up filtering interacts with insertion delay, so arms are scored on different populations
**Severity: Medium (paired-comparison validity).**
`metrics.score_trips` keeps trips with `depart_s >= 600`, and SUMO's `depart` is
the *actual* insertion time. A congested arm pushes insertions later, moving
trips into the scored window: at heavy demand the arms score 9,680 (webster),
9,766 (ceiling) and 9,755 (ccacamp) trips out of the same 14,400. **Fix:** select
the scored set by the route file's *intended* departure time, identically for
every arm.

### B4 — Saturation flow and queue are both counted per movement, on lanes that are shared
**Severity: Medium (systematic bias in the phase comparison).**
`queue_state.py:222–225` sets `queue_pcu[link] = halting PCU of the whole lane`,
and `acamp.press_pressure` then sums `s_m · q̂_m` over every movement of a phase.
**53 of this corridor's 73 links share a lane with another link** (measured),
up to 4 to a lane. The same queue is therefore counted once per movement, and
the static inflation factor differs *within* a junction: e.g. `1880441505` P0 is
inflated **3.00×** and P1 **1.29×**; `cluster_1880441740_4393296791` ranges
1.17× (P0) to 3.00× (P2, P3). The phase contest is biased by lane geometry.

**But the naive fix is worse.** Dividing `s_m` by the number of links sharing
its lane measured **+3.9% / +2.5% / +6.6%** (heavy SIG). The inflation is
currently acting as an unintended "number of movements served" weight, which is
correlated with real benefit. The correct fix is to aggregate pressure per
*lane group* (queue once, capacity once, benefit counted once) rather than to
rescale per movement — and it must be re-tuned, not dropped in.

### B5 — `max_wait_s` is not recomputed when the ceiling replaces `max_green_s`
**Severity: Medium (starvation protection inert; and the cause of heavy demand's violations).**
`extract_tier0_config.py:216` derives `max_wait_s = Σ max_green + n·(y+ar) + 60`,
i.e. 256 s at a 2-phase junction and 452 s at the 4-phase one, from the shipped
90 s ceiling. `scripts/m5_cycle_ceiling_probe.configs_with_ceiling` replaces
`max_green_s` with 12.5–90 s but leaves `max_wait_s` untouched. The bound is now
5–9× the cycle the corridor actually runs (measured emergent cycles: 46–232 s),
so I5 effectively never fires in normal operation — **2 starvation switches in
30 heavy runs**. The one place it does fire is the I3/I5 conflict that produces
heavy demand's interlock violations. **Fix:** derive `max_wait_s` from the
ceiling actually in force, so the bound tracks the ring's real rotation.

### B6 — Allocations are shares of the whole cycle, including time that is never green
**Severity: Low-Medium (mis-sized allocations feed `protect_allocated_green`).**
`acamp.allocate_green:993` computes `nominal_cycle_s × share`, where
`nominal_cycle_s` is Webster's *cycle*. The green actually available is
`cycle − n·(yellow + all_red)` — at a 2-phase junction, 40 − 16 = 24 s of a 40 s
cycle. Allocations therefore sum to ~1.7× the servable green. Measured
served/allocated at heavy: **0.63–0.88** at the two saturated 2-phase junctions.
Since `protect_allocated_green` holds a phase until `elapsed ≥ allocation`, an
inflated allocation makes protection last longer than intended. **Fix:** use the
effective green pool. **Caveat:** protection is worth +21% at heavy as it stands,
so this must be re-measured, not assumed to be an improvement.

### B7 — Webster's lost time (4 s) does not match the clearance the network displays (7–8 s)
**Severity: Medium (the baseline everything is quoted against).**
`webster.py:70` `_LOST_TIME_PER_PHASE_S = 4.0` while `yellow_s + all_red_s` is
7–8 s at every junction. Webster's optimum-cycle formula is fed the wrong `L`,
and the green pool is `cycle − n·4` when the junction will actually spend `n·8`.
The realised cycle overruns the "optimum" it was computed for by **1.15× to
1.80×** (measured, per junction and level; worst at the 4-phase junction at
light: 72 s displayed against a 40 s optimum).

**Correcting it does not rescue the baseline** — measured with `L = 8`:
+24.0% light (n.s. vs the original Webster), **+22.2% medium SIG worse**,
−4.7% heavy. So the mistiming is real but is *not* where CC-A-CAMP's advantage
comes from; report the baseline as "Webster with textbook lost time", not as
"optimal fixed time".

### B8 — Cosmetic / pre-existing
`ruff`: unsorted imports and one over-long line in
`tests/control/test_runner_decision_contract.py`. `mypy`:
`signal_controller/arbiter.py:238` redefines `notes` (pre-existing, also in the
frozen baseline).

---

## 4. Diagnostic findings that shape the improvements

**D1 — The min-green/ceiling box.** Mean served green is 11–14 s at light and
medium against a 10 s floor and a 12.5 s ceiling at most phases. There is almost
nothing for a controller to decide. This is the mechanical reason
"CC-A-CAMP vs ceiling" is n.s. at light and medium.

**D2 — A degenerate pressure signal.** Median |best − current| pressure gap is
**0.000**; all pressures are simultaneously ≤ 0 on 12.2–64.0% of ticks at light
and 4.3–89.2% at heavy (per junction). Where the gap is zero the hold bias
decides by default, and the hold bias is the only thing standing between the
controller and a coin flip.

**D3 — Green given to empty approaches.** On 43–65% of extend ticks the current
phase has neither a queue nor an approaching vehicle. A naive gap-out is *not*
the answer (tested: +3.9% / +15.7% SIG / +3.1%), because at 7–8 s of clearance
per switch the extra changes cost more than the wasted green. Lower clearance
first, then re-test gap-out.

**D4 — The supervisor is silent where it is needed.** At
`cluster_1880441740_4393296791` (heavy) the envelope is
Σ(max_green + 8 s) ≈ 237 s while the measured cycle is median 201 s, mean 232 s,
p90 414 s — so the trigger fires on ~1% of switches. Tightening
`cycle_target_factor` to 0.70 looked good on 3 training seeds (−10.5% medium)
and came back **+5.7% SIG worse at heavy** on the held-out seeds; 0.50 is worse
still. The supervisor needs a different trigger (e.g. per-phase owed-time), not
a smaller multiplier.

**D5 — The congestion gate is off almost everywhere.** `congestion_weight`
median is 0.000 (light), 0.004 (medium), 0.035 (heavy); only the corridor's
hottest junction crosses the 0.5 threshold. That is why `protect_allocated_green`
is a heavy-demand-only mechanism and why the lost-time term is inert.

**D6 — Teleports.** SUMO reported 71 teleport events in a 90-run benchmark
(heavy demand, `waited too long (yield)`). Each one removes a vehicle from a
jam, which flatters delay in exactly the arm that is worst. Worth counting per
arm and reporting.

---

## 5. Improvements, ranked

### Tier 1 — measured wins

**I1. Re-derive clearance intervals and minimum green from the network.**
`yellow_s` comes from netconvert's guessed program (5–6 s); `all_red_s` is a flat
2 s; `min_green_s` is a flat 10 s. Measured, paired, 10 seeds, zero interlock
violations in every arm:

vs **CC-A-CAMP** as shipped:

| arm | light | medium | heavy |
|---|---|---|---|
| yellow 3 s | **−18.9% SIG** (10/10) | **−21.0% SIG** (9/10) | −3.7% n.s. |
| yellow 3 s + min green 7 s | **−21.7% SIG** (10/10) | **−23.5% SIG** (10/10) | **−5.2% SIG** (7/10) |
| min green 7 s alone | −2.4% n.s. | +7.4% n.s. | +3.5% n.s. |

vs **Webster** as shipped, so the two changes can be compared on one scale:

| arm | light | medium | heavy |
|---|---|---|---|
| Webster, yellow 3 s | −14.3% SIG | −20.6% SIG | −7.6% SIG |
| CC-A-CAMP, yellow 3 s | −35.0% SIG | −30.0% SIG | −14.9% SIG |
| CC-A-CAMP, yellow 3 s + min green 7 s | −37.2% SIG | −32.2% SIG | −16.2% SIG |

Read this carefully: shorter clearance helps **both** arms, because it is a
corridor-level capacity change rather than a control improvement, and at heavy
demand it helps Webster slightly more (−7.6% against −3.7%). What it does not do
is erase CC-A-CAMP's lead — at 3 s yellow the controller is still 24% better
than the correspondingly re-timed Webster at light. The point stands that this
single Tier-0 number moves delay further than any algorithmic change landed so
far, and that it is worth attacking before any further pressure-function work.

*This is a modelling change and must be justified on safety grounds, not on
delay.* Yellow should be computed per approach from the ITE/IRC kinematic rule
(`y = t_r + v/(2a + 2gG)`, ~3–4 s at 40–50 km/h), all-red from the clearance
distance, and minimum green from pedestrian crossing needs where a crossing
exists. Anything below the kinematic value is not available. Re-run both arms
after changing it, since the baseline moves too.

**I2. Fix the occupancy unit bug (B1), then re-tune the gate.** The fix is
required for the spillback protection to exist at all. On its own it is neutral
(−0.4% / +2.4% / +1.8%, n.s.), so pair it with a `rho_jam`/`beta_gate` search on
training seeds and keep it only if the held-out gate agrees.

### Tier 2 — worth building, effect not yet measured

**I3. Aggregate pressure per lane group (B4).** Compute one queue, one
saturation flow and one discharge benefit per *lane*, then attribute it to the
phases that serve it, instead of summing per movement over shared lanes. Expect
the effect to be largest at `1880441505`, `2833253632`, `7871074777` and
`cluster_1880441541_*`, whose phases differ by up to 3× in inflation. Must be
re-tuned; the naive rescaling alone was worse (B4).

**I4. Replace the min/max-green box with an extension rule.** With clearance
made cheap (I1), the classic actuated mechanism becomes affordable: extend while
a vehicle arrives within a headway (a real gap-out), bounded by the ceiling.
Today's structure — a 10 s floor, a 12.5 s ceiling, and a pressure contest in
between — cannot express that. Test against the I1 configuration, not the
current one.

**I5. Give the supervisor a per-phase trigger (D4).** Track, per phase, the time
since it was last served; force a switch when that exceeds its own share of the
envelope, rather than when the whole cycle exceeds a corridor-level sum. This
keeps Levin et al.'s once-per-cycle guarantee while firing at the junction that
needs it, where the current global envelope is too loose to trigger.

**I6. Tune what is actually live.** `eta_arrival` at 1.0 was better than the
shipped 0.5 on 8/10 and 6/10 seeds (n.s. at n=10, worth a proper search), while
`lambda_f`, `rho_jam`, `beta_gate`, `switch_scale_ref` and `lost_time_weight`
are demonstrably inert as configured. Re-run `tuning.py` over the parameters
that survive I2, with the demand level as a conditioning variable — PROGRESS.md
itself lists "conditioning parameters on observed congestion" as never done.

### Tier 3 — research directions, in order of fit

1. **Cyclic max-pressure with a proper phase-order constraint** — Levin, Hu &
   Odell (2020) is already the supervisor's stated basis, but the implementation
   exempts phases with no demand and triggers on a corridor-sum envelope; the
   paper's constraint is per-cycle and per-phase. Note their own result: the
   constraint *cost* delay in their setting. Adopt it for the guarantee, not for
   the delay.
2. **Position-weighted / capacity-aware back-pressure.** The pressure here uses
   raw queue minus receiving queue with no link-capacity normalisation, which is
   why 12–89% of ticks have every phase negative at once. Capacity-aware
   variants and queue-ratio formulations restore a usable ranking under
   saturation.
3. **Schedule-driven control (SURTRAC).** Smith et al.'s formulation plans a
   short rolling schedule per junction and passes it to neighbours. It fits this
   corridor's shape (7 junctions, one arterial) far better than per-tick
   argmax, and it prices switching explicitly instead of through a hold bias.
4. **Offsets / green waves.** There is no coordination between junctions beyond
   what pressure implies; `coordinated_actuated.py` exists as a baseline and is
   not used in the gate. MAXBAND/MULTIBAND-style offset optimisation on top of
   the existing ceiling is a well-understood, low-risk addition.
5. **RL** (PressLight / MPLight / CoLight, and Advanced-MP's "expression"
   critique) is the obvious modern comparison, but on this corridor it would be
   training against a 2.5 s decision band and a dead spillback signal. Fix I1–I3
   first; then a shielded RL policy (interlocks as an action mask) is a
   defensible capstone extension and the safety kernel already provides the
   shield.
6. **Detector realism.** Everything reads SUMO ground truth. `m5_sensor_
   degradation.py` exists; the roadmap should include a noisy-detector arm before
   any claim about deployability.

---

## 6. Evaluation improvements

- **Fix throughput (B2) or drop it.** As shipped it cannot distinguish arms.
- **Score the same trip population for every arm (B3).**
- **Count teleports and spillback episodes per arm (D6)** and report them beside
  delay; a controller that gridlocks and teleports vehicles currently looks good.
- **Report a distribution, not only a mean:** p95 and max wait are already
  computed; the gate should fail on a p95 regression too.
- **More seeds at heavy.** Heavy's per-seed spread is ±60k on a 1.4M mean; 10
  seeds gives CIs wide enough that a 5% effect is borderline. 20–30 seeds costs
  minutes here.
- **State the baseline honestly (B7):** "Webster with textbook 4 s lost time",
  and publish the corrected-`L` arm alongside it.
- **Add a second network.** Every conclusion in this project is from one
  corridor with one demand profile; the ceiling result in particular is a claim
  about this corridor's Webster greens.

---

## 7. Roadmap

| # | Work | Expected effect | Effort | Depends on |
|---|---|---|---|---|
| 1 | I1 clearance + min green, re-derived and re-gated | −20% light/medium, −5% heavy (measured) | 1 day | safety justification |
| 2 | B1 unit fix + gate re-tune | unlocks spillback protection; delay-neutral until tuned | 1 day | — |
| 3 | B2/B3 metric fixes | correctness of every future comparison | hours | — |
| 4 | B5 `max_wait_s` derived from the live ceiling | restores I5; may remove heavy's violations at the source | hours | — |
| 5 | I3 lane-group pressure | removes a 1.0–3.0× structural bias | 2–3 days | 2, re-tune |
| 6 | I4 extension rule | the adaptive band I1 creates becomes usable | 2–3 days | 1 |
| 7 | I5 per-phase supervisor trigger | heavy-demand fairness and violations | 1–2 days | 4 |
| 8 | I6 re-tune live parameters, conditioned on demand | few % | 1 day of compute | 2, 5 |
| 9 | Offsets / green wave | unknown, likely largest remaining structural gain | 1 week | 1 |

---

## 8. Open questions

- Why is the pressure gap zero at the median tick? I measured it but did not
  decompose it per term; the likely cause is that both phases' `− r_m` terms
  dominate identically, but that is a **hypothesis**.
- Is 3 s yellow defensible for these approaches? The delay result is measured;
  the safety justification is not, and it decides whether I1 is available.
- Does the corridor's emergency-preemption path interact with I1? Not tested —
  no EV runs were included here.
- The 71 teleports: how much of heavy demand's delay difference between arms is
  teleport-mediated? Not measured.

---

## 9. References

- Varaiya, P. (2013). *Max pressure control of a network of signalized
  intersections.* Transportation Research Part C 36, 177–195.
  https://doi.org/10.1016/j.trc.2013.08.014
- Levin, M. W., Hu, J., Odell, M. (2020). *Max-pressure signal control with
  cyclical phase structure.* Transportation Research Part C 120, 102828.
  https://www.sciencedirect.com/science/article/abs/pii/S0968090X20307324
- Smith, S. F., Barlow, G., Xie, X.-F., Rubinstein, Z. (2013). *SURTRAC:
  Scalable Urban Traffic Control / Smart urban signal networks.* ICAPS.
  https://ojs.aaai.org/index.php/ICAPS/article/view/13594
- Xie, X.-F., Smith, S. F., Barlow, G. (2012). *Schedule-driven intersection
  control.* Transportation Research Part C.
  https://www.ri.cmu.edu/publications/schedule-driven-intersection-control
- Lämmer, S., Helbing, D. (2008). *Self-control of traffic lights and vehicle
  flows in urban road networks.* J. Stat. Mech. P04019.
  https://iopscience.iop.org/article/10.1088/1742-5468/2008/04/P04019
- Wei, H. et al. (2019). *PressLight: learning max-pressure control to coordinate
  traffic signals in an arterial network.* KDD.
  https://dl.acm.org/doi/10.1145/3292500.3330949
- Zhang, L. et al. (2022). *Expression might be enough: representing pressure and
  demand for reinforcement learning based traffic signal control.* ICML.
  https://proceedings.mlr.press/v162/zhang22ah/zhang22ah.pdf
- Sushmitha, R. et al. (2020). *Effect of vehicle composition on saturation flow
  at signalised intersections in mixed traffic conditions.* IET ITS.
  https://doi.org/10.1049/iet-its.2019.0470
- Webster, F. V. (1958). *Traffic signal settings.* Road Research Technical Paper
  No. 39, HMSO — the formula `webster.py` implements.
- Xu et al., Transp. Res. Part C 137 (2022) and Hsieh et al. (2017) are already
  cited in `memory.py` for the sublinear hold bias; both were taken as given
  here and not re-derived.

---

## Appendix — how to reproduce

The scratch harness is not in the repo (deliberately). To re-run any arm:

```bash
cd itms && make setup            # SUMO must stay pinned at 1.27.1
.venv/bin/pytest -q              # expect 549 passed, 6 skipped
.venv/bin/python scripts/m5_baseline_benchmark.py --out /tmp/fresh.json
.venv/bin/python scripts/compare_m5_baseline.py \
    baselines/2026-09-16_m5_traffic_coordination/m5_baseline_results.json /tmp/fresh.json
```

Every ablation in §2 is one `AcampConfig` field change plus
`m5_cycle_ceiling_probe.configs_with_ceiling(inputs, factor)`; every timing arm
in §5 is a `dataclasses.replace` on the `Tier0Config` before the run. The
per-arm results, the instrumented per-junction records and the analysis scripts
used for this report are attached to the session that produced it.

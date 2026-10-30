# Paper A: final benchmark (2026-10-28)

**Status: simulation results (SUMO 1.27.1), not field results. Targets were written before any run on the
fresh seeds (`TARGETS.md`); 5 of 9 targets pass. Not committed.** Generated tables: `results/SUMMARY.md`
(`summarise.py`), verdicts: `results/VERDICTS.md` (`verdicts.py`).

## 1. Setup

- **Networks (8):** arterial_lh, ingolstadt, narrow_lh, random_lh, grid4_rh_turns, berlin_adlershof,
  vijayawada_district, amaravati_v2. **Demand:** light / medium / heavy (flow ratio 0.25 / 0.5 / 1.0 at the busiest
  junction). 24 network-levels.
- **Seeds:** 279-288 for the main table (10 per cell), 279-283 for the ablation and camera runs. No experiment in this
  project had used seeds 279+ before; nothing was tuned on them. The only choices made before the run (max-pressure
  slot 10 s, actuated maxDur 50 s, RL checkpoint) used training seeds 101-110.
- **Controller (frozen, checksums in `FROZEN.txt`):** CC-A-CAMP as of 2026-10-28 (paired phases, 1.25x Webster
  ceiling with 20 s floor, cycle supervisor, 3 s gap-out, split-road sensing, shown overlaps, kinematic yellow), plus
  one safety fix made before the run (section 6).
- **Baselines, same networks / demand / seeds / phases / clearances:**
  Webster fixed time on the same (paired) phase layout; plain max-pressure (Varaiya 2013, 10 s slot, same sensing);
  SUMO's built-in actuated control (gap-based, max-gap 3 s, minDur = min green, maxDur 50 s); PressLight-style DQN
  (one agent per junction, trained on seeds 101-108, checkpoint chosen on 109-110), ingolstadt only.
- **Metric:** total person-delay per run; per seed the % change of ours against the other controller; mean over
  seeds with a t-based 95 % interval ("n.s." = interval includes 0); pooled figures use a t interval across cells. Delay counts finished trips only, so teleports
  and unfinished vehicles are reported beside it: where they are large the delay comparison is not reliable.
- **Where it ran:** Michael's Mac (main ITE table, vijayawada_district ablation), Preethi's Mac (flat all-red block,
  arterial_lh and ingolstadt ablations), the cloud workspace (RL, lane-less, cameras; berlin_adlershof, grid4_rh_turns,
  random_lh and narrow_lh ablations). The same seed gives the
  same result on every machine (checked: identical to the decimal on cloud vs Mac, arterial_lh seed 279, four
  controllers).

## 2. All-red setting

**All main numbers use the ITE all-red per junction** (`SIGNAL_ALL_RED=ite`: r = (W + 6 m) / v, 0.5 s steps,
1-4 s; network means 1.5-2.7 s). Ours and Webster were also run on the old flat 2.0 s, same seeds (section 4).

## 3. Targets (written before the run)

| # | target | result | verdict |
|---|---|---|---|
| S1 | 0 interlock violations, ours | 0 in ours' 240 ITE + 240 flat runs (0 for every controller in all 2,490 runs of this benchmark) | **pass** |
| S2 | ours never teleports significantly more than Webster | more on amaravati_v2 heavy (598 vs 186) and narrow_lh medium (1442 vs 1018) | **fail** |
| W1 | better than Webster on >= 18/24 | 19/24 | **pass** |
| W2 | worse than Webster on <= 2/24 | 1/24 (amaravati_v2 heavy) | **pass** |
| W3 | pooled gain vs Webster under ITE within 5 points of flat | -26.6 % vs -29.2 % (2.6 points) | **pass** |
| M1 | vs max-pressure: better >= 16/24, worse <= 3 | better 15, worse 4 | **fail** |
| A1 | vs actuated: better >= 16/24, worse <= 3 | better 14, worse 5 | **fail** |
| P1 | p95 wait worse than Webster on <= 3/24 | 2/24 | **pass** |
| R1 | vs PressLight (ingolstadt): better on 3 levels, 2 significant | better at light only; see section 5 | **fail** |

## 4. Main results (ITE all-red, seeds 279-288)

Ours against each baseline: % change in person-delay, 95 % interval, seeds on which ours was lower.
Negative = ours better. Teleports and vehicles still in the network at the 6,000 s cap are summed over the 10 seeds;
delay counts finished trips only, so cells with many of either are not reliable comparisons.

| network | level | vs Webster | vs max-pressure | vs actuated | teleports ours / W / MP / A | unfinished at cap ours / W / MP / A |
|---|---|---|---|---|---|---|
| amaravati_v2 | light | -36.0 [-37.9, -34.2] 10/10 | -59.2 [-62.1, -56.4] 10/10 | -24.5 [-29.2, -19.9] 10/10 | 3 / 2 / 245 / 1 | 0 |
| amaravati_v2 | medium | -22.3 [-29.5, -15.2] 10/10 | -60.8 [-63.4, -58.2] 10/10 | -2.2 [-11.3, +6.9] 7/10 | 7 / 6 / 681 / 14 | 0 / 0 / 821 / 0 |
| amaravati_v2 | heavy | +12.5 [+2.6, +22.3] 2/10 | +13.2 [+3.4, +22.9] 1/10 | +27.4 [+17.0, +37.9] 1/10 | 598 / 186 / 1809 / 79 | 2557 / 2466 / 4271 / 5 |
| arterial_lh | light | -46.0 [-49.7, -42.4] 10/10 | -24.3 [-31.0, -17.7] 10/10 | -12.8 [-21.3, -4.3] 9/10 | 0 | 0 |
| arterial_lh | medium | -36.3 [-40.0, -32.5] 10/10 | -28.3 [-33.1, -23.5] 10/10 | -17.3 [-22.8, -11.7] 10/10 | 0 | 0 |
| arterial_lh | heavy | -28.6 [-32.2, -24.9] 10/10 | -22.0 [-27.4, -16.6] 10/10 | -5.5 [-10.1, -0.9] 8/10 | 0 | 0 |
| berlin_adlershof | light | -40.0 [-41.5, -38.5] 10/10 | +4.5 [+2.2, +6.8] 0/10 | -31.8 [-33.7, -29.8] 10/10 | 0 | 0 |
| berlin_adlershof | medium | -37.3 [-38.7, -35.9] 10/10 | +2.3 [-1.5, +6.1] 3/10 | -25.3 [-30.4, -20.1] 10/10 | 2 / 3 / 8 / 5 | 0 |
| berlin_adlershof | heavy | -36.7 [-52.4, -21.1] 10/10 | +123.3 [-75.0, +321.5] 4/10 | -14.3 [-42.8, +14.3] 9/10 | 3894 / 6847 / 3873 / 4852 | 0 / 4 / 167 / 6 |
| grid4_rh_turns | light | -41.2 [-42.0, -40.3] 10/10 | -19.1 [-20.3, -17.8] 10/10 | -6.0 [-7.4, -4.6] 10/10 | 0 | 0 |
| grid4_rh_turns | medium | -31.3 [-32.2, -30.4] 10/10 | -13.1 [-14.6, -11.5] 10/10 | +5.0 [+2.8, +7.2] 0/10 | 0 | 0 |
| grid4_rh_turns | heavy | -5.6 [-6.7, -4.6] 10/10 | -4.7 [-6.5, -2.9] 10/10 | +19.5 [+18.1, +20.8] 0/10 | 0 | 0 |
| ingolstadt | light | -32.8 [-36.0, -29.6] 10/10 | -12.7 [-16.5, -9.0] 10/10 | -39.9 [-43.8, -36.0] 10/10 | 0 | 0 |
| ingolstadt | medium | -28.9 [-31.9, -25.8] 10/10 | -3.8 [-7.6, -0.0] 8/10 | -32.0 [-35.3, -28.7] 10/10 | 0 / 0 / 2 / 27 | 0 |
| ingolstadt | heavy | +10.4 [-56.2, +76.9] 6/10 | +246.4 [+77.6, +415.1] 0/10 | +135.6 [+22.8, +248.4] 3/10 | 213 / 261 / 34 / 68 | 0 / 91 / 0 / 0 |
| narrow_lh | light | -44.5 [-46.2, -42.8] 10/10 | -30.4 [-34.0, -26.7] 10/10 | -13.5 [-17.6, -9.4] 10/10 | 0 | 0 |
| narrow_lh | medium | -3.5 [-20.3, +13.2] 6/10 | +6.4 [-5.8, +18.6] 3/10 | +0.8 [-12.8, +14.3] 4/10 | 1442 / 1018 / 816 / 1662 | 813 / 0 / 0 / 1162 |
| narrow_lh | heavy | +14.6 [-12.8, +42.1] 4/10 | +25.1 [-11.7, +62.0] 3/10 | +14.4 [-6.8, +35.6] 3/10 | 4602 / 5228 / 4540 / 4905 | 30643 / 30951 / 30580 / 30496 |
| random_lh | light | -45.0 [-48.1, -41.9] 10/10 | -14.6 [-18.7, -10.6] 10/10 | -36.6 [-41.0, -32.2] 10/10 | 0 | 0 |
| random_lh | medium | -46.9 [-48.4, -45.4] 10/10 | -19.3 [-22.0, -16.6] 10/10 | -34.6 [-36.9, -32.2] 10/10 | 0 | 0 |
| random_lh | heavy | -30.5 [-32.6, -28.5] 10/10 | -20.0 [-24.4, -15.6] 10/10 | +9.9 [+4.2, +15.5] 1/10 | 0 / 0 / 3 / 0 | 0 |
| vijayawada_district | light | -31.3 [-39.3, -23.3] 10/10 | +10.7 [+3.7, +17.7] 2/10 | -18.4 [-21.8, -15.0] 10/10 | 0 / 10 / 3 / 1 | 0 |
| vijayawada_district | medium | -41.8 [-53.8, -29.8] 10/10 | -19.7 [-40.4, +1.0] 8/10 | -20.9 [-34.4, -7.3] 9/10 | 21 / 95 / 100 / 48 | 0 |
| vijayawada_district | heavy | -8.5 [-30.5, +13.5] 5/10 | -31.8 [-48.3, -15.2] 9/10 | +28.6 [-4.8, +62.0] 2/10 | 764 / 657 / 1389 / 585 | 0 |

Per-controller absolute values (delay per trip, p95 wait, stops per vehicle, unfinished vehicles, interlock
violations) for every cell: `results/SUMMARY.md`, "Main table".

**Pooled over the 24 network-levels** (mean of the per-cell % changes, 95 % interval across cells):

| comparison | all-red | mean | 95 % interval | ours significantly better | ours significantly worse |
|---|---|---|---|---|---|
| ours vs Webster | ITE | -26.6 % | [-34.7, -18.5] | 19 | 1 |
| ours vs Webster | flat 2.0 s | -29.2 % | [-36.6, -21.9] | 20 | 0 |
| ours vs max-pressure | ITE | +2.0 % | [-24.4, +28.4] | 15 | 4 |
| ours vs actuated | ITE | -3.9 % | [-19.0, +11.2] | 14 | 5 |

The pooled max-pressure and actuated means are pulled by three jammed cells (ingolstadt heavy, berlin heavy,
amaravati heavy); the counts are the better summary.

**Safety per controller (all 240 ITE runs each):** interlock violations 0 for every controller (SUMO's actuated
programs checked from outside every step for conflicting protected greens). Teleports: ours 11,546; Webster 14,313;
max-pressure 13,503; actuated 12,247, almost all in the jammed cells (berlin heavy, narrow_lh medium/heavy,
amaravati heavy, vijayawada heavy, ingolstadt heavy).

**Cost of the ITE all-red, same seeds (ITE vs flat 2.0 s), light and medium:** ours +8.1 to +11.7 % on arterial_lh,
berlin_adlershof, grid4_rh_turns and random_lh; +2 to +6 % on amaravati_v2 and vijayawada_district (n.s.); +18 % and
+46 % on ingolstadt; narrow_lh +0.2 % / -10.5 %. Webster: +3 to +14 % on most cells, -3.0 % on arterial_lh medium,
+21 to +24 % on ingolstadt, +38 % (n.s.) on vijayawada medium. Full table: `results/SUMMARY.md`.

**Clearances are rounded up to whole seconds in the simulation.** The runner counts yellow and all-red down in 1 s
steps, so a 3.5 s yellow is shown for 4 s and a 1.5 s all-red for 2 s. On narrow_lh the ITE all-red (1.5 s) is
therefore shown exactly as long as the flat 2.0 s: Webster's runs there are identical under both settings (checked:
same result to the decimal), while ours still differs because its timing calculations use the 1.5 s value. The
same rounding applies to every controller, but the "ITE" numbers mean ITE values rounded up to the next second.

## 5. Other runs

**PressLight (RL), ingolstadt, ITE, seeds 279-288.**

| level | ours vs PressLight | teleports ours / RL | vehicles unfinished at the 6,000 s cap, ours / RL |
|---|---|---|---|
| light | -3.8 % [-7.1, -0.5], 7/10 | 0 / 0 | 0 / 0 |
| medium | +142.3 % [+132.2, +152.4], 0/10 | 0 / 264 | 0 / 799 |
| heavy | +323.7 % [+109.8, +537.5], 0/10 | 213 / 219 | 0 / 1705 |

At medium and heavy demand PressLight leaves on average 80 and 170 vehicles per run in the network at the cap (ours: 0)
and teleports 26 and 22 per run. Its delay per finished trip is still about half of ours (35 vs 74 s at medium, 62 vs
227 s at heavy), so it is not only that fewer trips are scored; but the vehicles it never finishes are the ones
missing from its delay, and they are likely the most delayed. Read honestly: ours is better at light; at medium and
heavy PressLight serves the vehicles that do finish much better while it leaves part of the network stuck, and the
delay comparison is not valid until unfinished vehicles are counted. A metric that counts unfinished vehicles (e.g. delay including vehicles still
in the network at the cap) is needed before any claim either way. Our `ingolstadt` is SUMO's 2-signal fkk_in map,
not RESCO's InTAS Ingolstadt, so published RL numbers cannot be compared directly.

**Lane-less Indian traffic** (SUMO sublane model, 0.8 m; two-wheelers 37 % and autos 19 % of vehicles filter and
take any lateral position): arterial_lh_sublane and vijayawada_district_sublane, all four controllers, ITE, seeds
279-288. Pooled over 6 network-levels: ours vs Webster -32.7 % [-38.7, -26.8], vs max-pressure -17.0 %
[-33.9, -0.2], vs actuated -8.5 % [-23.0, +6.0]. Ours is better than every baseline at every level on
arterial_lh_sublane. On vijayawada_district_sublane max-pressure is better at light (+13.8 %); against max-pressure at
medium (-15.5 %) and against actuated at medium (-0.1 %) and heavy (+13.7 %) the differences are not significant.
vijayawada_district_sublane jams at heavy demand for every controller (teleports over 10 seeds: ours 647, Webster
648, max-pressure 1,091, actuated 510). 0 interlock violations.

**Cameras in the loop** (`vision:itms6_640:failsafe`, the adopted fine-tuned detector, arterial_lh and random_lh,
ITE, seeds 279-283). Cost of cameras against perfect sensing: arterial light +7.8 % [+0.6, +15.0], medium +0.8 %
(n.s.), heavy -2.5 % (n.s.); random_lh light +13.0 % (n.s.), medium +11.0 % [+4.7, +17.4], heavy +1.8 % (n.s.).
At heavy demand on random_lh the camera runs had 3 teleports against 0 with perfect sensing; no jam on arterial_lh.
0 interlock violations.

## 6. All-red: the interlock violations and the fix

The 2026-10-27 ITE runs had 4 I5 (maximum-wait) interlock rejections. Traced on training seeds: CC-A-CAMP treated a
waiting movement as urgent only within a fixed 15 s of its wait bound. Reaching it can take longer: berlin_adlershof
medium seed 103, junction joinedS_2, a phase was committed at wait 179 s and the change (3.5 s yellow + 3.5 s all-red),
7 s minimum green and a second change brought the movement to 200 s against a 195 s bound; amaravati_v2 medium seed
103, two phases were urgent together and the one served second overran by 8 s. The margin is now sized per junction:
`max(15 s, (phases - 1) x (min green + yellow + all-red) + 1 s)` (`acamp._wait_margin_s`). Result: all four cases
rerun with 0 violations, and 0 in every run of this benchmark. Cost on flat all-red, training seeds 101-103: identical
at light and medium on arterial_lh, random_lh and berlin_adlershof; at heavy demand random_lh -0.7/-0.6/+2.5 % and
berlin_adlershof +13.9/+11.1/-2.3 % per seed (the margin acts only near the bound).

## 7. Ablation (ITE, seeds 279-283, one part off at a time against the full controller)

Mean of per-network-level % changes in person-delay (positive = the part helps), 95 % t interval across cells. A part
that does not exist on a network (no split-phased junctions, no split roads, no overlap), or never acts there, gives
exactly 0 there and is included.

| part switched off | network-levels | mean % change in delay without it | 95 % interval |
|---|---|---|---|
| paired phases | 21 | +14.6 % | [+3.1, +26.1] |
| gap-out | 21 | +3.1 % | [-1.9, +8.1] |
| 20 s ceiling floor | 21 | +1.5 % | [-0.7, +3.7] |
| shown overlaps | 21 | -0.0 % | [-1.2, +1.2] |
| cycle supervisor ("static ceiling" arm) | 21 | -0.7 % | [-4.3, +2.9] |
| split-road sensing | 21 | -1.3 % | [-6.0, +3.3] |
| green ceiling (1.25x Webster) | 21 | -5.4 % | [-11.1, +0.2] |
| kinematic yellow (vs netconvert 3.0 s) | 21 | -5.6 % | [-14.1, +2.8] |

Networks: arterial_lh, berlin_adlershof, grid4_rh_turns, ingolstadt, narrow_lh, random_lh, vijayawada_district (7 of 7). Interlock violations in all ablation runs: 0.

Reading:
- **Paired phases are the largest single contributor** where they apply (arterial_lh +31 to +46 %, grid4_rh_turns +48
  to +76 % without them). This is a better signal program, not adaptive control: Webster on the same paired phases
  gets much of the same gain (2026-10-13 baseline).
- **The green ceiling does not help under ITE, and on six of seven networks it hurts.** Removing it (10x Webster) lowered
  delay on 11 of 12 light/medium cells of the first six networks; pooled over all 21 cells -5.4 % [-11.1, +0.2]
  (just not significant, because on vijayawada_district medium and heavy removing it was +22 % and +30 %, n.s.).
  With longer clearances each forced change costs more. The ceiling was chosen under the flat 2.0 s; it should be
  re-chosen on training seeds for ITE and retested on fresh seeds. Not adopted from this run.
- **The kinematic yellow helps where netconvert's guess is long and costs where it is short.** On six networks
  netconvert's yellow is 3.0 s (kinematic 3.5 s): switching the rule off shortens the yellow and delay falls about
  10 % (with less clearance). On vijayawada_district netconvert's yellow is 5.0-6.0 s: switching the rule off
  lengthens it and delay rises (+11.1 % [+3.2, +18.9] at light; +29 % and +23 % at medium and heavy, n.s.).
  Pooled -5.6 % [-14.1, +2.8], not significant. The rule's value is consistency with the safety standard, not delay.
- **Gap-out helps** on berlin_adlershof (+10 to +22 % without it) and random_lh (+8 % at medium); pooled +3.1 %, n.s.
- **20 s floor, cycle supervisor ("static ceiling" arm), split-road sensing, shown overlaps:** within about +-1.5 %
  pooled under ITE, none significant.
- So "network-derived timing drives most of the gain" holds in this sense: the phase layout built from the network's
  geometry (paired phases, +14.6 % [+3.1, +26.1] pooled, up to +76 % where it applies) and the Webster-based timing
  carry most of the advantage over Webster; the adaptive parts each add little, and the ceiling is currently neutral
  to harmful under ITE.

## 8. Failures (stated plainly)

- **Jams:** berlin_adlershof heavy and narrow_lh medium/heavy jam for every controller (816 to 6,847 teleports per
  controller over 10 seeds; at narrow_lh heavy about 30,000 vehicles unfinished per controller); delay there is not
  a valid comparison. At narrow_lh medium ours leaves 813 vehicles unfinished, Webster and max-pressure none. narrow_lh (single-lane roads with turns) gains only at light demand.
- **Heavy demand:** ours loses to Webster, max-pressure and actuated on amaravati_v2 heavy and teleports more than
  Webster there (598 vs 186); loses to actuated on grid4_rh_turns (medium, heavy), random_lh heavy and ingolstadt
  heavy; loses to max-pressure on ingolstadt heavy. vijayawada_district heavy is not significant against Webster.
- **Light demand:** plain max-pressure beats ours on berlin_adlershof (+4.5 %) and vijayawada_district (+10.7 %).
- **RL:** PressLight's numbers at medium/heavy rest on unfinished trips; the comparison needs a metric that counts
  them.
- **Simulation only:** SUMO drivers never run a red, so the safety benefit of the ITE all-red cannot be shown here;
  permissive turns assume drivers give way.

## Files

`TARGETS.md`, `FROZEN.txt`, `run_mac.sh`, `run_mac_A.sh`, `run_mac_B.sh`, `run_cloud.sh`, `cloud_all.sh`,
`run_cloud_abl.sh`, `run_cloud_flat.sh`, `setup_and_run_B.sh`, `summarise.py`, `verdicts.py`, `rl_models/`,
`results/` (`main_*_{ite,flat}.json`, `abl_*_ite.json`, `indian_*`, `camera_*`, `rl_ingolstadt_ite.json`, logs,
`SUMMARY.md`, `VERDICTS.md`). New code: `strategies/maxpressure.py`, `scripts/paper_a_baselines.py`,
`scripts/paper_a_rl.py`, `scenarios/make_sublane_variant.py`, the margin fix in `strategies/acamp.py`, the
`maxpressure`/`actuated`/`ync` arms in `m8_closed_loop_gate.py`, `SIGNAL_YELLOW=netconvert` in
`extract_tier0_config.py`, tests in `test_maxpressure_and_wait_margin.py`.

# Baseline — the controller on any road network (2026-09-29/30)

Until now every result in this project came from one network, the Vijayawada
corridor, and every script named its files. This baseline asks whether the
system works on road networks it was never built or tuned on: generated
grids, a radial network, irregular streets, turn bays, right-hand traffic,
two real cities from SUMO's own examples (Berlin and Ingolstadt), and a whole
Indian street grid built straight from raw OpenStreetMap (the district around
the corridor, not the corridor). In short:

1. **No controller setting was changed.** CC-A-CAMP runs with the parameters
   tuned on the corridor's TRAIN seeds, everywhere.
2. **What broke was how a network was read, in three places**, each fixed so
   the corridor is unchanged (its configuration is identical, and 15 of 15
   perfect-data runs that could be compared came out bit-identical):
   - a road SUMO cuts into several edges (turn bays, lane changes,
     OpenStreetMap tags) was measured on its last few metres only (§3.1);
   - signal programs list more than phases: change intervals that keep one
     movement green, German red+amber, pedestrian clearances inside a stage
     (§3.2);
   - a light over several junctions, or one that numbers its links its own
     way, was read through the wrong junction's conflict table (§3.3).
3. **With perfect data, the controller beat Webster at every demand level on
   eight of the nine new networks** (paired over 10 held-out seeds, all
   significant except two heavy levels: Ingolstadt, better on 10/10 seeds
   but three jammed Webster runs widen the interval, and the district, −15 %
   and better on 8/10). Zero interlock violations in the 290 runs behind
   those results.
4. **The three real networks passed every perfect-data target set before
   their held-out runs** (`TARGETS.md`), against Webster at light / medium /
   heavy: Berlin −38 / −35 / −33 %, Ingolstadt −28 / −35 / −55 %, the
   Vijayawada district −33 / −39 / −15 % (heavy n.s.). Ingolstadt's −55 % is
   mostly three Webster jams; on the other seven seeds it is −11.6 %
   (significant).
5. **One command builds a scenario for any city from OpenStreetMap**
   (`scenarios/city_from_osm.py`, §1.1; its download step needs ordinary
   internet access and has not been run from here). OSM marks one signal in
   the whole Vijayawada extract, so lights also go where three or more real
   roads (tertiary and above) meet. The district result above is this path,
   on the raw extract of the corridor's bounding box.
6. **One network type still fails: single-lane roads with turning traffic**
   (`narrow_lh`). At heavy demand every run of both controllers reaches the
   run-length cap; at medium the controller reaches it on 4 of 10 seeds,
   Webster on 1 (§5).
7. **Cameras** (§4) cost about what they cost on the corridor: +4.6 and
   +7.8 % against perfect data at medium on two generated networks (n.s.),
   still 15–53 % better than Webster (25–36 % at medium). On Berlin (62 cameras) they passed the
   three targets set before the runs: −33.0 % and −33.7 % against Webster
   at light and medium (5/5 seeds each), +8.1 % (significant) and +0.8 %
   (n.s.) against perfect data. That took two fixes for very short approach
   lanes, found on training seeds after the first attempt came out +26 % and
   +39 % (§4.1).
8. **Live services on another network:** the end-to-end run (SUMO, the
   controller and the camera service over Redis, cameras feeding the
   controller) on the 3x3 grid had 0.0 % of junction-ticks with a link in
   hard failure over 300 s, and no interlock violation. The 70–73 % seen in the
   first run came from the machine: it was running two gate workers at the
   same time (the simulation reached 150 steps in about nine minutes), and
   the feed counts an estimate older than 3 s as a hard failure. Idle, the
   same check shows none.

## 1. How a network becomes a scenario

`scenarios/build_scenario.py` takes any SUMO network, generated
(`--generate grid|spider|rand`) or given (`--net`, gzipped too), and writes a
scenario directory: the network, three demand levels, cameras, and a
`scenario.json`. `ITMS_SCENARIO=<dir>` points every service and harness at it
(`itms_domain.scenario`); unset, it is the corridor.

**Demand levels are set by load, not by a trip rate**: the busiest light's
flow ratio `Y` (the sum of its phases' critical flow ratios, which
`webster.compute_timing` reports as `degree_of_saturation`), 0.25 / 0.5 /
1.0 — where the corridor's own levels measure (0.245, 0.471, 0.996). Lost time
is not counted, so `Y = 1` is already past capacity. It uses Webster's
nominal saturation flow, which overstates what single lanes with turning
traffic carry (§5), and it looks at signals only (Berlin heavy, §2). Trips are `randomTrips` (fringe factor
5, 30 minutes), routed by `duarouter`; the vehicle mix is the corridor's
(`india`) on the left-hand networks and cars only on the right-hand ones.

| network | built from | drive | lights | phases per light | approach lanes | of them split (chained) | cameras |
|---|---|---|---:|---|---:|---:|---:|
| vijayawada (reference) | OSM, curated | left | 7 | 2, 4 | 40 | 0 | 19 |
| grid3_lh | `grid:3x3,300,2` | left | 9 | 2 | 72 | 0 | 36 |
| arterial_lh | `grid:6x1,300,3,200`, one phase per approach | left | 6 | 4 | 72 | 0 | 24 |
| narrow_lh | `grid:3x3,200,1` (one lane) | left | 9 | 2 | 36 | 0 | 36 |
| spider_lh | `spider:5,3,200,2` (radial) | left | 15 | 2, 3 | 110 | 0 | – |
| random_lh | `rand:40,200,2,3` (irregular) | left | 28 | 2–5 | 196 | 0 | – |
| grid4_rh_turns | `grid:4x4,250,2`, turn bays, one phase per approach | right | 16 | 4 | 192 | 192 | 64 |
| berlin_adlershof | SUMO `tools/game/DRT/osm.net.xml` (Berlin, OSM) | right | 15 | 2–5 | 96 | 27 | 62 |
| ingolstadt | SUMO `tools/game/fkk_in/ingolstadt.net.xml.gz` | right | 2 | 3 | 23 | 10 | – |
| vijayawada_district | raw OSM of the corridor's box, `city_from_osm.py` (1,440 junctions) | left | 37 | 2–4 | 174 | 12 | – |

Cameras "–": none were used on that network (the radial and random networks
have camera plans from their first build, unused here).

### 1.1 Any city from OpenStreetMap (`scenarios/city_from_osm.py`)

```bash
python scenarios/city_from_osm.py --bbox W,S,E,N --name <city> --lefthand   # downloads
python scenarios/city_from_osm.py --osm area.osm.xml --crop W,S,E,N --name <area> --lefthand
```

It downloads the box with SUMO's `osmGet.py` (ordinary internet access;
not from the build sandbox), converts it with the corridor's netconvert
options (`networks/vijayawada/build.sh`: OSM nodes within 25 m joined, lights
on one cluster joined, OSM signal tags read), keeps roads cars use, caps
speeds at 50 km/h as the corridor does (`cap_speeds.py`), places lights and
runs `build_scenario.py`.

**Where the lights go.** OpenStreetMap marks few signals in Indian cities:
converted with the tags alone, the Vijayawada extract has one light in its
whole street grid (its four signal-tagged nodes are one intersection), and
netconvert's own guess (`--tls.guess`, by the sum of incoming speeds) adds
three. So a junction also gets a light where
at least three of the roads entering it are tertiary or above
(`--signal-class`, `--signal-approaches`): two real roads crossing, or a T
of them. Residential streets meeting stay give-way. The corridor's seven
lights were picked by hand, by junction degree on the arterial.

**The district** is this path on the raw extract of the corridor's bounding
box (downloaded 2026-08-21; `rebuild.sh` has the command), cropped to the
box: the whole street grid around the corridor, the corridor's vehicle mix,
and 37 lights, none chosen by hand: the one OSM-tagged light and 36 from the
rule (it picked 37 junctions; netconvert joined two of them under one
light). A first build, without the 25 m junction join and the speed cap,
was used for development on TRAIN seeds 101–105
(`results/vijayawada_district_first_build_train.json`); the table in §2 is
the rebuild, on EVAL seeds only. On seed 101 the controller did worse than
Webster (+21.6 %), and SUMO kept removing stuck vehicles at two give-way
junctions joined by a 0.2 m edge. The rebuild still has that pair: the EVAL
gate's log (which also holds runs cut short by a container restart) records
818 teleports, 89 of them there, in runs of both controllers.

## 2. Perfect data against Webster

`scripts/m8_closed_loop_gate.py --arms webster,truth`, EVAL seeds 1–10, mean
person-delay (s), paired difference with its 95 % interval
(`scripts/any_network_report.py`).

| network | level | Webster | perfect data | vs Webster | seeds better |
|---|---|---:|---:|---|---:|
| vijayawada | medium | 105,878 | 72,836 | −31.2 % SIG | 10/10 |
| vijayawada | heavy | 645,098 | 475,779 | −26.2 % SIG | 10/10 |
| grid3_lh | light | 97,616 | 56,917 | −41.7 % SIG | 10/10 |
| | medium | 197,673 | 146,166 | −26.1 % SIG | 10/10 |
| | heavy | 1,825,951 | 1,631,675 | −10.6 % SIG | 10/10 |
| arterial_lh | light | 78,960 | 37,653 | −52.3 % SIG | 10/10 |
| | medium | 169,966 | 99,081 | −41.7 % SIG | 10/10 |
| | heavy | 597,597 | 280,295 | −53.1 % SIG | 10/10 |
| narrow_lh | light | 148,860 | 86,509 | −41.9 % SIG | 10/10 |
| | medium | 4,736,953 | 5,376,887 | +13.5 % n.s. | 3/10 |
| | heavy | 841,285 | 732,216 | (every run capped, §5) | 6/10 |
| spider_lh | light | 149,426 | 74,236 | −50.3 % SIG | 10/10 |
| | medium | 280,913 | 155,730 | −44.6 % SIG | 10/10 |
| | heavy | 1,541,291 | 665,213 | −56.8 % SIG | 10/10 |
| random_lh | light | 98,780 | 57,851 | −41.4 % SIG | 10/10 |
| | medium | 215,800 | 128,877 | −40.3 % SIG | 10/10 |
| | heavy | 956,211 | 681,573 | −28.7 % SIG | 10/10 |
| grid4_rh_turns | light | 60,176 | 41,024 | −31.8 % SIG | 10/10 |
| | medium | 146,982 | 115,813 | −21.2 % SIG | 10/10 |
| | heavy | 655,614 | 390,081 | −40.5 % SIG | 10/10 |
| berlin_adlershof | light | 25,347 | 15,701 | −38.1 % SIG | 10/10 |
| | medium | 64,243 | 41,671 | −35.1 % SIG | 10/10 |
| | heavy | 3,738,262 | 2,499,828 | −33.1 % SIG | 9/10 |
| ingolstadt | light | 8,998 | 6,476 | −28.0 % SIG | 10/10 |
| | medium | 44,535 | 28,911 | −35.1 % SIG | 10/10 |
| | heavy | 194,122 | 86,906 | −55.2 % n.s. | 10/10 |
| vijayawada_district | light | 120,877 | 80,553 | −33.4 % SIG | 10/10 |
| | medium | 310,721 | 189,564 | −39.0 % SIG | 10/10 |
| | heavy | 1,397,345 | 1,186,703 | −15.1 % n.s. | 8/10 |

- **Interlock violations: 0** in all 290 perfect-data runs in this table.
- **Run-length cap (6,000 s):** outside `narrow_lh` (§5), the controller
  never reached it; Webster reached it on three Berlin heavy seeds and one
  Ingolstadt heavy seed.
- **Ingolstadt heavy** is n.s. by the paired t-interval because Webster
  jammed on three seeds (392–427k against 97–107k on the other seven; one of
  the three reached the cap) while the controller stayed at 79–100k on all
  ten. Without those three it is −11.6 %, significant; the medians are 102k
  and 85k (−16.5 %).
- **Heavy on Berlin is badly jammed for both** (Webster 10.8 stops per
  vehicle, the controller 8.0; longest waits 4,893 s and 4,156 s; Webster
  reached the cap on 3 seeds, the controller on none, its runs ending at
  3,521–5,518 s). A light at flow ratio 1.0 in a real street network with
  unsignalised junctions is more than the network carries.
- **The district at heavy** is jammed for both too (6.3 and 5.6 stops per
  vehicle, runs ending at 3,150–3,897 s and 2,544–4,066 s). The controller is
  better on eight seeds and worse on two (+3.0 % and +23.0 %), and its
  longest single wait is longer (2,286 s against 1,832 s) although its mean
  wait is lower (174 s against 203 s). At light and medium its mean wait is
  less than half Webster's (16.7 s against 40.0 s; 24.5 s against 61.3 s).
- **Vijayawada, medium seeds 6–10** had not been run before; seeds 1–5 and
  all ten heavy seeds reproduce the earlier gate (`../2026-09-29_m8_heavy_jam/`,
  `closed_loop.json`) exactly.

## 3. What had to change

### 3.1 A road cut into several edges (`itms_domain.lane_chains`)

SUMO ends an edge wherever anything about the road changes. On the turn-bay
grid every approach lane was 4 m long (the stretch after the bay opens), so
the controller measured a queue of about one vehicle however long the real
one was. At heavy demand it did 2.2x Webster's delay (1,444,627 against
655,614, 0/10 seeds better), its longest wait 2,142 s.

`lane_chains` finds, for each approach lane, the lanes that continue it
upstream through nodes that are not junctions (no signal, at most two
neighbouring nodes), with each one's share of the lane's traffic (a lane
feeding two bay lanes gives each half) and its distance to the stop line; the
same downstream for receiving lanes. The simulator's queue sampler, the
camera estimator and both live services measure the chain: queues
(share-weighted), arrivals by distance to the stop line, and receiving
occupancy weighted by length. A chain never takes the same road's other
direction (the first version walked through a U-turn at a dead end onto it).

| grid4_rh_turns | Webster | before | after | before vs Webster | after vs Webster |
|---|---:|---:|---:|---|---|
| light | 60,176 | 44,832 | 41,024 | −25.5 % SIG | −31.8 % SIG |
| medium | 146,982 | 120,990 | 115,813 | −17.7 % SIG | −21.2 % SIG |
| heavy | 655,614 | 1,444,627 | 390,081 | +120.3 % SIG | −40.5 % SIG |

On the corridor the only chain is one receiving lane
(`848411146_2` → `470154178_0`); the 15 perfect-data runs that could be
compared with the earlier gate are bit-identical.

Not chained: a stop-bar presence detector (`ActuationDetector`) still reads
the stop-line lane, as a loop at the stop bar does; the discharge observer
(online calibration, off in these gates) too; and the camera's counted queue
past the view (`gap_count.py`) works per edge.

### 3.2 Signal programs (`itms_domain.signal_program`)

A program lists every state a light shows. The controller builds its own
change intervals, so it needs the green stages only. Three things are not
stages:

- **Change intervals**, even where one movement stays green: netconvert
  writes `yyyrrrGyy`. Counted as phases, they duplicated a neighbour's green
  set, the cabinet could not tell them apart on readback, and on the radial
  network the lights went to the readback failsafe about 970 times per run
  (50–78 per junction), and at heavy demand the controller did 2.8x
  Webster's delay (+176 %), with 24, 76 and 112 interlock violations at
  light, medium and heavy (ten runs each). German plans' red+amber (`u`) is a change interval
  too.
- **Parts of a stage**: consecutive greens with no amber between them, one a
  strict subset of the other — the pedestrian clearance of an OSM import
  with crossings. They had doubled a Berlin light to ten phases.
- **Repeats** of the same green in one cycle.

The camera service's phase numbering (`RoadNetwork.green_phases`) now uses
the same function, so the two cannot disagree.

The first radial and random runs had their demand levels set while the old
rule still counted change intervals as phases, so their "heavy" was
saturation 0.77 and 0.63 under the corrected rule. Both were rebuilt and
rerun; the table in §2 is the rerun. The runs at the lower levels
(`*_old_demand.json`, after the phase fix) point the same way (spider −45 /
−42 / −54 %, random −40 / −41 / −42 %).

### 3.3 Link numbering (`extract_tier0_config._program_agrees`)

The conflict table was read from the junction's `<request>` rows, keyed by
their index, which is the light's link index only when netconvert numbered
both. Two cases differ:

- **one light over several junctions** (`--tls.join`, `joinedS_*` in OSM
  imports): no junction describes it;
- **a light that numbers its links its own way** (Ingolstadt, edited in
  netedit: a junction with 35 requests under an 18-link program).

In both, conflicts now come from the program itself (two links conflict if no
green shows both), which is the network's own signal plan. The test for the
second case: the same number of links, and no green of the program showing
two protected links the junction calls foes. In the one run made before
the fix (TRAIN seed 101, medium), `gneJ21` was refused by the interlocks on
all 6,000 steps and the run reached the cap (its output was overwritten by
the rerun).

Not handled: a signal index that controls several lanes. Three of
Ingolstadt's 22 signal indices control two or three lanes each, and the
controller measures one of them. No other network here has one.

### 3.4 Smaller things

- Networks without a map projection (netgenerate's `projParameter="!"`):
  plain coordinates instead of a crash in pyproj.
- The live incident layer runs without hospital and police files (it has
  nowhere to send units, and says so).
- The web map's start centre: `VITE_MAP_CENTER="lat,lon"`; the builder
  writes the value as `map_center`.

## 4. Cameras

The camera arm (`vision:itms6_640:failsafe`: the fine-tuned detector's
measured error model on simulated camera frames, cameras planned by
`vision_service.placement`, queue counting past the view on) on two generated
networks, EVAL seeds 1–5, all arms compared on those five seeds:

| network | level | Webster | perfect data | cameras | cameras vs Webster | cameras vs perfect data |
|---|---|---:|---:|---:|---|---|
| grid3_lh (36 cameras) | medium | 198,840 | 142,333 | 148,848 | −25.1 % SIG (5/5) | +4.6 % n.s. (lower on 1/5) |
| | heavy | 1,828,413 | 1,646,539 | 1,549,986 | −15.2 % SIG (5/5) | −5.9 % SIG (lower on 4/5) |
| arterial_lh (24 cameras) | medium | 168,975 | 99,670 | 107,408 | −36.4 % SIG (5/5) | +7.8 % n.s. (1/5) |
| | heavy | 603,128 | 275,297 | 285,755 | −52.6 % SIG (5/5) | +3.8 % n.s. (2/5) |
| vijayawada (19 cameras, for comparison) | medium | | | | −28.2 % SIG (5/5) | +4.7 % SIG (0/5) |
| | heavy | | | | −16.8 % SIG (5/5) | +18.0 % n.s. (0/5) |

- **Zero interlock violations** in the 20 camera runs.
- **Confidence fed** to the controller averaged 0.92–0.93 on the grid and
  0.88 on the arterial, never below 0.5 on either. The ladder's fixed-time
  fallback fired on no grid decision and on 0–74 arterial decisions per run.
- The cameras cost about what they cost on the corridor at medium (+4.6 and
  +7.8 % against +4.7 %). The grid's heavy result, cameras 5.9 % *better*
  than perfect data, is within what the heavy regime does to a few seeds
  (`../2026-09-29_m8_heavy_jam/`: 12–22 changed decisions moved single runs
  by up to 37 %); it is not a claim that cameras beat ground truth.
- The corridor rows are its seeds 1–5 from the earlier gate
  (`../2026-09-29_m8_heavy_jam/closed_loop.json`); over its ten heavy seeds
  the cameras are +5.9 % n.s. against perfect data.

### 4.1 Berlin

62 cameras, EVAL seeds 1–5, light and medium (heavy jams both controllers
on this network, §2). Targets, written before any camera run there
(`TARGETS.md`): zero interlock violations, better than Webster at both
levels, mean person-delay within 15 % of perfect data at both.

| level | Webster | perfect data | cameras | cameras vs Webster | cameras vs perfect data |
|---|---:|---:|---:|---|---|
| light | 25,330 | 15,689 | 16,968 | −33.0 % SIG (5/5) | +8.1 % SIG (lower on 0/5) |
| medium | 63,956 | 42,044 | 42,400 | −33.7 % SIG (5/5) | +0.8 % n.s. (lower on 2/5) |

All three targets pass; zero interlock violations in the 10 camera runs.
Per seed against perfect data: light +2.2 to +16.7 %, medium −2.1 to
+4.4 %.

**The first attempt was stopped** after two light runs, +25.9 % and +38.7 %
against perfect data (`results/berlin_adlershof_vision_before_seen_fix.json`).
The stop-bar cross-check, which calls a camera blind when the loop at the
stop bar has a vehicle and the camera sees none, had flagged about 4,500
junction-ticks a run (about 22 % of the controller's junction-ticks). Two causes, both in short approach lanes, found
and fixed on TRAIN seeds 101–102 before the rerun:

1. **A test bug:** the gates' emulated stop-bar loop
   (`VisionLoop.stopbar`) read an empty approach lane shorter than its 20 m
   zone as occupied.
2. **A vehicle over the loop of a very short approach lane is tracked on the
   lane before it** (the lane its centre is on). The camera's "vehicles seen"
   now also counts the lanes feeding an approach lane shorter than 30 m, up
   to 30 m from the stop line (`LinkStateEstimator._short_approach_feeders`).

With the second fix alone the training runs were still +31 % and +25 %
against perfect data, with about 3,000 flagged junction-ticks a run
(`results/berlin_vision_train_feeder_fix_only.json`). With both they were +3.5 %
and +7.9 %, with none (`results/berlin_vision_train_both_fixes.json`). On
the EVAL rerun the cross-check flagged 0–169 junction-ticks a run (5 or
fewer in nine of the ten). Neither fix changes anything on a network whose
approach lanes are all 30 m or longer, which includes the corridor,
grid3_lh and arterial_lh, so their camera results stand.

**What still costs on Berlin: fixed-time fallback, partly from an empty
road's camera.** The ladder dropped to fixed time on 3.4–6.3 % of the
controller's junction-ticks, against none on the grid and at most 0.9 % on
the arterial. In the first 900 s of TRAIN seed 101 every one of those ticks
came from a single two-link light, `GS_2391105461`
(`results/berlin_fallback_trace_train101.json`). No vehicle in the demand
uses its approach `158236383#0`, so its camera sees nothing. After 600 s
the camera counts as never having worked (`ActivityMonitor`), its health is
capped at 0.3 (`CameraHealth.assess`), and the junction's confidence, the
lowest of its links', falls to 0.27, below the 0.5 that sends it to fixed
time. On an empty road that is a false alarm. The stop-bar loops could tell
an empty road from a blind camera, but that cross-check is not built (the
existing one handles the other case).

That light is one source, not the only one. Its link gives
about 1,400 link-ticks below 0.5 confidence per run (one a tick after
600 s). The EVAL runs had 1,700–1,900 such link-ticks at medium (6,000 on
seed 4) and 2,600–7,900 at light, and the blind check, which forces fixed
time too, still fired on up to 169 junction-ticks. The rest was not traced.
None of it was changed here: Berlin's cameras are the held-out test, and a
fix needs a test on other runs.

## 5. Where it still fails: single-lane roads with turning traffic

`narrow_lh` is a 3x3 grid of single-lane roads, two phases per light, turns
across opposing traffic permitted (yield). At heavy demand every run of both
controllers reaches the run-length cap. At medium the controller reaches it
on 4 of 10 seeds and Webster on 1; the other runs clear late (Webster
4,097–5,175 s, the controller 4,476–5,984 s, for 30 minutes of departures).
Person-delay on capped runs counts only finished trips, so the heavy "−13 %"
means nothing.

The demand level is part of the problem. It is set with Webster's nominal
saturation flow, but on a single lane a vehicle waiting to turn across
oncoming traffic holds up everything behind it, so the real capacity is far
lower and "medium" is already past it: Webster's delay rises 32-fold from
light to medium here (148,860 → 4,736,953), against 2-fold on the two-lane
grid. In the controller's traced run (TRAIN seed 101, `results/narrow_truth_101.json.gz`)
the queues are already long at 600 s. What remains is that, past capacity,
the controller jams to the cap more often than Webster (4 medium seeds
against 1). Nothing was tuned for it here: a fix would change the controller
(or the level definition) and needs its own test.

## 6. Other limitations

- **Real OpenStreetMap downloads** do not work from the build sandbox; the
  real networks here are
  SUMO's bundled OSM imports and the corridor box's extract downloaded in
  August. `city_from_osm.py --bbox` does the download on a normal machine;
  it has not been run from here.
- **Lights placed by road class are a guess.** Where OSM has no signal tags
  36 of the district's 37 lights come from a rule, not from the city's own list; a
  deployment would take the real list (`build_scenario.py --net` on a
  network with its signals set).
- **A queue past a give-way junction just upstream is not measured.** Chains
  (§3.1) stop at real junctions. In the district 49 of the 174 approach
  lanes are shorter than 30 m; 45 of those start at a give-way junction
  where another street meets the road just before the light (4 are chained;
  12 of the 174 in all).
- **The M6 anomaly model is trained on the corridor.** Its loader refuses a
  graph other than the one it was trained on ("saved detector topology does
  not match the given graph -- retrain"), so on another network the live
  detector disables itself rather than scoring it. Retraining per network is
  possible but not done here, and its recording and training scripts still
  use the corridor's paths.
- **Heavy demand can jam a whole real street network** (Berlin), because
  the level is set by the busiest light alone.
- Ingolstadt light: the controller's longest single wait (174 s) is longer
  than Webster's (79 s), though its mean wait is 40 % lower (9.2 s against
  15.3 s).
- The grid3, arterial and narrow runs and the turn-bay grid's "before" run
  were made before the phase-rule and link-numbering fixes. Those fixes give
  identical configurations on these networks, so they were not rerun.

## Files

- `TARGETS.md`: the real-network and camera targets, each written before
  its held-out runs.
- `results/`: every gate output used above (`*_old_demand.json` are the
  radial and random runs at the lower levels, `spider_lh_before_phase_fix.json`
  the radial run before the phase fix, `grid4_rh_turns.json` the turn-bay
  grid before chains, `vijayawada_district_first_build_train.json` the
  district's development runs, `berlin_adlershof_vision*.json` and
  `berlin_vision_train_*.json` the Berlin camera runs and their training
  checks (`feeder_fix_only`: the second fix of §4.1 alone), `berlin_fallback_trace_train101.json` the fallback trace), and
  `live_e2e_grid3_idle.txt`, the live check.
- `scenarios/`: each network's `scenario.json` (build parameters, trip
  periods, measured levels). `rebuild.sh` rebuilds every scenario.
- Code: `itms_domain/lane_chains.py`, `itms_domain/signal_program.py`,
  `scenarios/build_scenario.py`, `scenarios/city_from_osm.py`,
  `scripts/any_network_report.py`. Tests: `packages/domain/tests/`,
  `services/sim-service/tests/control/test_any_network.py`,
  `services/sim-service/tests/signal_controller/test_queue_state.py`,
  `services/vision-service/tests/test_ground_and_state.py`.

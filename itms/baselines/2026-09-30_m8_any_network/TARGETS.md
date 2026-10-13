# Real-city gate: targets set before the held-out runs

Written 2026-09-29T18:26:40Z, before any EVAL-seed (1-10) run on these networks. Seen
so far: one TRAIN-seed (101) smoke run per network, Webster and perfect data,
used only to find crashes (Ingolstadt's link numbering, fixed before this).

Networks: SUMO's bundled OpenStreetMap imports, right-hand traffic, never used
to build or tune anything in this project.
- berlin_adlershof: tools/game/DRT/osm.net.xml (Berlin south-east, 15 lights)
- ingolstadt: tools/game/fkk_in/ingolstadt.net.xml.gz (2 lights, hand-made
  German signal plans)

Arms: webster, truth (CC-A-CAMP on perfect data). Demand light/medium/heavy
(busiest junction at Webster degree of saturation 0.25/0.5/1.0), 10 EVAL seeds.

Pass, per network:
1. Zero interlock violations in every run.
2. Light and medium: perfect data better than Webster, significant (paired).
3. Heavy: perfect data not significantly worse than Webster.
4. No run of the controller hits the 6000-step cap on a seed where Webster
   does not.

## Cameras on Berlin (added 2026-09-30T04:29:11Z, before any camera run there)

62 cameras planned by `vision_service.placement` (every approach lane seen
from its stop line back at least 30 m). Arm `vision:itms6_640:failsafe`
(the fine-tuned detector's measured error model), EVAL seeds 1-5, light and
medium (heavy is gridlock for both controllers on this network, see above).

Pass:
1. Zero interlock violations.
2. Better than Webster at both levels (paired).
3. Mean person-delay within 15 % of perfect data at both levels.

## Vijayawada district from raw OSM (added 2026-09-30T11:51:29Z, before any held-out run)

`scenarios/city_from_osm.py` on the raw OpenStreetMap extract of the
corridor's bounding box (`vijayawada_corridor_bbox.osm.xml`), cropped to it:
the whole street grid, not the curated corridor. 37 lights, all placed by
the class rule (3+ entering roads tertiary or above; OSM tags one light).
Left-hand, the corridor's vehicle mix. Development so far: TRAIN seeds
101-105 at medium (perfect data 101-103 only) on a first build (before the 25 m junction join and the
50 km/h cap were added to the script); seed 101 had a give-way gridlock
(two priority junctions 0.2 m apart) that the rebuild's junction join is
meant to remove. No EVAL seed has been run.

Same four perfect-data targets as the two cities above, 10 EVAL seeds.

Note added after the district's held-out runs (2026-09-30): the rebuild did
not remove the two give-way junctions joined by a 0.2 m edge (their centres
are 14.4 m apart; netconvert's 25 m join did not merge them); vehicles
still got stuck there in runs of both controllers. Of the 37 lights, 36 came
from the class rule (37 junctions, two joined under one light) and one from
the OSM tag.

## Berlin cameras: first attempt stopped, rerun (note added 2026-09-30T15:16:44Z)

The first attempt was stopped after 2 of its 10 camera runs (light, EVAL
seeds 1 and 2: +25.9 % and +38.7 % against perfect data;
`results/berlin_adlershof_vision_before_seen_fix.json`). The stop-bar
cross-check had called the cameras blind on about 22 % of the controller's
junction-ticks (first written here as 15 %, which counted every simulation
step; corrected 2026-10-01) and the controller fell back to fixed time about
5,400 times a run. Two causes, both
in reading short approach lanes, found and fixed on TRAIN seeds 101-102:

1. the gates' emulated stop-bar loop (`VisionLoop.stopbar`) read an empty
   lane shorter than its 20 m zone as occupied;
2. a vehicle over the loop of a very short approach lane is tracked on the
   lane before it, so the camera's "vehicles seen" now counts the lanes
   feeding such an approach within 30 m of the stop line.

With both, TRAIN seeds 101 and 102 at light: no blind flags, cameras +3.5 %
and +7.9 % against perfect data. Neither fix changes anything on a network
whose approach lanes are all longer than 30 m (the corridor, grid3_lh,
arterial_lh), so their camera results stand. The rerun repeats all ten
Berlin camera runs; the targets above are unchanged.

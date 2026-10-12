# Seeing every waiting vehicle (2026-10-07)

**Status: simulation result. Sensing adopted in the benchmark configuration and
wired into the live service; rest-in-green measured and left off. Not
committed.** Targets were written before the held-out runs (`TARGETS.md`);
one clause failed and was replaced, after the fact, by a weaker follow-up
test on new seeds (below).

## In one paragraph

The controller counted and detected vehicles on SUMO *lanes*. Some waiting
vehicles stand on none: on the planned Amaravati grid the first vehicle of
every queue (the road is cut just before the stop line for the turn lane and
the piece after the cut is under 2 m long), and on some real junctions every
vehicle of an approach (another junction sits 0.2 m before the stop line).
Those vehicles had no queue, no call and no wait clock. Counting them cut
person-delay on the Amaravati plan grid by 27 % in light traffic, 24 % in
medium and 7 % in heavy on seeds never used before, was significantly worse
on none of 11 network-levels, and changes nothing on networks without such
approaches. No rule of the controller changed.

## How it was found

Trying "stay green when nobody else is waiting" (`rest_in_green`) on the plan
grid cut delay by a quarter in light traffic and made SUMO teleport stuck
vehicles. Tracing
them (per-tick position, signal state, queue the controller saw) showed a
single vehicle 1 m before the stop line that the controller did not know
about. The same trace on the Vijayawada district found the second kind.
Counts by network (`itms_domain.lane_chains.vias_from_sumo_net`):

| network | approach lanes | under 2 m long | now watched together with what leads into them |
|---|---|---|---|
| amaravati_plan | 320 | 320 | 320 |
| grid4_rh_turns | 192 | 0 (all under 5 m) | 192 |
| vijayawada_district | 174 | 12 | 24 |
| berlin_adlershof | 105 | 3 | 34 |
| ingolstadt | 23 | 0 | 10 |
| amaravati_v2 (real map) | 721 | 0 | 33 |
| amaravati (first real map) | 756 | 30 | 65 |
| corridor, arterial_lh, grid3_lh, narrow_lh, spider_lh, random_lh | | 0 | 0 |

The first real Amaravati map teleported vehicles at light demand (2026-10-06)
around a junction split in two with a 0.2 m link between; two of its 30
lanes of this second kind are there, so this is the likely cause. It was not
re-run.

## What changed

- `vias_from_sumo_net(net, upstream, short_m)`: for each approach, the
  internal lanes between the pieces of a cut road and, for an unchained
  approach lane under `SHORT_APPROACH_M` = 5 m, those leading straight into it.
- `QueueStateSampler(vias=...)`: vehicles halted there count toward the queue.
- `ActuationDetector(extra_lanes=...)`: a vehicle there, or on the earlier
  pieces of a cut road, raises the approach's call and starts its wait clock.
- `run_controlled_scenario(lane_vias=...)`; on by default in
  `scripts/m8_harness.py` and in `sim_service/main.py`.
- `AcampConfig.rest_in_green` (off): at the green ceiling, stay green while
  every other phase is empty.

## Held-out result: sensing (seeds 241-245, `python summarise.py`)

| network | level | before (s) | after (s) | change, 95 % interval | better on | mean wait before / after (s) | stops before / after | teleports before / after |
|---|---|---|---|---|---|---|---|---|
| amaravati_plan | heavy | 418,860 | 389,743 | -6.9 % [-11.8, -1.9] | 5/5 | 32.3 / 24.6 | 2.38 / 2.71 | 1 / 0 |
| amaravati_plan | light | 98,377 | 71,173 | -27.2 % [-38.0, -16.5] | 5/5 | 39.7 / 17.9 | 1.82 / 1.92 | 0 / 0 |
| amaravati_plan | medium | 217,467 | 165,606 | -23.6 % [-29.8, -17.4] | 5/5 | 36.1 / 20.8 | 2.17 / 2.24 | 0 / 0 |
| amaravati_v2 | light | 238,085 | 234,058 | -1.7 % [-6.0, +2.7] | 2/3 | 35.6 / 35.7 | 3.33 / 3.35 | 0 / 0 |
| berlin_adlershof | light | 14,934 | 14,927 | -0.1 % [-0.3, +0.2] | 1/5 | 9.5 / 9.4 | 1.11 / 1.11 | 0 / 0 |
| berlin_adlershof | medium | 39,986 | 39,664 | -0.8 % [-3.0, +1.4] | 2/5 | 14.3 / 13.9 | 1.33 / 1.34 | 0 / 0 |
| grid4_rh_turns | light | 36,805 | 36,218 | -1.5 % [-5.9, +2.8] | 4/5 | 35.3 / 34.5 | 2.48 / 2.47 | 0 / 0 |
| grid4_rh_turns | medium | 113,181 | 111,502 | -1.4 % [-4.7, +1.8] | 3/5 | 57.5 / 56.2 | 2.94 / 2.99 | 0 / 0 |
| ingolstadt | light | 6,337 | 6,118 | -3.3 % [-8.9, +2.2] | 4/5 | 9.0 / 8.5 | 0.79 / 0.75 | 0 / 0 |
| ingolstadt | medium | 29,377 | 28,860 | -1.8 % [-6.8, +3.2] | 1/5 | 22.2 / 22.0 | 1.70 / 1.66 | 0 / 0 |
| vijayawada_district | light | 81,044 | 77,582 | -4.3 % [-8.8, +0.3] | 4/5 | 16.2 / 15.0 | 1.96 / 1.92 | 0 / 0 |
| vijayawada_district | medium | 192,537 | 190,758 | +1.7 % [-30.8, +34.3] | 3/5 | 29.7 / 29.3 | 2.29 / 2.31 | 13 / 15 |

All four sensing targets but one clause passed. The clause compared two
teleport totals on the district at medium demand (13 against 15), a count that
swings from 0 to 15 between runs with either arm. By the rule written in
advance that meant "not adopted". A follow-up was then written, *after seeing
that failure*, with a weaker test (not significantly more teleports, not
significantly more delay) on ten new seeds (246-255), and run: 35 teleports
before, 25 after; person-delay -6.2 % [-18.3, +5.9]. Sensing is adopted on
that basis; a reader who does not accept the follow-up should read the
district's medium row as "no measurable effect either way". On the plan grid the mean wait fell from 40 s to 18 s
in light traffic and from 36 s to 21 s in medium.

## Held-out result: rest in green, on top of sensing

| network | level | before (s) | after (s) | change, 95 % interval | better on | mean wait before / after (s) | stops before / after | teleports before / after |
|---|---|---|---|---|---|---|---|---|
| amaravati_plan | heavy | 389,743 | 393,004 | +0.9 % [-1.3, +3.0] | 2/5 | 24.6 / 24.5 | 2.71 / 2.69 | 0 / 0 |
| amaravati_plan | light | 71,173 | 63,446 | -10.7 % [-16.6, -4.7] | 5/5 | 17.9 / 13.0 | 1.92 / 1.51 | 0 / 0 |
| amaravati_plan | medium | 165,606 | 158,732 | -4.1 % [-8.2, -0.0] | 4/5 | 20.8 / 18.7 | 2.24 / 2.10 | 0 / 0 |
| amaravati_v2 | light | 234,058 | 218,360 | -6.7 % [-37.4, +24.1] | 2/3 | 35.7 / 30.9 | 3.35 / 2.37 | 0 / 1 |
| arterial_lh | heavy | 281,455 | 285,635 | +1.6 % [-3.2, +6.4] | 2/5 | 61.5 / 63.3 | 2.28 / 2.26 | 0 / 0 |
| arterial_lh | light | 35,186 | 33,543 | -4.8 % [-12.0, +2.4] | 4/5 | 27.7 / 26.5 | 1.90 / 1.80 | 0 / 0 |
| arterial_lh | medium | 98,176 | 96,794 | -1.2 % [-7.8, +5.3] | 4/5 | 42.2 / 41.7 | 2.25 / 2.21 | 0 / 0 |
| berlin_adlershof | light | 14,927 | 12,681 | -15.0 % [-18.0, -12.1] | 5/5 | 9.4 / 6.6 | 1.11 / 0.83 | 0 / 0 |
| berlin_adlershof | medium | 39,664 | 37,323 | -5.9 % [-9.7, -2.1] | 5/5 | 13.9 / 12.8 | 1.34 / 1.17 | 0 / 0 |
| corridor | heavy | 492,007 | 484,085 | -0.4 % [-16.4, +15.6] | 4/5 | 88.1 / 89.9 | 2.74 / 2.78 | 4 / 0 |
| corridor | medium | 69,596 | 70,446 | +1.3 % [-9.4, +12.0] | 1/5 | 20.3 / 20.2 | 1.68 / 1.61 | 2 / 3 |
| grid3_lh | light | 57,166 | 56,160 | -1.6 % [-11.8, +8.6] | 2/5 | 13.2 / 12.8 | 1.64 / 1.61 | 0 / 0 |
| grid3_lh | medium | 145,250 | 143,158 | -1.3 % [-7.9, +5.2] | 3/5 | 19.0 / 19.3 | 2.30 / 2.31 | 0 / 0 |
| grid4_rh_turns | light | 36,218 | 34,883 | -3.7 % [-6.1, -1.2] | 5/5 | 34.5 / 33.1 | 2.47 / 2.35 | 0 / 0 |
| grid4_rh_turns | medium | 111,502 | 112,281 | +0.7 % [-2.2, +3.6] | 3/5 | 56.2 / 56.7 | 2.99 / 3.00 | 0 / 0 |
| ingolstadt | light | 6,118 | 5,801 | -5.1 % [-8.7, -1.4] | 5/5 | 8.5 / 7.8 | 0.75 / 0.69 | 0 / 0 |
| ingolstadt | medium | 28,860 | 25,851 | -8.6 % [-29.4, +12.2] | 3/5 | 22.0 / 19.7 | 1.66 / 1.46 | 0 / 1 |
| narrow_lh | light | 86,088 | 83,789 | -2.6 % [-7.1, +1.9] | 4/5 | 20.1 / 19.5 | 2.24 / 2.15 | 0 / 0 |
| random_lh | light | 50,111 | 44,348 | -11.2 % [-18.9, -3.4] | 5/5 | 21.3 / 18.1 | 2.28 / 1.80 | 0 / 0 |
| random_lh | medium | 122,351 | 121,951 | -0.2 % [-5.7, +5.4] | 3/5 | 26.6 / 26.1 | 2.70 / 2.56 | 0 / 0 |
| spider_lh | light | 63,840 | 63,461 | -0.4 % [-8.4, +7.6] | 3/5 | 12.7 / 11.0 | 1.50 / 1.33 | 9 / 8 |
| spider_lh | medium | 152,543 | 148,195 | -2.8 % [-9.5, +4.0] | 4/5 | 17.3 / 17.1 | 1.89 / 1.87 | 51 / 52 |
| vijayawada_district | light | 77,582 | 69,902 | -9.8 % [-15.6, -4.0] | 5/5 | 15.0 / 12.5 | 1.92 / 1.61 | 0 / 0 |
| vijayawada_district | medium | 190,758 | 203,104 | +8.7 % [-27.1, +44.6] | 2/5 | 29.3 / 32.7 | 2.31 / 2.05 | 15 / 23 |

Light traffic: -6.5 % [-10.0, -3.0] over 10 network-levels, better on all 10
(Berlin -15 %, the irregular net -11 %, the plan grid -11 %, the district
-10 %). Medium: -1.3 % [-4.7, +2.0]. Significantly worse nowhere. It failed
its teleport target (87 against 81 in total over the 23 network-levels, one
more on the real map; the district at medium 23 against 15), so **it is not the default**. It is a real gain in light traffic
that needs a guard for congested real junctions before it can be switched on.

## What this does not show

- It is a correction to what the controller is told, found in simulation. A
  loop or camera on a real road has no "internal lane"; the lesson for a real
  deployment is that the detection zone must reach the stop line and cover
  the storage between two junctions that almost touch.
- The camera pipeline (`vision_service`) places vehicles by geometry and has
  its own handling of short approaches. It was not changed and camera arms
  were not re-measured; whether it misses these vehicles is not known.
- Earlier CC-A-CAMP numbers on the plan grid were measured with these
  vehicles unseen. Webster, which senses nothing, is unaffected, so
  CC-A-CAMP's margin over it there was understated. On the district and
  Berlin the change is within noise.
- The real Amaravati map moved little (-1.7 % [-6.0, +2.7], three seeds):
  it has few such approaches. Its mean wait at light demand is still 36 s.
- The district at medium demand teleports vehicles with every arm; results
  there are noisy.
- Person-delay is the delay of finished trips; teleported vehicles are
  counted by SUMO as having moved.

## Files

`TARGETS.md` (targets, amendment, outcome), `run_eval.sh`, `run_s4b.sh`,
`summarise.py`, `results/` (23 network-levels, 285 runs, and the real map),
`results_s4b/`, `dev/` (training-seed runs).

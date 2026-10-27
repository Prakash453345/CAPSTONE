# Rest in green as an off-peak mode, second test (2026-10-13)

**Status: simulation result. Adopted as an off-peak switch (off by default). Not
committed.** Targets were written before the held-out runs (`TARGETS.md`).

## In one paragraph

At its green ceiling the controller changes phase even when no other road has anyone
waiting or arriving, and pays a change interval (yellow + all-red) for nothing. "Rest in
green" keeps the green instead. The first test (2026-10-12) passed on delay but failed a
safety target on the spider network's teleports. Those turned out to be a defect in the
network: its centre junction had no right-of-way rules, and every collision was on that
junction's exits. With the centre signalised, and on today's default controller (paired
phases included), fresh seeds at light demand gave **-9.0 % person-delay over ten
networks (lower on all ten, significantly on six), and -15.3 % on the real Amaravati map**, with no interlock
violation and no extra teleports.

## Held-out result (light demand, seeds 274-278; real map 274-276)

| network | level | before (s) | after (s) | change, 95 % interval | better on | mean wait before / after (s) | stops before / after | teleports before / after |
|---|---|---|---|---|---|---|---|---|
| amaravati_plan | light | 68,651 | 61,592 | -10.2 % [-16.8, -3.6] | 5/5 | 15.5 / 13.1 | 1.77 / 1.48 | 0 / 0 |
| amaravati_v2 | light | 231,316 | 196,017 | -15.3 % [-18.8, -11.8] | 3/3 | 35.5 / 27.2 | 3.33 / 2.29 | 1 / 0 |
| arterial_lh | light | 21,344 | 18,957 | -10.8 % [-21.9, +0.4] | 5/5 | 9.7 / 8.3 | 1.20 / 0.99 | 0 / 0 |
| berlin_adlershof | light | 14,886 | 12,614 | -15.2 % [-18.7, -11.7] | 5/5 | 9.3 / 6.4 | 1.11 / 0.81 | 0 / 0 |
| grid3_lh | light | 57,691 | 53,679 | -6.9 % [-10.5, -3.3] | 5/5 | 13.6 / 12.4 | 1.66 / 1.57 | 0 / 0 |
| grid4_rh_turns | light | 20,467 | 18,261 | -10.7 % [-15.0, -6.5] | 5/5 | 14.4 / 12.4 | 1.68 / 1.46 | 0 / 0 |
| ingolstadt | light | 6,080 | 5,982 | -1.5 % [-8.8, +5.8] | 4/5 | 8.3 / 8.2 | 0.76 / 0.71 | 0 / 0 |
| narrow_lh | light | 85,830 | 84,481 | -1.6 % [-6.6, +3.4] | 3/5 | 19.4 / 19.4 | 2.18 / 2.16 | 0 / 0 |
| random_lh | light | 52,328 | 44,369 | -15.1 % [-21.9, -8.2] | 5/5 | 20.9 / 18.2 | 2.27 / 1.86 | 0 / 0 |
| spider_lh (original, reported) | light | 59,351 | 56,663 | -4.3 % [-11.4, +2.8] | 4/5 | 10.7 / 9.8 | 1.33 / 1.20 | 7 / 10 |
| spider_lh_tl | light | 83,459 | 75,170 | -9.5 % [-22.6, +3.6] | 4/5 | 17.5 / 16.5 | 1.75 / 1.65 | 0 / 0 |
| vijayawada_district | light | 75,245 | 68,378 | -9.0 % [-16.8, -1.1] | 4/5 | 15.5 / 12.8 | 1.92 / 1.60 | 0 / 0 |

Targets: L1 no violation; L2 -9.0 % [-12.4, -5.7] over the ten (spider_lh_tl counted,
the original spider and the real map reported); L3 significantly worse nowhere; L4
significantly more teleports nowhere. All four pass.

## The spider network

`netgenerate --spider` with `--default-junction-type traffic_light` produced 15
signalised junctions and left the centre, A1, `unregulated`: five two-lane roads where
every connection has priority and nobody yields. All 113 collisions found in the
spider logs of the check-up and the rest-guard runs (`results/checkup`,
`results/rest_ovl`) are on A1's exits (A1B1..A1B5); so are the 17 in this test's
original-spider log.
`scenarios/generated/spider_lh_tl` is the same network with A1 signalised (netconvert,
layout `opposites`; the other 15 programs and their links checked unchanged). Its
delays are higher than the original's, presumably because A1 now runs a five-phase
signal instead of letting vehicles pass through each other (not tested). A priority junction at A1 (`spider_lh_pri`) was
tried first and dropped: vehicles on its minor roads waited long enough to be
teleported (10 yield teleports) and light delay was 66,000-138,000 s per seed against
~58,000 s (stopped after 5 of 12 runs).

## What this does not show

- It is tested at **light demand only**. On training seeds in the first test it lost at
  medium and heavy on arterial_lh (+5 %, +3.5 %), so it is a switch for light-traffic
  hours (an operator's time-of-day plan), not an automatic mode. Four automatic guards
  were tried in the first test; none kept the light-traffic gain without the losses.
- On four of the ten networks the interval includes zero on its own: arterial_lh
  (5/5 seeds better), spider_lh_tl, and ingolstadt and narrow_lh (about -1.5 %, i.e.
  no measurable effect). The target is the mean over the ten.
- The real map ran three seeds, not five (each run takes 7-10 minutes).
- Simulation (SUMO 1.27), not a field result.

## Could it stay on all day? (training seeds 101-103, after the test)

With paired phases, rest no longer loses in busy traffic on the networks where it lost
before: arterial_lh medium -3.0 % [+5, -7, -8], heavy -0.3 %; grid4_rh_turns medium
-0.4 %; Amaravati plan grid heavy +0.8 %. But on the Vijayawada district at medium it
cut delay 9.6 % (every seed) while teleports rose from 2 to 5, nearly all on one
give-way lane (850997565_0) that gets no gap while a nearby signal rests. Capping the
rest did not help (30 s: -5.5 %, 4 teleports; 90 s: +9.6 %, 13 teleports, one seed +50 %).
So it stays a light-traffic switch. Running all day would need the controller to leave
gaps for give-way roads just past its exits. `dev/busy_*.json`.

## Files

`TARGETS.md` (targets, outcome), `run_eval.sh`, `summarise.py`, `results/`
(`SUMMARY.md`, per-network JSON and logs), `dev/` (training seeds 101-103: spider_lh_tl,
spider_lh_pri, arterial_lh and grid4_rh_turns with paired phases).

## Where it lives

- `AcampConfig.rest_in_green` (off by default, docstring updated).
- `sim_service/main.py`: `SIGNAL_OFFPEAK_REST=1` switches it on for every junction.
- Gate arm `truth:rest`; `scenarios/generated/spider_lh_tl/`.

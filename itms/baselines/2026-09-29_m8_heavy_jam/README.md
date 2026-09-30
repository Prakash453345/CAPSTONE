# Baseline — M8, the heavy-demand jam traced (2026-09-29)

The fine-tune's closed loop (`../2026-09-27_m8_finetune_v2/`) had one
camera-driven heavy run in five go into a long jam (640 px seed 5: 728,941 s
person-delay against 454,138 on perfect data, a 1,150 s wait, 3,047 s to
empty the network). This baseline traces it, tests a fix, and measures the
heavy regime more widely than five seeds could. In short:

1. **Cause of the traced jam:** a queue past the camera's view. At
   `cluster_1880441740_4393296791` the shared lane `470178558_2` (599 m,
   filmed for its last 98 m) held 20–65 halted vehicles (26 PCU on average
   over 600–1,800 s) while the camera's estimate stayed at 11 PCU or less.
2. **Confirmed by an oracle:** adding the true out-of-view queue back to the
   camera's estimate removed the jam (506,303).
3. **The fix counts the queue past the view.** Three versions were measured
   (§4). The third is adopted by a rule written before any of its held-out
   results came in (§5). It leaves the average where it was (−0.9 % n.s.)
   and cuts the worst run: 702k → 602k on TRAIN, and 729k → 593k held out
   (where the drop is seed 5, the traced seed). Medium demand is
   bit-identical.
4. **The heavy regime is chaotic, with perfect data too.** The bottleneck
   junction runs at Webster degree of saturation 0.996. Perfect data ranged
   409k–639k over ten TRAIN seeds. A change of 12–22 signal decisions per
   run moved single runs by up to 37 %. At heavy demand, per-seed
   comparisons on two to five seeds cannot resolve differences of 10 %.
5. **With ten seeds, the camera system's cost at heavy demand is not
   significant:** +6.9 % n.s. against perfect data on EVAL seeds 1–10 (95 %
   interval −9.6 % to +23.5 %; 4/10 seeds lower), −2.4 % on the five seeds
   (6–10) no camera arm had run before. On TRAIN seeds 101–110 it is +10.2 %
   n.s. (and +10.0 %, significant, with counting). The "one run in five"
   became one extreme run in ten (seed 5), with seed 7 also poor (+31 %
   against perfect data, a 771 s wait).

## 1. The jam, traced (`jam_analysis.txt`)

`scripts/m8_jam_trace.py` wraps every junction's strategy and logs, every
10 s, the phase and, per link, what the runner measured (truth) next to what
the controller was fed (the camera). Seed 5 at heavy demand, perfect data
against cameras (`vision:itms6_640:failsafe`), both reproducing their gate
records exactly:

- Vehicles running diverge from 900 s (252 against 207) and the camera run
  still has 134 at 2,100 s against 55.
- Five of the seven junctions are the same in both. `cluster_1880441532_…`
  runs about twice the queue for ten minutes (up to 17 PCU). At
  `cluster_1880441740_4393296791` the lane-level queue reaches three times
  the truth run's by 1,800 s (67 against 20 PCU), and the receiving lane of
  the junction upstream fills behind it.
- Per lane, 600–1,800 s (mean PCU):

  | lane | links (phase) | truth run | camera run: real | camera run: fed |
  |---|---|---:|---:|---:|
  | `470178558_2` | L5 (P0), L6–L7 (P1) | 8.2 | **26.4** | **6.9** |
  | `374043424_0` | L0–L2 (P2) | 12.3 | 6.6 | 4.9 |
  | every other lane | | ≤ 4.5 | ≤ 4.6 | ≤ 4.2 |

- SUMO teleported one vehicle from `470178558_2` at 1,638 s, after 300 s
  waiting to yield.

Where the missing queue was (`scripts/m8_lane_undercount.py`,
`undercount_s5.json`; lane `470178558_2`, the camera covers its last 97.9 m):

| t (s) | halted, truth | in the camera's view | beyond it | tracked as stopped | estimate (PCU) | visible queue back (m) |
|---:|---:|---:|---:|---:|---:|---:|
| 600 | 8 | 8 | 0 | 8 | 4.1 | 45 |
| 800 | 22 | 16 | 6 | 13 | 7.6 | 63 |
| 1,000 | 33 | 16 | 17 | 11 | 6.3 | 67 |
| 1,200 | 34 | 14 | 20 | 10 | 7.1 | 54 |
| 1,400 | 33 | 12 | 21 | 9 | 8.0 | 70 |
| 1,600 | 61 | 11 | 50 | 8 | 7.4 | 4 |

- Most of the missing queue is **beyond the view** (up to 54 of 65 halted
  vehicles, at 1,620 s).
- Some is **inside it**: vehicles behind vehicles (at 1,000 s, 16 halted in
  view and 11 tracked as stopped). The visible queue mostly ended 45–70 m
  back. The estimator's truncation rule needs it within 8 m of the view's
  end (98 m), and fired only briefly: at 760 s the visible back reached
  90 m and it added 1.4 PCU. Late in the jam (from 1,440 s) the visible
  queue read as 4 m, because its front vehicle was not seen as stopped.
- The furniture filter dropped at most one real vehicle.

**The oracle** (`m8_jam_trace.py --oracle-hidden`): the same run with the
true halted PCU beyond each camera's near view added to the camera estimate.
**506,303**, no teleport, 2,614 steps. So the out-of-view queue is what
turned this run into a jam.

## 2. Counting the queue past the view (`vision_service/state/gap_count.py`)

Most long approach lanes are also the receiving lane of the junction
upstream, whose camera films their first ~100 m. 9 of the corridor's 19
approach edges are filmed at both ends. For those, vehicles are counted in
across a line in the upstream view and out across a line in the near view;
what is between the lines, less what can be seen there and what is still
driving through, is queued out of sight. The count runs free only while a
queue stands across the near line, and is thrown away whenever every lane's
zone around that line has been empty for 3 s (a queue that reached it
would stand or stream through it) — so counting drift lasts one episode.
Entries (8 edges nobody films upstream) use the arrival rate learned at the
near line while nothing queues there. The module docstring has the details
and the reasons for each choice.

**The count itself is accurate** (open loop, perfect-data control, cameras
filming, TRAIN seed 103 heavy, `gap_count_accuracy_train103.json`; measured
with every counted PCU reported, as version 1 did — the adopted version
reports only the excess over 10 PCU per edge, so its estimate lies between
the two columns):
- on the lane-ticks where 15 PCU or more really stood (24 of 10,741), the
  lane estimate's bias went from **−8.5 PCU to −3.7** (mean error 8.5 → 3.8);
- over all lane-ticks on counted edges the mean error barely moved
  (0.140 → 0.146 PCU): the count adds a little noise to the ordinary case;
- counted inflow was 0–15 % below the true inflow per edge (missed tracks);
- over whole runs, in which every vehicle that went in came out, the
  out-counts ran 2–11 % below the in-counts on seven edges and 3 % above on
  two. That is the drift the re-anchoring exists for.

## 3. How chaotic heavy demand is

- **The bottleneck is at capacity.** Webster's timing for
  `cluster_1880441740_4393296791` at heavy demand has degree of saturation
  **0.996** (critical flow ratios P0 0.366, P1 0.366, P2 0.139, P3 0.126;
  180 s cycle). The other junctions' lane-level queues stay small (mostly
  under 10 PCU, up to 17 at `cluster_1880441532_…`) in every run traced.
- **Perfect data, TRAIN seeds 101–110** (`closed_loop_train.json`):
  409k–639k, mean 504k; longest waits up to 821 s. Webster 645k–682k.
  Seed 101 (639k) came within 2 % of Webster on that seed (650k).
- **12–22 decisions move a run by up to 37 %.** `scripts/m8_split_floor_probe.py`
  (`split_floor_probe.json`) gave each phase, under congestion, an
  allocation of at least its Webster green. It changed 12–22 allocations per
  run, and on perfect data moved seeds by −17 %, −3 %, **+31 %**, −5 %,
  +5 %, −8 %, +11 %, +4 %, −3 %, **+37 %**: mean +3.5 %, worst 625k against
  639k. Not adopted; it is recorded because it measures the noise.
- **Consequence for every heavy-demand comparison in this project:** single
  runs move by up to 37 % from a dozen-odd decisions, so a difference under
  about 10 % on five seeds is inside the noise, and a two-seed verdict of any
  size cannot be told from it. That includes the occlusion horizon's
  "+21.8 % and +14.7 %" (`docs/vision_system_design.md` §3.6).

## 4. The three versions of counting, in the loop

`vision:itms6_640:failsafe`, heavy demand. "No count" is the system as it
was.

**Version 1** — counted edges only, everything counted reported. First run
on seed 5 with the evidence zone at the far end of the near view: worse
(794k), because at 60–100 m a standing queue is hidden behind its own
front, the empty-looking far end kept throwing the count away. Moved to the
middle of the near view (the version measured below).

| seeds | effect against no count |
|---|---|
| TRAIN 101, 102 | −11.4 %, −27.4 % |
| EVAL 5 (the jam) | −35.7 % (468,551; run by `m8_lane_undercount.py`, the same closed loop outside the gate) |
| EVAL 1–4 | +1.9 %, +10.5 %, +7.7 %, **+28.5 %** |

Seed 4, traced: counting raised the fed queue on `470178558_2` (P0/P1) while
P2's lane (`374043424_0`, an entry, not counted) stayed under-counted; P1's
share of time went from 32 to 50 samples and P2's from 19 to 13, and P2's
real queue grew to 17.7 PCU. A partly counted junction is unbalanced.

**Version 2** — entries modelled too (§2), everything reported. EVAL seeds
1–10 (`closed_loop.json`, arm `...:count_v2`):

| | mean | vs perfect data | vs no count | worst run |
|---|---:|---|---|---:|
| no count | 508,718 | +6.9 % n.s. (4/10 lower) | | 728,941 |
| count v2 | 531,192 | +11.6 % n.s. (3/10 lower) | +4.4 % n.s. (4/10 lower) | 642,017 |

Seed 5: 524,740. But seed 8 went 427,196 → 642,017.

**Version 3** — as version 2, but only an edge's hidden queue above
**10 PCU** is reported (the excess), and below that the estimate is exactly
what it was without counting. Chosen a priori (not tuned) after version 2,
so that ordinary runs are left alone and only a runaway is acted on.

TRAIN seeds 101–110 (`closed_loop_train.json`, `report_train.md`):

| | mean | vs perfect data | worst run |
|---|---:|---|---:|
| Webster | 664,035 | | 681,674 |
| perfect data | 504,153 | | 638,597 |
| no count | 555,790 | +10.2 % n.s. (2/10 lower) | **701,979** (seed 109) |
| count v3 | 554,801 | +10.0 % SIG (3/10 lower) | 602,174 |

Count v3 against no count: **−0.2 % n.s. (5/10 lower)**; seed 109 went
701,979 → 602,174; seed 107 was identical to no count (nothing reported).

EVAL seeds 1–10 (`closed_loop.json`, `report.md`):

| | mean | vs perfect data | vs no count | worst run | longest wait |
|---|---:|---|---|---:|---:|
| Webster | 645,098 | +35.6 % SIG | | 686,492 | 727 s |
| perfect data | 475,779 | | | 546,084 | 613 s |
| no count | 508,718 | +6.9 % n.s. (4/10 lower) | | 728,941 | 1,150 s |
| count v2 | 531,192 | +11.6 % n.s. (3/10 lower) | +4.4 % n.s. (4/10 lower) | 642,017 | 682 s |
| **count v3** | **504,052** | +5.9 % n.s. (3/10 lower) | **−0.9 % n.s.** (4/10 lower) | **593,316** | 822 s |

Per seed, count v3 against no count: +6.0, +11.1, +3.8, +12.7, **−19.8**
(seed 5), 0.0, −7.3, −1.4, 0.0, −4.8 %. Seeds 6 and 9 are identical to no count,
so nothing was reported on them. Against Webster:
−21.9 %, lower on 10/10 seeds.

**Medium demand, seeds 1–5:** count v3 is **bit-identical** to no count on
every seed, every recorded field included, so nothing was reported.

## 5. Verdict

**Adopted: count v3, on by default** (`EstimatorConfig.gap_counting`,
`GapConfig.report_above_pcu = 10`). The rule was written down before any of
its held-out results came in. Count v3 is adopted only if, at heavy demand on EVAL
seeds 1–10:
- the mean with counting is no higher than without; and
- the worst run is lower;

and medium demand is unchanged or better. Result:

| | TRAIN 101–110 | EVAL 1–10 | medium EVAL 1–5 |
|---|---|---|---|
| mean vs no count | −0.2 % | −0.9 % | identical |
| worst run | 602k against 702k | 593k against 729k | identical |

What it is and is not:
- **The worst-run evidence leans on the traced seed.** Held out, the worst
  run fell because seed 5 fell, and seed 5 is where the jam was traced and
  version 1 was developed. TRAIN seed 109 (701,979 → 602,174), whose camera
  runs had not been made before, is the cleaner support.
- **It is a guard against the runaway that was traced.** A lane whose queue
  has run far past its camera now reads as long. Ordinary runs are left
  alone as far as the count allows.
- **It does not close the camera's gap to perfect data at heavy demand**
  (+5.9 % n.s., against +6.9 %). Neither version that reported every counted
  PCU did better: v2 was +4.4 % against no count.
- **The worst runs are still worse than perfect data's worst** (593k against
  546k on EVAL). The adopted version is below Webster on all ten seeds. The
  rejected versions each had one run at or above Webster's on that seed:
  v1 seed 4 (634,717 against 631,855) and v2 seed 8 (642,017 against
  641,194).
- **Longest waits moved both ways.** Seed 5's longest wait went from
  1,150 s to 595 s, and seeds 7, 8 and 10 also dropped. Seeds 1–4 rose
  (406 → 546, 641 → 822, 679 → 735 and 623 → 709 s). So the worst single
  wait over ten runs fell from 1,150 s to 822 s, while the median longest
  wait did not change (572 → 568 s).

Not adopted:
- counting versions 1 and 2;
- the split-floor probe.

Both are kept as scripts and recorded here.

**Open:** the bottleneck itself. The shared lane `470178558_2` needs both P0
and P1 to empty, and P2's single lane is capped at 28.6 s. The junction runs
at degree of saturation 0.996. A controller that is stable there would need
its own study, with 20 or more seeds per arm, because of §3.

## Files

| file | what |
|---|---|
| `jam_analysis.txt` | the trace tables (§1): per-lane truth vs fed, network counts, green durations |
| `undercount_s5.json` | §1's breakdown of the missing queue, every 20 s |
| `gap_count_accuracy_train103.json` | §2, open loop |
| `split_floor_probe.json` | §3 (its floor-0 runs are perfect data, TRAIN 101–110) |
| `closed_loop.json`, `report.md` | EVAL seeds 1–10 heavy (Webster, perfect data, no count, count v2, count v3) and 1–5 medium; `scripts/m8_gap_report.py closed_loop.json` |
| `closed_loop_train.json`, `report_train.md` | TRAIN seeds 101–110 heavy: Webster, perfect data, no count, count v3 |
| `closed_loop_v1.json` | version 1's runs |

Arm names: `vision:itms6_640:failsafe:nogap` is the camera system without
counting (the gate's `:nogap` modifier). `...:count_v1` and `...:count_v2`
are the rejected versions, renamed from the gate's plain arm they ran under
at the time. The plain `vision:itms6_640:failsafe` is the adopted version.

Runs reused rather than repeated: EVAL seeds 1–5 of Webster, perfect data
and no count come from `../2026-09-27_m8_finetune_v2/closed_loop.json`
(`reused_from` in each record). Seed 5's trace reproduced that record to the
PCU-second (728,941 and 454,138), so they are the same runs.

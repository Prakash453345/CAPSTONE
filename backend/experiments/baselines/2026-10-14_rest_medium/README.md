# Rest in green at medium demand, held-out (2026-10-14)

**Status: simulation result. One of four targets failed, narrowly. Not adopted for medium demand. Not committed.**
Targets were written first (`TARGETS.md`). Seeds 279-283, medium demand, eight networks, arms `truth` and `truth:rest`.

| network | change in person-delay, 95 % interval | better on | stops before / after | teleports before / after |
|---|---|---|---|---|
| amaravati_plan | -0.5 % [-6.3, +5.3] | 3/5 | 2.16 / 2.10 | 0 / 0 |
| arterial_lh | -8.6 % [-19.5, +2.4] | 4/5 | 1.47 / 1.34 | 0 / 0 |
| berlin_adlershof | -6.8 % [-10.9, -2.8] | 5/5 | 1.35 / 1.19 | 0 / 0 |
| grid3_lh | +2.2 % [-5.0, +9.3] | 2/5 | 2.29 / 2.33 | 0 / 0 |
| grid4_rh_turns | -1.7 % [-5.4, +2.1] | 3/5 | 2.09 / 2.06 | 0 / 0 |
| ingolstadt | -2.6 % [-31.0, +25.8] | 3/5 | 1.58 / 1.55 | 0 / 0 |
| random_lh | -5.6 % [-11.7, +0.5] | 4/5 | 2.70 / 2.47 | 0 / 0 |
| spider_lh_tl | -0.1 % [-13.2, +13.0] | 2/5 | 2.63 / 2.54 | 0 / 0 |

Overall (mean of the eight network means): **-3.0 % [-6.1, +0.1]**.

| target | result |
|---|---|
| M1 no interlock violation | pass (0) |
| M2 overall <= -2.0 % and upper end of interval < 0 | **fail**: mean -3.0 %, interval ends at +0.1 |
| M3 no network significantly worse | pass |
| M4 teleports with rest <= plain + 2 | pass (0 and 0 over all 80 runs) |

Reading: rest at medium demand is on average a few percent better and harms no network, but
the gain is not distinguishable from zero with five seeds on eight networks. Per network
only berlin_adlershof is significant (-6.8 %, 5/5 seeds); grid3_lh is +2.2 % (2/5 better).
Training-seed runs (seeds 101-103, same eight networks) gave -3.6 %. Heavy demand and the
Vijayawada district were not part of this test (Vijayawada, ten training seeds: -7.8 % with a
wide interval, see 2026-10-14_exit_gap_test.md). Simulation (SUMO 1.27.1), not a field result.

Files: `TARGETS.md`, `run_eval.sh`, `summarise.py`, `results/` (JSON + logs, `SUMMARY.md`).

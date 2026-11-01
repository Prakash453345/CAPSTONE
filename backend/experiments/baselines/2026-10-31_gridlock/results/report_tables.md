## Summary across all 24 network-levels (240 runs per method)

| method | mean person-delay per trip (s) | mean p95 wait (s) | stops per vehicle | v3 wins / ties (of 240 seeds) | v3 vs method, pooled % [95 % interval] | interlock violations | teleports |
|---|---|---|---|---|---|---|---|
| v3 (ours) | 1201.4 | 649.7 | 4.08 | - | - | 0 | 11922 |
| paper A | 1209.8 | 651.2 | 4.24 | 127 / 100 | -6.1 [-9.4, -2.7] | 0 | 11911 |
| Webster | 1198.3 | 703.4 | 4.81 | 216 / 0 | -29.4 [-38.9, -19.9] | 0 | 13455 |
| max-pressure | 1317.0 | 787.1 | 4.71 | 195 / 0 | -8.2 [-27.0, +10.5] | 0 | 12798 |
| actuated | 1191.9 | 624.2 | 4.41 | 170 / 0 | -9.9 [-23.0, +3.1] | 0 | 12283 |

Delay, p95 and stops here are means of the 24 per-cell means, so the heavy gridlocking cells (thousands of seconds
per trip) dominate them; the pooled % (t interval across the 24 per-cell mean % changes, each cell weighted equally)
is the headline comparison. The same by demand level (8 networks each):

| level | method | mean person-delay per trip (s) | mean p95 wait (s) | stops per vehicle | v3 wins / ties (of 80) | v3 vs method, pooled % [95 % interval] | interlock violations | teleports |
|---|---|---|---|---|---|---|---|---|
| light | v3 (ours) | 131.0 | 46.6 | 1.61 | - | - | 0 | 0 |
| light | paper A | 150.3 | 54.1 | 1.94 | 75 / 0 | -13.9 [-19.7, -8.2] | 0 | 1 |
| light | Webster | 243.7 | 108.4 | 2.62 | 80 / 0 | -47.6 [-53.5, -41.7] | 0 | 3 |
| light | max-pressure | 232.5 | 212.5 | 2.21 | 80 / 0 | -29.9 [-43.1, -16.6] | 0 | 244 |
| light | actuated | 199.9 | 79.3 | 2.46 | 80 / 0 | -33.6 [-43.4, -23.7] | 0 | 13 |
| medium | v3 (ours) | 753.7 | 525.4 | 4.15 | - | - | 0 | 1521 |
| medium | paper A | 759.4 | 522.2 | 4.30 | 52 / 20 | -4.2 [-9.7, +1.2] | 0 | 1509 |
| medium | Webster | 746.4 | 500.1 | 4.94 | 72 / 0 | -30.2 [-48.5, -11.9] | 0 | 800 |
| medium | max-pressure | 895.9 | 693.8 | 4.90 | 70 / 0 | -21.9 [-39.1, -4.7] | 0 | 1744 |
| medium | actuated | 753.8 | 576.1 | 4.12 | 60 / 0 | -17.0 [-32.2, -1.7] | 0 | 1615 |
| heavy | v3 (ours) | 2719.6 | 1377.2 | 6.48 | - | - | 0 | 10401 |
| heavy | paper A | 2719.6 | 1377.2 | 6.48 | 0 / 80 | 0 (identical) | 0 | 10401 |
| heavy | Webster | 2604.9 | 1501.8 | 6.87 | 64 / 0 | -10.3 [-25.6, +5.0] | 0 | 12652 |
| heavy | max-pressure | 2822.5 | 1454.9 | 7.02 | 45 / 0 | +27.1 [-23.3, +77.4] | 0 | 10810 |
| heavy | actuated | 2621.9 | 1217.2 | 6.66 | 30 / 0 | +20.7 [-4.4, +45.8] | 0 | 10655 |

## PressLight (RL, paper A's trained models), ingolstadt only

| level | method | delay | p95 | stops | v3 wins | v3 vs PressLight (%) | interlock viol. | teleports | unfinished trips |
|---|---|---|---|---|---|---|---|---|---|
| light | PressLight | 31.3 | 51.8 | 0.75 | 10/10 | -14.8 [-18.3, -11.3] | 0 | 0 | 0 |
| light | v3 (ours) | 26.6 | 31.3 | 0.79 | - | - | 0 | 0 | 0 |
| medium | PressLight | 35.3 | 70.5 | 0.82 | 0/10 | +135.2 [+120.8, +149.6] | 0 | 261 | 799 |
| medium | v3 (ours) | 72.0 | 136.7 | 1.80 | - | - | 0 | 1 | 0 |
| heavy | PressLight | 61.8 | 82.0 | 1.14 | 0/10 | +122.2 [+6.1, +238.3] | 0 | 212 | 1676 |
| heavy | v3 (ours) | 119.4 | 280.6 | 1.15 | - | - | 0 | 68 | 0 |

At medium and heavy PressLight leaves many trips unfinished at the time cap; delay is measured on finished trips,
so its delay there is not comparable (it looks low because the stuck vehicles are not scored).

## Per-network results (means over seeds 309-318)

Delay = person-delay per scored trip (person-seconds; occupancy-weighted, buses count more). p95 = 95th-percentile wait (s). Stops = stops per vehicle.
Wins = seeds where v3's person-delay is lower (ties = identical runs). % = v3 vs that method, per-seed % change in
person-delay, mean and t-based 95 % interval; below 0 means v3 has less delay.

### v3 (ours)

| network | level | delay | p95 | stops | interlock viol. | teleports |
|---|---|---|---|---|---|---|
| amaravati | light | 379.0 | 103.3 | 3.43 | 0 | 0 |
| amaravati | medium | 604.3 | 333.3 | 5.47 | 0 | 12 |
| amaravati | heavy | 2413.0 | 2068.4 | 11.31 | 0 | 508 |
| arterial | light | 84.1 | 28.8 | 1.10 | 0 | 0 |
| arterial | medium | 102.5 | 36.6 | 1.43 | 0 | 0 |
| arterial | heavy | 172.9 | 65.9 | 2.09 | 0 | 0 |
| berlin | light | 41.1 | 32.7 | 0.92 | 0 | 0 |
| berlin | medium | 58.3 | 63.1 | 1.31 | 0 | 2 |
| berlin | heavy | 1780.7 | 2656.2 | 8.55 | 0 | 4498 |
| grid4 | light | 41.9 | 35.5 | 1.48 | 0 | 0 |
| grid4 | medium | 60.1 | 49.6 | 2.18 | 0 | 0 |
| grid4 | heavy | 100.5 | 98.6 | 3.30 | 0 | 0 |
| ingolstadt | light | 26.6 | 31.3 | 0.79 | 0 | 0 |
| ingolstadt | medium | 72.0 | 136.7 | 1.80 | 0 | 1 |
| ingolstadt | heavy | 119.4 | 280.6 | 1.15 | 0 | 68 |
| narrow | light | 138.2 | 48.9 | 2.09 | 0 | 0 |
| narrow | medium | 4659.3 | 3392.8 | 16.53 | 0 | 1481 |
| narrow | heavy | 15540.9 | 4524.2 | 13.92 | 0 | 4734 |
| random | light | 151.3 | 54.8 | 1.67 | 0 | 0 |
| random | medium | 198.0 | 72.2 | 2.42 | 0 | 0 |
| random | heavy | 568.3 | 293.3 | 4.96 | 0 | 0 |
| vijayawada | light | 185.4 | 37.9 | 1.36 | 0 | 0 |
| vijayawada | medium | 275.0 | 118.6 | 2.09 | 0 | 25 |
| vijayawada | heavy | 1061.4 | 1030.1 | 6.53 | 0 | 593 |

### paper A

| network | level | delay | p95 | stops | v3 wins / ties | v3 vs this method (%) | interlock viol. | teleports |
|---|---|---|---|---|---|---|---|---|
| amaravati | light | 395.2 | 110.5 | 3.49 | 7/10 | -3.8 [-8.8, +1.2] | 0 | 1 |
| amaravati | medium | 604.3 | 333.3 | 5.47 | 0/10 (10 ties) | 0 (identical) | 0 | 12 |
| amaravati | heavy | 2413.0 | 2068.4 | 11.31 | 0/10 (10 ties) | 0 (identical) | 0 | 508 |
| arterial | light | 101.3 | 34.9 | 1.39 | 9/10 | -16.5 [-24.0, -9.1] | 0 | 0 |
| arterial | medium | 118.2 | 41.4 | 1.59 | 10/10 | -13.2 [-16.9, -9.5] | 0 | 0 |
| arterial | heavy | 172.9 | 65.9 | 2.09 | 0/10 (10 ties) | 0 (identical) | 0 | 0 |
| berlin | light | 49.7 | 44.4 | 1.21 | 10/10 | -17.2 [-20.1, -14.2] | 0 | 0 |
| berlin | medium | 60.4 | 67.8 | 1.44 | 8/10 | -3.5 [-6.3, -0.7] | 0 | 1 |
| berlin | heavy | 1780.7 | 2656.2 | 8.55 | 0/10 (10 ties) | 0 (identical) | 0 | 4498 |
| grid4 | light | 50.7 | 41.8 | 1.82 | 10/10 | -17.2 [-19.4, -15.0] | 0 | 0 |
| grid4 | medium | 62.1 | 51.5 | 2.26 | 10/10 | -3.2 [-3.8, -2.5] | 0 | 0 |
| grid4 | heavy | 100.5 | 98.6 | 3.30 | 0/10 (10 ties) | 0 (identical) | 0 | 0 |
| ingolstadt | light | 28.5 | 35.1 | 0.83 | 10/10 | -6.4 [-9.6, -3.3] | 0 | 0 |
| ingolstadt | medium | 75.3 | 151.8 | 1.97 | 8/10 | -4.3 [-8.4, -0.2] | 0 | 0 |
| ingolstadt | heavy | 119.4 | 280.6 | 1.15 | 0/10 (10 ties) | 0 (identical) | 0 | 68 |
| narrow | light | 150.8 | 50.8 | 2.22 | 9/10 | -8.1 [-13.0, -3.2] | 0 | 0 |
| narrow | medium | 4659.3 | 3392.8 | 16.53 | 0/10 (10 ties) | 0 (identical) | 0 | 1481 |
| narrow | heavy | 15540.9 | 4524.2 | 13.92 | 0/10 (10 ties) | 0 (identical) | 0 | 4734 |
| random | light | 196.7 | 61.0 | 2.47 | 10/10 | -23.0 [-25.6, -20.4] | 0 | 0 |
| random | medium | 231.3 | 73.8 | 2.86 | 10/10 | -14.2 [-17.9, -10.6] | 0 | 0 |
| random | heavy | 568.3 | 293.3 | 4.96 | 0/10 (10 ties) | 0 (identical) | 0 | 0 |
| vijayawada | light | 229.6 | 54.5 | 2.11 | 10/10 | -19.2 [-20.6, -17.8] | 0 | 0 |
| vijayawada | medium | 264.1 | 65.6 | 2.27 | 6/10 | +4.6 [-12.2, +21.4] | 0 | 15 |
| vijayawada | heavy | 1061.4 | 1030.1 | 6.53 | 0/10 (10 ties) | 0 (identical) | 0 | 593 |

### Webster

| network | level | delay | p95 | stops | v3 wins / ties | v3 vs this method (%) | interlock viol. | teleports |
|---|---|---|---|---|---|---|---|---|
| amaravati | light | 613.6 | 211.5 | 5.20 | 10/10 | -38.1 [-40.8, -35.4] | 0 | 3 |
| amaravati | medium | 854.5 | 506.2 | 6.79 | 10/10 | -27.8 [-37.3, -18.3] | 0 | 23 |
| amaravati | heavy | 2243.5 | 1795.7 | 11.92 | 3/10 | +7.6 [-0.6, +15.9] | 0 | 162 |
| arterial | light | 183.5 | 65.1 | 1.82 | 10/10 | -54.2 [-57.2, -51.1] | 0 | 0 |
| arterial | medium | 183.9 | 64.0 | 1.77 | 10/10 | -44.3 [-46.2, -42.3] | 0 | 0 |
| arterial | heavy | 241.1 | 90.3 | 2.38 | 10/10 | -28.3 [-30.8, -25.7] | 0 | 0 |
| berlin | light | 83.2 | 130.2 | 1.52 | 10/10 | -50.6 [-51.6, -49.6] | 0 | 0 |
| berlin | medium | 96.1 | 136.5 | 1.82 | 10/10 | -39.3 [-41.2, -37.5] | 0 | 3 |
| berlin | heavy | 2256.0 | 3306.7 | 10.18 | 8/10 | -17.8 [-41.7, +6.1] | 0 | 6434 |
| grid4 | light | 86.2 | 83.4 | 2.44 | 10/10 | -51.3 [-52.0, -50.7] | 0 | 0 |
| grid4 | medium | 90.4 | 85.2 | 2.56 | 10/10 | -33.5 [-34.3, -32.6] | 0 | 0 |
| grid4 | heavy | 106.2 | 98.8 | 2.96 | 10/10 | -5.3 [-6.8, -3.8] | 0 | 0 |
| ingolstadt | light | 44.6 | 68.8 | 1.11 | 10/10 | -40.3 [-42.1, -38.4] | 0 | 0 |
| ingolstadt | medium | 103.1 | 340.1 | 1.94 | 10/10 | -30.1 [-34.6, -25.6] | 0 | 2 |
| ingolstadt | heavy | 131.3 | 256.3 | 1.12 | 9/10 | +12.1 [-52.7, +76.8] | 0 | 72 |
| narrow | light | 257.1 | 82.0 | 2.76 | 10/10 | -46.2 [-48.7, -43.7] | 0 | 0 |
| narrow | medium | 3769.3 | 2446.3 | 17.87 | 2/10 | +19.9 [-2.5, +42.2] | 0 | 697 |
| narrow | heavy | 13515.1 | 4368.5 | 13.69 | 5/10 | +8.6 [-23.5, +40.7] | 0 | 5202 |
| random | light | 360.1 | 120.7 | 3.58 | 10/10 | -58.0 [-59.8, -56.2] | 0 | 0 |
| random | medium | 426.8 | 158.9 | 3.80 | 10/10 | -53.6 [-55.1, -52.1] | 0 | 0 |
| random | heavy | 824.0 | 447.4 | 5.89 | 10/10 | -31.0 [-33.3, -28.7] | 0 | 0 |
| vijayawada | light | 321.5 | 105.3 | 2.50 | 10/10 | -42.3 [-43.5, -41.1] | 0 | 0 |
| vijayawada | medium | 446.8 | 263.6 | 2.97 | 10/10 | -32.6 [-48.4, -16.8] | 0 | 75 |
| vijayawada | heavy | 1521.9 | 1650.9 | 6.85 | 9/10 | -28.3 [-40.3, -16.4] | 0 | 782 |

### max-pressure

| network | level | delay | p95 | stops | v3 wins / ties | v3 vs this method (%) | interlock viol. | teleports |
|---|---|---|---|---|---|---|---|---|
| amaravati | light | 933.0 | 1365.1 | 4.81 | 10/10 | -59.0 [-61.8, -56.3] | 0 | 243 |
| amaravati | medium | 1696.9 | 1953.9 | 6.28 | 10/10 | -62.2 [-64.9, -59.6] | 0 | 634 |
| amaravati | heavy | 2305.1 | 2347.8 | 9.85 | 1/10 | +13.2 [+4.0, +22.5] | 0 | 1747 |
| arterial | light | 131.9 | 39.0 | 1.58 | 10/10 | -36.2 [-39.8, -32.6] | 0 | 0 |
| arterial | medium | 159.6 | 52.7 | 1.93 | 10/10 | -35.8 [-38.1, -33.4] | 0 | 0 |
| arterial | heavy | 225.7 | 97.0 | 2.67 | 10/10 | -23.3 [-26.0, -20.7] | 0 | 0 |
| berlin | light | 47.6 | 41.2 | 1.12 | 10/10 | -13.7 [-15.8, -11.5] | 0 | 0 |
| berlin | medium | 61.5 | 62.6 | 1.37 | 7/10 | -4.9 [-9.6, -0.3] | 0 | 12 |
| berlin | heavy | 1409.9 | 2193.3 | 8.00 | 6/10 | +143.0 [-113.1, +399.1] | 0 | 3524 |
| grid4 | light | 62.0 | 50.4 | 2.29 | 10/10 | -32.3 [-33.6, -31.1] | 0 | 0 |
| grid4 | medium | 72.2 | 59.8 | 2.55 | 10/10 | -16.8 [-17.7, -15.8] | 0 | 0 |
| grid4 | heavy | 103.9 | 104.1 | 3.35 | 8/10 | -3.2 [-5.3, -1.1] | 0 | 0 |
| ingolstadt | light | 32.6 | 40.7 | 0.87 | 10/10 | -18.2 [-20.6, -15.8] | 0 | 0 |
| ingolstadt | medium | 78.1 | 172.4 | 1.92 | 9/10 | -7.9 [-12.0, -3.7] | 0 | 2 |
| ingolstadt | heavy | 66.4 | 98.1 | 1.51 | 0/10 | +79.9 [-11.4, +171.2] | 0 | 37 |
| narrow | light | 205.0 | 59.6 | 2.64 | 10/10 | -32.5 [-34.9, -30.2] | 0 | 0 |
| narrow | medium | 4445.3 | 2869.0 | 19.70 | 5/10 | +1.9 [-11.4, +15.2] | 0 | 996 |
| narrow | heavy | 16253.7 | 4576.8 | 17.13 | 2/10 | +51.8 [-4.3, +107.9] | 0 | 4413 |
| random | light | 241.8 | 59.4 | 2.70 | 10/10 | -37.2 [-41.4, -32.9] | 0 | 0 |
| random | medium | 283.4 | 79.5 | 3.19 | 10/10 | -30.1 [-33.1, -27.0] | 0 | 0 |
| random | heavy | 707.4 | 570.0 | 7.47 | 10/10 | -19.6 [-22.7, -16.6] | 0 | 9 |
| vijayawada | light | 205.8 | 44.5 | 1.64 | 10/10 | -9.8 [-12.2, -7.5] | 0 | 1 |
| vijayawada | medium | 370.0 | 300.8 | 2.30 | 9/10 | -19.7 [-40.5, +1.1] | 0 | 100 |
| vijayawada | heavy | 1508.1 | 1652.2 | 6.17 | 8/10 | -25.1 [-41.6, -8.6] | 0 | 1080 |

### actuated

| network | level | delay | p95 | stops | v3 wins / ties | v3 vs this method (%) | interlock viol. | teleports |
|---|---|---|---|---|---|---|---|---|
| amaravati | light | 532.3 | 156.2 | 4.95 | 10/10 | -28.7 [-31.3, -26.0] | 0 | 4 |
| amaravati | medium | 608.0 | 258.7 | 6.05 | 6/10 | -0.7 [-6.4, +5.1] | 0 | 2 |
| amaravati | heavy | 1896.1 | 1155.6 | 13.73 | 1/10 | +17.6 [+8.4, +26.8] | 0 | 121 |
| arterial | light | 122.3 | 31.3 | 1.68 | 10/10 | -31.1 [-35.9, -26.4] | 0 | 0 |
| arterial | medium | 153.2 | 40.6 | 1.83 | 10/10 | -32.8 [-37.2, -28.4] | 0 | 0 |
| arterial | heavy | 180.6 | 70.2 | 2.17 | 8/10 | -4.2 [-7.8, -0.7] | 0 | 0 |
| berlin | light | 70.7 | 91.4 | 1.52 | 10/10 | -41.9 [-43.4, -40.4] | 0 | 0 |
| berlin | medium | 79.9 | 103.4 | 1.71 | 10/10 | -27.0 [-28.9, -25.1] | 0 | 0 |
| berlin | heavy | 1715.8 | 2511.9 | 8.31 | 5/10 | +90.8 [-81.0, +262.7] | 0 | 5010 |
| grid4 | light | 53.3 | 37.9 | 2.14 | 10/10 | -21.4 [-23.1, -19.6] | 0 | 0 |
| grid4 | medium | 59.1 | 45.0 | 2.32 | 3/10 | +1.7 [-0.2, +3.5] | 0 | 0 |
| grid4 | heavy | 83.8 | 78.9 | 2.92 | 0/10 | +20.0 [+17.6, +22.5] | 0 | 0 |
| ingolstadt | light | 45.6 | 84.3 | 1.24 | 10/10 | -41.0 [-45.4, -36.6] | 0 | 0 |
| ingolstadt | medium | 104.1 | 340.7 | 2.09 | 10/10 | -30.6 [-35.4, -25.9] | 0 | 30 |
| ingolstadt | heavy | 96.3 | 253.3 | 1.75 | 5/10 | +23.2 [-37.5, +83.9] | 0 | 63 |
| narrow | light | 164.6 | 41.2 | 2.30 | 10/10 | -15.9 [-20.1, -11.6] | 0 | 0 |
| narrow | medium | 4371.0 | 3574.4 | 12.60 | 4/10 | +6.8 [-8.9, +22.6] | 0 | 1556 |
| narrow | heavy | 15481.3 | 4427.3 | 14.04 | 5/10 | -2.0 [-26.6, +22.7] | 0 | 4909 |
| random | light | 317.0 | 98.0 | 3.35 | 10/10 | -52.2 [-54.7, -49.6] | 0 | 0 |
| random | medium | 337.1 | 112.2 | 3.60 | 10/10 | -41.2 [-43.6, -38.8] | 0 | 0 |
| random | heavy | 529.0 | 259.2 | 5.06 | 3/10 | +8.2 [+0.0, +16.4] | 0 | 0 |
| vijayawada | light | 293.1 | 93.9 | 2.51 | 10/10 | -36.5 [-39.2, -33.7] | 0 | 9 |
| vijayawada | medium | 317.7 | 133.9 | 2.73 | 7/10 | -12.0 [-28.6, +4.7] | 0 | 27 |
| vijayawada | heavy | 992.5 | 981.6 | 5.27 | 3/10 | +12.2 [-12.3, +36.7] | 0 | 552 |



### Sensing: `truth:via2` against `truth`

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

S1 violations in the new arms: 0
S2 Amaravati plan grid light: -27.2 % [-38.0, -16.5] -> pass
S2 Amaravati plan grid medium: -23.6 % [-29.8, -17.4] -> pass
S3 significantly worse on: none
S4 teleports (before, after) by network: {'amaravati_plan': (1, 0), 'amaravati_v2': (0, 0), 'berlin_adlershof': (0, 0), 'grid4_rh_turns': (0, 0), 'ingolstadt': (0, 0), 'vijayawada_district': (13, 15)}

### Rest: `truth:via2:rest` against `truth:via2` (or `truth` where sensing changes nothing)

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
R1 light, 10 network-levels: -6.5 % [-10.0, -3.0]; better on 10
R2 medium, 10 network-levels: -1.3 % [-4.7, +2.0]; better on 7
R3 significantly worse on: none
R4 teleports (before, after) by network: {'amaravati_plan': (0, 0), 'amaravati_v2': (0, 1), 'arterial_lh': (0, 0), 'berlin_adlershof': (0, 0), 'corridor': (6, 3), 'grid3_lh': (0, 0), 'grid4_rh_turns': (0, 0), 'ingolstadt': (0, 1), 'narrow_lh': (0, 0), 'random_lh': (0, 0), 'spider_lh': (60, 60), 'vijayawada_district': (15, 23)}; total 81 -> 88

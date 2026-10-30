# M7 routing held-out targets (written 2026-10-17T15:45Z, before any held-out run)

Code: EtaCostModel (seconds) + A*, should_reroute (max(15 s, 10 %) + 5 s), HexIndex
(cell = median block, 2 rings, live anomalies penalised). Tuned only on dev seeds 1-10
(random_lh, amaravati_plan). Nothing changes after this file.

Held-out: seeds 300-329; networks random_lh, amaravati_plan, vijayawada_district;
demand medium (heavy dropped: under fixed-time background signals the networks gridlock,
EV teleported in 20/120 dev runs on random_lh heavy); incident on (on the free-flow path,
20 s after dispatch, speed 2 m/s for 900 s, reported 10 s later as high/0.8) and off.
Arms: dist, weighted (production router + rule), eta_rr (new), eta_hex (new + hex band).
Metric: EV travel time, paired by seed; mean of per-seed % difference, bootstrap 95 % CI.

| id | comparison | condition | pass if |
|---|---|---|---|
| H1 | eta_rr vs weighted | incident, pooled | mean <= -5 % and CI upper < 0 |
| H2 | eta_rr vs weighted | no incident, pooled | CI upper <= +3 % |
| H3 | eta_rr vs dist | incident, pooled | mean <= -15 % and CI upper < 0 |
| H4 | eta_rr vs dist | no incident, pooled | CI upper <= +3 % |
| H5 | eta_hex vs eta_rr | vijayawada_district, both | CI within [-5 %, +5 %]; edges sampled per tick at least 2x fewer; mean plan time lower |
| H6 | all arms | all | EV arrives in every run (no DNF) |

Dev expectation (not a target): H1 likely fails (dev -2.6 % [-10.0, +5.1]); H4 at risk (dev +2.5 % [-1.4, +7.1]).

## Amendment (2026-10-17T16:28Z, after the run, before reading vijayawada beyond seeds 300-302)
SUMO 1.27.1 crashed (connection closed at t~923 s) on vijayawada_district seed 303 in every
arm, also with no incident; it does not crash with the EV bluelight device removed. All
vijayawada seeds 300-329 are re-run without the bluelight device (EV_BLUELIGHT=0), same for
all arms, so pairs stay fair. The partial bluelight runs (seeds 300-302) are kept in
results/vij_bluelight_crashed/ and are not used. Other networks unchanged.

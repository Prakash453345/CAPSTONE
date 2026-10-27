# Targets: rest in green at medium demand (written 2026-10-14, before any held-out run)

Question: can `rest_in_green` (arm `truth:rest`) run at medium demand, not only off-peak?
Held-out seeds 279-283 (never used), medium demand, arms `truth` and `truth:rest`.
Networks (8): amaravati_plan, arterial_lh, berlin_adlershof, grid3_lh, grid4_rh_turns,
ingolstadt, random_lh, spider_lh_tl. (Vijayawada district and heavy demand are not in this test.)
Per network: mean of the five paired per-seed % changes in person-delay (rest vs plain).
Overall: mean of the eight network means, with a 95 % t interval over the eight (t = 2.365).

- M1 Safety: zero interlock violations in either arm.
- M2 Benefit: overall mean change <= -2.0 % AND the upper end of its 95 % interval < 0.
- M3 No harm: no network whose own 95 % interval (5 seeds, t = 2.776) lies entirely above 0.
- M4 Gridlock: total teleports with rest <= total teleports plain + 2, summed over all 40 runs.

All four pass -> rest becomes an option for medium demand (still off by default; the
live-service switch stays). Any fail -> stays an off-peak switch; report which target failed.
Outcome (run 2026-10-14): M1 PASS (0 violations). M2 FAIL: overall -3.0 % [-6.1, +0.1]; the
mean clears -2.0 % but the interval's upper end is +0.1, not below 0. M3 PASS (no network
significantly worse). M4 PASS (0 teleports in both arms). Result: rest stays an off-peak switch.

# Resume notes (2026-10-11 23:50 IST, stopped by user)

- Held-out run for `truth:ovl3` (TARGETS.md written first), seeds 256-260.
  Relaunch `baselines/2026-10-11_overlaps/run_eval.sh` (resumable); then
  `python baselines/2026-10-11_overlaps/summarise.py`.
- When stopped: 15 of 19 network-levels done (plan grid medium, district light/medium and
  the real map amaravati_v2 light still to finish). Interim: O1 0 violations; O2 -8.6 %
  [-14.7, -2.5] over 12 light/medium network-levels; O3 heavy mean -11.8 %; O4, O5 none.
- Code (not committed): Phase.overlap_movements / shown_movements (itms_domain/signal.py),
  with_overlaps(owned=False), turnaround_links (overlaps.py); interlocks I1/I2/I5, cabinet
  and runner use shown movements; gate arms ovl, ovl2, ovl3, ovl4; harness
  overlaps_kept_timing. Tests: 904 passed, 6 skipped.
- If adopted: make ovl3 the default in m8_harness (and the live service), write README,
  PROGRESS entry, project doc, fact-check, sync to the Mac.
- Rest-in-green (off): district medium train seeds 104-113: -9.0 %, teleports 18 vs 25.

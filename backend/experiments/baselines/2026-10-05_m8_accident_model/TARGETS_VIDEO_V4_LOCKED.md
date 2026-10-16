# Accident detector V4: motion-proposed local crops + VideoMAE — targets LOCKED 2026-10-12, before the run

V3 (whole frame squashed to 224 px) reached 52.6 % detect / 4.8 % early (in-dist), 56.5 % / 7.0 % (geo). Hypothesis: small distant crashes are lost in the squash. Fix: look closer where things move.
Cache: 4 fps, aspect-preserving, longest side 960 px (JPEG), plus a 32x32 frame-difference motion map per frame.
Views per 4-s window (16 frames): 1 global squash (as V3) + up to 2 LOCAL crops (side 0.4 x shorter frame side, shown at 224 px) centred on the two strongest, non-overlapping motion peaks of that window.
Score of a window = max over its views. Same VideoMAE (Kinetics-400) backbone, same window labels (<= impact-1.0 s normal; impact+0.5..+3 s accident; rest ignored), real clips only.
Training views come from the SAME proposal mechanism as inference: normal windows -> any random view (motion peaks in pre-crash traffic are the hard negatives); accident windows -> a local crop that
contains the annotated crash centre (or the global view if none does). The annotation is used only to label training windows, never at inference.
Protocol unchanged: 20 % grouped validation of the train clips picks threshold + k-of-n (early-alarm cap 4 %), frozen; the full test splits (1,520 / 1,573) scored once. Seed 0.
Targets = B1-B5 of TARGETS_LOCKED.md, unchanged: B1 detect <=10 s >=70 % (in-dist); B2 early <=5 %; B3 median delay <=5 s; B4 geo >=60 % detect and <=8 % early; B5 no test tuning.
Pre-registered diagnostic (not a target): proposal coverage on 300 train clips = share of accident windows where a local crop contains the annotated crash centre, printed next to a
random-crop chance level before training. If coverage is not clearly above chance the mechanism cannot help and the run should be stopped.
Limits: one seed; all-accident clips (no false alarms per camera-day); ~80 % US footage; 3x inference cost of V3; motion peaks may follow ordinary traffic.

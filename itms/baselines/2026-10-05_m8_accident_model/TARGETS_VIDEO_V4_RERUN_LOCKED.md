# V4 rerun for deployment — rules fixed BEFORE the run (2026-10-13)

Why: the first V4 run (2026-10-12/13, `accident_v4_results`) did not save its trained weights, so nothing can be loaded
into `detect`. It is also unknown whether that run used the fixed loader (older transformers silently dropped
VideoMAE's pretrained q/v biases). The notebook now saves weights + a deployment JSON, pins `-U transformers`, and
refuses to train if the pretrained biases did not load.

Targets: unchanged (B1–B5 of `TARGETS_VIDEO_V4_LOCKED.md`). Protocol, code, seeds and the validation/test splits: unchanged.

Rules:
1. Both runs are reported, side by side. The rerun is NOT a second try at the test set: nobody chooses between the
   two runs on test results. The rerun's weights are the deployed ones because they are the only ones that exist.
2. If the rerun misses a target the first run passed (or the reverse), the write-up says so; deployed wording stays
   "ACCIDENT (needs confirmation)" either way.
3. Deployed bundle = the geo-aware model and its chosen rule (its validation met the 4 % early cap; the
   in-distribution one did not). Decided now, not after seeing test numbers.
4. Nothing is tuned on either test split. Test splits are scored once per run, inside the notebook.

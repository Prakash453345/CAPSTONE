The four files as they were for `dev13_*` and `dev15_*` (TRAIN seeds, 2026-10-04).

They are kept because the `hol:trap` and `hol:trap:b2` arms of `dev15_*` need a
switch (`carry_into_alternate` in `runner.py`, `HolConfig.carry_into_variant`)
that was removed afterwards: it made the runner show the yellow trap on purpose,
to measure what the ordinary change into a variant costs against it. Nothing
else in the repository can reproduce those two arms.

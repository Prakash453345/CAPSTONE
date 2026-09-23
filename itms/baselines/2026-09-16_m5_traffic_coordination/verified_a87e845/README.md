# Verification — commits after the baseline (HEAD `a87e845`, 2026-09-17)

Independent re-test of the changes made after the frozen baseline
(`56fc44b`), run in a clean Linux environment (Python 3.11.15, eclipse-sumo
1.27.1) — separate from the `after_runner_fixes/` run done on the Mac.

## Commits reviewed

| commit | change | verdict |
|---|---|---|
| `1a88b6a` runner plan contract | (1) extend adds `step_length`, not the plan's `green_s`, to elapsed; (2) a 2-step plan with `steps[0].green_s > tick` now **holds** instead of truncating min green; (3) fault recovery goes yellow → all-red → green instead of jumping green → conflicting green | Correct. All strategies (`webster`, `fixed_time`, `camp`, `acamp`, `semi_actuated`, `coordinated_actuated`) only exit once `elapsed >= min_green`, so their exit `green_s` is one tick and they are unaffected. Existing fault-recovery tests were extended (drive the transition to completion), not weakened; 9 new contract tests added. |
| `626e45e` green corridor | preemption picks phases that serve the EV movement **protected**, not merely permissive | Correct — checked with a scratch case: old code preempted onto the permissive phase, new code picks the protected one. Side effect: if a junction has *no* phase protecting the EV's movement, it now returns no preemption there (safer, but no corridor at that junction). No unit test was added for this. |
| `a87e845` compare script | differences ≤ 1e-9 × baseline mean count as "same" | Sound — only removes float-summation noise; real changes (e.g. the +0.1% below) are still reported. |

## Tests

- `pytest`: **549 passed, 6 skipped** (baseline 540 → +9 new runner-contract tests, 0 failures)
- `ruff`: 2 cosmetic issues in `tests/control/test_runner_decision_contract.py` (unsorted imports line 25, line > 100 chars line 61)
- `mypy`: 1 error in `signal_controller/arbiter.py:238` (`notes` redefined) — pre-existing, also present in the baseline code

## Benchmark vs baseline (90 runs, same seeds)

**0 significant regressions.** 89 of 90 runs are bit-identical to the baseline.
The one run that changed is `ceiling / heavy / seed 6`: interlock violations
2 → 1, delay +0.5% on that seed — exactly where the fault-recovery path runs,
because the second violation was a knock-on effect of the old
green → green jump.

| level | arm | delay | stops | violations |
|---|---|---|---|---|
| light | all three arms | identical | identical | 0 |
| medium | all three arms | identical | identical | 0 |
| heavy | webster | identical | identical | 0 |
| heavy | ceiling | +0.1% (n.s.) | n.s. | **2 → 1** |
| heavy | **ccacamp** | identical | identical | 0 |

The current controller (CC-A-CAMP) never faults, so its results are unchanged.
Its lead over Webster stays at −19.9% / −11.4% / −11.6% delay.

This run matches the Mac run in `after_runner_fixes/` on all 90 runs
(macOS arm64 vs Linux x86_64).

**What the benchmark does not show:** the min-green hold path and the
green-corridor change are never triggered in these scenarios (they need
emergency preemption). Only unit tests cover them; the green-corridor fix has
none of its own.

## Files

- `m5_after_results.json` — 90 per-run records
- `compare_vs_baseline.txt` — full paired comparison against the baseline
- `compare_vs_other_ai_run.txt` — this run vs the Mac `after_runner_fixes/` run (all "same")
- `benchmark_log.txt`, `pytest_full.txt`

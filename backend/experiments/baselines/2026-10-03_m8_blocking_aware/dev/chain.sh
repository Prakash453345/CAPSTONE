#!/usr/bin/env bash
# held-out run first, then what is left of dev22 (camera light, agreement); both resumable
cd "$(dirname "$0")/../.."
[ -f baselines/2026-10-03_m8_blocking_aware/results/eval_done.txt ] || baselines/2026-10-03_m8_blocking_aware/run_eval.sh
[ -f results/hol/dev22_done.txt ] || results/hol/run_dev22.sh

#!/usr/bin/env bash
# Part D of amendment 3: the district between "medium" and "heavy". Waits for run 4.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-03_m8_blocking_aware/results_run4
while [ ! -f $R/eval_done.txt ]; do sleep 20; done
ITMS_SCENARIO=scenarios/generated/vijayawada_district_mid .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
  --levels d65,d80 --arms truth,hol --seed-list $(seq -s, 201 210) --out $R/vijayawada_district_mid.json > $R/vijayawada_district_mid.log 2>&1
echo done > $R/mid_done.txt

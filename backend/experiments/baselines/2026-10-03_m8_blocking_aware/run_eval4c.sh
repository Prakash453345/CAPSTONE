#!/usr/bin/env bash
# Part E of amendment 3: two more single-lane networks. Waits for part D.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-03_m8_blocking_aware/results_run4
while [ ! -f $R/mid_done.txt ]; do sleep 20; done
for N in narrow_grid54_lh narrow_rand_lh; do
  ITMS_SCENARIO=scenarios/generated/$N .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
    --levels d40,d45 --arms truth,hol --seed-list $(seq -s, 201 210) --out $R/$N.json > $R/$N.log 2>&1
done
echo done > $R/more_done.txt

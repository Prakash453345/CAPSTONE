#!/usr/bin/env bash
# Held-out run for paired phases (TARGETS.md was written first). Seeds 269-273. From itms/.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-13_paired_phases/results
run() { ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
  --levels $2 --arms truth,truth:pair --seed-list 269,270,271,272,273 --out $R/$1.json > $R/$1_$2.log 2>&1; }
run arterial_lh light,medium,heavy
run grid4_rh_turns light,medium
echo done > $R/eval_done.txt

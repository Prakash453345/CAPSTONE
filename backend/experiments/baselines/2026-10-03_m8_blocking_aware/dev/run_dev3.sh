#!/usr/bin/env bash
# Development (TRAIN seeds 101-103): blocking-aware controller vs CC-A-CAMP on the single-lane grid.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev3_sweep.json > results/hol/dev3_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light,medium --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out results/hol/dev3_narrow.json > results/hol/dev3_narrow.log 2>&1
echo done > results/hol/dev3_done.txt

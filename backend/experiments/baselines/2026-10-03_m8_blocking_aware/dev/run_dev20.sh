#!/usr/bin/env bash
# Development (TRAIN seeds 106-110, to make ten with dev13/dev19): hol:idle against hol:term.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python scripts/m8_closed_loop_gate.py --levels d35,d40,d45 \
  --arms truth,hol:idle,hol:term --seed-list 106,107,108,109,110 --workers 2 --resume \
  --out results/hol/dev20_sweep.json > results/hol/dev20_sweep.log 2>&1
echo done > results/hol/dev20_done.txt

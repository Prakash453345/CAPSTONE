#!/usr/bin/env bash
# Training seeds 101-103: split-phased junctions rebuilt with facing approaches together
# (truth:pair) and with protected-turn phases added (truth:pairt). Only arterial_lh and
# grid4_rh_turns have split-phased junctions. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/layout
run() { ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
  --levels $2 --arms truth,truth:pair,truth:pairt --seed-list 101,102,103 --out $O/$1.json > $O/${1}_$2.log 2>&1; }
run arterial_lh light,medium,heavy
run grid4_rh_turns light,medium
echo done > $O/done.txt

#!/usr/bin/env bash
# Training seeds 101-103: the floor under the green ceiling (20 s, 30 s) against CC-A-CAMP on
# networks other than the Amaravati plan grid, where the ceiling is below the floor.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/amaravati
while [ ! -f $O/floor_done.txt ]; do sleep 15; done
run() {  # scenario-or-"-", levels
  if [ "$1" = "-" ]; then unset ITMS_SCENARIO; n=corridor; else export ITMS_SCENARIO=scenarios/generated/$1; n=$1; fi
  .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels $2 \
    --arms truth,truth:f20,truth:f30 --seed-list 101,102,103 --out $O/screen_$n.json > $O/screen_$n.log 2>&1
}
run arterial_lh light,medium
run - medium,heavy
run grid4_rh_turns light,medium
run berlin_adlershof light,medium
run grid3_lh light,medium
echo done > $O/screen_done.txt

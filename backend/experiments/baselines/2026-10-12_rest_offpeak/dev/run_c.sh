#!/usr/bin/env bash
# Training seeds 101-103: rest only while the junction's congestion weight is below x
# (truth:rest:restc<x>) -- plain rest gained at light demand and lost at medium/heavy on
# arterial_lh. Waits for run.sh. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/rest_ovl
while [ ! -f $O/done.txt ]; do sleep 15; done
A=truth:rest:restc0.1,truth:rest:restc0.25
run() {  # scenario-or-"-", levels
  if [ "$1" = "-" ]; then unset ITMS_SCENARIO; n=corridor; else export ITMS_SCENARIO=scenarios/generated/$1; n=$1; fi
  .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels $2 \
    --arms truth,truth:rest,$A --seed-list 101,102,103 --out $O/$n.json > $O/${n}_c_$2.log 2>&1
}
run arterial_lh light,medium,heavy
run berlin_adlershof light,medium
run grid4_rh_turns light,medium
run - medium,heavy
run amaravati_plan light,medium
echo done > $O/done_c.txt

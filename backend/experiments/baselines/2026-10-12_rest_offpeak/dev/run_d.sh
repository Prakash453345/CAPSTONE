#!/usr/bin/env bash
# Training seeds 101-103: truth:rest:restd -- rest only while the running phase still has
# demand (a queue or a vehicle arriving). Waits for run_c.sh. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/rest_ovl
while [ ! -f $O/done_c.txt ]; do sleep 15; done
run() {  # scenario-or-"-", levels
  if [ "$1" = "-" ]; then unset ITMS_SCENARIO; n=corridor; else export ITMS_SCENARIO=scenarios/generated/$1; n=$1; fi
  .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels $2 \
    --arms truth,truth:rest,truth:rest:restd --seed-list 101,102,103 --out $O/$n.json > $O/${n}_d_$2.log 2>&1
}
run arterial_lh light,medium,heavy
run berlin_adlershof light,medium
run grid4_rh_turns light,medium
run - medium,heavy
run spider_lh light,medium
run random_lh light,medium
run grid3_lh light,medium
run ingolstadt light,medium
run amaravati_plan light,medium
run vijayawada_district light,medium
echo done > $O/done_d.txt

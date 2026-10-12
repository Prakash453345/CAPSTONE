#!/usr/bin/env bash
# Training seeds 101-103: truth:ovl (every phase also shows the movements that conflict with
# nothing it shows) against truth, on every network where it adds something. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/overlaps
while [ ! -f results/rest_guard/tele/done.txt ]; do sleep 10; done
run() {  # scenario-or-"-", levels
  if [ "$1" = "-" ]; then unset ITMS_SCENARIO; n=corridor; else export ITMS_SCENARIO=scenarios/generated/$1; n=$1; fi
  .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels $2 \
    --arms truth,truth:ovl3 --seed-list 101,102,103 --out $O/$n.json > $O/${n}_$2.log 2>&1
}
run arterial_lh light,medium,heavy
run grid4_rh_turns light,medium
run amaravati_plan light,medium
run spider_lh light,medium
run random_lh light,medium
run berlin_adlershof light,medium
run - medium,heavy
run vijayawada_district light,medium
run amaravati_plan heavy
echo done > $O/done.txt
run amaravati_v2 light
echo done > $O/v2_done.txt

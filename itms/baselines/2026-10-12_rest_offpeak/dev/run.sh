#!/usr/bin/env bash
# Training seeds 101-103: rest-in-green on top of the current default (every waiting vehicle
# seen, free turns shown). Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/rest_ovl
run() {  # scenario-or-"-", levels
  if [ "$1" = "-" ]; then unset ITMS_SCENARIO; n=corridor; else export ITMS_SCENARIO=scenarios/generated/$1; n=$1; fi
  .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels $2 \
    --arms truth,truth:rest --seed-list 101,102,103 --out $O/$n.json > $O/${n}_$2.log 2>&1
}
run arterial_lh light,medium
run berlin_adlershof light,medium
run grid4_rh_turns light,medium
run - medium,heavy
run amaravati_plan light,medium
run vijayawada_district light,medium
run amaravati_v2 light
echo done > $O/done.txt

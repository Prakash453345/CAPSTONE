#!/usr/bin/env bash
# Held-out run for overlaps shown, not owned (TARGETS.md was written first). Seeds 256-260.
# Run from itms/; resumable. Since adoption (2026-10-12) `truth` includes the overlaps:
# to reproduce, run the arms truth:noovl,truth:ovl3 and compare against truth:noovl.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-11_overlaps/results
S=256,257,258,259,260
run() {  # scenario-or-"-", levels
  if [ "$1" = "-" ]; then unset ITMS_SCENARIO; n=corridor; else export ITMS_SCENARIO=scenarios/generated/$1; n=$1; fi
  .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels $2 \
    --arms truth,truth:ovl3 --seed-list $S --out $R/$n.json > $R/${n}_$2.log 2>&1
}
run arterial_lh light,medium,heavy
run grid4_rh_turns light,medium
run spider_lh light,medium
run random_lh light,medium
run berlin_adlershof light,medium
run - medium,heavy
run amaravati_plan light,medium,heavy
run vijayawada_district light,medium
run amaravati_v2 light
echo done > $R/eval_done.txt

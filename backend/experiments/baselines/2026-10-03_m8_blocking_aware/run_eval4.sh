#!/usr/bin/env bash
# Held-out run 4 (TARGETS.md amendment 3 was written first): the two small leads left
# open by round 2, on seeds whose outcome for these arms has not been seen.
#  G: the wider wait guard (hol:g1) where rings of three or more phases have variants;
#  C: acting at once with a longer visit (p0:b3) when blocked lanes come from cameras.
# Run from itms/; resumable.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
R=baselines/2026-10-03_m8_blocking_aware/results_run4
mkdir -p $R
gate() {  # scenario-or-"", out name, then gate arguments
  local s=$1 out=$2; shift 2
  if [ -n "$s" ]; then export ITMS_SCENARIO=scenarios/generated/$s; else unset ITMS_SCENARIO; fi
  .venv/bin/python $G --workers 2 --resume --out $R/$out.json "$@" > $R/$out.log 2>&1
}
V=vision:itms6_640:failsafe:hol
gate ""                  corridor            --levels heavy --arms truth,hol:rev6,hol:g1 --seed-list $(seq -s, 201 210)
gate vijayawada_district vijayawada_district --levels heavy --arms truth,hol:rev6,hol:g1 --seed-list $(seq -s, 201 210)
echo done > $R/guard_done.txt
gate narrow_sweep narrow_sweep_cameras --levels d45   --arms $V,$V:p0:b3 --seed-list 201,202,203,204
gate vijayawada_district_mid vijayawada_district_mid --levels d65,d80 --arms truth,hol --seed-list $(seq -s, 201 210)
echo done > $R/eval_done.txt

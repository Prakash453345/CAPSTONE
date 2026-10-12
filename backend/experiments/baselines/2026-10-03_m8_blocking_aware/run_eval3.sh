#!/usr/bin/env bash
# Held-out run 3 (fresh seeds 201-220, never used before; TARGETS.md amendment 2 was
# written first). The controller is the default of 2026-10-05 (p0:b3); `hol:rev6` is
# the controller of run 2 on the same seeds. Run from itms/; resumable.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
R=baselines/2026-10-03_m8_blocking_aware/results_run3
mkdir -p $R
S20=$(seq -s, 201 220); S10=$(seq -s, 201 210); S5=$(seq -s, 201 205)
gate() {  # scenario-or-"", out name, then gate arguments
  local s=$1 out=$2; shift 2
  if [ -n "$s" ]; then export ITMS_SCENARIO=scenarios/generated/$s; else unset ITMS_SCENARIO; fi
  .venv/bin/python $G --workers 2 --resume --out $R/$out.json "$@" > $R/$out.log 2>&1
}
# 1. the single-lane grid, perfect data, 20 seeds
gate narrow_sweep narrow_sweep --levels d30,d35,d40,d45 --arms truth,hol:p0:b3:g1,hol:rev6 --seed-list $S20
gate narrow_lh    narrow_lh    --levels light           --arms truth,hol:p0:b3:g1,hol:rev6 --seed-list $S20
# 2. the other networks that have variants, 10 seeds
gate ""                  corridor            --levels medium,heavy       --arms truth,hol:p0:b3:g1 --seed-list $S10
gate vijayawada_district vijayawada_district --levels light,medium,heavy --arms truth,hol:p0:b3:g1 --seed-list $S10
# 3. the networks that have none: must equal CC-A-CAMP to the last digit
for S in berlin_adlershof grid3_lh arterial_lh grid4_rh_turns spider_lh random_lh ingolstadt; do
  gate $S identical_$S --levels heavy --arms truth,hol --seed-list 201
done
# 4. cameras in the loop, 5 seeds (perfect-data runs of the same seeds are in step 1)
gate narrow_sweep narrow_sweep_cameras --levels d45   --arms vision:itms6_640:failsafe:hol --seed-list $S5
gate narrow_lh    narrow_lh_cameras    --levels light --arms vision:itms6_640:failsafe:hol --seed-list $S5
echo done > $R/eval_done.txt

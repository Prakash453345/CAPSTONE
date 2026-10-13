#!/usr/bin/env bash
# The held-out runs of this baseline (EVAL seeds; TARGETS.md was written first).
# Run from itms/ with the venv built; resumable (each gate keeps finished runs).
# The gate pins the workers' Python hash seed (0), so every run repeats exactly.
set -u
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
R=baselines/2026-10-03_m8_blocking_aware/results
gate() {  # scenario-or-"", out name, then gate arguments
  local s=$1 out=$2; shift 2
  if [ -n "$s" ]; then export ITMS_SCENARIO=scenarios/generated/$s; else unset ITMS_SCENARIO; fi
  .venv/bin/python $G --workers 2 --resume --out $R/$out.json "$@" > $R/$out.log 2>&1
}
# 1. the single-lane grid, perfect data: Webster, CC-A-CAMP, blocking-aware
gate narrow_sweep narrow_sweep --levels d30,d35,d40,d45 --arms webster,truth,hol --seeds 10
gate narrow_lh    narrow_lh    --levels light,medium    --arms webster,truth,hol --seeds 10
# 2. what each part does, at the demand where CC-A-CAMP locks (reported, no target)
gate narrow_sweep narrow_sweep_parts --levels d45 --arms hol:price,hol:p0 --seeds 10
# 3. the other networks that have single-lane approaches
gate ""                  corridor            --levels medium,heavy       --arms truth,hol --seeds 10
gate berlin_adlershof    berlin_adlershof    --levels light,medium,heavy --arms truth,hol --seeds 10
gate vijayawada_district vijayawada_district --levels light,medium,heavy --arms truth,hol --seeds 10
# 4. the networks that have none: must equal CC-A-CAMP to the last digit
for S in grid3_lh arterial_lh grid4_rh_turns spider_lh random_lh ingolstadt; do
  gate $S identical_$S --levels heavy --arms truth,hol --seed-list 1
done
# 5. cameras in the loop on the single-lane grid, with the overview cameras
gate narrow_sweep narrow_sweep_cameras --levels d45   --arms vision:itms6_640:failsafe:hol,truth,hol,webster --seeds 5
gate narrow_lh    narrow_lh_cameras    --levels light --arms vision:itms6_640:failsafe:hol,truth,hol,webster --seeds 5
echo done > $R/eval_done.txt

#!/usr/bin/env bash
# Development (TRAIN seeds), the final controller (revision 5, back to the base phase only
# when the variant's approach is empty): what dev19/dev20 (`hol:idle`, the same thing) did
# not cover -- flow ratio 0.50, the other networks with single-lane approaches, cameras in
# the loop, and how well the overview cameras' blocked-lane reading matches the simulator's.
# Resumable: run again after an interruption.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev21_medium.json > $O/dev21_medium.log 2>&1
.venv/bin/python $G --levels medium,heavy --arms truth,hol --seed-list 101,102,103 --workers 2 --resume \
  --out $O/dev21_corridor.json > $O/dev21_corridor.log 2>&1
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels light,medium,heavy --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev21_vijayawada_district.json > $O/dev21_vijayawada_district.log 2>&1
echo done > $O/dev21a_done.txt
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45 --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev21_cam_sweep.json > $O/dev21_cam_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev21_cam_light.json > $O/dev21_cam_light.log 2>&1
for P in ideal itms6_640; do
  [ -f $O/dev21_agreement_$P.json ] || ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python scripts/m8_blocked_lane_agreement.py \
    --level medium --seed 101 --steps 900 --preset $P --out $O/dev21_agreement_$P.json > $O/dev21_agreement_$P.log 2>&1 &
done
wait
echo done > $O/dev21_done.txt

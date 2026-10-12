#!/usr/bin/env bash
# Development (TRAIN seeds), revision 5: a variant is its base phase without the protected
# streams the turn yields to; entered keeping its greens, left by an ordinary change. CC-A-CAMP on the
# single-lane grid: dev13 (same hash seed). Then the camera loop and the camera-versus-
# simulator agreement of the blocked-lane reading.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms hol,hol:nobudget \
  --seed-list 101,102,103,104,105 --workers 2 --resume --out $O/dev18_sweep.json > $O/dev18_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms hol,hol:nobudget \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out $O/dev18_light.json > $O/dev18_light.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev18_medium.json > $O/dev18_medium.log 2>&1
echo done > $O/dev18a_done.txt
.venv/bin/python $G --levels medium,heavy --arms truth,hol --seed-list 101,102,103 --workers 2 --resume \
  --out $O/dev18_corridor.json > $O/dev18_corridor.log 2>&1
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels light,medium,heavy --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev18_vijayawada_district.json > $O/dev18_vijayawada_district.log 2>&1
echo done > $O/dev18b_done.txt
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45 --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev18_cam_sweep.json > $O/dev18_cam_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev18_cam_light.json > $O/dev18_cam_light.log 2>&1
for P in ideal itms6_640; do
  ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python scripts/m8_blocked_lane_agreement.py \
    --level medium --seed 101 --steps 900 --preset $P --out $O/dev18_agreement_$P.json > $O/dev18_agreement_$P.log 2>&1 &
done
wait
echo done > $O/dev18_done.txt

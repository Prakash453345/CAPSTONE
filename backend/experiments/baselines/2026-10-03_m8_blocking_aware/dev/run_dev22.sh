#!/usr/bin/env bash
# Development (TRAIN seeds), revision 6 (guards from the fourth review: wait bound at rings of
# three or more phases, family ceiling, kernel-enforced variant rules, only a yielding blocker
# counts). Same coverage as dev19-dev21, with the new wait-overrun columns for both arms.
# Resumable: run again after an interruption.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms truth,hol \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out $O/dev22_sweep.json > $O/dev22_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms truth,hol \
  --seed-list 101,102,103,104,105,106,107,108,109,110 --workers 2 --resume --out $O/dev22_light.json > $O/dev22_light.log 2>&1
echo done > $O/dev22a_done.txt
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev22_medium.json > $O/dev22_medium.log 2>&1
.venv/bin/python $G --levels medium,heavy --arms truth,hol --seed-list 101,102,103 --workers 2 --resume \
  --out $O/dev22_corridor.json > $O/dev22_corridor.log 2>&1
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels light,medium,heavy --arms truth,hol \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev22_vijayawada_district.json > $O/dev22_vijayawada_district.log 2>&1
echo done > $O/dev22b_done.txt
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d45 --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev22_cam_sweep.json > $O/dev22_cam_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms vision:itms6_640:failsafe:hol \
  --seed-list 101,102 --workers 2 --resume --out $O/dev22_cam_light.json > $O/dev22_cam_light.log 2>&1
for P in ideal itms6_640; do
  [ -f $O/dev22_agreement_$P.json ] || ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python scripts/m8_blocked_lane_agreement.py \
    --level medium --seed 101 --steps 900 --preset $P --out $O/dev22_agreement_$P.json > $O/dev22_agreement_$P.log 2>&1 &
done
wait
echo done > $O/dev22_done.txt

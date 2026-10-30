#!/usr/bin/env bash
# Round 2 dev, part 2 on the Mac: 30-minute memory (hold 1800 s) on 5 networks. TRAINING seeds 101-103. From itms/.
cd "$(dirname "$0")/../../.."
export SUMO_BINARY=$PWD/.venv/bin/sumo SIGNAL_ALL_RED=ite PYTHONHASHSEED=0
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
D=baselines/2026-10-29_weak_spots/dev2
ARM="truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3:s.ceiling_relax_hold_s=1800"
for n in vijayawada_district ingolstadt arterial_lh random_lh grid4_rh_turns; do
  ITMS_SCENARIO=scenarios/generated/$n caffeinate -i .venv/bin/python scripts/m8_closed_loop_gate.py --workers 4 --resume \
    --levels heavy,medium,light --arms "$ARM" --seed-list 101,102,103 --out $D/gate3_${n}.json
done

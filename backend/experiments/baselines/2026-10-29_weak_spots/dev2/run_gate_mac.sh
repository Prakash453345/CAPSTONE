#!/usr/bin/env bash
# Round 2 dev on the Mac: berlin and vijayawada, TRAINING seeds 101-103. From itms/: bash baselines/2026-10-29_weak_spots/dev2/run_gate_mac.sh
cd "$(dirname "$0")/../../.."
export SUMO_BINARY=$PWD/.venv/bin/sumo SIGNAL_ALL_RED=ite PYTHONHASHSEED=0
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
D=baselines/2026-10-29_weak_spots/dev2
B="truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3"
ARMS="$B:s.ceiling_relax_hold_s=300,$B:s.ceiling_relax_hold_s=900,$B:s.ceiling_relax_network_max=0.2,$B:s.ceiling_relax_network_max=0.1"
for n in ${NETS:-vijayawada_district berlin_adlershof}; do
  ITMS_SCENARIO=scenarios/generated/$n caffeinate -i .venv/bin/python scripts/m8_closed_loop_gate.py --workers ${W:-4} --resume \
    --levels heavy,medium,light --arms "$ARMS" --seed-list 101,102,103 --out $D/gate_${n}.json
done

#!/usr/bin/env bash
# Design check (DESIGN.md section 5), Mac part (new backend/ layout). From the backend folder:
#   NETS="vijayawada_district amaravati_v2" bash experiments/baselines/2026-11-06_heavy/run_check_mac.sh
# Old layout (itms_paper_a folder): LAYOUT=old NETS="berlin_adlershof" bash baselines/2026-11-06_heavy/run_check_mac.sh
# Resumable: run the same command again after any stop.
if [ "$LAYOUT" = old ]; then cd "$(dirname "$0")/../.."; G=scripts/m8_closed_loop_gate.py; SC=scenarios/generated; R=baselines/2026-11-06_heavy/check
else cd "$(dirname "$0")/../../.."; G=experiments/m8_closed_loop_gate.py; SC=data/scenarios/generated; R=experiments/baselines/2026-11-06_heavy/check; fi
export PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite SUMO_BINARY=.venv/bin/sumo
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
ARMS="truth,truth:s.imminent_extension=true,truth:s.imminent_extension=true:s.imminent_only_loaded=true"
mkdir -p $R
for n in $NETS; do
  ITMS_SCENARIO=$SC/$n caffeinate -i .venv/bin/python $G --workers ${WORKERS:-4} --resume \
    --levels light,medium,heavy --arms "$ARMS" --seed-list 101,102,103,104,105 --out $R/check_${n}.json 2>&1 | tee -a $R/check_${n}.log | grep --line-buffered -E "^\[|runs to do|wrote|Error"
  if [ "$n" = vijayawada_district ]; then   # weak spot: v3 vs paper A, vijayawada medium, seeds 104-110
    ITMS_SCENARIO=$SC/$n caffeinate -i .venv/bin/python $G --workers ${WORKERS:-4} --resume \
      --levels medium --arms "truth,truth:s.ceiling_relax_factor=none" --seed-list 104,105,106,107,108,109,110 \
      --out $R/vij_medium_weakspot.json 2>&1 | tee -a $R/vij_medium_weakspot.log | grep --line-buffered -E "^\[|runs to do|wrote|Error"
  fi
done

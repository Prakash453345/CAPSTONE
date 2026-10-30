#!/usr/bin/env bash
# Michael's Mac after the 2026-10-28 three-way split: the main table on ITE all-red (resumes what
# run_mac.sh already finished) and the vijayawada_district ablation. Flat-all-red block and the other
# ablations moved to Preethi's Mac (run_mac_B.sh) and the cloud. From itms/.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
export PYTHONHASHSEED=0
export SUMO_BINARY=${SUMO_BINARY:-$PWD/.venv/bin/sumo}  # never a different sumo on PATH
R=baselines/2026-10-28_paper_a/results; W=${W:-4}; mkdir -p $R
SEEDS=279,280,281,282,283,284,285,286,287,288
gate() { if [ "$2" = ite ]; then export SIGNAL_ALL_RED=ite; else unset SIGNAL_ALL_RED; fi
  ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers $W --resume \
    --levels light,medium,heavy --arms $3 --seed-list $4 --out $R/$5_$1_$2.json >> $R/$5_$1_$2.log 2>&1; }
for n in arterial_lh ingolstadt narrow_lh random_lh grid4_rh_turns berlin_adlershof vijayawada_district amaravati_v2; do
  gate $n ite truth,webster:pair,maxpressure,actuated $SEEDS main; done
echo "$(date -u +%FT%TZ) main_ite" >> $R/progress_mac.txt
gate vijayawada_district ite "truth:c10,truth:nopair,truth:ync,truth:f0,truth:s.gap_out_grace_s=-1,truth:nov,truth:s.cycle_supervisor=false,truth:noovl" 279,280,281,282,283 abl
date -u +%FT%TZ > $R/done_mac_A.txt

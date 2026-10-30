#!/usr/bin/env bash
# Preethi's Mac after the 2026-10-28 three-way split: the flat 2.0 s all-red block (ours and Webster,
# seeds 279-288, longest network first), then the ablation (5 seeds) on six networks in forward order
# (the cloud runs the same ablation in reverse order; any overlap is identical and merged).
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
export PYTHONHASHSEED=0
export SUMO_BINARY=${SUMO_BINARY:-$PWD/.venv/bin/sumo}  # never a different sumo on PATH
R=baselines/2026-10-28_paper_a/results; W=${W:-4}; mkdir -p $R
SEEDS=279,280,281,282,283,284,285,286,287,288
gate() { if [ "$2" = ite ]; then export SIGNAL_ALL_RED=ite; else unset SIGNAL_ALL_RED; fi
  ITMS_SCENARIO=scenarios/generated/$1 .venv/bin/python scripts/m8_closed_loop_gate.py --workers $W --resume \
    --levels light,medium,heavy --arms $3 --seed-list $4 --out $R/$5_$1_$2.json >> $R/$5_$1_$2.log 2>&1; }
date -u +%FT%TZ > $R/started_mac_B.txt
for n in amaravati_v2 vijayawada_district berlin_adlershof grid4_rh_turns random_lh narrow_lh ingolstadt arterial_lh; do
  gate $n flat truth,webster:pair $SEEDS main; done
echo "$(date -u +%FT%TZ) main_flat" >> $R/progress_mac_B.txt
for n in arterial_lh ingolstadt narrow_lh random_lh grid4_rh_turns berlin_adlershof; do
  gate $n ite "truth:c10,truth:nopair,truth:ync,truth:f0,truth:s.gap_out_grace_s=-1,truth:nov,truth:s.cycle_supervisor=false,truth:noovl" 279,280,281,282,283 abl
done
date -u +%FT%TZ > $R/done_mac_B.txt
cd baselines/2026-10-28_paper_a && zip -qr ~/Desktop/paper_a_results_preethi.zip results && echo "results zipped to ~/Desktop/paper_a_results_preethi.zip"

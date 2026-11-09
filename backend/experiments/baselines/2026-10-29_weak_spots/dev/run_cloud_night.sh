#!/usr/bin/env bash
# Overnight cloud queue (2026-10-29): waits for run_relax_cloud.sh, then smart-limit arms on grid4 and narrow_lh,
# then the rest of the narrow_lh ceiling test (resumes from the Mac's partial file). TRAINING seeds 101-103. Resumable.
cd "$(dirname "$0")/../../.."
export SUMO_HOME=$(python3 -c 'import sumo,os;print(os.path.dirname(sumo.__file__))') PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite
D=baselines/2026-10-29_weak_spots/dev
while pgrep -f run_relax_cloud.sh > /dev/null; do sleep 30; done
RELAX="truth:s.ceiling_relax_factor=8,truth:s.ceiling_relax_factor=3,truth:s.ceiling_relax_factor=8:s.ceiling_relax_below=0.3,truth:s.ceiling_relax_factor=8:s.kappa_switch=1"
for n in random_lh ingolstadt arterial_lh grid4_rh_turns narrow_lh; do
  ITMS_SCENARIO=scenarios/generated/$n python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light,medium,heavy \
    --arms "$RELAX" --seed-list 101,102,103 --out $D/relax_${n}.json >> $D/relax_${n}.log 2>&1
done
ITMS_SCENARIO=scenarios/generated/narrow_lh python3 scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light,medium,heavy \
  --arms truth,truth:c1.5:f20,truth:c2:f20,truth:c3:f20,truth:c10:f20,actuated --seed-list 101,102,103 --out $D/ceil_narrow_lh.json >> $D/ceil_narrow_lh.log 2>&1
date -u +%FT%TZ > $D/night_done.txt

#!/usr/bin/env bash
# Development (TRAIN seeds 101-110), after the held-out run of revision 6: three leads.
#  a) act on a blockage at once (p0), a longer family budget (b3), both;
#  b) a higher green ceiling for CC-A-CAMP itself (c2, c3).
# CC-A-CAMP and the default controller at light, d35, d40, d45 are in dev22. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
S=101,102,103,104,105,106,107,108,109,110
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d35,d40,d45 --arms hol:p0,hol:b3,hol:p0:b3 \
  --seed-list $S --workers 2 --resume --out $O/dev23_sweep.json > $O/dev23_sweep.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d30 --arms truth,hol,hol:p0,hol:b3,hol:p0:b3 \
  --seed-list $S --workers 2 --resume --out $O/dev23_d30.json > $O/dev23_d30.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms hol:p0,hol:b3,hol:p0:b3 \
  --seed-list $S --workers 2 --resume --out $O/dev23_light.json > $O/dev23_light.log 2>&1
echo done > $O/dev23a_done.txt
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels light --arms truth:c2,truth:c3 \
  --seed-list $S --workers 2 --resume --out $O/dev23_ceil_light.json > $O/dev23_ceil_light.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_sweep .venv/bin/python $G --levels d30,d35,d40,d45 --arms truth:c2,truth:c3 \
  --seed-list $S --workers 2 --resume --out $O/dev23_ceil_sweep.json > $O/dev23_ceil_sweep.log 2>&1
echo done > $O/dev23_done.txt

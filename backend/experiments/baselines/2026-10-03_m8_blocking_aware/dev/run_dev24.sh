#!/usr/bin/env bash
# Development (TRAIN seeds 101-103): the two candidates from dev23 (b3, p0:b3) on the other
# networks and at 0.50, and where waits pass their bound on the jammed networks
# (`wait_overruns` in each record, new). Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
G=scripts/m8_closed_loop_gate.py
O=results/hol
while [ ! -f $O/dev23_done.txt ]; do sleep 15; done
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels heavy --arms truth,hol,hol:b3,hol:p0:b3 \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev24_district_heavy.json > $O/dev24_district_heavy.log 2>&1
.venv/bin/python $G --levels heavy --arms truth,hol,hol:b3,hol:p0:b3 --seed-list 101,102,103 --workers 2 --resume \
  --out $O/dev24_corridor_heavy.json > $O/dev24_corridor_heavy.log 2>&1
echo done > $O/dev24a_done.txt
ITMS_SCENARIO=scenarios/generated/vijayawada_district .venv/bin/python $G --levels light,medium --arms hol:b3,hol:p0:b3 \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev24_district.json > $O/dev24_district.log 2>&1
.venv/bin/python $G --levels medium --arms hol:b3,hol:p0:b3 --seed-list 101,102,103 --workers 2 --resume \
  --out $O/dev24_corridor.json > $O/dev24_corridor.log 2>&1
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python $G --levels medium --arms hol:b3,hol:p0:b3 \
  --seed-list 101,102,103 --workers 2 --resume --out $O/dev24_medium.json > $O/dev24_medium.log 2>&1
echo done > $O/dev24_done.txt

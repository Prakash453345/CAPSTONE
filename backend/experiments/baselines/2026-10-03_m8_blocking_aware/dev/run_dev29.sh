#!/usr/bin/env bash
# Development (TRAIN 101-103), direction 3: the 0.50 jam. The parent's gate against a
# full receiving link shuts at an occupancy of 0.85, which a standing queue of this
# vehicle mix may never reach; try 0.6 and 0.7. Records now carry `entry_delay_s`
# (time waiting to enter the network, not part of person-delay). Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=results/hol
ITMS_SCENARIO=scenarios/generated/narrow_lh .venv/bin/python scripts/m8_closed_loop_gate.py --levels medium \
  --arms truth,hol,hol:r0.6,hol:r0.7 --seed-list 101,102,103 --workers 1 --resume \
  --out $O/dev29_medium.json > $O/dev29_medium.log 2>&1
echo done > $O/dev29_done.txt

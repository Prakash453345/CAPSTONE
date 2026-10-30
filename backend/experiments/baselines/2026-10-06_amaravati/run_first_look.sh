#!/usr/bin/env bash
# First look (training seeds 101-103, no targets): Webster against CC-A-CAMP on the
# Amaravati planned network, perfect data. Resumable.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-06_amaravati/results
ITMS_SCENARIO=scenarios/generated/amaravati .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume \
  --levels light,medium,heavy --arms webster,truth --seed-list 101,102,103 --out $R/first_look.json > $R/first_look.log 2>&1
echo done > $R/first_look_done.txt

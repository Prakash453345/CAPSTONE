#!/usr/bin/env bash
# Follow-up F3b (TARGETS.md): Amaravati plan grid, light demand, ten new seeds.
cd "$(dirname "$0")/../.."
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
R=baselines/2026-10-07_ceiling_floor/results_f3b; mkdir -p $R
ITMS_SCENARIO=scenarios/generated/amaravati_plan .venv/bin/python scripts/m8_closed_loop_gate.py --workers 2 --resume --levels light \
  --arms truth,truth:f20 --seed-list $(seq -s, 226 235) --out $R/amaravati_plan.json > $R/amaravati_plan.log 2>&1
echo done > $R/done.txt

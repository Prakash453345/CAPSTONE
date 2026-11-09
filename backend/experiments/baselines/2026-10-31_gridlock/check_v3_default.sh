#!/usr/bin/env bash
# Checks that this machine's default controller is v3, bit-identical to the fresh-seed test (2026-10-31_gridlock),
# and that s.ceiling_relax_factor=none still gives paper A's controller. Arterial, light, seeds 309-310 (~2 min).
# Run from the folder that holds .venv (backend/ in the new layout, itms_paper_a/ in the old one).
set -e
if [ -f experiments/m8_closed_loop_gate.py ]; then G=experiments/m8_closed_loop_gate.py; SC=data/scenarios/generated/arterial_lh
else G=scripts/m8_closed_loop_gate.py; SC=scenarios/generated/arterial_lh; fi
export PYTHONHASHSEED=0 SIGNAL_ALL_RED=ite SUMO_BINARY=.venv/bin/sumo
export SUMO_HOME=$(.venv/bin/python -c 'import sumo,os;print(os.path.dirname(sumo.__file__))')
O=$(mktemp -d)/check.json
ITMS_SCENARIO=$SC .venv/bin/python $G --workers 2 --levels light --arms "truth,truth:s.ceiling_relax_factor=none" \
  --seed-list 309,310 --out $O > ${O%.json}.log 2>&1 || { tail -20 ${O%.json}.log; exit 1; }
.venv/bin/python - "$O" <<'PY'
import json, sys
want = {("truth", 309): 21398.096, ("truth", 310): 17705.947,
        ("truth:s.ceiling_relax_factor=none", 309): 25256.53, ("truth:s.ceiling_relax_factor=none", 310): 23938.038}
got = {(r["arm"], r["seed"]): r["person_delay_s"] for r in json.load(open(sys.argv[1]))["records"]}
ok = True
for k, v in want.items():
    same = abs(got.get(k, -1) - v) < 1e-6; ok &= same
    print(("same " if same else "DIFF ") + ("v3 default " if k[0] == "truth" else "paper A    ") + f"seed {k[1]}: {got.get(k)} (expected {v})")
print("CHECK PASS" if ok else "CHECK FAIL")
PY

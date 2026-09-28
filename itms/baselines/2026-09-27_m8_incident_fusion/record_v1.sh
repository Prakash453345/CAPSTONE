# run from itms/ (the gate now also records the tracker columns; version 1 reads only the first seven)
.venv/bin/python scripts/m8_incident_gate.py --presets itms6_640 --levels medium,heavy --seeds 5 --seed-set train --workers 2 --features-dir data/m8_fusion/features --out data/m8_fusion/train.json --resume
.venv/bin/python scripts/m8_incident_gate.py --presets itms6_640 --levels medium,heavy --seeds 5 --seed-set eval --workers 2 --features-dir data/m8_fusion/features --out data/m8_fusion/eval.json --resume
echo ALLDONE

# run from itms/; the second command resumes from a copy of eval.json, so it adds only seeds 6-10
cp data/m8_fusion/eval.json data/m8_fusion/eval_v2.json
.venv/bin/python scripts/m8_incident_gate.py --presets itms6_640 --levels medium,heavy --seeds 5 --seed-set train --workers 2 --features-dir data/m8_fusion/features_v2 --out data/m8_fusion/train_v2.json --resume
.venv/bin/python scripts/m8_incident_gate.py --presets itms6_640 --levels medium,heavy --seeds 10 --seed-set eval --workers 2 --features-dir data/m8_fusion/features_v2 --out data/m8_fusion/eval_v2.json --resume
echo ALLDONE

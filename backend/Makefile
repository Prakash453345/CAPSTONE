.PHONY: dev dev-amaravati seed-accounts setup infra-up infra-up-all infra-down test test-fast test-anomaly test-all lint bench down clean \
	vision-dev vision-model test-vision m8-cameras m8-perception m8-incidents m8-closed-loop \
	m8-video m8-live

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

$(VENV)/bin/activate:
	python3 -m venv $(VENV)

setup: $(VENV)/bin/activate
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements-dev.txt -q
	$(PIP) install -e libs/common -q
	$(PIP) install -e libs/domain -q
	$(PIP) install -e services/simulation-service -q
	$(PIP) install -e services/api-gateway -q
	$(PIP) install -e libs/geo -q
	$(PIP) install -e services/vision-service -q

# Postgres (console accounts, road network) and Redis (the service bus) are all
# `make dev` needs. MinIO only stores vision evidence clips, and only when
# vision-service runs with MINIO_ENDPOINT/VISION_EVIDENCE set -- it used to be
# started here too, so an unavailable MinIO image failed the whole stack and
# left the console with no backend (2026-10-18). Use `infra-up-all` for it.
infra-up:
	docker compose -f infra/docker-compose.yml up -d postgres redis
	./scripts/wait-for-healthy.sh itms-postgres itms-redis

# Everything, including MinIO: needed only for vision evidence storage.
infra-up-all:
	docker compose -f infra/docker-compose.yml up -d postgres redis minio
	./scripts/wait-for-healthy.sh itms-postgres itms-redis itms-minio

dev: setup infra-up
	./scripts/dev.sh

# The same stack on the Amaravati capital complex instead of the Vijayawada
# corridor. Built the same way the corridor was (scenarios/generated/
# amaravati_capital/build.sh): one named arterial, its real cross streets,
# seven signals -- 86 edges, so it runs at 31x real time light / 13.5x heavy,
# against the corridor's 44x. Vijayawada stays the default; this is opt-in.
# Run the web app with VITE_CITY=amaravati so its road pickers match.
dev-amaravati: setup infra-up
	ITMS_SCENARIO=scenarios/generated/amaravati_capital ./scripts/dev.sh

# Create or update every account listed in a CSV (default .local/accounts.csv,
# git-ignored: it holds passwords). Safe to repeat. Format: api_gateway/services/seed_accounts.py.
seed-accounts: setup
	$(PY) -m api_gateway.services.seed_accounts $${ACCOUNTS:-.local/accounts.csv}

# Default: everything except the M6 anomaly-detector tests, which need the
# optional `[anomaly]` extra (numpy/torch, ~1GB, not installed by `setup`).
# Those tests use `pytest.importorskip` and report SKIPPED rather than
# erroring out when the extra is absent -- see `test-anomaly` below to
# actually run them. Includes the slow_property suite (~55s, the real M2
# gate) -- use `test-fast` for a quicker dev loop.
test: setup
	REDIS_URL=$${REDIS_URL:-redis://localhost:6379/0} \
	RUN_INTEGRATION_TESTS=$${RUN_INTEGRATION_TESTS:-0} \
	$(VENV)/bin/pytest -q

# Quick dev-loop subset: skips the 10,000-example-per-invariant Hypothesis
# suite (test_interlocks_properties.py) and, like `test`, skips anomaly
# tests if the extra isn't installed. Not a substitute for `make test`
# before anything you intend to call passing.
test-fast: setup
	REDIS_URL=$${REDIS_URL:-redis://localhost:6379/0} \
	RUN_INTEGRATION_TESTS=$${RUN_INTEGRATION_TESTS:-0} \
	$(VENV)/bin/pytest -q -m "not slow_property"

# Installs the M6 anomaly detector's extra (numpy/torch) and runs just its
# tests -- separate from `test` because the extra is large and only this
# one module needs it.
test-anomaly: setup
	$(PIP) install -e "services/simulation-service[anomaly]" -q
	$(VENV)/bin/pytest -q \
		services/simulation-service/tests/control/test_anomaly_calibration.py \
		services/simulation-service/tests/control/test_anomaly_detector.py \
		services/simulation-service/tests/control/test_anomaly_fusion.py \
		services/simulation-service/tests/control/test_anomaly_live_pipeline.py

# Everything, including the anomaly extra. What CI should run.
test-all: test-anomaly
	REDIS_URL=$${REDIS_URL:-redis://localhost:6379/0} \
	RUN_INTEGRATION_TESTS=$${RUN_INTEGRATION_TESTS:-0} \
	$(VENV)/bin/pytest -q

lint: setup
	$(VENV)/bin/ruff check .
	$(VENV)/bin/mypy libs services

# M3 gate [build guide §7/§8]: 3 tuned baseline controllers x 10 seeds,
# person-delay/throughput/max-wait/stops with 95% CIs. Shells out to 30
# real SUMO processes -- a few minutes, not a test-suite-speed target.
bench: setup
	$(VENV)/bin/python experiments/bench.py

# ---- M8: vision ------------------------------------------------------------
# The vision service in SimCam mode: films sim-service's live vehicle stream
# through the planned cameras and publishes vision.link-state,
# vision.camera-status and VISION anomalies. Run it next to `make dev`.
vision-dev: setup
	VISION_MODE=simcam $(PY) -m vision_service.main

# The adopted detector for VISION_MODE=video: the fine-tune of IISc's UVH-26
# model (experiments/baselines/2026-09-27_m8_finetune_v2/). Unzip the fine-tune notebook's
# results into data/uvh26/finetune_v2/ first; data/ is not in git.
MODEL_SRC := data/uvh26/finetune_v3/itms_six_aug_640.onnx
vision-model:
	@test -f $(MODEL_SRC) || { echo "missing $(MODEL_SRC): unzip the v3 fine-tune notebook's results there"; exit 1; }
	mkdir -p data/models && cp $(MODEL_SRC) data/models/itms_six_aug_640.onnx
	@echo "data/models/itms_six_aug_640.onnx is the video-mode detector"

test-vision: setup
	$(VENV)/bin/pytest -q libs/geo services/vision-service

# Re-plan the Vijayawada camera registry (one camera per signalised approach).
m8-cameras: setup
	$(PY) experiments/m8_plan_cameras.py

# The three M8 gates. Each runs real SUMO; minutes to hours on a laptop --
# see experiments/baselines/2026-09-25_m8_review/README.md for the exact commands and
# the numbers they produced.
m8-perception: setup
	$(PY) experiments/m8_perception_gate.py --out experiments/results/m8_perception.json

m8-incidents: setup
	$(PY) experiments/m8_incident_gate.py --seed-set train --out experiments/results/m8_incident_train.json
	$(PY) experiments/m8_incident_gate.py --seed-set eval --out experiments/results/m8_incident_eval.json
	$(PY) experiments/m8_incident_analysis.py experiments/results/m8_incident_train.json \
		experiments/results/m8_incident_eval.json --budget 10 --out experiments/results/m8_incident_analysis.json

m8-closed-loop: setup
	$(PY) experiments/m8_closed_loop_gate.py --out experiments/results/m8_closed_loop.json

# The live stack end to end: sim-service's A-CA-MP on the cameras
# (CONTROL_SENSOR=vision) and the vision service in SimCam mode, over a
# throwaway Redis on port 6390 (needs redis-server). ~5 minutes.
m8-live: setup
	experiments/m8_live_e2e.sh

# Real-footage smoke test (needs the [yolo,onnx] extras and a clip):
#   make m8-video VIDEO=path/to/clip.mp4
m8-video: setup
	$(PIP) install -e "services/vision-service[yolo,onnx]" -q
	$(PY) experiments/m8_real_video_smoke.py --video $(VIDEO) --onnx --redact-demo \
		--out experiments/results/m8_video/$$(basename $(VIDEO) | cut -d. -f1)

down:
	docker compose -f infra/docker-compose.yml down

clean: down
	rm -rf $(VENV)

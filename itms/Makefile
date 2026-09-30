.PHONY: dev setup infra-up infra-down test test-fast test-anomaly test-all lint bench down clean \
	vision-dev vision-model test-vision m8-cameras m8-perception m8-incidents m8-closed-loop \
	m8-video m8-live \
	m6-graph m6-data m6-train m6-gate

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

$(VENV)/bin/activate:
	python3 -m venv $(VENV)

setup: $(VENV)/bin/activate
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements-dev.txt -q
	$(PIP) install -e packages/common -q
	$(PIP) install -e packages/domain -q
	$(PIP) install -e services/sim-service -q
	$(PIP) install -e services/api-service -q
	$(PIP) install -e packages/anomaly -q
	$(PIP) install -e services/incident-service -q
	$(PIP) install -e packages/geo -q
	$(PIP) install -e services/vision-service -q

infra-up:
	docker compose up -d postgres redis minio
	./scripts/wait-for-healthy.sh

dev: setup infra-up
	./scripts/dev.sh

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
	$(PIP) install -e "services/sim-service[anomaly]" -q
	$(VENV)/bin/pytest -q \
		services/sim-service/tests/control/test_anomaly_calibration.py \
		services/sim-service/tests/control/test_anomaly_detector.py \
		services/sim-service/tests/control/test_anomaly_fusion.py \
		services/sim-service/tests/control/test_anomaly_live_pipeline.py

# Everything, including the anomaly extra. What CI should run.
test-all: test-anomaly
	REDIS_URL=$${REDIS_URL:-redis://localhost:6379/0} \
	RUN_INTEGRATION_TESTS=$${RUN_INTEGRATION_TESTS:-0} \
	$(VENV)/bin/pytest -q

lint: setup
	$(VENV)/bin/ruff check .
	$(VENV)/bin/mypy packages services

# M3 gate [build guide §7/§8]: 3 tuned baseline controllers x 10 seeds,
# person-delay/throughput/max-wait/stops with 95% CIs. Shells out to 30
# real SUMO processes -- a few minutes, not a test-suite-speed target.
bench: setup
	$(VENV)/bin/python scripts/bench.py

# ---- M8: vision ------------------------------------------------------------
# The vision service in SimCam mode: films sim-service's live vehicle stream
# through the planned cameras and publishes vision.link-state,
# vision.camera-status and VISION anomalies. Run it next to `make dev`.
vision-dev: setup
	VISION_MODE=simcam $(PY) -m vision_service.main

# The adopted detector for VISION_MODE=video: the fine-tune of IISc's UVH-26
# model (baselines/2026-09-27_m8_finetune_v2/). Unzip the fine-tune notebook's
# results into data/uvh26/finetune_v2/ first; data/ is not in git.
MODEL_SRC := data/uvh26/finetune_v2/itms_six_fp32_640.onnx
vision-model:
	@test -f $(MODEL_SRC) || { echo "missing $(MODEL_SRC): unzip the fine-tune notebook's results there"; exit 1; }
	mkdir -p data/models && cp $(MODEL_SRC) data/models/itms_six_fp32_640.onnx
	@echo "data/models/itms_six_fp32_640.onnx is the video-mode detector"

test-vision: setup
	$(VENV)/bin/pytest -q packages/geo services/vision-service

# Re-plan the Vijayawada camera registry (one camera per signalised approach).
m8-cameras: setup
	$(PY) scripts/m8_plan_cameras.py

# The three M8 gates. Each runs real SUMO; minutes to hours on a laptop --
# see baselines/2026-09-25_m8_review/README.md for the exact commands and
# the numbers they produced.
m8-perception: setup
	$(PY) scripts/m8_perception_gate.py --out results/m8_perception.json

m8-incidents: setup
	$(PY) scripts/m8_incident_gate.py --seed-set train --out results/m8_incident_train.json
	$(PY) scripts/m8_incident_gate.py --seed-set eval --out results/m8_incident_eval.json
	$(PY) scripts/m8_incident_analysis.py results/m8_incident_train.json \
		results/m8_incident_eval.json --budget 10 --out results/m8_incident_analysis.json

m8-closed-loop: setup
	$(PY) scripts/m8_closed_loop_gate.py --out results/m8_closed_loop.json

# The live stack end to end: sim-service's A-CA-MP on the cameras
# (CONTROL_SENSOR=vision) and the vision service in SimCam mode, over a
# throwaway Redis on port 6390 (needs redis-server). ~5 minutes.
m8-live: setup
	scripts/m8_live_e2e.sh

# Real-footage smoke test (needs the [yolo,onnx] extras and a clip):
#   make m8-video VIDEO=path/to/clip.mp4
m8-video: setup
	$(PIP) install -e "services/vision-service[yolo,onnx]" -q
	$(PY) scripts/m8_real_video_smoke.py --video $(VIDEO) --onnx --redact-demo \
		--out results/m8_video/$$(basename $(VIDEO) | cut -d. -f1)

down:
	docker compose down

clean: down
	rm -rf $(VENV)

# ---- M6: Anomaly detection & incident pipeline ----

m6-graph: setup
	$(VENV)/bin/python scripts/build_graph.py \
		--net scenarios/networks/vijayawada/vijayawada_corridor.net.xml \
		--output scenarios/networks/vijayawada/adjacency.json \
		--network-name vijayawada_corridor

m6-data: setup
	$(VENV)/bin/python scripts/generate_training_data.py \
		--output-dir data/m6 --seeds 5 --demand-levels light,medium,heavy

m6-train: setup
	$(VENV)/bin/python scripts/train_anomaly_detector.py \
		--data-dir data/m6/normal \
		--graph scenarios/networks/vijayawada/adjacency.json \
		--output-dir models --epochs 50

m6-gate: setup
	$(VENV)/bin/python scripts/m6_gate.py \
		--data-dir data/m6 \
		--model models/anomaly_detector.pt \
		--graph scenarios/networks/vijayawada/adjacency.json \
		--scaler models/scaler.json \
		--conformal models/conformal.json

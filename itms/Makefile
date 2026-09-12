.PHONY: dev setup infra-up infra-down test lint bench down clean m6-graph m6-data m6-train m6-gate

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
infra-up:
	docker compose up -d postgres redis minio
	./scripts/wait-for-healthy.sh

dev: setup infra-up
	./scripts/dev.sh

test: setup
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

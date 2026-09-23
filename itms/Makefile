.PHONY: dev setup infra-up infra-down test test-fast test-anomaly test-all lint bench down clean

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

down:
	docker compose down

clean: down
	rm -rf $(VENV)

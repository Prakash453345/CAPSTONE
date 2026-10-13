#!/usr/bin/env bash
# Runs sim-service and api-service side by side, in the foreground, with both
# logs interleaved and both processes killed together on Ctrl+C. This replaces
# a heavier process manager for M0 — revisit once there are more than two
# processes to juggle.
set -euo pipefail

VENV=".venv"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

cleanup() {
  echo ""
  echo "stopping sim-service and api-service..."
  kill "${SIM_PID:-0}" "${API_PID:-0}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$VENV/bin/python" -m sim_service.main &
SIM_PID=$!

"$VENV/bin/uvicorn" api_gateway.main:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

sleep 1
echo ""
echo "=========================================================="
echo " api-gateway: http://localhost:8000/health"
echo " ws stream:   ws://localhost:8000/v1/stream"
echo " console:     cd ../frontend && npm run dev  ->  http://localhost:5173"
echo " minio console: http://localhost:9001 (itms / itms12345)"
echo " Ctrl+C to stop both services (infra keeps running; 'make down' stops it)"
echo "=========================================================="
echo ""

wait "$SIM_PID" "$API_PID"

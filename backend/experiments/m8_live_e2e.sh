#!/usr/bin/env bash
# M8 live end to end: sim-service runs the corridor in SUMO with A-CA-MP taking
# its queue state from the cameras (CONTROL_SENSOR=vision), while the vision
# service films sim-service's own vehicle stream (SimCam) -- both talking
# over a real, throwaway Redis. Checks that link state flows both ways and
# the controller actually used it.
#
#   experiments/m8_live_e2e.sh            # 300 simulated seconds at real time
#   STEPS=600 experiments/m8_live_e2e.sh
#
# Needs redis-server on PATH and the repo's .venv (make setup). Logs go to
# ${OUT:-results/m8_live_e2e}/.
set -u
cd "$(dirname "$0")/.."
. .venv/bin/activate
PORT=${PORT:-6390}
STEPS=${STEPS:-300}
OUT=${OUT:-results/m8_live_e2e}
mkdir -p "$OUT"
redis-server --port "$PORT" --daemonize yes --save "" --appendonly no --logfile "$PWD/$OUT/redis.log"
sleep 1
export REDIS_URL=redis://localhost:$PORT/0
cleanup() { kill "$VPID" 2>/dev/null; redis-cli -p "$PORT" shutdown nosave >/dev/null 2>&1; }
trap cleanup EXIT

VISION_MODE=simcam python -m vision_service.main > "$OUT/vision.log" 2>&1 &
VPID=$!
sleep 8
SIM_MODE=sumo CONTROL_SENSOR=vision SIM_MAX_STEPS=$STEPS SIM_REALTIME_FACTOR=1.0 \
  python -m sim_service.main > "$OUT/sim.log" 2>&1
echo "sim-service exit code: $?"
sleep 2
echo "--- stream lengths"
for s in traffic.vehicle-positions signal.changed vision.link-state vision.camera-status anomaly.updated; do
  echo "$s $(redis-cli -p "$PORT" XLEN $s)"
done
echo "--- vision service still running: $(kill -0 $VPID 2>/dev/null && echo yes || echo NO)"
echo "--- errors in the logs"
grep -c -E "Traceback|ERROR|exception" "$OUT/vision.log" "$OUT/sim.log"
echo "--- the controller's feed"
grep "vision feed" "$OUT/sim.log" | tail -2
grep "scenario finished" "$OUT/sim.log" | tail -1

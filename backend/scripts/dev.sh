#!/usr/bin/env bash
# Runs the simulation service and the api-gateway side by side, in the foreground, with both
# logs interleaved and both processes killed together on Ctrl+C. This replaces
# a heavier process manager for M0 — revisit once there are more than two
# processes to juggle.
set -euo pipefail

VENV=".venv"

# Settings live in backend/.env (copy .env.example; it is git-ignored, so the SMTP
# password never lands in the repo). Values already exported in the shell win.
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    key="${key#export }"; key="${key// /}"
    case "$val" in \"*\") val="${val:1:${#val}-2}" ;; \'*\') val="${val:1:${#val}-2}" ;; esac
    printenv "$key" >/dev/null || export "$key=$val"
  done < .env
  echo "loaded settings from .env"
fi
# Your own settings (SMTP_* for password-reset email, etc.) live in .env.local,
# which git ignores. Load it so they apply on every run without retyping.
if [ -f ".env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.local
  set +a
  echo "loaded settings from .env.local"
fi
# A fixed session key, so a restart does not sign everyone out: .env's
# AUTH_SECRET, else the one kept in .local/auth_secret.env.
if [ -z "${AUTH_SECRET:-}" ] && [ -f .local/auth_secret.env ]; then
  AUTH_SECRET="$(tr -d '[:space:]' < .local/auth_secret.env)"
  export AUTH_SECRET="${AUTH_SECRET#AUTH_SECRET=}"
fi

# An api-service left over from an earlier run holds the port, and the new one
# dies with "[Errno 48] Address already in use" in the middle of the log.
if command -v lsof >/dev/null 2>&1 && lsof -ti :8000 >/dev/null 2>&1; then
  echo "port 8000 is already in use (PID $(lsof -ti :8000 | tr '\n' ' '))."
  echo "That is usually an api-service from an earlier run. Stop it with:"
  echo "    lsof -ti :8000 | xargs kill"
  exit 1
fi

export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
# Local dev is plain http, where browsers drop "Secure" cookies (Safari even on
# localhost), so sign-in would silently fail. Production must leave this on.
export AUTH_COOKIE_SECURE="${AUTH_COOKIE_SECURE:-false}"
# No mail server locally: print password-reset codes in the api-gateway log
# instead of failing. With SMTP_HOST set (in .env) the codes are emailed.
export AUTH_DEV_LOG_CODES="${AUTH_DEV_LOG_CODES:-true}"
export DATABASE_URL="${DATABASE_URL:-postgresql://itms:itms@localhost:5432/itms}"
# The console's interactive features -- operator anomalies, emergency dispatch,
# green corridors -- are the live loop, which is the only mode that drains the
# `commands.operator` stream. The default ("sumo") just streams M1 traffic, so
# "Calculate route" posted a command nothing consumed and the request never
# appeared (2026-10-18). Set SIM_MODE=sumo here to get the plain M1 loop back.
export SIM_MODE="${SIM_MODE:-live}"
export SIM_DEMAND="${SIM_DEMAND:-light}"
export SIM_REALTIME_FACTOR="${SIM_REALTIME_FACTOR:-1.0}"

cleanup() {
  echo ""
  echo "stopping sim-service and api-service..."
  kill "${SIM_PID:-0}" "${API_PID:-0}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$VENV/bin/python" -m sim_service.main &
SIM_PID=$!

# 127.0.0.1, not 0.0.0.0: commands and uploads need no API key, so keep the
# gateway off the network; the console reaches it through Vite's proxy.
"$VENV/bin/uvicorn" api_gateway.main:app --host 127.0.0.1 --port 8000 --reload &
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

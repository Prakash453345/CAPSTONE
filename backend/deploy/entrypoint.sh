#!/bin/sh
# One image, several jobs: `api` (site + API + live stream on port 8000),
# `sim` (the live simulation), `seed` / `users` (account commands).
set -e
cd /app/backend
if [ -z "${SUMO_HOME:-}" ]; then
  SUMO_HOME="$(python -c 'import os, sumo; print(os.path.dirname(sumo.__file__))')"
  export SUMO_HOME
fi
job="${1:-api}"
[ $# -gt 0 ] && shift
case "$job" in
  api)   exec uvicorn api_gateway.main:app --host 0.0.0.0 --port 8000 \
           --proxy-headers --forwarded-allow-ips='*' "$@" ;;
  sim)   export SIM_MODE="${SIM_MODE:-live}"  # the live sim the site drives
         exec python -m sim_service.main "$@" ;;
  seed)  exec python -m api_gateway.services.seed_accounts "$@" ;;
  users) exec python -m api_gateway.services.users "$@" ;;
  *)     exec "$job" "$@" ;;
esac

#!/usr/bin/env bash
# Polls `docker inspect` until every named container reports healthy, or bails
# after ~2 minutes. Used by `make infra-up` so `make dev` doesn't race the
# stack coming up. Takes the container names as arguments; with none it waits
# for the two services the console actually needs (MinIO is optional -- see
# `make infra-up-all`).
set -euo pipefail

# `$#` rather than ${#SERVICES[@]}: an empty array under `set -u` is an error
# in bash 3.2, which is what macOS ships as /bin/bash.
if [ "$#" -eq 0 ]; then
  SERVICES=(itms-postgres itms-redis)
else
  SERVICES=("$@")
fi
MAX_WAIT_S=120
INTERVAL_S=3
elapsed=0

echo "waiting for ${SERVICES[*]} to become healthy..."

while true; do
  all_healthy=true
  for name in "${SERVICES[@]}"; do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$name" 2>/dev/null || echo "missing")"
    if [ "$status" != "healthy" ]; then
      all_healthy=false
    fi
  done

  if [ "$all_healthy" = true ]; then
    echo "all infra containers healthy after ${elapsed}s"
    exit 0
  fi

  if [ "$elapsed" -ge "$MAX_WAIT_S" ]; then
    echo "timed out after ${MAX_WAIT_S}s waiting for infra to become healthy" >&2
    docker compose ps >&2
    exit 1
  fi

  sleep "$INTERVAL_S"
  elapsed=$((elapsed + INTERVAL_S))
done

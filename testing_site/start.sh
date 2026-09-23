#!/usr/bin/env bash
# Start the ITMS Test Lab. Nothing to install -- the control server is standard
# library only, so this works before the repo's own virtualenv exists (and will
# then tell you that it needs to be created).
#
#   ./start.sh                 # http://127.0.0.1:8420
#   ./start.sh --port 9000     # any flag is passed straight through to server.py
#
# Ctrl+C stops the site and anything it started (api-service, a simulation, a
# gate script). Redis, if it came up as the repo's Docker container, keeps
# running -- `make down` in itms/ stops that.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PY="$candidate"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo "Need Python 3.9 or newer on PATH to run the test lab's control server." >&2
  exit 1
fi

# -u: unbuffered, so the startup banner and any traceback appear immediately
# even when this is piped into a log or run from a launcher.
exec "$PY" -u server.py "$@"

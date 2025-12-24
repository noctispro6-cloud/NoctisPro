#!/usr/bin/env bash
set -euo pipefail

# Wait for Postgres to accept TCP connections.
# Uses python stdlib socket so no extra deps needed.

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_WAIT_SECONDS="${DB_WAIT_SECONDS:-60}"

python - <<'PY'
import os, socket, time, sys

host = os.environ.get("DB_HOST", "db")
port = int(os.environ.get("DB_PORT", "5432"))
timeout = float(os.environ.get("DB_WAIT_SECONDS", "60"))

deadline = time.time() + timeout
last_err = None
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            sys.exit(0)
    except OSError as e:
        last_err = e
        time.sleep(1)

print(f"ERROR: DB not reachable at {host}:{port} after {timeout}s: {last_err}", file=sys.stderr)
sys.exit(1)
PY

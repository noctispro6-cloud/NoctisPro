#!/usr/bin/env bash
set -euo pipefail

# Idempotent Docker deployment (safe for constant updates)
# - Uses Postgres container with a named volume (DB persists across redeploys)
# - Uses a named volume for MEDIA_ROOT (uploads/DICOM persist)
# - Runs Django migrations automatically on web container start

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run with sudo (Docker access + ports)." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not installed." >&2
  exit 2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose plugin not installed." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f ".env" ]]; then
  echo "ERROR: missing .env. Create it from .env.docker.example:" >&2
  echo "  cp .env.docker.example .env" >&2
  exit 2
fi

ensure_secret_key() {
  # Auto-generate SECRET_KEY once, keep it stable for future deploys.
  local current
  current="$(grep -E '^SECRET_KEY=' .env 2>/dev/null | sed -E 's/^SECRET_KEY=//')"

  if [[ -z "${current}" || "${current}" == "CHANGE_ME_TO_A_LONG_RANDOM_VALUE" || "${current}" == "change-me" ]]; then
    echo "Generating SECRET_KEY in .env ..."
    local key
    key="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
    # Replace if present, else append.
    if grep -qE '^SECRET_KEY=' .env; then
      sed -i -E "s/^SECRET_KEY=.*/SECRET_KEY=${key}/" .env
    else
      printf "\nSECRET_KEY=%s\n" "$key" >> .env
    fi
    chmod 600 .env 2>/dev/null || true
  fi
}

ensure_secret_key

# NGROK_AUTHTOKEN must be provided by operator in .env
if ! grep -qE '^NGROK_AUTHTOKEN=.+$' .env || grep -qE '^NGROK_AUTHTOKEN=(PASTE_YOUR_NGROK_AUTHTOKEN)?$' .env; then
  echo "ERROR: Set NGROK_AUTHTOKEN in .env before deploying." >&2
  exit 2
fi

docker compose up -d --build

echo ""
echo "Deploy complete."
echo "Check services:"
echo "  docker compose ps"
echo "ngrok URL:"
echo "  docker compose logs -n 50 ngrok"


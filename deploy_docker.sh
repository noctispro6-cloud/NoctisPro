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

docker compose up -d --build

echo ""
echo "Deploy complete."
echo "Check services:"
echo "  docker compose ps"
echo "ngrok URL:"
echo "  docker compose logs -n 50 ngrok"


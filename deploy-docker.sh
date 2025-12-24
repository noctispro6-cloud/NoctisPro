#!/usr/bin/env bash
set -euo pipefail

err() { echo "[ERROR] $*" >&2; }
info() { echo "[INFO]  $*" >&2; }

usage() {
  cat <<'EOF'
Usage:
  ./deploy-docker.sh
  ./deploy-docker.sh --ngrok

What this does:
- Builds and starts the Noctis Pro stack via docker compose
- Uses named volumes so DB + uploads persist across code updates

Notes:
- DB persistence is in the docker volume "noctis_pgdata"
  Updating code: docker compose up -d --build   (SAFE)
  Destroying DB: docker compose down -v         (DELETES volumes)
EOF
}

want_ngrok=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ngrok) want_ngrok=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "Unknown arg: $1"; usage; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  err "docker not found. Install Docker Engine + Docker Compose plugin first."
  exit 127
fi

if ! docker compose version >/dev/null 2>&1; then
  err "docker compose plugin not found. Install Docker Compose v2 plugin."
  exit 127
fi

if [[ ! -f ".env.docker" ]]; then
  if [[ -f ".env.docker.example" ]]; then
    info "Creating .env.docker from .env.docker.example (please edit secrets/hosts/ngrok)."
    cp .env.docker.example .env.docker
  else
    err "Missing .env.docker and .env.docker.example."
    exit 2
  fi
fi

args=(--env-file .env.docker up -d --build)
if [[ "$want_ngrok" == "1" ]]; then
  args=(--profile ngrok "${args[@]}")
fi

info "Starting containers..."
docker compose "${args[@]}"

info "Running a quick health check (web logs tail)..."
docker compose logs --tail=30 web || true

info "Done."
info "Web:   http://localhost:8000"
info "DICOM: <server-ip>:11112 (AE: NOCTIS_SCP)"
if [[ "$want_ngrok" == "1" ]]; then
  info "Ngrok: check: docker compose logs --tail=200 ngrok"
fi

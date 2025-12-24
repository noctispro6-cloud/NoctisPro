#!/usr/bin/env bash
set -euo pipefail

err() { echo "[ERROR] $*" >&2; }
info() { echo "[INFO]  $*" >&2; }

read_env_kv() {
  # read_env_kv KEY /path/to/env -> prints value or empty
  local key="${1:?}" file="${2:?}" line
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    if [[ "$line" == "${key}="* ]]; then
      printf '%s' "${line#${key}=}"
      return 0
    fi
  done < "$file"
}

stop_systemd_if_running() {
  local unit="${1:?}"
  command -v systemctl >/dev/null 2>&1 || return 0
  systemctl list-unit-files "${unit}" >/dev/null 2>&1 || return 0
  systemctl is-active --quiet "${unit}" >/dev/null 2>&1 || return 0

  info "Stopping systemd unit ${unit} (to avoid port conflicts)..."
  if [[ "${EUID:-$(id -u)}" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    sudo systemctl stop "${unit}" || true
  else
    systemctl stop "${unit}" || true
  fi
}

ensure_port_free() {
  local port="${1:?}"

  # Stop the known host-level DICOM receiver if it is running.
  stop_systemd_if_running "noctis-pro-dicom.service"

  # Stop any docker containers (any stack) that already publish the port.
  local ids
  ids="$(docker ps -q --filter "publish=${port}" 2>/dev/null || true)"
  if [[ -n "$ids" ]]; then
    info "Stopping containers publishing port ${port}..."
    docker stop ${ids} >/dev/null 2>&1 || true
  fi

  # Verify we can bind the port (gives a clear error early).
  python3 - <<PY
import socket, sys
port = int("${port}")
s = socket.socket()
try:
    s.bind(("0.0.0.0", port))
except OSError as e:
    print(f"[ERROR] Host port {port} is still in use: {e}", file=sys.stderr)
    sys.exit(3)
finally:
    try:
        s.close()
    except Exception:
        pass
PY
}

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

dicom_port="$(read_env_kv DICOM_PORT .env.docker)"
dicom_port="${dicom_port:-11112}"

info "Cleaning up old compose resources (safe; volumes persist)..."
docker compose down --remove-orphans >/dev/null 2>&1 || true

info "Ensuring host port ${dicom_port} is available..."
ensure_port_free "${dicom_port}"

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
info "DICOM: <server-ip>:${dicom_port} (AE: NOCTIS_SCP)"
if [[ "$want_ngrok" == "1" ]]; then
  info "Ngrok: check: docker compose logs --tail=200 ngrok"
fi

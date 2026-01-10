#!/usr/bin/env bash
set -euo pipefail

# Clean production deploy script for NoctisPro (Docker Compose)
# - Creates/validates .env.docker for production-safe defaults
# - Starts the stack (db/web/dicom) and optional ngrok profile
#
# Notes:
# - This does NOT configure TLS/reverse-proxy. Put nginx/caddy in front separately.
# - This script intentionally refuses insecure defaults (empty SECRET_KEY, DB_PASSWORD=change-me, DEBUG=True).

err() { echo "[ERROR] $*" >&2; }
info() { echo "[INFO]  $*" >&2; }

as_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

require_cmd() {
  local c="${1:?}"
  command -v "$c" >/dev/null 2>&1 || { err "Missing required command: $c"; exit 127; }
}

random_token() {
  # prints a URL-safe secret
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(50))
PY
}

random_password() {
  # prints a strong password
  python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(32)))
PY
}

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

set_env_kv() {
  # set_env_kv KEY VALUE FILE
  local key="${1:?}" val="${2-}" file="${3:?}"
  if [[ ! -f "$file" ]]; then
    printf '%s=%s\n' "$key" "$val" >"$file"
    return 0
  fi
  if grep -qE "^${key}=" "$file" 2>/dev/null; then
    # Replace in-place (portable-ish: use python, avoids sed -i differences)
    python3 - <<PY
import io
import sys
from pathlib import Path

key = ${key!r}
val = ${val!r}
path = Path(${file!r})
lines = path.read_text(encoding="utf-8").splitlines(True)
out = []
replaced = False
for ln in lines:
    if ln.startswith(key + "=") and not replaced:
        out.append(f"{key}={val}\n")
        replaced = True
    else:
        out.append(ln)
if not replaced:
    out.append(f"{key}={val}\n")
path.write_text("".join(out), encoding="utf-8")
PY
  else
    printf '\n%s=%s\n' "$key" "$val" >>"$file"
  fi
}

port_in_use() {
  local port="${1:?}"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH "sport = :${port}" 2>/dev/null | awk 'NR==1{found=1} END{exit found?0:1}'
    return $?
  fi
  python3 - <<PY >/dev/null 2>&1
import socket
port = int("${port}")
s = socket.socket()
try:
    s.bind(("0.0.0.0", port))
    ok = True
except OSError:
    ok = False
finally:
    try: s.close()
    except Exception: pass
raise SystemExit(0 if (not ok) else 1)
PY
}

ensure_port_free() {
  local port="${1:?}"

  # Stop any docker containers (any stack) that already publish the port.
  local ids
  ids="$(docker ps -q --filter "publish=${port}" 2>/dev/null || true)"
  if [[ -n "$ids" ]]; then
    info "Stopping containers publishing port ${port}..."
    docker stop ${ids} >/dev/null 2>&1 || true
  fi

  # Best-effort kill of any remaining listeners.
  if port_in_use "${port}"; then
    info "Attempting to stop any process listening on port ${port}..."
    if command -v fuser >/dev/null 2>&1; then
      as_root fuser -k -n tcp "${port}" >/dev/null 2>&1 || true
    fi
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
  ./deploy-production.sh --domain example.com [--email admin@example.com] [--web-port 8000] [--dicom-port 11112] [--with-ngrok]

What this does:
  - Ensures a production-safe .env.docker exists (generates secrets if missing)
  - Builds and starts the stack via docker compose (db/web/dicom)
  - Optionally starts the ngrok profile (requires NGROK_AUTHTOKEN in .env.docker)

Important:
  - This script does NOT set up TLS. Put nginx/caddy in front and terminate HTTPS there.
  - Never expose ngrok/public endpoints without proper auth + strong host/CSRF configuration.
EOF
}

domain=""
email=""
web_port=""
dicom_port=""
with_ngrok=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) domain="${2:-}"; shift 2 ;;
    --email) email="${2:-}"; shift 2 ;; # reserved for future (certbots/reverse proxy), not used currently
    --web-port) web_port="${2:-}"; shift 2 ;;
    --dicom-port) dicom_port="${2:-}"; shift 2 ;;
    --with-ngrok) with_ngrok=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "Unknown arg: $1"; usage; exit 2 ;;
  esac
done

[[ -n "$domain" ]] || { err "--domain is required"; usage; exit 2; }

# Ensure we're in repo root (docker-compose.yml present)
[[ -f "docker-compose.yml" ]] || { err "Run this from the NoctisPro repo root (missing docker-compose.yml)"; exit 2; }

require_cmd docker
require_cmd python3
if ! docker compose version >/dev/null 2>&1; then
  err "docker compose plugin not found. Install Docker Compose v2 plugin."
  exit 127
fi

env_file=".env.docker"
if [[ ! -f "$env_file" ]]; then
  if [[ -f ".env.docker.example" ]]; then
    info "Creating ${env_file} from .env.docker.example with secure defaults..."
    cp .env.docker.example "$env_file"
  else
    info "Creating ${env_file} from scratch with secure defaults..."
    : >"$env_file"
  fi
fi

# Normalize/seed production-safe config.
set_env_kv "DEBUG" "False" "$env_file"
set_env_kv "DOMAIN_NAME" "$domain" "$env_file"

current_secret="$(read_env_kv SECRET_KEY "$env_file")"
if [[ -z "${current_secret}" || "${current_secret}" == "change-me" || "${current_secret}" == "changeme" || "${current_secret}" == django-insecure* ]]; then
  info "Generating strong SECRET_KEY..."
  set_env_kv "SECRET_KEY" "$(random_token)" "$env_file"
fi

current_db_pw="$(read_env_kv DB_PASSWORD "$env_file")"
if [[ -z "${current_db_pw}" || "${current_db_pw}" == "change-me" || "${current_db_pw}" == "changeme" ]]; then
  info "Generating strong DB_PASSWORD..."
  set_env_kv "DB_PASSWORD" "$(random_password)" "$env_file"
fi

# Ports (optional overrides)
if [[ -n "$web_port" ]]; then
  set_env_kv "WEB_PORT" "$web_port" "$env_file"
fi
if [[ -n "$dicom_port" ]]; then
  set_env_kv "DICOM_PORT" "$dicom_port" "$env_file"
fi

web_port_final="$(read_env_kv WEB_PORT "$env_file")"
web_port_final="${web_port_final:-8000}"
dicom_port_final="$(read_env_kv DICOM_PORT "$env_file")"
dicom_port_final="${dicom_port_final:-11112}"

# Host / CSRF defaults (production-safe)
# - ALLOWED_HOSTS should include your domain + localhost (useful for ssh port-forwarding)
set_env_kv "ALLOWED_HOSTS" "${domain},localhost,127.0.0.1" "$env_file"

# Prefer HTTPS for production CSRF origin, but keep local HTTP for admin ops.
set_env_kv "CSRF_TRUSTED_ORIGINS" "https://${domain},http://localhost:${web_port_final}" "$env_file"

# Keep media serving disabled by default; serve via authenticated endpoints only.
set_env_kv "SERVE_MEDIA_FILES" "False" "$env_file"

if [[ "$with_ngrok" == "1" ]]; then
  # ngrok must be configured explicitly.
  ngtok="$(read_env_kv NGROK_AUTHTOKEN "$env_file")"
  if [[ -z "$ngtok" ]]; then
    err "NGROK_AUTHTOKEN is required in ${env_file} when using --with-ngrok"
    exit 2
  fi
fi

info "Cleaning up old compose resources (safe; volumes persist)..."
docker compose down --remove-orphans >/dev/null 2>&1 || true

info "Ensuring host port ${web_port_final} is available..."
ensure_port_free "${web_port_final}"
info "Ensuring host port ${dicom_port_final} is available..."
ensure_port_free "${dicom_port_final}"
if [[ "$with_ngrok" == "1" ]]; then
  info "Ensuring host port 4040 is available (ngrok local API)..."
  ensure_port_free "4040"
fi

args=(--env-file "$env_file" up -d --build)
if [[ "$with_ngrok" == "1" ]]; then
  args=(--profile ngrok "${args[@]}")
fi

info "Starting containers..."
docker compose "${args[@]}"

info "Status:"
docker compose ps || true

info "Recent web logs:"
docker compose logs --tail=60 web || true

info "Done."
info "Web:   http://localhost:${web_port_final}"
info "DICOM: <server-ip>:${dicom_port_final} (AE: NOCTIS_SCP)"
if [[ "$with_ngrok" == "1" ]]; then
  info "Ngrok logs: docker compose logs --tail=200 ngrok"
fi


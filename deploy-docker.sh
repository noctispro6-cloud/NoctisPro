#!/usr/bin/env bash
set -euo pipefail

err() { echo "[ERROR] $*" >&2; }
info() { echo "[INFO]  $*" >&2; }

as_root() {
  # Run a command as root (uses sudo if not already root).
  if [[ "${EUID:-$(id -u)}" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

get_ngrok_https_url() {
  # Best-effort: read the public HTTPS URL from the local ngrok API.
  # Returns 0 and prints the URL if available; otherwise returns non-zero.
  python3 - <<'PY'
import json
import sys
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as resp:
        data = json.load(resp)
except Exception:
    sys.exit(1)

for t in (data.get("tunnels") or []):
    u = (t.get("public_url") or "").strip()
    if u.startswith("https://"):
        print(u)
        sys.exit(0)

sys.exit(2)
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
  # set_env_kv KEY VALUE /path/to/env
  # Uses python for portability (avoids sed -i differences).
  local key="${1:?}" val="${2-}" file="${3:?}"
  python3 - <<PY
from pathlib import Path

key = ${key!r}
val = ${val!r}
path = Path(${file!r})

if not path.exists():
    path.write_text(f"{key}={val}\n", encoding="utf-8")
    raise SystemExit(0)

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
    if out and not out[-1].endswith("\n"):
        out[-1] = out[-1] + "\n"
    out.append(f"{key}={val}\n")
path.write_text("".join(out), encoding="utf-8")
PY
}

gen_secret_key() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(50))
PY
}

gen_password() {
  python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(32)))
PY
}

stop_systemd_if_running() {
  local unit="${1:?}"
  command -v systemctl >/dev/null 2>&1 || return 0
  systemctl list-unit-files "${unit}" >/dev/null 2>&1 || return 0
  systemctl is-active --quiet "${unit}" >/dev/null 2>&1 || return 0

  info "Stopping systemd unit ${unit} (to avoid port conflicts)..."
  as_root systemctl stop "${unit}" || true
}

port_in_use() {
  local port="${1:?}"
  if command -v ss >/dev/null 2>&1; then
    # -H: no header; returns output if a listener exists.
    ss -ltnH "sport = :${port}" 2>/dev/null | awk 'NR==1{found=1} END{exit found?0:1}'
    return $?
  fi
  # Fallback: attempt bind test (slow but reliable).
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

describe_port_owner() {
  local port="${1:?}"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :${port}" 2>/dev/null || true
  else
    return 0
  fi
}

kill_port_listeners() {
  local port="${1:?}"

  # Best-effort kill of any remaining listeners.
  if command -v fuser >/dev/null 2>&1; then
    info "Attempting to stop any process listening on port ${port}..."
    as_root fuser -k -n tcp "${port}" >/dev/null 2>&1 || true
  fi

  # If still in use and ss is available, show owner to help debugging.
  if port_in_use "${port}"; then
    info "Port ${port} is still in use; current listener(s):"
    describe_port_owner "${port}" >&2 || true
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

  # If any other host process is holding the port, try to stop it.
  if port_in_use "${port}"; then
    kill_port_listeners "${port}"
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
  ./deploy-docker.sh --production
  ./deploy-docker.sh --production --ngrok

What this does:
- Builds and starts the Noctis Pro stack via docker compose
- Uses named volumes so DB + uploads persist across code updates

Notes:
- DB persistence is in the docker volume "noctis_pgdata"
  Updating code: docker compose up -d --build   (SAFE)
  Destroying DB: docker compose down -v         (DELETES volumes)

Production notes:
- If DEBUG=False, SECRET_KEY must be set to a strong value.
- If DB_PASSWORD is left as "change-me", Postgres is insecure.
- Use --production to auto-generate missing secrets into .env.docker.
EOF
}

want_ngrok=0
want_production=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ngrok) want_ngrok=1; shift ;;
    --production|--prod) want_production=1; shift ;;
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

#
# Production-safe env validation / initialization
#
debug_val="$(read_env_kv DEBUG .env.docker)"
secret_key_val="$(read_env_kv SECRET_KEY .env.docker)"
db_pw_val="$(read_env_kv DB_PASSWORD .env.docker)"

debug_is_true=0
if [[ "${debug_val:-False}" =~ ^([Tt][Rr][Uu][Ee]|1|yes|on)$ ]]; then
  debug_is_true=1
fi

secret_is_bad=0
if [[ -z "${secret_key_val}" ]]; then
  secret_is_bad=1
elif [[ "${secret_key_val,,}" == "change-me" || "${secret_key_val,,}" == "changeme" ]]; then
  secret_is_bad=1
elif [[ "${secret_key_val}" == django-insecure* ]]; then
  secret_is_bad=1
fi

db_pw_is_bad=0
if [[ -z "${db_pw_val}" ]]; then
  db_pw_is_bad=1
elif [[ "${db_pw_val,,}" == "change-me" || "${db_pw_val,,}" == "changeme" ]]; then
  db_pw_is_bad=1
fi

if [[ "$want_production" == "1" ]]; then
  # Force DEBUG=False for production deployments.
  set_env_kv DEBUG False .env.docker
  debug_is_true=0

  if [[ "$secret_is_bad" == "1" ]]; then
    info "Generating strong SECRET_KEY into .env.docker (production mode)..."
    set_env_kv SECRET_KEY "$(gen_secret_key)" .env.docker
    secret_is_bad=0
  fi

  if [[ "$db_pw_is_bad" == "1" ]]; then
    info "Generating strong DB_PASSWORD into .env.docker (production mode)..."
    set_env_kv DB_PASSWORD "$(gen_password)" .env.docker
    db_pw_is_bad=0
  fi
fi

# Refuse unsafe production config (common cause of "connection refused" behind ngrok).
if [[ "$debug_is_true" == "0" && "$secret_is_bad" == "1" ]]; then
  err "DEBUG=False but SECRET_KEY is missing/weak in .env.docker."
  err "Fix: set SECRET_KEY to a strong value, or run: ./deploy-docker.sh --production"
  exit 2
fi

if [[ "$want_production" == "1" && "$db_pw_is_bad" == "1" ]]; then
  err "DB_PASSWORD is missing/weak in .env.docker (production mode)."
  err "Fix: set DB_PASSWORD, or re-run: ./deploy-docker.sh --production"
  exit 2
fi

dicom_port="$(read_env_kv DICOM_PORT .env.docker)"
dicom_port="${dicom_port:-11112}"

web_port="$(read_env_kv WEB_PORT .env.docker)"
web_port="${web_port:-8000}"

info "Cleaning up old compose resources (safe; volumes persist)..."
docker compose down --remove-orphans >/dev/null 2>&1 || true

info "Ensuring host port ${web_port} is available..."
# Stop the known host-level web service if it is running (to avoid port conflicts).
stop_systemd_if_running "noctis-pro.service"
ensure_port_free "${web_port}"

info "Ensuring host port ${dicom_port} is available..."
ensure_port_free "${dicom_port}"

if [[ "$want_ngrok" == "1" ]]; then
  info "Ensuring host port 4040 is available (ngrok local API)..."
  ensure_port_free "4040"
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
info "Web:   http://localhost:${web_port}"
info "DICOM: <server-ip>:${dicom_port} (AE: NOCTIS_SCP)"
if [[ "$want_ngrok" == "1" ]]; then
  # ngrok allocates the public URL asynchronously; poll the local API briefly.
  ngrok_url=""
  for _ in $(seq 1 60); do
    ngrok_url="$(get_ngrok_https_url 2>/dev/null || true)"
    if [[ -n "$ngrok_url" ]]; then
      break
    fi
    sleep 0.5
  done

  if [[ -n "$ngrok_url" ]]; then
    printf '%s' "$ngrok_url" > .tunnel-url 2>/dev/null || true
    info "Ngrok: ${ngrok_url}"
    info "Ngrok API: http://localhost:4040"
  else
    info "Ngrok: (starting) check: docker compose logs --tail=200 ngrok"
    info "Ngrok API: http://localhost:4040 (should show the public URL once ready)"
  fi
fi

#!/usr/bin/env bash
set -euo pipefail

# Quick ngrok Tunnel launcher (auto-config)
#
# - Installs ngrok if missing
# - (Optionally) configures authtoken from NGROK_AUTHTOKEN
# - Starts an HTTPS tunnel to a local port (default: 8000)
# - Writes the public URL to a file (default: /workspace/.tunnel-url)
#
# Usage:
#   NGROK_AUTHTOKEN=... ./scripts/quick-ngrok.sh
#   NGROK_AUTHTOKEN=... NGROK_DOMAIN=your-reserved-domain.ngrok.app ./scripts/quick-ngrok.sh
#   ./scripts/quick-ngrok.sh --addr 8000 --write /workspace/.tunnel-url
#   ./scripts/quick-ngrok.sh --url http://localhost:8000
#
# Notes:
# - By default this runs ngrok in the background (daemon) and exits once the HTTPS
#   URL is detected and written. Use --foreground if you want it to stay attached.

TARGET_URL="http://localhost:8000"
ADDR="8000"
URL_FILE="/workspace/.tunnel-url"
LOG_OUT="/tmp/ngrok.out"
WEB_ADDR="127.0.0.1:4040"
ENV_FILE="/workspace/.ngrok.env"
PID_FILE=""
FOREGROUND=0
NON_INTERACTIVE=0
REUSE_EXISTING=1
STOP_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      TARGET_URL="${2:-}"
      shift 2
      ;;
    --addr)
      ADDR="${2:-}"
      shift 2
      ;;
    --write|--out|--file)
      URL_FILE="${2:-}"
      shift 2
      ;;
    --web-addr)
      WEB_ADDR="${2:-}"
      shift 2
      ;;
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --daemon)
      FOREGROUND=0
      shift
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      shift
      ;;
    --no-reuse)
      REUSE_EXISTING=0
      shift
      ;;
    --stop)
      STOP_ONLY=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--url http://localhost:8000] [--addr 8000] [--write /path/to/url-file] [--web-addr 127.0.0.1:4040] [--foreground|--daemon] [--non-interactive] [--no-reuse] [--stop]" >&2
      exit 2
      ;;
  esac
done

# Auto-detect non-interactive mode if not a TTY
if [[ "${NON_INTERACTIVE}" != "1" ]]; then
  if [[ ! -t 0 || ! -t 1 ]]; then
    NON_INTERACTIVE=1
  fi
fi

# Derive ADDR from --url if provided (best-effort)
if [[ -n "${TARGET_URL}" ]]; then
  # shellcheck disable=SC2001
  _maybe_port="$(echo "${TARGET_URL}" | sed -nE 's#^https?://[^:/]+:([0-9]+).*$#\1#p')"
  if [[ -n "${_maybe_port}" ]]; then
    ADDR="${_maybe_port}"
  fi
fi

mkdir -p "$(dirname "${URL_FILE}")"
PID_FILE="${URL_FILE}.pid"

load_saved_env() {
  if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}" || true
  fi
}

prompt_for_config_if_missing() {
  # In non-interactive contexts we never prompt.
  if [[ "${NON_INTERACTIVE}" == "1" ]]; then
    # If a reserved domain is requested, an authtoken is required.
    if [[ -n "${NGROK_DOMAIN:-}" && -z "${NGROK_AUTHTOKEN:-}" ]]; then
      echo "[ERROR] NGROK_DOMAIN is set but NGROK_AUTHTOKEN is missing." >&2
      echo "[HINT] Export NGROK_AUTHTOKEN (or unset NGROK_DOMAIN to get a random HTTPS URL)." >&2
      exit 2
    fi
    return 0
  fi

  # Interactive prompts (TTY only): token optional unless using a reserved domain.
  if [[ -z "${NGROK_DOMAIN:-}" ]]; then
    echo "Enter your reserved domain (optional; press Enter to skip):"
    read -r NGROK_DOMAIN
  fi
  if [[ -n "${NGROK_DOMAIN:-}" && -z "${NGROK_AUTHTOKEN:-}" ]]; then
    echo "Enter your ngrok authtoken (required for reserved domains; will not echo), then press Enter:"
    read -r -s NGROK_AUTHTOKEN
    echo ""
  fi

  # Offer to save for next time (only if we actually have something worth saving).
  if [[ -n "${NGROK_AUTHTOKEN:-}" || -n "${NGROK_DOMAIN:-}" ]]; then
    echo "Save these settings to ${ENV_FILE} so you don't retype? (y/N)"
    read -r _save
    case "${_save,,}" in
      y|yes)
        umask 077
        {
          if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
            echo "NGROK_AUTHTOKEN=${NGROK_AUTHTOKEN}"
          fi
          if [[ -n "${NGROK_DOMAIN:-}" ]]; then
            echo "NGROK_DOMAIN=${NGROK_DOMAIN}"
          fi
        } > "${ENV_FILE}"
        echo "[INFO] Saved."
        ;;
      *) ;;
    esac
  fi
}

install_ngrok() {
  if command -v ngrok >/dev/null 2>&1; then
    return 0
  fi

  echo "[INFO] ngrok not found; installing..." >&2

  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *)
      echo "[ERROR] Unsupported architecture for ngrok: $arch" >&2
      return 1
      ;;
  esac

  local url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${arch}.tgz"
  curl -fsSL "$url" -o /tmp/ngrok.tgz
  tar -xzf /tmp/ngrok.tgz -C /tmp

  if [[ -w "/usr/local/bin" ]]; then
    install -m 0755 /tmp/ngrok /usr/local/bin/ngrok
  else
    mkdir -p "${HOME}/.local/bin"
    install -m 0755 /tmp/ngrok "${HOME}/.local/bin/ngrok"
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
}

extract_url() {
  # Prefer the local API (stable) over log scraping.
  curl -fsS "http://${WEB_ADDR}/api/tunnels" 2>/dev/null | python3 - <<'PY'
import json,sys
try:
    data=json.load(sys.stdin)
except Exception:
    sys.exit(0)
for t in data.get('tunnels', []) or []:
    url=(t.get('public_url') or '').strip()
    if url.startswith('https://'):
        print(url)
        break
PY
}

load_saved_env
prompt_for_config_if_missing
install_ngrok

stop_ngrok() {
  # Stop a previously started instance (best-effort).
  if [[ -n "${PID_FILE}" && -f "${PID_FILE}" ]]; then
    local _pid=""
    _pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${_pid}" ]] && kill -0 "${_pid}" 2>/dev/null; then
      kill "${_pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}" || true
  fi
  if pgrep -x ngrok >/dev/null 2>&1; then
    pkill -x ngrok || true
  fi
}

if [[ "${STOP_ONLY}" == "1" ]]; then
  stop_ngrok
  rm -f "${URL_FILE}" 2>/dev/null || true
  echo "[DONE] ngrok stopped."
  exit 0
fi

# If an ngrok agent already exists, try to reuse it (fast path).
if [[ "${REUSE_EXISTING}" == "1" ]] && pgrep -x ngrok >/dev/null 2>&1; then
  URL="$(extract_url || true)"
  if [[ -n "${URL}" ]]; then
    echo -n "${URL}" >"${URL_FILE}"
    echo "Tunnel URL: ${URL}"
    exit 0
  fi
fi

# Configure token automatically if provided
if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  ngrok config add-authtoken "${NGROK_AUTHTOKEN}" >/dev/null 2>&1 || true
fi

: >"${LOG_OUT}"

# Start an HTTPS tunnel to the local port.
# If you have a reserved domain, set NGROK_DOMAIN=yourdomain.ngrok.app
DOMAIN_ARGS=()
if [[ -n "${NGROK_DOMAIN:-}" ]]; then
  DOMAIN_ARGS=(--domain "${NGROK_DOMAIN}")
fi

# Best-effort: avoid ERR_NGROK_108 (multiple agent sessions) by stopping strays.
stop_ngrok

nohup ngrok http "${ADDR}" \
  "${DOMAIN_ARGS[@]}" \
  --web-addr "${WEB_ADDR}" \
  >"${LOG_OUT}" 2>&1 &

PID=$!
echo -n "${PID}" > "${PID_FILE}"

# Wait for URL to appear (up to ~30s)
URL=""
for _ in $(seq 1 60); do
  URL="$(extract_url || true)"
  if [[ -n "${URL}" ]]; then
    echo -n "${URL}" >"${URL_FILE}"
    echo "Tunnel URL: ${URL}"
    break
  fi
  sleep 0.5
done

# If we never got a URL, fail fast with a helpful hint.
if [[ -z "${URL}" ]]; then
  echo "[ERROR] ngrok tunnel URL not detected." >&2
  echo "[HINT] Check logs: ${LOG_OUT}" >&2
  echo "[HINT] Common causes: port ${ADDR} not listening, wrong NGROK_DOMAIN (not reserved), invalid token, or another ngrok already running." >&2
  kill "${PID}" 2>/dev/null || true
  rm -f "${PID_FILE}" 2>/dev/null || true
  exit 1
fi

# Foreground mode: stay attached to the ngrok process.
if [[ "${FOREGROUND}" == "1" ]]; then
  wait "${PID}" || true
fi

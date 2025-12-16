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

TARGET_URL="http://localhost:8000"
ADDR="8000"
URL_FILE="/workspace/.tunnel-url"
LOG_OUT="/tmp/ngrok.out"
WEB_ADDR="127.0.0.1:4040"

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
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--url http://localhost:8000] [--addr 8000] [--write /path/to/url-file] [--web-addr 127.0.0.1:4040]" >&2
      exit 2
      ;;
  esac
done

# Derive ADDR from --url if provided (best-effort)
if [[ -n "${TARGET_URL}" ]]; then
  # shellcheck disable=SC2001
  _maybe_port="$(echo "${TARGET_URL}" | sed -nE 's#^https?://[^:/]+:([0-9]+).*$#\1#p')"
  if [[ -n "${_maybe_port}" ]]; then
    ADDR="${_maybe_port}"
  fi
fi

mkdir -p "$(dirname "${URL_FILE}")"

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

install_ngrok

# Best-effort: avoid ERR_NGROK_108 (multiple agent sessions)
if pgrep -x ngrok >/dev/null 2>&1; then
  pkill -x ngrok || true
fi

# Configure token automatically if provided
if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  ngrok config add-authtoken "${NGROK_AUTHTOKEN}" >/dev/null 2>&1 || true
fi

# Start and keep the tunnel alive
while true; do
  : >"${LOG_OUT}"

  # Start an HTTPS tunnel to the local port
  # If you have a reserved domain, set NGROK_DOMAIN=yourdomain.ngrok.app
  DOMAIN_ARGS=()
  if [[ -n "${NGROK_DOMAIN:-}" ]]; then
    DOMAIN_ARGS=(--domain "${NGROK_DOMAIN}")
  fi

  nohup ngrok http "${ADDR}" \
    "${DOMAIN_ARGS[@]}" \
    --web-addr "${WEB_ADDR}" \
    >"${LOG_OUT}" 2>&1 &

  PID=$!

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
    if [[ -z "${NGROK_AUTHTOKEN:-}" ]]; then
      echo "[HINT] Set NGROK_AUTHTOKEN to let this script auto-configure ngrok." >&2
    else
      echo "[HINT] Check logs: ${LOG_OUT}" >&2
    fi
    kill "${PID}" 2>/dev/null || true
    exit 1
  fi

  # If process exits, restart after brief delay
  wait "${PID}" || true
  sleep 2

done

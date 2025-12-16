#!/usr/bin/env bash
set -euo pipefail

# Quick HTTPS tunnel launcher (emergency-friendly).
#
# This script prefers ngrok if you provide NGROK_DOMAIN/NGROK_AUTHTOKEN, but it
# will fall back to Cloudflare Quick Tunnel (random https://xxxx.trycloudflare.com)
# if you don’t have ngrok credentials available.
#
# It writes the detected public URL into a file (default: /workspace/.tunnel-url)
# so Django can auto-detect it (see `noctis_pro/settings.py`).
#
# Usage:
#   ./scripts/quick-tunnel.sh
#   ./scripts/quick-tunnel.sh --addr 8000 --write /workspace/.tunnel-url
#   NGROK_AUTHTOKEN=... NGROK_DOMAIN=reserved.ngrok.app ./scripts/quick-tunnel.sh

ADDR="8000"
URL_FILE="/workspace/.tunnel-url"
LOG_OUT="/tmp/cloudflared.out"
PID_FILE=""
NON_INTERACTIVE=0
STOP_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --addr)
      ADDR="${2:-}"
      shift 2
      ;;
    --write|--out|--file)
      URL_FILE="${2:-}"
      shift 2
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      shift
      ;;
    --stop)
      STOP_ONLY=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--addr 8000] [--write /path/to/url-file] [--non-interactive] [--stop]" >&2
      exit 2
      ;;
  esac
done

if [[ "${NON_INTERACTIVE}" != "1" ]]; then
  if [[ ! -t 0 || ! -t 1 ]]; then
    NON_INTERACTIVE=1
  fi
fi

mkdir -p "$(dirname "${URL_FILE}")"
PID_FILE="${URL_FILE}.pid"

stop_cloudflared() {
  if [[ -f "${PID_FILE}" ]]; then
    local _pid=""
    _pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${_pid}" ]] && kill -0 "${_pid}" 2>/dev/null; then
      kill "${_pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}" || true
  fi
  if pgrep -x cloudflared >/dev/null 2>&1; then
    pkill -x cloudflared || true
  fi
}

extract_cloudflare_url() {
  # cloudflared logs contain a random trycloudflare URL; parse it (best-effort).
  if [[ ! -f "${LOG_OUT}" ]]; then
    return 0
  fi
  sed -nE 's/.*(https:\/\/[A-Za-z0-9.-]+\.trycloudflare\.com).*/\1/p' "${LOG_OUT}" | tail -n 1 || true
}

install_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    return 0
  fi

  echo "[INFO] cloudflared not found; installing..." >&2
  local arch platform url
  arch="$(uname -m)"
  platform="linux-amd64"
  case "${arch}" in
    x86_64|amd64) platform="linux-amd64" ;;
    aarch64|arm64) platform="linux-arm64" ;;
    *)
      echo "[ERROR] Unsupported architecture for cloudflared: ${arch}" >&2
      return 1
      ;;
  esac

  # Prefer a user-space install if we can't write to /usr/local/bin
  url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-${platform}"
  curl -fsSL "${url}" -o /tmp/cloudflared
  chmod +x /tmp/cloudflared
  if [[ -w "/usr/local/bin" ]]; then
    install -m 0755 /tmp/cloudflared /usr/local/bin/cloudflared
  else
    mkdir -p "${HOME}/.local/bin"
    install -m 0755 /tmp/cloudflared "${HOME}/.local/bin/cloudflared"
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
}

if [[ "${STOP_ONLY}" == "1" ]]; then
  stop_cloudflared
  rm -f "${URL_FILE}" 2>/dev/null || true
  echo "[DONE] tunnel stopped."
  exit 0
fi

# If ngrok is configured, prefer it.
if [[ -n "${NGROK_DOMAIN:-}" || -n "${NGROK_AUTHTOKEN:-}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  exec "${SCRIPT_DIR}/quick-ngrok.sh" --addr "${ADDR}" --write "${URL_FILE}" --non-interactive
fi

# Otherwise, Cloudflare Quick Tunnel (no token required).
install_cloudflared
stop_cloudflared

: >"${LOG_OUT}"

nohup cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${ADDR}" >"${LOG_OUT}" 2>&1 &
PID=$!
echo -n "${PID}" > "${PID_FILE}"

URL=""
for _ in $(seq 1 120); do
  URL="$(extract_cloudflare_url || true)"
  if [[ -n "${URL}" ]]; then
    echo -n "${URL}" > "${URL_FILE}"
    echo "Tunnel URL: ${URL}"
    exit 0
  fi
  sleep 0.5
done

echo "[ERROR] Cloudflare tunnel URL not detected." >&2
echo "[HINT] Check logs: ${LOG_OUT}" >&2
echo "[HINT] Common causes: port ${ADDR} not listening, outbound network blocked, or cloudflared failed to start." >&2
exit 1


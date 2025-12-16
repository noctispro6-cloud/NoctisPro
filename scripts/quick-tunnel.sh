#!/usr/bin/env bash
set -euo pipefail

# Quick Cloudflare Tunnel launcher (no account/domain required)
#
# - Publishes a public HTTPS URL like: https://xxxx.trycloudflare.com
# - Keeps the tunnel running and restarts it if it dies
# - Writes the latest URL to a file (default: /workspace/.tunnel-url)
#
# Usage:
#   ./scripts/quick-tunnel.sh
#   ./scripts/quick-tunnel.sh --url http://localhost:8000 --write /workspace/.tunnel-url

TARGET_URL="http://localhost:8000"
URL_FILE="/workspace/.tunnel-url"
LOG_OUT="/tmp/cloudflared.out"
LOG_FILE="/tmp/cloudflared.log"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      TARGET_URL="${2:-}"
      shift 2
      ;;
    --write|--out|--file)
      URL_FILE="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--url http://localhost:8000] [--write /path/to/url-file]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$(dirname "$URL_FILE")"

install_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    return 0
  fi

  echo "[INFO] cloudflared not found; installing..." >&2
  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    armv7l|armv7) arch="arm" ;;
    *)
      echo "[ERROR] Unsupported architecture for cloudflared: $arch" >&2
      return 1
      ;;
  esac

  local url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}"
  local dest=""

  # Prefer installing to /usr/local/bin if writable (common on servers)
  if [[ -w "/usr/local/bin" ]]; then
    dest="/usr/local/bin/cloudflared"
    curl -fsSL "$url" -o "$dest"
    chmod +x "$dest"
    return 0
  fi

  # Fallback: user-local install
  mkdir -p "${HOME}/.local/bin"
  dest="${HOME}/.local/bin/cloudflared"
  curl -fsSL "$url" -o "$dest"
  chmod +x "$dest"
  export PATH="${HOME}/.local/bin:${PATH}"
}

extract_url() {
  # Try to extract the tunnel URL from either stdout log or logfile
  grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_OUT" "$LOG_FILE" 2>/dev/null | head -n1 || true
}

install_cloudflared

# Kill any existing cloudflared tunnel from previous runs (best-effort)
pkill -f "cloudflared tunnel" 2>/dev/null || true

while true; do
  : > "$LOG_OUT"
  : > "$LOG_FILE"

  nohup cloudflared tunnel \
    --url "$TARGET_URL" \
    --no-autoupdate \
    --loglevel info \
    --logfile "$LOG_FILE" \
    > "$LOG_OUT" 2>&1 &
  PID=$!

  # Wait for URL to appear (up to ~30s)
  for _ in $(seq 1 60); do
    URL="$(extract_url)"
    if [[ -n "${URL}" ]]; then
      echo -n "$URL" > "$URL_FILE"
      echo "Tunnel URL: $URL"
      break
    fi
    sleep 0.5
  done

  # If process exits, restart after brief delay
  wait "$PID" || true
  sleep 2
done


#!/usr/bin/env bash
set -euo pipefail

# Configure a single ngrok agent with multiple tunnels to avoid ERR_NGROK_108.
# This script is additive and does NOT modify existing deployment scripts.
#
# Usage (as root or with sudo):
#   ./scripts/configure_ngrok_multi.sh <NGROK_AUTHTOKEN> [config_path]
#
# Example:
#   sudo ./scripts/configure_ngrok_multi.sh YOUR_AUTHTOKEN /etc/ngrok.yml

AUTHTOKEN="${1:-}"
CONF_PATH="${2:-/etc/ngrok.yml}"

if [[ -z "${AUTHTOKEN}" ]]; then
  echo "ERROR: ngrok authtoken is required" >&2
  exit 1
fi

TMP_DIR="$(dirname "${CONF_PATH}")"
mkdir -p "${TMP_DIR}"

cat > "${CONF_PATH}" <<YAML
version: 2
authtoken: ${AUTHTOKEN}
tunnels:
  noctis-web:
    addr: 8000
    proto: http
    schemes:
      - https
  # Uncomment the below if you have a paid ngrok plan supporting tcp
  # noctis-dicom:
  #   addr: 11112
  #   proto: tcp
YAML

chmod 600 "${CONF_PATH}"

echo "[INFO] ngrok multi-tunnel config written to ${CONF_PATH}"
echo "[INFO] You can start tunnels with: ngrok start --all --config ${CONF_PATH}"
echo "[INFO] If using systemd, set ExecStart=/usr/local/bin/ngrok start --all --config ${CONF_PATH}"

# Optional: gracefully terminate stray ngrok agents to prevent ERR_NGROK_108
if pgrep -x ngrok >/dev/null 2>&1; then
  echo "[INFO] Stopping existing ngrok agent sessions to avoid multiple-session limit..."
  pkill -x ngrok || true
fi

echo "[DONE] Configure ngrok multi-tunnel completed."


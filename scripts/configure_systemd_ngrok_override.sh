#!/usr/bin/env bash
set -euo pipefail

# One-time systemd override for noctispro-ngrok.service to use a single ngrok
# agent with multiple tunnels. This is additive and doesn't modify existing
# deployment scripts or units; it writes a drop-in override.
#
# Prerequisites:
#   - /etc/ngrok.yml prepared (e.g., via scripts/configure_ngrok_multi.sh)
#   - ngrok binary installed and accessible at /usr/local/bin/ngrok (adjust if needed)
#
# Usage (as root or with sudo):
#   ./scripts/configure_systemd_ngrok_override.sh [/etc/ngrok.yml]

CONF_PATH="${1:-/etc/ngrok.yml}"

if [[ ! -f "${CONF_PATH}" ]]; then
  echo "ERROR: ngrok config not found at ${CONF_PATH}. Run configure_ngrok_multi.sh first." >&2
  exit 1
fi

UNIT_NAME="noctispro-ngrok.service"
DROPIN_DIR="/etc/systemd/system/${UNIT_NAME}.d"
mkdir -p "${DROPIN_DIR}"

cat >"${DROPIN_DIR}/override.conf" <<OVR
[Service]
ExecStart=
ExecStart=/usr/local/bin/ngrok start --all --config ${CONF_PATH}
OVR

chmod 644 "${DROPIN_DIR}/override.conf"

echo "[INFO] Drop-in written: ${DROPIN_DIR}/override.conf"
echo "[INFO] Reloading systemd and restarting ${UNIT_NAME}..."
systemctl daemon-reload

# Stop any stray agents to avoid ERR_NGROK_108 session limit
if pgrep -x ngrok >/dev/null 2>&1; then
  echo "[INFO] Stopping existing ngrok processes..."
  pkill -x ngrok || true
fi

systemctl restart "${UNIT_NAME}"
systemctl status "${UNIT_NAME}" --no-pager || true
echo "[DONE] ${UNIT_NAME} now uses: ngrok start --all --config ${CONF_PATH}"


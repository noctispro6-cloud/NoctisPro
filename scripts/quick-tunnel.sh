#!/usr/bin/env bash
set -euo pipefail

# SUSPENDED: Non-ngrok tunneling is disabled for this project deployment.
# Use ngrok instead:
#   NGROK_AUTHTOKEN="..." NGROK_DOMAIN="your-reserved-domain.ngrok.app" ./scripts/quick-ngrok.sh
# Or for full server deploy:
#   NGROK_AUTHTOKEN="..." NGROK_DOMAIN="your-reserved-domain.ngrok.app" sudo bash scripts/contabo_ubuntu2404_deploy.sh --fresh

echo "[ERROR] quick-tunnel.sh is suspended (Cloudflare Tunnel disabled)." >&2
echo "[HINT] Use: ./scripts/quick-ngrok.sh" >&2
exit 2


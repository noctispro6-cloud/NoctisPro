#!/usr/bin/env bash

set -euo pipefail

# Quick Cloudflare Tunnel launcher (no account/domain required)
# - Keeps a trycloudflare.com tunnel running
# - Writes the latest URL to /workspace/.tunnel-url

LOG_OUT="/tmp/cloudflared.out"
LOG_FILE="/tmp/cloudflared.log"
URL_FILE="/workspace/.tunnel-url"

mkdir -p /workspace

extract_url() {
	# Try to extract the tunnel URL from either stdout log or logfile
	grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_OUT" "$LOG_FILE" 2>/dev/null | head -n1 || true
}

# Kill any existing cloudflared from previous runs
pkill -f "/usr/local/bin/cloudflared tunnel" 2>/dev/null || true

while true; do
	: > "$LOG_OUT"
	: > "$LOG_FILE"

	nohup /usr/local/bin/cloudflared tunnel \
	  --url http://localhost:8000 \
	  --no-autoupdate \
	  --loglevel info \
	  --logfile "$LOG_FILE" \
	  > "$LOG_OUT" 2>&1 &
	PID=$!

	# Wait for URL to appear (up to ~30s)
	for _ in $(seq 1 60); do
		URL=$(extract_url)
		if [[ -n "${URL}" ]]; then
			echo -n "$URL" > "$URL_FILE"
			echo "Tunnel URL: $URL"
			break
		fi
		sleep 0.5
	done

	# If process exits, restart after brief delay
	wait $PID || true
	sleep 2
done


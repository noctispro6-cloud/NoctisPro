#!/bin/sh
set -eu

# NOTE:
# - Docker Compose env files treat quotes as literal characters; sanitize here.
# - We run inside the ngrok container; 'web' is the compose service name.

token="${NGROK_AUTHTOKEN:-}"
token="${token#\"}"; token="${token%\"}"; token="${token#\'}"; token="${token%\'}"
token="$(printf "%s" "$token" | tr -d "\r" | xargs || true)"

if [ -z "$token" ]; then
  echo "ERROR: NGROK_AUTHTOKEN is required (set it in .env.docker)" >&2
  exit 2
fi
export NGROK_AUTHTOKEN="$token"

domain="${NGROK_DOMAIN:-}"
domain="${domain#\"}"; domain="${domain%\"}"; domain="${domain#\'}"; domain="${domain%\'}"
domain="$(printf "%s" "$domain" | tr -d "\r" | xargs || true)"

if [ -n "$domain" ]; then
  # Accept either a bare hostname (reserved.ngrok.app) or a pasted URL (https://reserved.ngrok.app).
  domain="${domain#http://}"; domain="${domain#https://}"
  domain="${domain%%/*}"; domain="${domain%.}"
  # Ensure the local API listens on all interfaces so Docker port publishing works.
  exec ngrok http web:8000 --web-addr=0.0.0.0:4040 --domain="$domain"
fi

# Ensure the local API listens on all interfaces so Docker port publishing works.
exec ngrok http web:8000 --web-addr=0.0.0.0:4040

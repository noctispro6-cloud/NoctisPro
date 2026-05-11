#!/usr/bin/env bash
# Set up TLS certificates for NoctisPro with Cloudflare Origin Certificate.
# Run this AFTER creating the origin certificate in the Cloudflare dashboard.
#
# Usage:
#   bash scripts/setup-tls.sh <domain>
#   e.g. bash scripts/setup-tls.sh pacs.yourdomain.com
#
# You will be prompted to paste the certificate and key from Cloudflare.
set -euo pipefail

DOMAIN="${1:-}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"

[ -n "$DOMAIN" ] || { echo "Usage: $0 <domain>"; exit 1; }
[ "$(id -u)" = "0" ] || { echo "Run as root: sudo bash $0 $DOMAIN"; exit 1; }

CERT_DIR="$APP_DIR/nginx/letsencrypt/live/$DOMAIN"
mkdir -p "$CERT_DIR"

echo ""
echo "=== Cloudflare Origin Certificate setup for $DOMAIN ==="
echo ""
echo "Go to: Cloudflare Dashboard → your domain → SSL/TLS → Origin Server"
echo "Click 'Create Certificate', keep defaults (15 years), click Next."
echo ""

# fullchain.pem
echo "Paste the ORIGIN CERTIFICATE (starts with -----BEGIN CERTIFICATE-----)."
echo "Press Enter then Ctrl+D when done:"
cat > "$CERT_DIR/fullchain.pem"
echo ""

# privkey.pem
echo "Paste the PRIVATE KEY (starts with -----BEGIN PRIVATE KEY-----)."
echo "Press Enter then Ctrl+D when done:"
cat > "$CERT_DIR/privkey.pem"
echo ""

chmod 600 "$CERT_DIR/privkey.pem"
chmod 644 "$CERT_DIR/fullchain.pem"

echo "Certificates written to $CERT_DIR"
echo ""
echo "Next: set SSL/TLS mode in Cloudflare to 'Full (strict)'"
echo "      then start the stack: sudo systemctl start noctispro"

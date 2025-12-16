#!/usr/bin/env bash
set -euo pipefail

# One-shot deploy for Contabo Ubuntu 24.04
# - Installs OS deps
# - Clones repo into /opt/noctispro
# - Creates venv and installs Python deps
# - Writes env file (/etc/noctispro/noctispro.env)
# - Migrates DB + collectstatic
# - Configures systemd (web + dicom receiver)
# - Configures nginx + Let's Encrypt for the domain
# - Opens firewall ports (22/80/443/11112)
#
# Usage:
#   sudo bash scripts/contabo_ubuntu2404_deploy.sh noctis-pro.com admin@noctis-pro.com
#   sudo bash scripts/contabo_ubuntu2404_deploy.sh noctis-pro.com admin@noctis-pro.com --fresh
#   sudo bash scripts/contabo_ubuntu2404_deploy.sh --fresh
#   sudo bash scripts/contabo_ubuntu2404_deploy.sh --domain noctis-pro.com --email admin@noctis-pro.com --fresh

DOMAIN=""
LE_EMAIL=""
FRESH_INSTALL=0
USE_NGROK=0
# Track whether values were explicitly provided (vs defaults/prompts).
DOMAIN_PROVIDED=0
EMAIL_PROVIDED=0
# These can be provided via flags or environment variables:
#   NGROK_AUTHTOKEN="..." NGROK_DOMAIN="noctis-pro.com.ngrok.app" sudo bash scripts/contabo_ubuntu2404_deploy.sh --ngrok --fresh
NGROK_AUTHTOKEN="${NGROK_AUTHTOKEN:-}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"
NGROK_DOMAIN_PROVIDED=0
NGROK_TOKEN_PROVIDED=0

is_interactive() {
  [[ -t 0 && -t 1 ]]
}

# Backwards-compatible arg parsing:
# - Positional: <domain> <email> [--fresh]
# - Flags: --domain <domain> --email <email> --fresh
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      DOMAIN="${2:-}"
      DOMAIN_PROVIDED=1
      shift 2
      ;;
    --email)
      LE_EMAIL="${2:-}"
      EMAIL_PROVIDED=1
      shift 2
      ;;
    --fresh)
      FRESH_INSTALL=1
      shift
      ;;
    --ngrok)
      USE_NGROK=1
      shift
      ;;
    --ngrok-domain)
      USE_NGROK=1
      NGROK_DOMAIN="${2:-}"
      NGROK_DOMAIN_PROVIDED=1
      shift 2
      ;;
    --ngrok-token|--ngrok-authtoken)
      USE_NGROK=1
      NGROK_AUTHTOKEN="${2:-}"
      NGROK_TOKEN_PROVIDED=1
      shift 2
      ;;
    *)
      if [[ -z "${DOMAIN}" ]]; then
        DOMAIN="$1"
        DOMAIN_PROVIDED=1
      elif [[ -z "${LE_EMAIL}" ]]; then
        LE_EMAIL="$1"
        EMAIL_PROVIDED=1
      fi
      shift
      ;;
  esac
done

# Interactive prompts (TTY only): make the script friendlier when run without args.
if is_interactive; then
  if [[ "${USE_NGROK}" != "1" && "${DOMAIN_PROVIDED}" == "0" ]]; then
    read -r -p "Domain for HTTPS (default: noctis-pro.com): " _domain_in
    DOMAIN="${_domain_in:-noctis-pro.com}"
  fi
  if [[ "${USE_NGROK}" != "1" && "${EMAIL_PROVIDED}" == "0" ]]; then
    read -r -p "Let's Encrypt email (default: admin@${DOMAIN:-noctis-pro.com}): " _email_in
    LE_EMAIL="${_email_in:-admin@${DOMAIN:-noctis-pro.com}}"
  fi
  if [[ "${USE_NGROK}" == "1" ]]; then
    if [[ -z "${NGROK_DOMAIN}" ]]; then
      read -r -p "ngrok reserved domain (e.g. noctis-pro.com.ngrok.app): " _ngrok_domain_in
      NGROK_DOMAIN="${_ngrok_domain_in}"
    fi
    if [[ -z "${NGROK_AUTHTOKEN}" ]]; then
      read -r -s -p "ngrok authtoken: " _ngrok_token_in
      echo
      NGROK_AUTHTOKEN="${_ngrok_token_in}"
    fi
  fi
fi

# Default domain if not provided
DOMAIN="${DOMAIN:-noctis-pro.com}"
if [[ -z "${LE_EMAIL}" ]]; then
  LE_EMAIL="admin@${DOMAIN}"
fi

# Normalize/validate DOMAIN early (accept users pasting full URLs)
DOMAIN="${DOMAIN#http://}"
DOMAIN="${DOMAIN#https://}"
DOMAIN="${DOMAIN%%/*}"
DOMAIN="${DOMAIN%.}"

# ngrok mode: use the ngrok reserved domain as the public hostname and skip nginx/Let's Encrypt.
if [[ "${USE_NGROK}" == "1" ]]; then
  if [[ -z "${NGROK_DOMAIN}" ]]; then
    echo "[!] --ngrok requires --ngrok-domain <reserved-domain> (e.g., noctis-pro.com.ngrok.app)" >&2
    exit 2
  fi
  if [[ -z "${NGROK_AUTHTOKEN}" ]]; then
    echo "[!] --ngrok requires --ngrok-token <authtoken> (or set NGROK_AUTHTOKEN env var)" >&2
    exit 2
  fi
  DOMAIN="${NGROK_DOMAIN#http://}"
  DOMAIN="${DOMAIN#https://}"
  DOMAIN="${DOMAIN%%/*}"
  DOMAIN="${DOMAIN%.}"
  LE_EMAIL="admin@${DOMAIN}"
fi

# Guard against legacy/incorrect domain value (missing hyphen).
# If someone passes "noctispro.com" we always deploy as "noctis-pro.com".
if [[ "${DOMAIN}" == "noctispro.com" ]]; then
  echo "[!] Detected legacy domain 'noctispro.com' -> using 'noctis-pro.com' instead" >&2
  DOMAIN="noctis-pro.com"
fi

if [[ -z "${DOMAIN}" || "${DOMAIN}" == *" "* ]]; then
  echo "[!] Invalid domain. Provide a hostname like: example.com" >&2
  exit 2
fi

APP_DIR="/opt/noctispro"
ENV_DIR="/etc/noctis-pro"
ENV_FILE="${ENV_DIR}/noctis-pro.env"
LEGACY_ENV_DIR="/etc/noctispro"
LEGACY_ENV_FILE="${LEGACY_ENV_DIR}/noctispro.env"
SYSTEMD_DIR="/etc/systemd/system"
NGINX_SITE="/etc/nginx/sites-available/noctis-pro"
NGINX_SITE_LINK="/etc/nginx/sites-enabled/noctis-pro"
REPO_URL="https://github.com/noctispro6-cloud/NoctisPro"
ACME_ROOT="/var/www/noctis-acme"

echo "[+] Domain: ${DOMAIN}"
echo "[+] Email: ${LE_EMAIL}"
echo "[+] App dir: ${APP_DIR}"

# Detect whether www.<domain> actually resolves; many installs only set the apex A record.
# In ngrok mode we do not include www.*.
INCLUDE_WWW=0
if [[ "${USE_NGROK}" != "1" ]] && getent ahosts "www.${DOMAIN}" >/dev/null 2>&1; then
  INCLUDE_WWW=1
fi

DOMAINS=("${DOMAIN}")
if [[ "${INCLUDE_WWW}" == "1" ]]; then
  DOMAINS+=("www.${DOMAIN}")
fi

ALLOWED_HOSTS_CSV="$(IFS=,; echo "${DOMAINS[*]}")"
CSRF_TRUSTED_ORIGINS_CSV="$(printf 'https://%s,' "${DOMAINS[@]}")"
CSRF_TRUSTED_ORIGINS_CSV="${CSRF_TRUSTED_ORIGINS_CSV%,}"
SERVER_NAMES="${ALLOWED_HOSTS_CSV//,/ }"

export DEBIAN_FRONTEND=noninteractive

if [[ "${FRESH_INSTALL}" == "1" ]]; then
  echo "[+] Fresh reinstall requested: removing previous NoctisPro install artifacts..."
  # Stop/disable app services (ignore if not present)
  systemctl stop noctis-pro.service 2>/dev/null || true
  systemctl stop noctis-pro-dicom.service 2>/dev/null || true
  systemctl stop noctis-pro-ngrok-tunnel.service 2>/dev/null || true
  systemctl stop noctispro-web.service 2>/dev/null || true
  systemctl stop noctispro-dicom.service 2>/dev/null || true
  systemctl disable noctis-pro.service 2>/dev/null || true
  systemctl disable noctis-pro-dicom.service 2>/dev/null || true
  systemctl disable noctis-pro-ngrok-tunnel.service 2>/dev/null || true
  systemctl disable noctispro-web.service 2>/dev/null || true
  systemctl disable noctispro-dicom.service 2>/dev/null || true

  # Remove systemd unit files (ignore if missing)
  rm -f "${SYSTEMD_DIR}/noctis-pro.service" || true
  rm -f "${SYSTEMD_DIR}/noctis-pro-dicom.service" || true
  rm -f "${SYSTEMD_DIR}/noctis-pro-ngrok-tunnel.service" || true
  rm -f "${SYSTEMD_DIR}/noctispro-web.service" || true
  rm -f "${SYSTEMD_DIR}/noctispro-dicom.service" || true
  systemctl daemon-reload || true

  # Remove nginx site config + link (ignore if missing)
  rm -f "${NGINX_SITE}" "${NGINX_SITE_LINK}" || true

  # Remove env dir + app dir (includes venv/db/staticfiles/media)
  rm -rf "${ENV_DIR}" "${LEGACY_ENV_DIR}" || true
  rm -rf "${APP_DIR}" || true
fi

echo "[+] Installing OS packages..."
apt-get update -y
apt-get install -y \
  ca-certificates curl git \
  python3 python3-venv python3-pip \
  build-essential pkg-config \
  nginx ufw psmisc \
  certbot python3-certbot-nginx \
  libpq-dev \
  libjpeg-dev zlib1g-dev \
  libopenjp2-7 \
  libmagic1

echo "[+] Configuring firewall (UFW)..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 11112/tcp
ufw --force enable

echo "[+] Creating directories..."
mkdir -p "${APP_DIR}"
mkdir -p "${ENV_DIR}"
mkdir -p "${LEGACY_ENV_DIR}"
ln -sf "${ENV_FILE}" "${LEGACY_ENV_FILE}"
mkdir -p "${ACME_ROOT}"

echo "[+] Cloning/updating repo..."
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch --all --prune
  git -C "${APP_DIR}" reset --hard origin/main || git -C "${APP_DIR}" reset --hard origin/master
else
  rm -rf "${APP_DIR}"
  git clone "${REPO_URL}" "${APP_DIR}"
fi

echo "[+] Creating Python venv..."
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip wheel setuptools

echo "[+] Installing Python requirements..."
REQ_FILE="${APP_DIR}/requirements.server.txt"
if [[ ! -f "${REQ_FILE}" ]]; then
  REQ_FILE="${APP_DIR}/requirements.optimized.txt"
fi
"${APP_DIR}/venv/bin/pip" install --no-cache-dir -r "${REQ_FILE}"

echo "[+] Writing environment file..."
SECRET_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"

cat > "${ENV_FILE}" <<EOF
DJANGO_SETTINGS_MODULE=noctis_pro.settings
DEBUG=False
SECRET_KEY=${SECRET_KEY}

DOMAIN_NAME=${DOMAIN}
ALLOWED_HOSTS=${ALLOWED_HOSTS_CSV}
CSRF_TRUSTED_ORIGINS=${CSRF_TRUSTED_ORIGINS_CSV}

# HTTPS will be enabled after a successful certificate issuance.
# Nginx will handle redirects; these flags can be tightened later if desired.
SSL_ENABLED=False
SECURE_SSL_REDIRECT=False
SECURE_HSTS_SECONDS=0
SERVE_MEDIA_FILES=False

# Default SQLite (works on small VPS). For Postgres, set DB_* vars here.
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=${APP_DIR}/db.sqlite3
EOF

chmod 600 "${ENV_FILE}"
if [[ "${USE_NGROK}" == "1" ]]; then
  # Helps Django auto-allow the host and generate correct absolute URLs.
  echo "NGROK_URL=https://${DOMAIN}" >> "${ENV_FILE}"
fi

echo "[+] Running migrations + collectstatic..."
cd "${APP_DIR}"
set +u
source "${ENV_FILE}"
set -u
"${APP_DIR}/venv/bin/python" "${APP_DIR}/manage.py" migrate --noinput
"${APP_DIR}/venv/bin/python" "${APP_DIR}/manage.py" collectstatic --noinput

echo "[+] Ensuring initial admin exists (username: admin)..."
# If the app already auto-creates, this is still safe; it will no-op if exists.
ADMIN_PW="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(14))
PY
)"
"${APP_DIR}/venv/bin/python" "${APP_DIR}/manage.py" create_admin --username admin --email "admin@${DOMAIN}" --password "${ADMIN_PW}" || true

echo "[+] Creating systemd units..."
cat > "${SYSTEMD_DIR}/noctis-pro.service" <<EOF
[Unit]
Description=NoctisPro (Django ASGI via Daphne)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/daphne -b 127.0.0.1 -p 8000 noctis_pro.asgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > "${SYSTEMD_DIR}/noctis-pro-dicom.service" <<EOF
[Unit]
Description=NoctisPro DICOM Receiver (pynetdicom SCP)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/dicom_receiver.py --port 11112 --aet NOCTIS_SCP
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now noctis-pro.service
systemctl enable --now noctis-pro-dicom.service

install_ngrok() {
  if command -v ngrok >/dev/null 2>&1; then
    return 0
  fi
  echo "[+] Installing ngrok..."
  local arch
  arch="$(uname -m)"
  local platform="linux-amd64"
  case "${arch}" in
    x86_64|amd64)
      platform="linux-amd64"
      ;;
    aarch64|arm64)
      platform="linux-arm64"
      ;;
    *)
      echo "[!] Unsupported architecture for ngrok install: ${arch}" >&2
      echo "    Please install ngrok manually and re-run with --ngrok." >&2
      exit 2
      ;;
  esac

  local url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-${platform}.tgz"
  curl -fsSL "${url}" -o /tmp/ngrok.tgz
  tar -xzf /tmp/ngrok.tgz -C /tmp
  install -m 0755 /tmp/ngrok /usr/local/bin/ngrok
}

if [[ "${USE_NGROK}" == "1" ]]; then
  echo "[+] Setting up ngrok HTTPS tunnel (skipping nginx/Let's Encrypt)..."
  install_ngrok

  # Persist tunnel URL so Django can auto-detect it (see noctis_pro/settings.py).
  echo -n "https://${DOMAIN}" > "${APP_DIR}/.tunnel-url"

  # Write ngrok config (root-only readable).
  NGROK_CFG="${ENV_DIR}/ngrok.yml"
  cat > "${NGROK_CFG}" <<YAML
version: 2
authtoken: ${NGROK_AUTHTOKEN}
tunnels:
  noctis-web:
    proto: http
    addr: 8000
    schemes:
      - https
    domain: ${DOMAIN}
YAML
  chmod 600 "${NGROK_CFG}"

  # Create a dedicated systemd unit for the tunnel.
  cat > "${SYSTEMD_DIR}/noctis-pro-ngrok-tunnel.service" <<EOF
[Unit]
Description=Noctis Pro Public HTTPS Tunnel (ngrok)
After=network-online.target noctis-pro.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ngrok start --config ${NGROK_CFG} noctis-web
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now noctis-pro-ngrok-tunnel.service
fi

if [[ "${USE_NGROK}" != "1" ]]; then
echo "[+] Configuring nginx reverse proxy..."
cat > "${NGINX_SITE}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAMES};

    client_max_body_size 6G;

    # Allow Let's Encrypt HTTP-01 challenges without involving the app.
    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_ROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
        access_log off;
        expires 30d;
    }

    location /media/ {
        alias ${APP_DIR}/media/;
        access_log off;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        # Preserve upstream scheme from a front proxy (e.g., Cloudflare Flexible),
        # otherwise fall back to the direct nginx scheme.
        set \$forwarded_proto \$scheme;
        if (\$http_x_forwarded_proto != "") { set \$forwarded_proto \$http_x_forwarded_proto; }
        proxy_set_header X-Forwarded-Proto \$forwarded_proto;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
EOF

echo "[+] Ensuring ports 80/443 are free for nginx..."
# Stop common conflicting web servers if installed/enabled.
for svc in apache2 httpd caddy lighttpd haproxy; do
  systemctl stop "${svc}" 2>/dev/null || true
  systemctl disable "${svc}" 2>/dev/null || true
  systemctl mask "${svc}" 2>/dev/null || true
done
# Kill any remaining listeners on 80/443 (best-effort).
fuser -k 80/tcp 2>/dev/null || true
fuser -k 443/tcp 2>/dev/null || true

rm -f /etc/nginx/sites-enabled/default || true
ln -sf "${NGINX_SITE}" "${NGINX_SITE_LINK}"
nginx -t

# nginx "reload" fails if nginx isn't running yet; start/enable and fall back to restart.
systemctl enable --now nginx 2>/dev/null || true
if systemctl is-active --quiet nginx; then
  systemctl reload nginx
else
  systemctl restart nginx
fi

echo "[+] Verifying HTTP-01 challenge path is reachable locally..."
mkdir -p "${ACME_ROOT}/.well-known/acme-challenge"
echo "noctis-acme-ok" > "${ACME_ROOT}/.well-known/acme-challenge/noctis-acme-test"
PREFLIGHT_OK=1
LOCAL_OK=1
PUBLIC_OK=1

# Detect common DNS/IPv6 pitfall:
# If an AAAA record exists but this server has no working IPv6, some clients
# (and Let's Encrypt validation) may hit the IPv6 address and fail.
HAS_DNS_AAAA=0
if getent ahosts "${DOMAIN}" 2>/dev/null | awk '{print $1}' | grep -q ":"; then
  HAS_DNS_AAAA=1
fi
HAS_LOCAL_IPV6=0
if ip -6 route show default 2>/dev/null | grep -q "default"; then
  HAS_LOCAL_IPV6=1
elif ip -6 addr show scope global 2>/dev/null | grep -q "inet6"; then
  HAS_LOCAL_IPV6=1
fi
if [[ "${HAS_DNS_AAAA}" == "1" && "${HAS_LOCAL_IPV6}" == "0" ]]; then
  echo "[!] Warning: ${DOMAIN} has an AAAA (IPv6) record, but this server does not appear to have working IPv6." >&2
  echo "    This can break HTTPS access and Let's Encrypt issuance." >&2
  echo "    Fix options:" >&2
  echo "      - Remove the AAAA record for ${DOMAIN} (and www.${DOMAIN} if present), OR" >&2
  echo "      - Enable IPv6 routing on this server and ensure nginx listens on :: (this script enables :: listeners)." >&2
fi

# 1) Local validation (bypasses DNS): ensure nginx is serving the ACME root.
# This catches common misconfigurations (nginx not running, wrong root, wrong server_name).
if ! curl -fsS --max-time 5 -H "Host: ${DOMAIN}" \
  "http://127.0.0.1/.well-known/acme-challenge/noctis-acme-test" >/dev/null 2>&1; then
  LOCAL_OK=0
fi
if [[ "${INCLUDE_WWW}" == "1" ]]; then
  if ! curl -fsS --max-time 5 -H "Host: www.${DOMAIN}" \
    "http://127.0.0.1/.well-known/acme-challenge/noctis-acme-test" >/dev/null 2>&1; then
    LOCAL_OK=0
  fi
fi

# 2) Public validation (uses DNS): ensures the hostname resolves to this server and port 80 is reachable.
if ! curl -4 -fsS --max-time 8 \
  "http://${DOMAIN}/.well-known/acme-challenge/noctis-acme-test" >/dev/null 2>&1; then
  PUBLIC_OK=0
fi
if [[ "${INCLUDE_WWW}" == "1" ]]; then
  if ! curl -4 -fsS --max-time 8 \
    "http://www.${DOMAIN}/.well-known/acme-challenge/noctis-acme-test" >/dev/null 2>&1; then
    PUBLIC_OK=0
  fi
fi

# If AAAA exists, also sanity-check IPv6 reachability quickly (best-effort).
if [[ "${HAS_DNS_AAAA}" == "1" ]]; then
  if ! curl -6 -fsS --max-time 5 "http://${DOMAIN}/.well-known/acme-challenge/noctis-acme-test" >/dev/null 2>&1; then
    echo "[!] IPv6 check failed for ${DOMAIN} (AAAA exists but HTTP over IPv6 is not reachable)." >&2
    echo "    If users or Let's Encrypt hit IPv6 first, HTTPS may fail. Remove the AAAA record or fix IPv6 routing." >&2
  fi
fi

if [[ "${LOCAL_OK}" == "0" || "${PUBLIC_OK}" == "0" ]]; then
  PREFLIGHT_OK=0
fi

echo "[+] Issuing Let's Encrypt certificate (requires DNS A record already set)..."
CERT_OK=0
CERTBOT_ARGS=(-d "${DOMAIN}")
if [[ "${INCLUDE_WWW}" == "1" ]]; then
  CERTBOT_ARGS+=(-d "www.${DOMAIN}")
fi
if [[ "${PREFLIGHT_OK}" == "1" ]]; then
  if certbot certonly --webroot -w "${ACME_ROOT}" \
    "${CERTBOT_ARGS[@]}" \
    --non-interactive --agree-tos -m "${LE_EMAIL}"; then
    CERT_OK=1
  fi
else
  echo "[!] Preflight failed: HTTP-01 challenge URL not reachable." >&2
  if [[ "${LOCAL_OK}" == "0" ]]; then
    echo "    Local check failed (nginx -> ACME webroot not serving):" >&2
    echo "      curl -v -H 'Host: ${DOMAIN}' http://127.0.0.1/.well-known/acme-challenge/noctis-acme-test" >&2
    echo "    Fix: ensure nginx is running and serving ${ACME_ROOT} for /.well-known/acme-challenge/." >&2
  fi
  if [[ "${PUBLIC_OK}" == "0" ]]; then
    echo "    Public check failed (DNS/Firewall/Proxy):" >&2
    echo "      curl -v http://${DOMAIN}/.well-known/acme-challenge/noctis-acme-test" >&2
    echo "    Common causes:" >&2
    echo "      - DNS A record does not point to this server (or not propagated yet)" >&2
    echo "      - Port 80 blocked by provider firewall / security group" >&2
    echo "      - Cloudflare proxy enabled (orange cloud) while port 80/HTTP is not reachable" >&2
    echo "      - AAAA (IPv6) record exists but this server has no working IPv6 routing" >&2
    echo "    Quick checks:" >&2
    echo "      getent ahosts ${DOMAIN}" >&2
    echo "      ss -lntp | awk '\$4 ~ /:80$|:443$/ {print}'" >&2
    echo "      ufw status verbose" >&2
  fi
  echo "    - Re-run cert issuance manually once fixed:" >&2
  echo "      sudo certbot certonly --webroot -w ${ACME_ROOT} ${CERTBOT_ARGS[*]} -m ${LE_EMAIL} --agree-tos" >&2
fi

if [[ "${CERT_OK}" == "1" ]]; then
  echo "[+] Certificate issued successfully; enabling HTTPS nginx config..."

  # Mark HTTPS enabled for Django (optional; nginx already redirects below)
  perl -0777 -i -pe 's/^SSL_ENABLED=.*$/SSL_ENABLED=True/m; s/^SECURE_SSL_REDIRECT=.*$/SECURE_SSL_REDIRECT=True/m; s/^SECURE_HSTS_SECONDS=.*$/SECURE_HSTS_SECONDS=31536000/m' "${ENV_FILE}" || true

  cat > "${NGINX_SITE}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAMES};

    # Allow Let's Encrypt HTTP-01 challenges on plain HTTP.
    location ^~ /.well-known/acme-challenge/ {
        root ${ACME_ROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${SERVER_NAMES};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    client_max_body_size 6G;

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
        access_log off;
        expires 30d;
    }

    location /media/ {
        alias ${APP_DIR}/media/;
        access_log off;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port 443;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
EOF

  nginx -t
  systemctl reload nginx || systemctl restart nginx
  systemctl restart noctis-pro.service || true
fi
fi

echo ""
echo "============================================================"
echo "DEPLOY COMPLETE"
echo "============================================================"
echo "Web:   https://${DOMAIN}"
echo "Admin: https://${DOMAIN}/admin/"
echo "DICOM: ${DOMAIN}:11112  (Called AE: NOCTIS_SCP)"
echo ""
echo "Admin login:"
echo "  username: admin"
echo "  password: ${ADMIN_PW}"
echo ""
if [[ "${USE_NGROK}" == "1" ]]; then
  echo "ngrok tunnel enabled: ${DOMAIN}"
  echo "Note: nginx/Let's Encrypt was skipped (ngrok provides HTTPS)."
else
  echo "If SSL failed, confirm DNS A record points to this server,"
  echo "then re-run: sudo certbot certonly --webroot -w ${ACME_ROOT} -d ${DOMAIN} -d www.${DOMAIN}"
fi
echo "============================================================"


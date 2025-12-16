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

# Backwards-compatible arg parsing:
# - Positional: <domain> <email> [--fresh]
# - Flags: --domain <domain> --email <email> --fresh
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      DOMAIN="${2:-}"
      shift 2
      ;;
    --email)
      LE_EMAIL="${2:-}"
      shift 2
      ;;
    --fresh)
      FRESH_INSTALL=1
      shift
      ;;
    *)
      if [[ -z "${DOMAIN}" ]]; then
        DOMAIN="$1"
      elif [[ -z "${LE_EMAIL}" ]]; then
        LE_EMAIL="$1"
      fi
      shift
      ;;
  esac
done

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
INCLUDE_WWW=0
if getent ahosts "www.${DOMAIN}" >/dev/null 2>&1; then
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
  systemctl stop noctispro-web.service 2>/dev/null || true
  systemctl stop noctispro-dicom.service 2>/dev/null || true
  systemctl disable noctis-pro.service 2>/dev/null || true
  systemctl disable noctis-pro-dicom.service 2>/dev/null || true
  systemctl disable noctispro-web.service 2>/dev/null || true
  systemctl disable noctispro-dicom.service 2>/dev/null || true

  # Remove systemd unit files (ignore if missing)
  rm -f "${SYSTEMD_DIR}/noctis-pro.service" || true
  rm -f "${SYSTEMD_DIR}/noctis-pro-dicom.service" || true
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

echo "[+] Configuring nginx reverse proxy..."
cat > "${NGINX_SITE}" <<EOF
server {
    listen 80;
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
        proxy_set_header X-Forwarded-Proto \$scheme;
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
if ! curl -fsS --max-time 8 \
  "http://${DOMAIN}/.well-known/acme-challenge/noctis-acme-test" >/dev/null 2>&1; then
  PUBLIC_OK=0
fi
if [[ "${INCLUDE_WWW}" == "1" ]]; then
  if ! curl -fsS --max-time 8 \
    "http://www.${DOMAIN}/.well-known/acme-challenge/noctis-acme-test" >/dev/null 2>&1; then
    PUBLIC_OK=0
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
echo "If SSL failed, confirm DNS A record points to this server,"
echo "then re-run: sudo certbot certonly --webroot -w ${ACME_ROOT} -d ${DOMAIN} -d www.${DOMAIN}"
echo "============================================================"


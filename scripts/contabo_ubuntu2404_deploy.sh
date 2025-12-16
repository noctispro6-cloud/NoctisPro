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
#   sudo bash scripts/contabo_ubuntu2404_deploy.sh noctispro.com admin@noctispro.com

DOMAIN="${1:-}"
LE_EMAIL="${2:-}"

if [[ -z "${DOMAIN}" ]]; then
  echo "Usage: sudo bash $0 <domain> <letsencrypt-email>"
  exit 2
fi

if [[ -z "${LE_EMAIL}" ]]; then
  LE_EMAIL="admin@${DOMAIN}"
fi

APP_DIR="/opt/noctispro"
ENV_DIR="/etc/noctispro"
ENV_FILE="${ENV_DIR}/noctispro.env"
SYSTEMD_DIR="/etc/systemd/system"
NGINX_SITE="/etc/nginx/sites-available/noctispro"
NGINX_SITE_LINK="/etc/nginx/sites-enabled/noctispro"
REPO_URL="https://github.com/noctispro6-cloud/NoctisPro"

echo "[+] Domain: ${DOMAIN}"
echo "[+] Email: ${LE_EMAIL}"
echo "[+] App dir: ${APP_DIR}"

export DEBIAN_FRONTEND=noninteractive

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

ALLOWED_HOSTS=${DOMAIN},www.${DOMAIN}
CSRF_TRUSTED_ORIGINS=https://${DOMAIN},https://www.${DOMAIN}

# Behind nginx
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
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
cat > "${SYSTEMD_DIR}/noctispro-web.service" <<EOF
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

cat > "${SYSTEMD_DIR}/noctispro-dicom.service" <<EOF
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
systemctl enable --now noctispro-web.service
systemctl enable --now noctispro-dicom.service

echo "[+] Configuring nginx reverse proxy..."
cat > "${NGINX_SITE}" <<EOF
server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};

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

echo "[+] Issuing Let's Encrypt certificate (requires DNS A record already set)..."
certbot --nginx -d "${DOMAIN}" -d "www.${DOMAIN}" \
  --non-interactive --agree-tos -m "${LE_EMAIL}" \
  --redirect || true

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
echo "then re-run: sudo certbot --nginx -d ${DOMAIN} -d www.${DOMAIN}"
echo "============================================================"


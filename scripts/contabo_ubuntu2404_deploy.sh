#!/usr/bin/env bash
set -euo pipefail

# One-shot deploy for Contabo Ubuntu 24.04
# - Installs OS deps
# - Clones repo into /opt/noctispro
# - Creates venv and installs Python deps
# - Writes env file (/etc/noctispro/noctispro.env)
# - Migrates DB + collectstatic
# - Configures systemd (web + dicom receiver)
# - Configures ngrok tunnel (ONLY supported public access)
# - Opens firewall ports (22/11112). Web is exposed only via ngrok.
#
# Usage:
#   NGROK_AUTHTOKEN="..." NGROK_DOMAIN="noctis-pro.com.ngrok.app" sudo bash scripts/contabo_ubuntu2404_deploy.sh --fresh
#   sudo bash scripts/contabo_ubuntu2404_deploy.sh --ngrok-domain noctis-pro.com.ngrok.app --ngrok-token "..." --fresh

DOMAIN=""
LE_EMAIL=""
FRESH_INSTALL=0
USE_NGROK=1
# Track whether values were explicitly provided (vs defaults/prompts).
DOMAIN_PROVIDED=0
EMAIL_PROVIDED=0
# These can be provided via flags or environment variables:
#   NGROK_AUTHTOKEN="..." NGROK_DOMAIN="noctis-pro.com.ngrok.app" sudo bash scripts/contabo_ubuntu2404_deploy.sh --ngrok --fresh
NGROK_AUTHTOKEN="${NGROK_AUTHTOKEN:-}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"
NGROK_DOMAIN_PROVIDED=0
NGROK_TOKEN_PROVIDED=0

extract_ngrok_authtoken_from_file() {
  # Print the authtoken from a ngrok YAML config file (best-effort), or nothing.
  # Avoids leaking the token into logs (callers should not echo the value).
  local cfg="${1:-}"
  [[ -n "${cfg}" && -f "${cfg}" ]] || return 1
  # Extract first matching "authtoken: ..." line, stripping quotes and inline comments.
  # Example lines:
  #   authtoken: abc123
  #   authtoken: "abc123"  # comment
  local token=""
  token="$(sed -nE 's/^[[:space:]]*authtoken[[:space:]]*:[[:space:]]*"?([^"#]+)"?[[:space:]]*(#.*)?$/\1/p' "${cfg}" | sed -n '1p' | tr -d '\r' | xargs || true)"
  if [[ -n "${token}" ]]; then
    printf '%s' "${token}"
  fi
}

discover_existing_ngrok_authtoken() {
  # Search common locations for an existing authtoken.
  local cfg token
  for cfg in \
    "/etc/noctis-pro/ngrok.yml" \
    "/etc/noctispro/ngrok.yml" \
    "/etc/ngrok.yml" \
    "/root/.config/ngrok/ngrok.yml" \
    "${HOME:-/root}/.config/ngrok/ngrok.yml"
  do
    token="$(extract_ngrok_authtoken_from_file "${cfg}")"
    if [[ -n "${token}" ]]; then
      printf '%s' "${token}"
      return 0
    fi
  done
  return 1
}

adopt_existing_ngrok_token_if_missing() {
  # If no token was provided, try to adopt an already-configured server token.
  if [[ -z "${NGROK_AUTHTOKEN}" ]]; then
    local token=""
    token="$(discover_existing_ngrok_authtoken || true)"
    if [[ -n "${token}" ]]; then
      NGROK_AUTHTOKEN="${token}"
      echo "[+] Adopted existing ngrok authtoken from server config."
    fi
  fi
}

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

# If the server already has an ngrok authtoken configured, adopt it so we don't
# force re-entry or overwrite/remove it during deployment.
adopt_existing_ngrok_token_if_missing

# Interactive prompts (TTY only): make the script friendlier when run without args.
if is_interactive; then
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

# This deployment script supports ONLY ngrok public access.
# If someone passes legacy flags without --ngrok, we force ngrok mode and require token/domain.
if [[ "${USE_NGROK}" != "1" ]]; then
  echo "[!] Non-ngrok deployment paths are suspended; forcing ngrok mode." >&2
  USE_NGROK=1
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
  adopt_existing_ngrok_token_if_missing
  if [[ -z "${NGROK_AUTHTOKEN}" ]]; then
    echo "[!] ngrok authtoken not provided and no existing server token found." >&2
    echo "    Provide --ngrok-token <authtoken> (or set NGROK_AUTHTOKEN) once, and future runs will reuse it." >&2
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
  # Preserve an already-configured ngrok token before removing /etc/noctis-pro.
  # This allows --fresh installs to keep the ngrok auth state.
  adopt_existing_ngrok_token_if_missing

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
  ufw psmisc \
  libpq-dev \
  libjpeg-dev zlib1g-dev \
  libopenjp2-7 \
  libmagic1

echo "[+] Configuring firewall (UFW)..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
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
  echo "[!] This deployment script supports ONLY ngrok. Non-ngrok steps are suspended." >&2
  exit 2
fi

echo ""
echo "============================================================"
echo "DEPLOY COMPLETE"
echo "============================================================"
echo "Public URL: https://${DOMAIN}"
PUBLIC_IP="$(curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
if [[ -z "${PUBLIC_IP}" ]]; then
  PUBLIC_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
if [[ -n "${PUBLIC_IP}" ]]; then
  echo "DICOM: ${PUBLIC_IP}:11112  (Called AE: NOCTIS_SCP)"
else
  echo "DICOM: <server-public-ip>:11112  (Called AE: NOCTIS_SCP)"
fi
echo ""
echo "Admin login:"
echo "  username: admin"
echo "  password: ${ADMIN_PW}"
echo ""
if [[ "${USE_NGROK}" == "1" ]]; then
  echo "ngrok tunnel enabled: ${DOMAIN}"
else
  echo "[!] Non-ngrok deployment is suspended."
fi
echo "============================================================"


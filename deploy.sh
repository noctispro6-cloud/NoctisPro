#!/usr/bin/env bash
set -euo pipefail

# Noctis Pro - Single deployment script for Ubuntu 24.04
#
# Supports two public access modes:
#   1) Domain mode: nginx + Let's Encrypt (certbot)
#   2) Ngrok mode: public HTTPS via ngrok tunnel (optional reserved domain)
#
# Installs into: /opt/noctispro
# Writes env to: /etc/noctis-pro/noctis-pro.env
# Installs systemd units from: tools/systemd/

APP_DIR_DEFAULT="/opt/noctispro"
ENV_DIR="/etc/noctis-pro"
ENV_FILE="${ENV_DIR}/noctis-pro.env"
SYSTEMD_DIR="/etc/systemd/system"

MODE=""
DOMAIN=""
EMAIL=""
FRESH=0

NGROK_AUTHTOKEN="${NGROK_AUTHTOKEN:-}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"

APP_DIR="${APP_DIR_DEFAULT}"

usage() {
  cat <<'EOF'
Usage (run from repo root after clone):

  sudo ./deploy.sh --mode domain --domain example.com --email admin@example.com

  sudo ./deploy.sh --mode ngrok --ngrok-token "YOUR_TOKEN" [--ngrok-domain reserved.ngrok.app]

Optional:
  --fresh                 Wipe existing /opt/noctispro and /etc/noctis-pro first
  --app-dir /opt/noctispro Override install dir (must match systemd units if you change them)

Notes:
- Domain mode requires DNS A/AAAA records already pointing at this server.
- Ngrok mode requires an ngrok authtoken. If you omit --ngrok-domain, ngrok will assign
  a random public URL; the tunnel service will persist it to /opt/noctispro/.tunnel-url.
EOF
}

err() { echo "[ERROR] $*" >&2; }
info() { echo "[INFO]  $*" >&2; }

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    err "Run with sudo (needs to install packages and write system files)."
    exit 1
  fi
}

normalize_host() {
  local v="${1:-}"
  v="${v#http://}"
  v="${v#https://}"
  v="${v%%/*}"
  v="${v%.}"
  printf '%s' "$v"
}

read_env_kv() {
  # read_env_kv KEY /path/to/env -> prints value or empty
  local key="${1:?}" file="${2:?}"
  [[ -f "$file" ]] || return 0
  # shellcheck disable=SC2002
  cat "$file" | sed -nE "s/^${key}=//p" | sed -n '1p' | tr -d '\r'
}

gen_secret_key() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

install_os_packages() {
  export DEBIAN_FRONTEND=noninteractive
  info "Installing OS packages..."
  apt-get update -y
  apt-get install -y \
    ca-certificates curl git rsync \
    python3 python3-venv python3-pip \
    build-essential pkg-config \
    ufw psmisc \
    libpq-dev \
    libjpeg-dev zlib1g-dev \
    libopenjp2-7 \
    libmagic1

  if [[ "$MODE" == "domain" ]]; then
    apt-get install -y nginx certbot python3-certbot-nginx
  fi
}

configure_firewall() {
  info "Configuring firewall (UFW)..."
  ufw --force reset
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp
  ufw allow 11112/tcp
  if [[ "$MODE" == "domain" ]]; then
    ufw allow 80/tcp
    ufw allow 443/tcp
  fi
  ufw --force enable
}

fresh_wipe() {
  [[ "$FRESH" == "1" ]] || return 0
  info "Fresh install requested: stopping services and wiping prior install..."

  systemctl stop noctis-pro.service 2>/dev/null || true
  systemctl stop noctis-pro-dicom.service 2>/dev/null || true
  systemctl stop noctis-pro-tunnel.service 2>/dev/null || true
  systemctl stop noctis-pro-celery.service 2>/dev/null || true

  systemctl disable noctis-pro.service 2>/dev/null || true
  systemctl disable noctis-pro-dicom.service 2>/dev/null || true
  systemctl disable noctis-pro-tunnel.service 2>/dev/null || true
  systemctl disable noctis-pro-celery.service 2>/dev/null || true

  rm -f "${SYSTEMD_DIR}/noctis-pro.service" || true
  rm -f "${SYSTEMD_DIR}/noctis-pro-dicom.service" || true
  rm -f "${SYSTEMD_DIR}/noctis-pro-tunnel.service" || true
  rm -f "${SYSTEMD_DIR}/noctis-pro-celery.service" || true

  systemctl daemon-reload || true

  rm -rf "$ENV_DIR" || true
  rm -rf "$APP_DIR" || true

  rm -f /etc/nginx/sites-enabled/noctis-pro 2>/dev/null || true
  rm -f /etc/nginx/sites-available/noctis-pro 2>/dev/null || true
  systemctl reload nginx 2>/dev/null || true
}

sync_app_code() {
  info "Syncing application code into ${APP_DIR}..."

  local src
  src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  mkdir -p "$APP_DIR"

  # If already running from the target directory, do nothing.
  if [[ "$(realpath -m "$src")" == "$(realpath -m "$APP_DIR")" ]]; then
    info "Repo already located at ${APP_DIR}; skipping sync."
    return 0
  fi

  rsync -a --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '*.pyc' \
    "$src/" "$APP_DIR/"
}

setup_venv_and_deps() {
  info "Creating Python venv + installing requirements..."
  python3 -m venv "${APP_DIR}/venv"
  "${APP_DIR}/venv/bin/pip" install --upgrade pip wheel setuptools

  local req="${APP_DIR}/requirements.server.txt"
  if [[ ! -f "$req" ]]; then
    req="${APP_DIR}/requirements.optimized.txt"
  fi
  "${APP_DIR}/venv/bin/pip" install --no-cache-dir -r "$req"
}

write_env_file() {
  mkdir -p "$ENV_DIR"
  chmod 755 "$ENV_DIR"

  local secret
  secret="$(read_env_kv SECRET_KEY "$ENV_FILE")"
  if [[ -z "$secret" ]]; then
    secret="$(gen_secret_key)"
  fi

  local domain_hosts_csv csrf_csv
  domain_hosts_csv="${DOMAIN}"
  csrf_csv="https://${DOMAIN}"

  # Add www.<domain> automatically if it resolves (domain mode only)
  if [[ "$MODE" == "domain" ]] && getent ahosts "www.${DOMAIN}" >/dev/null 2>&1; then
    domain_hosts_csv+="",www.${DOMAIN}"
    csrf_csv+="",https://www.${DOMAIN}"
  fi

  info "Writing ${ENV_FILE}..."
  umask 077
  cat > "$ENV_FILE" <<EOF
# Generated by deploy.sh
APP_DIR=${APP_DIR}
DJANGO_SETTINGS_MODULE=noctis_pro.settings

DEBUG=False
SECRET_KEY=${secret}

DOMAIN_NAME=${DOMAIN}
ALLOWED_HOSTS=${domain_hosts_csv}
CSRF_TRUSTED_ORIGINS=${csrf_csv}

# Serve media/static via Django (app already has views for this)
SERVE_MEDIA_FILES=True

# SQLite default (works out-of-the-box). Override with DB_* for Postgres.
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=${APP_DIR}/db.sqlite3

# Reverse proxy settings (nginx sets X-Forwarded-Proto)
USE_X_FORWARDED_HOST=False
USE_X_FORWARDED_PORT=False
EOF

  if [[ "$MODE" == "domain" ]]; then
    echo "SSL_ENABLED=True" >> "$ENV_FILE"
    echo "SECURE_SSL_REDIRECT=True" >> "$ENV_FILE"
  else
    echo "SSL_ENABLED=False" >> "$ENV_FILE"
    echo "SECURE_SSL_REDIRECT=False" >> "$ENV_FILE"
  fi

  if [[ "$MODE" == "ngrok" ]]; then
    # Used by settings + tunnel unit
    echo "NGROK_AUTHTOKEN=${NGROK_AUTHTOKEN}" >> "$ENV_FILE"
    if [[ -n "$NGROK_DOMAIN" ]]; then
      echo "NGROK_DOMAIN=${NGROK_DOMAIN}" >> "$ENV_FILE"
      echo "NGROK_URL=https://${NGROK_DOMAIN}" >> "$ENV_FILE"
    fi
  fi

  chmod 600 "$ENV_FILE"
}

django_manage() {
  ( set +u
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set -u
    cd "$APP_DIR"
    "${APP_DIR}/venv/bin/python" "$APP_DIR/manage.py" "$@"
  )
}

migrate_and_collectstatic() {
  info "Running migrations + collectstatic..."
  django_manage migrate --noinput
  django_manage collectstatic --noinput
}

ensure_admin_user() {
  info "Ensuring an admin login exists..."

  local pw
  pw="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(14))
PY
)"

  # Create a superuser if none exist.
  ( set +u
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set -u
    cd "$APP_DIR"
    "${APP_DIR}/venv/bin/python" "$APP_DIR/manage.py" shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    u = User.objects.create_superuser(username='admin', email='admin@${DOMAIN}', password='${pw}')
    # Some installs rely on role as well.
    try:
        u.role = 'admin'
        u.is_verified = True
        u.save(update_fields=['role','is_verified'])
    except Exception:
        pass
    print('ADMIN_CREATED')
else:
    print('ADMIN_EXISTS')
" >/tmp/noctis-admin.out
  )

  if grep -q 'ADMIN_CREATED' /tmp/noctis-admin.out 2>/dev/null; then
    info "Admin created: username=admin password=${pw}"
  else
    info "Admin already exists (not changing password)."
  fi
}

install_systemd_units() {
  info "Installing systemd unit files..."

  local src_dir="${APP_DIR}/tools/systemd"
  if [[ ! -d "$src_dir" ]]; then
    err "Missing ${src_dir}. This repo must include tools/systemd/*.service"
    exit 2
  fi

  install -m 0644 "${src_dir}/noctis-pro.service" "${SYSTEMD_DIR}/noctis-pro.service"
  install -m 0644 "${src_dir}/noctis-pro-dicom.service" "${SYSTEMD_DIR}/noctis-pro-dicom.service"

  # Tunnel unit is only for ngrok mode.
  if [[ "$MODE" == "ngrok" ]]; then
    install -m 0644 "${src_dir}/noctis-pro-tunnel.service" "${SYSTEMD_DIR}/noctis-pro-tunnel.service"
  else
    rm -f "${SYSTEMD_DIR}/noctis-pro-tunnel.service" || true
  fi

  # Celery unit exists, but the app currently has celery config disabled.
  # Install it but don't enable it by default.
  install -m 0644 "${src_dir}/noctis-pro-celery.service" "${SYSTEMD_DIR}/noctis-pro-celery.service"

  systemctl daemon-reload
}

enable_services() {
  info "Enabling services..."
  systemctl enable --now noctis-pro.service
  systemctl enable --now noctis-pro-dicom.service

  if [[ "$MODE" == "ngrok" ]]; then
    install_ngrok
    systemctl enable --now noctis-pro-tunnel.service
  else
    systemctl stop noctis-pro-tunnel.service 2>/dev/null || true
    systemctl disable noctis-pro-tunnel.service 2>/dev/null || true
  fi
}

install_ngrok() {
  if command -v ngrok >/dev/null 2>&1; then
    return 0
  fi
  info "Installing ngrok..."
  local arch platform url
  arch="$(uname -m)"
  platform="linux-amd64"
  case "$arch" in
    x86_64|amd64) platform="linux-amd64" ;;
    aarch64|arm64) platform="linux-arm64" ;;
    *) err "Unsupported architecture for ngrok: ${arch}"; exit 2 ;;
  esac
  url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-${platform}.tgz"
  curl -fsSL "$url" -o /tmp/ngrok.tgz
  tar -xzf /tmp/ngrok.tgz -C /tmp
  install -m 0755 /tmp/ngrok /usr/local/bin/ngrok
}

configure_nginx_for_domain() {
  info "Configuring nginx for ${DOMAIN}..."

  local site_avail="/etc/nginx/sites-available/noctis-pro"
  local site_enabled="/etc/nginx/sites-enabled/noctis-pro"

  cat > "$site_avail" <<EOF
server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};

    client_max_body_size 5120M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

  ln -sf "$site_avail" "$site_enabled"
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
}

issue_letsencrypt_cert() {
  info "Issuing Let's Encrypt certificate via certbot (nginx plugin)..."
  info "If this fails, your domain DNS likely isn't pointing to this server yet."

  # certbot will edit nginx config to add TLS + redirect.
  certbot --nginx \
    -d "${DOMAIN}" \
    -d "www.${DOMAIN}" \
    -m "${EMAIL}" \
    --agree-tos \
    --non-interactive \
    --redirect

  systemctl reload nginx
}

show_result() {
  echo ""
  echo "============================================================"
  echo "DEPLOY COMPLETE"
  echo "============================================================"

  if [[ "$MODE" == "domain" ]]; then
    echo "Web:   https://${DOMAIN}"
  else
    # Tunnel unit will persist the final URL in /opt/noctispro/.tunnel-url.
    if [[ -s "${APP_DIR}/.tunnel-url" ]]; then
      echo "Web:   $(cat "${APP_DIR}/.tunnel-url" 2>/dev/null || true)"
    elif [[ -n "$NGROK_DOMAIN" ]]; then
      echo "Web:   https://${NGROK_DOMAIN}"
    else
      echo "Web:   (starting) check: journalctl -u noctis-pro-tunnel.service -n 100 --no-pager"
    fi
  fi

  local ip
  ip="$(curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  if [[ -z "$ip" ]]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi
  echo "DICOM: ${ip:-<server-ip>}:11112  (Called AE: NOCTIS_SCP)"

  echo "System services:"
  echo "  - noctis-pro.service"
  echo "  - noctis-pro-dicom.service"
  if [[ "$MODE" == "ngrok" ]]; then
    echo "  - noctis-pro-tunnel.service"
  fi
  echo "============================================================"
}

# ---------------------- arg parsing ----------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --email) EMAIL="${2:-}"; shift 2 ;;
    --fresh) FRESH=1; shift ;;
    --ngrok-token|--ngrok-authtoken) NGROK_AUTHTOKEN="${2:-}"; shift 2 ;;
    --ngrok-domain) NGROK_DOMAIN="${2:-}"; shift 2 ;;
    --app-dir) APP_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) err "Unknown arg: $1"; usage; exit 2 ;;
  esac
done

MODE="$(normalize_host "$MODE")"

if [[ "$MODE" != "domain" && "$MODE" != "ngrok" ]]; then
  err "--mode must be 'domain' or 'ngrok'"
  usage
  exit 2
fi

require_root

if [[ "$MODE" == "domain" ]]; then
  DOMAIN="$(normalize_host "$DOMAIN")"
  if [[ -z "$DOMAIN" ]]; then
    err "--domain is required in domain mode"
    usage
    exit 2
  fi
  EMAIL="${EMAIL:-admin@${DOMAIN}}"
else
  # ngrok mode: domain is informational (Django will use tunnel URL), but keep a default.
  DOMAIN="$(normalize_host "${DOMAIN:-noctis-pro.com}")"
  NGROK_DOMAIN="$(normalize_host "$NGROK_DOMAIN")"
  if [[ -z "$NGROK_AUTHTOKEN" ]]; then
    err "--ngrok-token (or NGROK_AUTHTOKEN env var) is required in ngrok mode"
    usage
    exit 2
  fi
fi

# ---------------------- execution ----------------------
install_os_packages
fresh_wipe
configure_firewall
sync_app_code
setup_venv_and_deps
write_env_file
migrate_and_collectstatic
ensure_admin_user
install_systemd_units
enable_services

if [[ "$MODE" == "domain" ]]; then
  configure_nginx_for_domain
  issue_letsencrypt_cert
  systemctl restart noctis-pro.service
fi

show_result

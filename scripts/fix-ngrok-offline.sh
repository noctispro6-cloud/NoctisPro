#!/usr/bin/env bash
#
# Noctis Pro - Fix ngrok "endpoint offline" (ERR_NGROK_3200)
#
# What this does (safe, best-effort):
# - Restarts the Noctis web service (port 8000) and the ngrok tunnel systemd unit
# - Ensures ngrok binary exists (installs if missing)
# - Ensures /etc/noctis-pro/ngrok.yml exists if NGROK_AUTHTOKEN is configured
# - Writes/updates /opt/noctispro/.tunnel-url when possible
# - If the reserved domain fails (token/domain mismatch), optionally falls back to
#   a random ngrok URL (prints it so you can use it immediately)
#
# Run:
#   sudo bash scripts/fix-ngrok-offline.sh
#
set -euo pipefail

log() { echo "[fix-ngrok] $*" >&2; }

need_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    log "ERROR: run as root: sudo bash $0"
    exit 1
  fi
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

install_ngrok() {
  if have_cmd ngrok; then
    return 0
  fi
  log "ngrok not found; installing..."
  local arch platform url
  arch="$(uname -m)"
  platform="linux-amd64"
  case "${arch}" in
    x86_64|amd64) platform="linux-amd64" ;;
    aarch64|arm64) platform="linux-arm64" ;;
    *)
      log "ERROR: unsupported architecture for ngrok: ${arch}"
      return 1
      ;;
  esac
  url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-${platform}.tgz"
  curl -fsSL "${url}" -o /tmp/ngrok.tgz
  tar -xzf /tmp/ngrok.tgz -C /tmp
  install -m 0755 /tmp/ngrok /usr/local/bin/ngrok
  rm -f /tmp/ngrok.tgz /tmp/ngrok
}

unit_exists() {
  local unit="$1"
  systemctl list-unit-files --no-pager --no-legend 2>/dev/null | awk '{print $1}' | grep -qx "${unit}"
}

pick_tunnel_unit() {
  if unit_exists "noctis-pro-ngrok-tunnel.service"; then
    echo "noctis-pro-ngrok-tunnel.service"
  elif unit_exists "noctis-pro-tunnel.service"; then
    echo "noctis-pro-tunnel.service"
  else
    echo ""
  fi
}

read_env_file_var() {
  # best-effort parse KEY=VALUE lines (no shell eval)
  local file="$1" key="$2"
  [[ -f "${file}" ]] || return 0
  awk -v k="${key}" '
    $0 ~ "^[[:space:]]*#"{next}
    match($0, "^[[:space:]]*"k"[[:space:]]*=") {
      sub("^[[:space:]]*"k"[[:space:]]*=[[:space:]]*", "", $0)
      gsub(/^[\"\047]/, "", $0); gsub(/[\"\047][[:space:]]*$/, "", $0)
      print $0
      exit 0
    }
  ' "${file}" 2>/dev/null || true
}

ensure_ngrok_config() {
  local cfg="/etc/noctis-pro/ngrok.yml"
  local env1="/etc/noctis-pro/noctis-pro.env"
  local env2="/etc/noctispro/noctispro.env"
  local token domain
  token="$(read_env_file_var "${env1}" "NGROK_AUTHTOKEN")"
  [[ -n "${token}" ]] || token="$(read_env_file_var "${env2}" "NGROK_AUTHTOKEN")"
  domain="$(read_env_file_var "${env1}" "NGROK_DOMAIN")"
  [[ -n "${domain}" ]] || domain="$(read_env_file_var "${env2}" "NGROK_DOMAIN")"

  if [[ -f "${cfg}" ]]; then
    return 0
  fi
  if [[ -z "${token}" ]]; then
    log "No ${cfg} and NGROK_AUTHTOKEN not found in ${env1} or ${env2} (will still try restarting units)."
    return 0
  fi

  log "Creating ${cfg} from env (token present)."
  install -d -m 0755 "$(dirname "${cfg}")"
  umask 077
  {
    echo "version: 2"
    echo "authtoken: ${token}"
    echo "tunnels:"
    echo "  noctis-web:"
    echo "    proto: http"
    echo "    addr: 8000"
    echo "    schemes:"
    echo "      - https"
    if [[ -n "${domain}" ]]; then
      echo "    domain: ${domain}"
    fi
  } > "${cfg}"
  chmod 600 "${cfg}"
}

stop_stray_ngrok() {
  if pgrep -x ngrok >/dev/null 2>&1; then
    log "Stopping stray ngrok processes (avoids multiple-session issues)."
    pkill -x ngrok || true
  fi
}

restart_and_wait_web() {
  if unit_exists "noctis-pro.service"; then
    log "Restarting noctis-pro.service"
    systemctl restart noctis-pro.service
  fi
  log "Waiting for http://127.0.0.1:8000 to respond..."
  for _ in $(seq 1 40); do
    if curl -fsS --max-time 2 "http://127.0.0.1:8000/" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  log "WARN: web app did not respond on 127.0.0.1:8000 (ngrok may still start, but will proxy errors)."
  return 0
}

show_last_logs() {
  local unit="$1"
  log "Last tunnel logs (${unit}):"
  journalctl -u "${unit}" -n 120 --no-pager -o cat 2>/dev/null || true
}

fallback_to_random_domain() {
  # If the reserved domain is misconfigured, drop NGROK_DOMAIN so ngrok will allocate a random URL.
  local env="/etc/noctis-pro/noctis-pro.env"
  if [[ ! -f "${env}" ]]; then
    env="/etc/noctispro/noctispro.env"
  fi
  if [[ ! -f "${env}" ]]; then
    log "No env file found to disable NGROK_DOMAIN; skipping fallback."
    return 1
  fi

  if grep -qE '^[[:space:]]*NGROK_DOMAIN[[:space:]]*=' "${env}"; then
    local bak="${env}.bak.$(date +%Y%m%d%H%M%S)"
    cp -a "${env}" "${bak}"
    log "Backing up ${env} -> ${bak}"
    # comment out NGROK_DOMAIN line
    perl -0777 -pe 's/^[ \t]*NGROK_DOMAIN[ \t]*=.*$/# NGROK_DOMAIN disabled by fix-ngrok-offline.sh (reserved domain failing)/m' -i "${env}" || true
    log "Disabled NGROK_DOMAIN in ${env} to allow random ngrok URL."
  else
    log "NGROK_DOMAIN not set in ${env}; nothing to disable."
  fi

  # Also remove domain from ngrok.yml if present.
  if [[ -f "/etc/noctis-pro/ngrok.yml" ]]; then
    perl -0777 -pe 's/^\s*domain:\s*.*\n//m' -i "/etc/noctis-pro/ngrok.yml" || true
  fi
  return 0
}

write_tunnel_url_if_detectable() {
  # If using reserved domain, unit already writes it. If random, read from local ngrok API.
  local app_dir="/opt/noctispro"
  local url_file="${app_dir}/.tunnel-url"
  if [[ -f "${url_file}" ]] && [[ -s "${url_file}" ]]; then
    log "Current tunnel URL: $(cat "${url_file}" 2>/dev/null || true)"
    return 0
  fi
  for _ in $(seq 1 80); do
    local url=""
    url="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 - <<'PY'
import json,sys
try:
    data=json.load(sys.stdin)
except Exception:
    sys.exit(0)
for t in data.get("tunnels", []) or []:
    u=(t.get("public_url") or "").strip()
    if u.startswith("https://"):
        print(u)
        break
PY
)" || true
    if [[ -n "${url}" ]]; then
      echo -n "${url}" > "${url_file}" 2>/dev/null || true
      log "Detected ngrok URL: ${url}"
      return 0
    fi
    sleep 0.5
  done
  return 0
}

main() {
  need_root

  if ! have_cmd systemctl; then
    log "ERROR: systemctl not available (this script must run on the server host, not inside a container)."
    exit 1
  fi

  local tunnel_unit
  tunnel_unit="$(pick_tunnel_unit)"
  if [[ -z "${tunnel_unit}" ]]; then
    log "ERROR: Could not find ngrok tunnel unit (expected noctis-pro-ngrok-tunnel.service or noctis-pro-tunnel.service)."
    log "If you deployed with scripts/contabo_ubuntu2404_deploy.sh, re-run it with --ngrok."
    exit 1
  fi

  install_ngrok || true
  ensure_ngrok_config || true
  stop_stray_ngrok || true
  restart_and_wait_web || true

  log "Restarting tunnel unit: ${tunnel_unit}"
  systemctl restart "${tunnel_unit}" || true
  sleep 2

  if systemctl is-active --quiet "${tunnel_unit}"; then
    write_tunnel_url_if_detectable || true
    log "DONE: ${tunnel_unit} is active."
    exit 0
  fi

  log "Tunnel unit is not active; attempting diagnosis..."
  show_last_logs "${tunnel_unit}"

  # If logs indicate reserved domain issues, fall back to random URL so at least the UI is reachable.
  if journalctl -u "${tunnel_unit}" -n 200 --no-pager 2>/dev/null | grep -qiE 'reserved|domain|not owned|not authorized|ERR_NGROK_4|authentication failed|authtoken'; then
    log "Detected likely reserved-domain/token issue. Falling back to a random ngrok URL (temporary)."
    fallback_to_random_domain || true
    stop_stray_ngrok || true
    systemctl restart "${tunnel_unit}" || true
    sleep 2
    if systemctl is-active --quiet "${tunnel_unit}"; then
      write_tunnel_url_if_detectable || true
      log "DONE: tunnel is active (random URL). Check /opt/noctispro/.tunnel-url"
      exit 0
    fi
    show_last_logs "${tunnel_unit}"
  fi

  log "FAILED: Could not bring ngrok tunnel online. Next best step is to run:"
  log "  sudo journalctl -u ${tunnel_unit} -e --no-pager"
  exit 2
}

main "$@"


#!/usr/bin/env bash
# =============================================================================
# NoctisPro — WireGuard VPN Setup
# Run once on the AWS server:  sudo bash tools/setup-wireguard.sh
#
# What it does:
#   1. Installs WireGuard
#   2. Creates server keypair and wg0 interface (10.8.0.1)
#   3. Enables IP forwarding
#   4. Starts and enables wg-quick@wg0
#   5. Prints instructions for adding clinics
#
# After setup, add clinics with:
#   sudo bash tools/add-clinic.sh "Clinic Name"
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${CYAN}=== $* ===${NC}"; }

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    err "Run with sudo"
    exit 1
  fi
}

require_root

# ── Detect public IP ──────────────────────────────────────────────────────────
PUBLIC_IP=$(curl -4 -fsS --max-time 8 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
info "Server public IP: ${PUBLIC_IP}"

# ── Detect main network interface ─────────────────────────────────────────────
IFACE=$(ip route show default | awk '/default/ {print $5; exit}')
if [[ -z "$IFACE" ]]; then
  IFACE="eth0"
  warn "Could not detect interface, defaulting to eth0"
fi
info "Network interface: ${IFACE}"

# ── Install WireGuard ─────────────────────────────────────────────────────────
section "Installing WireGuard"
apt-get update -y -qq
apt-get install -y wireguard wireguard-tools

# ── Generate server keys ──────────────────────────────────────────────────────
section "Generating server keys"
mkdir -p /etc/wireguard
chmod 700 /etc/wireguard

if [[ -f /etc/wireguard/server_private.key ]]; then
  warn "Server keys already exist — skipping key generation"
else
  wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
  chmod 600 /etc/wireguard/server_private.key
  info "Server keys created"
fi

SERVER_PRIV=$(cat /etc/wireguard/server_private.key)
SERVER_PUB=$(cat /etc/wireguard/server_public.key)

# ── Write wg0.conf ────────────────────────────────────────────────────────────
section "Writing /etc/wireguard/wg0.conf"

if [[ -f /etc/wireguard/wg0.conf ]]; then
  cp /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.bak
  warn "Existing wg0.conf backed up to wg0.conf.bak"
fi

cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address    = 10.8.0.1/24
ListenPort = 51820
PrivateKey = ${SERVER_PRIV}

# NAT: allow VPN clients to reach the DICOM port on this server
PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o ${IFACE} -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o ${IFACE} -j MASQUERADE

# Clinics are appended below by add-clinic.sh
EOF

chmod 600 /etc/wireguard/wg0.conf
info "wg0.conf written"

# ── IP forwarding ─────────────────────────────────────────────────────────────
section "Enabling IP forwarding"
grep -qxF 'net.ipv4.ip_forward=1' /etc/sysctl.conf || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -p -q
info "IP forwarding enabled"

# ── Start WireGuard ───────────────────────────────────────────────────────────
section "Starting WireGuard"
systemctl enable wg-quick@wg0
systemctl restart wg-quick@wg0
sleep 2

if systemctl is-active --quiet wg-quick@wg0; then
  info "WireGuard is running"
  wg show
else
  err "WireGuard failed to start — check: journalctl -u wg-quick@wg0 -n 30"
  exit 1
fi

# ── Store metadata for add-clinic.sh ─────────────────────────────────────────
cat > /etc/wireguard/server_meta <<EOF
SERVER_PUB=${SERVER_PUB}
SERVER_PUBLIC_IP=${PUBLIC_IP}
NEXT_CLIENT_IP=2
EOF
chmod 600 /etc/wireguard/server_meta

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  WireGuard server ready${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  VPN subnet   : 10.8.0.0/24"
echo "  Server VPN IP: 10.8.0.1"
echo "  Listen port  : 51820 (UDP)"
echo "  Public IP    : ${PUBLIC_IP}"
echo ""
echo -e "${YELLOW}ACTION REQUIRED — open UDP port 51820 in AWS Security Group:${NC}"
echo "  EC2 → Security Groups → Inbound rules → Add rule"
echo "  Type: Custom UDP | Port: 51820 | Source: 0.0.0.0/0"
echo ""
echo -e "${CYAN}Add a clinic (generates a ready-to-import config file):${NC}"
echo '  sudo bash tools/add-clinic.sh "Clinic Name"'
echo ""

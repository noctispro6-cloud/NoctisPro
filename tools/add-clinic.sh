#!/usr/bin/env bash
# =============================================================================
# NoctisPro — Add a clinic to the WireGuard VPN
# Usage:  sudo bash tools/add-clinic.sh "Clinic Name"
#
# Creates:
#   /etc/wireguard/clients/<slug>.conf  — import this on the clinic's PC
#   Appends a [Peer] block to /etc/wireguard/wg0.conf
#   Reloads WireGuard live (no downtime for existing clinics)
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Validate ──────────────────────────────────────────────────────────────────
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  err "Run with sudo"
  exit 1
fi

if [[ $# -lt 1 || -z "${1:-}" ]]; then
  err "Usage: sudo bash tools/add-clinic.sh \"Clinic Name\""
  exit 1
fi

CLINIC_NAME="$1"

if [[ ! -f /etc/wireguard/server_meta ]]; then
  err "Server not set up yet. Run: sudo bash tools/setup-wireguard.sh"
  exit 1
fi

# ── Load server metadata ──────────────────────────────────────────────────────
source /etc/wireguard/server_meta   # provides SERVER_PUB, SERVER_PUBLIC_IP, NEXT_CLIENT_IP

CLIENT_IP="10.8.0.${NEXT_CLIENT_IP}"
SLUG=$(echo "$CLINIC_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-\|-$//g')
OUT_DIR="/etc/wireguard/clients"
OUT_FILE="${OUT_DIR}/${SLUG}.conf"

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

# ── Check for duplicate ───────────────────────────────────────────────────────
if grep -q "# CLINIC: ${CLINIC_NAME}" /etc/wireguard/wg0.conf 2>/dev/null; then
  err "A clinic named '${CLINIC_NAME}' is already registered."
  exit 1
fi

# ── Generate client keypair ───────────────────────────────────────────────────
CLIENT_PRIV=$(wg genkey)
CLIENT_PUB=$(echo "$CLIENT_PRIV" | wg pubkey)

info "Clinic      : ${CLINIC_NAME}"
info "VPN IP      : ${CLIENT_IP}"
info "Config file : ${OUT_FILE}"

# ── Write client config (import this on the clinic PC) ───────────────────────
cat > "$OUT_FILE" <<EOF
# WireGuard config for: ${CLINIC_NAME}
# Import this file on the clinic's Windows/Linux PC via the WireGuard app.
# The PC must be on the same local network as the imaging machine.
#
# Imaging machine DICOM settings:
#   Called AE Title : NOCTIS_SCP
#   Host / IP       : 10.8.0.1
#   Port            : 11112

[Interface]
PrivateKey = ${CLIENT_PRIV}
Address    = ${CLIENT_IP}/24
DNS        = 1.1.1.1

[Peer]
PublicKey           = ${SERVER_PUB}
Endpoint            = ${SERVER_PUBLIC_IP}:51820
AllowedIPs          = 10.8.0.1/32
PersistentKeepalive = 25
EOF

chmod 600 "$OUT_FILE"

# ── Append peer to server config ──────────────────────────────────────────────
cat >> /etc/wireguard/wg0.conf <<EOF

# CLINIC: ${CLINIC_NAME}
[Peer]
PublicKey  = ${CLIENT_PUB}
AllowedIPs = ${CLIENT_IP}/32
EOF

# ── Reload WireGuard without dropping existing connections ───────────────────
wg syncconf wg0 <(wg-quick strip wg0)
info "WireGuard reloaded — existing clinics unaffected"

# ── Bump next IP counter ──────────────────────────────────────────────────────
NEXT=$((NEXT_CLIENT_IP + 1))
sed -i "s/^NEXT_CLIENT_IP=.*/NEXT_CLIENT_IP=${NEXT}/" /etc/wireguard/server_meta

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Clinic added: ${CLINIC_NAME}${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  Clinic VPN IP : ${CLIENT_IP}"
echo "  Config file   : ${OUT_FILE}"
echo ""
echo -e "${CYAN}Steps for the clinic:${NC}"
echo "  1. Install WireGuard for Windows: https://www.wireguard.com/install/"
echo "  2. Copy ${OUT_FILE} to the clinic PC"
echo "  3. Open WireGuard → 'Import tunnel from file' → select the .conf file"
echo "  4. Click 'Activate'"
echo ""
echo -e "${CYAN}Configure the imaging machine DICOM destination:${NC}"
echo "  Called AE Title : NOCTIS_SCP"
echo "  Host / IP       : 10.8.0.1"
echo "  Port            : 11112"
echo ""
echo -e "${CYAN}Test from the clinic PC (once VPN is active):${NC}"
echo "  ping 10.8.0.1"
echo ""
echo -e "${YELLOW}To view the config file contents (send to clinic):${NC}"
echo "  cat ${OUT_FILE}"
echo ""

# Show current peers
wg show

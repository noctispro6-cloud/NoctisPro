#!/usr/bin/env bash
# =============================================================================
# NoctisPro — Register a clinic's Tailscale IP for DICOM receive
# Usage:  sudo bash tools/add-clinic-tailscale.sh "Clinic Name" 100.x.x.x
#
# What it does:
#   1. Records the clinic name + Tailscale IP
#   2. Adds the IP to DICOM_ALLOWED_NETS in the env file
#   3. Restarts the DICOM receiver live (no downtime)
#   4. Prints exact settings for the modality and clinic PC
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${CYAN}=== $* ===${NC}"; }

# ── Help ──────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo ""
  echo "Usage: sudo bash tools/add-clinic-tailscale.sh \"Clinic Name\" 100.x.x.x"
  echo ""
  echo "The clinic PC must:"
  echo "  1. Have Tailscale installed and logged into the SAME account as the server"
  echo "  2. Have a DICOM forwarder running to relay from the modality:"
  echo ""
  echo "     Option A — Orthanc (full PACS, free):"
  echo "       https://www.orthanc-server.com/download.php"
  echo "       Configure DicomModalities to forward to this server's Tailscale IP"
  echo ""
  echo "     Option B — dcm4che storescu (command line):"
  echo "       Modality → clinic PC (receives on port 104) → forwards to server:11112"
  echo ""
  echo "     Option C — Simple Python forwarder (included below, run on clinic PC):"
  echo "       python3 tools/dicom_forwarder.py --listen 104 --target SERVER_TS_IP:11112"
  echo ""
  exit 0
fi

# ── Validate ──────────────────────────────────────────────────────────────────
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  err "Run with sudo"
  exit 1
fi

if [[ $# -lt 2 ]]; then
  err "Usage: sudo bash tools/add-clinic-tailscale.sh \"Clinic Name\" 100.x.x.x"
  exit 1
fi

CLINIC_NAME="$1"
CLINIC_IP="$2"

# Validate it looks like a Tailscale IP
if ! echo "$CLINIC_IP" | grep -qE '^100\.(6[4-9]|[7-9][0-9]|1[0-2][0-7])\.[0-9]{1,3}\.[0-9]{1,3}$'; then
  err "IP '${CLINIC_IP}' does not look like a Tailscale address (should be 100.64.x.x – 100.127.x.x)"
  exit 1
fi

# ── Load server metadata ──────────────────────────────────────────────────────
META=/etc/noctis-pro/tailscale_meta
if [[ ! -f "$META" ]]; then
  err "Server Tailscale not set up yet. Run: sudo bash tools/setup-tailscale.sh"
  exit 1
fi
source "$META"   # provides SERVER_TS_IP

# ── Check for duplicate ───────────────────────────────────────────────────────
REGISTRY=/etc/noctis-pro/tailscale_clinics
touch "$REGISTRY"
if grep -q "^${CLINIC_IP}," "$REGISTRY" 2>/dev/null; then
  warn "IP ${CLINIC_IP} already registered — updating name"
  sed -i "/^${CLINIC_IP},/d" "$REGISTRY"
fi

# ── Register clinic ───────────────────────────────────────────────────────────
echo "${CLINIC_IP},${CLINIC_NAME},$(date +%Y-%m-%d)" >> "$REGISTRY"
info "Clinic '${CLINIC_NAME}' registered with IP ${CLINIC_IP}"

# ── Add IP to DICOM_ALLOWED_NETS ──────────────────────────────────────────────
section "Updating DICOM allowed networks"

ADDED=0
for ENV_FILE in /etc/noctis-pro/noctis-pro.env /etc/noctispro/noctispro.env; do
  [[ -f "$ENV_FILE" ]] || continue
  ADDED=1

  if grep -q "^DICOM_ALLOWED_NETS=" "$ENV_FILE"; then
    CURRENT=$(grep "^DICOM_ALLOWED_NETS=" "$ENV_FILE" | cut -d= -f2- | tr -d '"')
    if echo "$CURRENT" | grep -q "$CLINIC_IP"; then
      info "IP already in DICOM_ALLOWED_NETS in ${ENV_FILE}"
    else
      NEW_VAL="${CURRENT:+${CURRENT},}${CLINIC_IP}"
      sed -i "s|^DICOM_ALLOWED_NETS=.*|DICOM_ALLOWED_NETS=\"${NEW_VAL}\"|" "$ENV_FILE"
      info "Added ${CLINIC_IP} to DICOM_ALLOWED_NETS in ${ENV_FILE}"
    fi
  else
    echo "DICOM_ALLOWED_NETS=\"${CLINIC_IP}\"" >> "$ENV_FILE"
    info "Added DICOM_ALLOWED_NETS to ${ENV_FILE}"
  fi
done

if [[ $ADDED -eq 0 ]]; then
  mkdir -p /etc/noctis-pro
  echo "DICOM_ALLOWED_NETS=\"${CLINIC_IP}\"" > /etc/noctis-pro/noctis-pro.env
  info "Created /etc/noctis-pro/noctis-pro.env with DICOM_ALLOWED_NETS"
fi

# ── Restart DICOM receiver ────────────────────────────────────────────────────
section "Reloading DICOM receiver"
if systemctl is-active --quiet noctis-pro-dicom; then
  systemctl restart noctis-pro-dicom
  info "DICOM receiver restarted — new IP active"
else
  warn "noctis-pro-dicom not running — start it when ready"
fi

# ── Show all registered clinics ───────────────────────────────────────────────
section "Registered clinics"
echo ""
printf "  %-18s %-25s %s\n" "Tailscale IP" "Clinic Name" "Added"
printf "  %-18s %-25s %s\n" "──────────────────" "─────────────────────────" "──────────"
while IFS=, read -r ip name date; do
  printf "  %-18s %-25s %s\n" "$ip" "$name" "$date"
done < "$REGISTRY"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Clinic added: ${CLINIC_NAME}${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  Clinic Tailscale IP : ${CLINIC_IP}"
echo "  Server Tailscale IP : ${SERVER_TS_IP}"
echo ""
echo -e "${CYAN}Steps for the clinic PC:${NC}"
echo "  1. Install Tailscale and sign in to the same account"
echo "  2. Make sure Tailscale shows IP: ${CLINIC_IP}"
echo "  3. Run a DICOM forwarder (Orthanc or simple forwarder)"
echo ""
echo -e "${CYAN}Modality DICOM settings (on CT/MRI scanner):${NC}"
echo "  Called AE Title : NOCTIS_SCP"
echo "  Host / IP       : ${CLINIC_IP}  ← send to clinic PC first"
echo "  Port            : 104 (or whatever the forwarder listens on)"
echo ""
echo -e "${CYAN}Clinic PC forwarder target:${NC}"
echo "  Forward to      : ${SERVER_TS_IP}:11112"
echo "  AE Title        : NOCTIS_SCP"
echo ""
echo -e "${CYAN}Test from clinic PC (after Tailscale is connected):${NC}"
echo "  ping ${SERVER_TS_IP}"
echo ""

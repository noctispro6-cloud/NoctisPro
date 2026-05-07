#!/usr/bin/env bash
# =============================================================================
# NoctisPro — Tailscale Setup (Server)
# Run once on the server:  sudo bash tools/setup-tailscale.sh
#
# What it does:
#   1. Installs Tailscale
#   2. Starts and authenticates (you follow the URL it prints)
#   3. Adds the Tailscale subnet (100.64.0.0/10) to DICOM_ALLOWED_NETS
#      in /etc/noctis-pro/noctis-pro.env
#   4. Restarts the DICOM receiver so it picks up the new allowlist
#
# After setup, add each clinic with:
#   sudo bash tools/add-clinic-tailscale.sh "Clinic Name" 100.x.x.x
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${CYAN}=== $* ===${NC}"; }

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  err "Run with sudo"
  exit 1
fi

# ── Install Tailscale ─────────────────────────────────────────────────────────
section "Installing Tailscale"
if command -v tailscale &>/dev/null; then
  info "Tailscale already installed — $(tailscale version | head -1)"
else
  curl -fsSL https://tailscale.com/install.sh | sh
  info "Tailscale installed"
fi

# ── Start and authenticate ────────────────────────────────────────────────────
section "Starting Tailscale"
systemctl enable --now tailscaled 2>/dev/null || true

if tailscale status &>/dev/null 2>&1; then
  info "Already authenticated"
else
  info "Opening browser auth — follow the URL below:"
  tailscale up --ssh
fi

# ── Get Tailscale IP ──────────────────────────────────────────────────────────
TS_IP=$(tailscale ip -4 2>/dev/null || echo "")
if [[ -z "$TS_IP" ]]; then
  err "Could not get Tailscale IP — make sure you completed authentication"
  exit 1
fi
info "Server Tailscale IP: ${TS_IP}"

# ── Update DICOM_ALLOWED_NETS ─────────────────────────────────────────────────
section "Updating DICOM allowed networks"

# The Tailscale CGNAT range — covers all Tailscale device IPs
TS_SUBNET="100.64.0.0/10"

# Try both possible env file locations
for ENV_FILE in /etc/noctis-pro/noctis-pro.env /etc/noctispro/noctispro.env; do
  [[ -f "$ENV_FILE" ]] || continue

  if grep -q "DICOM_ALLOWED_NETS" "$ENV_FILE"; then
    # Append Tailscale subnet to existing value if not already there
    CURRENT=$(grep "^DICOM_ALLOWED_NETS=" "$ENV_FILE" | cut -d= -f2- | tr -d '"')
    if echo "$CURRENT" | grep -q "$TS_SUBNET"; then
      info "Tailscale subnet already in DICOM_ALLOWED_NETS in ${ENV_FILE}"
    else
      NEW_VAL="${CURRENT:+${CURRENT},}${TS_SUBNET}"
      sed -i "s|^DICOM_ALLOWED_NETS=.*|DICOM_ALLOWED_NETS=\"${NEW_VAL}\"|" "$ENV_FILE"
      info "Updated DICOM_ALLOWED_NETS in ${ENV_FILE}"
    fi
  else
    echo "DICOM_ALLOWED_NETS=\"${TS_SUBNET}\"" >> "$ENV_FILE"
    info "Added DICOM_ALLOWED_NETS to ${ENV_FILE}"
  fi
done

# If no env file exists yet, create the primary one
if [[ ! -f /etc/noctis-pro/noctis-pro.env ]] && [[ ! -f /etc/noctispro/noctispro.env ]]; then
  mkdir -p /etc/noctis-pro
  echo "DICOM_ALLOWED_NETS=\"${TS_SUBNET}\"" > /etc/noctis-pro/noctis-pro.env
  info "Created /etc/noctis-pro/noctis-pro.env with DICOM_ALLOWED_NETS"
fi

# ── Restart DICOM receiver ────────────────────────────────────────────────────
section "Restarting DICOM receiver"
if systemctl is-active --quiet noctis-pro-dicom; then
  systemctl restart noctis-pro-dicom
  info "DICOM receiver restarted"
else
  warn "noctis-pro-dicom service not active — start it manually when ready"
fi

# ── Save Tailscale metadata for add-clinic-tailscale.sh ──────────────────────
mkdir -p /etc/noctis-pro
cat > /etc/noctis-pro/tailscale_meta <<EOF
SERVER_TS_IP=${TS_IP}
EOF
chmod 600 /etc/noctis-pro/tailscale_meta
info "Metadata saved to /etc/noctis-pro/tailscale_meta"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Tailscale server ready${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  Server Tailscale IP : ${TS_IP}"
echo "  DICOM allowed range : ${TS_SUBNET}  (all Tailscale devices)"
echo "  DICOM port          : 11112"
echo "  DICOM AE title      : NOCTIS_SCP"
echo ""
echo -e "${CYAN}Clinic PC setup (Windows or Linux):${NC}"
echo "  1. Install Tailscale: https://tailscale.com/download"
echo "  2. Sign in to the SAME Tailscale account as this server"
echo "  3. Note the clinic PC's Tailscale IP (100.x.x.x)"
echo ""
echo -e "${CYAN}Register the clinic and get their IP into the system:${NC}"
echo '  sudo bash tools/add-clinic-tailscale.sh "Clinic Name" 100.x.x.x'
echo ""
echo -e "${CYAN}Modality DICOM settings (on CT/MRI/X-ray):${NC}"
echo "  Called AE Title : NOCTIS_SCP"
echo "  Host / IP       : ${TS_IP}"
echo "  Port            : 11112"
echo ""
echo -e "${YELLOW}NOTE: The modality cannot use Tailscale directly.${NC}"
echo "  Set up a DICOM forwarder on the clinic PC — see:"
echo '  sudo bash tools/add-clinic-tailscale.sh --help'
echo ""

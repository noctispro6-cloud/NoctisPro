#!/usr/bin/env bash
# NoctisPro server bootstrap — run once on a fresh Ubuntu 22.04 / 24.04 VPS.
# Usage: sudo bash scripts/install-server.sh
set -euo pipefail

APP_DIR="/opt/noctispro"
REPO_URL="${NOCTISPRO_REPO:-}"   # set this or clone manually before running

log()  { echo -e "\e[32m[install]\e[0m $*"; }
warn() { echo -e "\e[33m[warn]\e[0m $*"; }
die()  { echo -e "\e[31m[error]\e[0m $*"; exit 1; }

[ "$(id -u)" = "0" ] || die "Run as root: sudo bash $0"

# ── 1. System updates ────────────────────────────────────────────────────────
log "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl git ufw fail2ban unattended-upgrades \
    ca-certificates gnupg lsb-release

# ── 2. Docker ────────────────────────────────────────────────────────────────
log "Installing Docker..."
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
    log "Docker installed: $(docker --version)"
else
    log "Docker already installed."
fi

# ── 3. Firewall ──────────────────────────────────────────────────────────────
log "Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     comment 'SSH'
ufw allow 80/tcp     comment 'HTTP (Let'\''s Encrypt / redirect)'
ufw allow 443/tcp    comment 'HTTPS'
ufw allow 11112/tcp  comment 'DICOM C-STORE'
ufw --force enable
ufw status verbose

# ── 4. SSH hardening ─────────────────────────────────────────────────────────
log "Hardening SSH..."
SSHD=/etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/'  "$SSHD"
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/'  "$SSHD"
sed -i 's/^#*MaxAuthTries.*/MaxAuthTries 3/'                        "$SSHD"
systemctl reload sshd
log "SSH: password auth disabled, root login restricted."

# ── 5. Fail2ban ──────────────────────────────────────────────────────────────
log "Configuring fail2ban..."
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
port    = 22
EOF
systemctl enable --now fail2ban
log "Fail2ban active."

# ── 6. Unattended security upgrades ─────────────────────────────────────────
log "Enabling automatic security updates..."
cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF
systemctl enable --now unattended-upgrades

# ── 7. Clone repository ──────────────────────────────────────────────────────
if [ -n "$REPO_URL" ]; then
    log "Cloning repository to $APP_DIR..."
    git clone "$REPO_URL" "$APP_DIR"
else
    warn "NOCTISPRO_REPO not set — skipping clone."
    warn "Manually run: git clone <repo-url> $APP_DIR"
fi

# ── 8. Systemd service for auto-start ────────────────────────────────────────
log "Installing NoctisPro systemd service..."
cat > /etc/systemd/system/noctispro.service <<EOF
[Unit]
Description=NoctisPro PACS Stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d --remove-orphans
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=300
TimeoutStopSec=120
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable noctispro.service
log "Systemd service installed. Stack will start automatically on reboot."

# ── 9. 3 AM auto-update cron ────────────────────────────────────────────────
log "Installing nightly update cron job..."
cat > /etc/cron.d/noctispro-update <<EOF
# NoctisPro: pull latest code and rebuild at 3:00 AM server time
0 3 * * * root bash $APP_DIR/scripts/update.sh >> /var/log/noctispro-update.log 2>&1
EOF
chmod 644 /etc/cron.d/noctispro-update
log "Cron job installed: runs at 03:00 daily."

# ── 10. Logrotate ────────────────────────────────────────────────────────────
cat > /etc/logrotate.d/noctispro <<EOF
/var/log/noctispro-update.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
}
EOF

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
log "=== Server bootstrap complete ==="
echo ""
echo "  Next steps:"
echo "  1. cd $APP_DIR"
echo "  2. cp .env.docker.example .env.docker && nano .env.docker"
echo "  3. bash scripts/setup-tls.sh        # get Cloudflare origin cert"
echo "  4. sudo systemctl start noctispro   # start the stack"
echo ""

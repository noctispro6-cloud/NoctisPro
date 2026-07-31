#!/usr/bin/env bash
# One-time setup on the opportunistic SECONDARY node (e.g. a laptop VM) to join a NoctisPro
# cloud deployment over Tailscale. Run scripts/setup-cloud-node.sh on the cloud server FIRST
# and have its Tailscale IP + NFS export path ready. See DEPLOY_OPPORTUNISTIC_NODE.md for
# the full picture.
#
# Usage: sudo bash scripts/setup-laptop-node.sh <cloud-tailscale-addr> <nfs-export-path>
set -euo pipefail

CLOUD_ADDR="${1:?Usage: $0 <cloud-tailscale-addr> <nfs-export-path>}"
EXPORT_PATH="${2:?Usage: $0 <cloud-tailscale-addr> <nfs-export-path>}"
MOUNT_POINT="/mnt/noctis-media-nfs"

log()  { echo -e "\e[32m[laptop-node]\e[0m $*"; }
warn() { echo -e "\e[33m[warn]\e[0m $*"; }
die()  { echo -e "\e[31m[error]\e[0m $*"; exit 1; }

[ "$(id -u)" = "0" ] || die "Run as root: sudo bash $0 <cloud-tailscale-addr> <nfs-export-path>"

# ── 1. Tailscale ──────────────────────────────────────────────────────────────
if ! command -v tailscale &>/dev/null; then
    log "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
else
    log "Tailscale already installed."
fi

if ! tailscale ip -4 &>/dev/null; then
    log "Authenticating this node with Tailscale — follow the printed URL in a browser."
    tailscale up
fi
log "This node's Tailscale IP: $(tailscale ip -4)"

# ── 2. Mount the cloud server's media export over NFS ─────────────────────────
if ! command -v mount.nfs &>/dev/null; then
    log "Installing nfs-common..."
    apt-get update -qq
    apt-get install -y -qq nfs-common
fi

mkdir -p "$MOUNT_POINT"
if ! grep -qF "$MOUNT_POINT" /etc/fstab 2>/dev/null; then
    # nofail + x-systemd.automount: this VM still boots fine, and can still be worked on,
    # even if the cloud server or Tailscale happens to be unreachable at boot time — the
    # mount is attempted lazily on first access instead of blocking startup.
    echo "${CLOUD_ADDR}:${EXPORT_PATH} ${MOUNT_POINT} nfs4 nofail,x-systemd.automount,noatime 0 0" >> /etc/fstab
    log "Added fstab entry for ${MOUNT_POINT}."
else
    log "fstab entry for ${MOUNT_POINT} already present — leaving as-is."
fi
systemctl daemon-reload
mount "$MOUNT_POINT" || die "Mount failed — check the cloud server's UFW/exportfs (scripts/setup-cloud-node.sh) and that Tailscale is up on both ends."
log "Mounted ${CLOUD_ADDR}:${EXPORT_PATH} at ${MOUNT_POINT}."

# ── 3. Docker ──────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    log "Installing Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
else
    log "Docker already installed."
fi

log ""
log "Tailscale + NFS + Docker are ready. Remaining manual steps (this repo must already be"
log "checked out on this machine, e.g. /opt/noctispro):"
log "  1. cp .env.docker.node.example .env.docker.node"
log "  2. Edit .env.docker.node:"
log "       - SECRET_KEY / DB_PASSWORD / DB_NAME / DB_USER: copy EXACTLY from the cloud"
log "         server's .env.docker — a mismatched SECRET_KEY causes random logouts/CSRF"
log "         failures whenever a request lands on this node instead of the cloud."
log "       - CLOUD_TAILSCALE_ADDR=${CLOUD_ADDR}"
log "       - REDIS_URL / CELERY_BROKER_URL / CELERY_RESULT_BACKEND -> redis://${CLOUD_ADDR}:6379/0"
log "         (add :<password>@ if the cloud server set REDIS_PASSWORD)"
log "       - NODE_MEDIA_MOUNT=${MOUNT_POINT}"
log "  3. docker compose -f docker-compose.node.yml up -d --build"
log "  4. Back on the cloud server, register this node with HAProxy:"
log "       scripts/add-opportunistic-node.sh add <name> $(tailscale ip -4):8000"

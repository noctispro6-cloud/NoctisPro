#!/usr/bin/env bash
# One-time setup on the CLOUD server to accept an opportunistic secondary node (e.g. a
# laptop) over Tailscale: installs Tailscale, exports the media volume over NFS restricted
# to the tailnet, and opens the firewall for exactly that traffic. See
# DEPLOY_OPPORTUNISTIC_NODE.md for the full picture — this is one half of it; the other
# half is scripts/setup-laptop-node.sh, run on the secondary node.
set -euo pipefail

NFS_SUBNET="100.64.0.0/10"   # Tailscale's CGNAT range — every tailnet device, nothing else.

log()  { echo -e "\e[32m[cloud-node]\e[0m $*"; }
warn() { echo -e "\e[33m[warn]\e[0m $*"; }
die()  { echo -e "\e[31m[error]\e[0m $*"; exit 1; }

[ "$(id -u)" = "0" ] || die "Run as root: sudo bash $0"

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

TS_IP="$(tailscale ip -4)"
log "This server's Tailscale IP: ${TS_IP}"

# ── 2. Firewall: allow the tailnet to reach NFS / pgbouncer / redis ──────────
# Everything else on this host stays exactly as scripts/install-server.sh left it — this
# only adds allow rules scoped to the tailnet subnet, it doesn't touch existing rules.
if command -v ufw &>/dev/null; then
    log "Opening firewall for the tailnet (${NFS_SUBNET}) -> NFS/pgbouncer/redis..."
    ufw allow from "$NFS_SUBNET" to any port 2049 proto tcp comment 'NFS (tailnet only)'
    ufw allow from "$NFS_SUBNET" to any port 6432 proto tcp comment 'pgbouncer (tailnet only)'
    ufw allow from "$NFS_SUBNET" to any port 6379 proto tcp comment 'redis (tailnet only)'
else
    warn "ufw not found — make sure ports 2049/6432/6379 are reachable from ${NFS_SUBNET} some other way."
fi

# ── 3. NFS export of the media volume ─────────────────────────────────────────
if ! command -v exportfs &>/dev/null; then
    log "Installing nfs-kernel-server..."
    apt-get update -qq
    apt-get install -y -qq nfs-kernel-server
fi

MEDIA_VOL="$(docker volume ls --format '{{.Name}}' | grep -E '_noctis_media$' | head -n1 || true)"
[ -n "$MEDIA_VOL" ] || die "Couldn't find the noctis_media Docker volume — has the stack been started at least once (docker compose -f docker-compose.prod.yml up -d)?"
MEDIA_PATH="$(docker volume inspect "$MEDIA_VOL" --format '{{ .Mountpoint }}')"
log "Media volume: ${MEDIA_VOL} -> ${MEDIA_PATH}"

EXPORT_LINE="${MEDIA_PATH} ${NFS_SUBNET}(rw,sync,no_subtree_check,no_root_squash)"
if ! grep -qF "$MEDIA_PATH" /etc/exports 2>/dev/null; then
    echo "$EXPORT_LINE" >> /etc/exports
    log "Added export: $EXPORT_LINE"
else
    log "Export for $MEDIA_PATH already present in /etc/exports — leaving as-is."
fi
exportfs -ra
systemctl enable --now nfs-kernel-server

log ""
log "Done. On the secondary node, run scripts/setup-laptop-node.sh with:"
log "  CLOUD_TAILSCALE_ADDR = ${TS_IP}"
log "  NFS export path      = ${MEDIA_PATH}"
log ""
log "Then, back on this server:"
log "  - Add TAILSCALE_IP=${TS_IP} to .env.docker (and REDIS_PASSWORD, if you want redis"
log "    authenticated over the tailnet — see the comment on the redis service in"
log "    docker-compose.prod.yml) and run: docker compose -f docker-compose.prod.yml up -d"
log "  - Once the secondary node is up and reachable, register it with HAProxy:"
log "      scripts/add-opportunistic-node.sh add <name> <secondary-tailscale-ip>:8000"

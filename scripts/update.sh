#!/usr/bin/env bash
# NoctisPro zero-downtime update script
# Runs automatically via cron at 3 AM, or manually: sudo bash scripts/update.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="docker compose -f $APP_DIR/docker-compose.prod.yml --env-file $APP_DIR/.env.docker"
LOGFILE="/var/log/noctispro-update.log"
BRANCH="${NOCTISPRO_BRANCH:-main}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOGFILE"; }

cd "$APP_DIR"

# Auto-size each service's Docker `mem_limit` from this host's actual RAM (shared with
# scripts/start-stack.sh, which applies the same sizing on initial boot). web/celery/dicom get
# recreated by this script on every run, so they pick up a fresh limit each time; db/redis/pgbouncer/
# nginx only pick up a changed limit the next time *they* happen to be recreated (this script
# deliberately leaves them running for zero-downtime updates), but exporting these now means a
# fresh `up` of the full stack always gets sane values without anyone hand-tuning them.
# shellcheck source=./compute-prod-mem-limits.sh
source "$APP_DIR/scripts/compute-prod-mem-limits.sh"
log "Detected ${total_mb}MB host RAM -> mem_limit db=${DB_MEM_LIMIT} pgbouncer=${PGBOUNCER_MEM_LIMIT} redis=${REDIS_MEM_LIMIT} web=${WEB_MEM_LIMIT} celery=${CELERY_MEM_LIMIT} dicom=${DICOM_MEM_LIMIT} nginx=${NGINX_MEM_LIMIT} lb=${HAPROXY_MEM_LIMIT}"

# Preserve a manually-scaled replica count across this update. `up -d` without --scale
# would otherwise reset web/celery back down to 1 replica each, since Compose doesn't
# remember an ad-hoc --scale count between separate `up` invocations.
# shellcheck source=./read-replica-counts.sh
source "$APP_DIR/scripts/read-replica-counts.sh"
log "Replica counts -> web=${WEB_REPLICAS} celery=${CELERY_REPLICAS}"

log "=== NoctisPro update started ==="

# 1. Pull latest code
# --force (or FORCE_UPDATE=1) skips the "nothing changed" shortcut below and always
# rebuilds/restarts — needed after someone `git pull`s by hand (e.g. to inspect a
# file) without rebuilding, or after a prior run of this script died before it
# reached the build step; in both cases HEAD == origin but the running containers
# are still on stale code/deps.
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1
[ "${FORCE_UPDATE:-}" = "1" ] && FORCE=1

log "Pulling $BRANCH from origin..."
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ] && [ "$FORCE" -ne 1 ]; then
    log "Already up to date ($LOCAL). Nothing to do. (use --force to rebuild/restart anyway)"
    exit 0
fi

if [ "$LOCAL" = "$REMOTE" ]; then
    log "Already up to date ($LOCAL); --force given, rebuilding/restarting anyway."
else
    log "New commits available: $LOCAL -> $REMOTE"
    git pull origin "$BRANCH"
fi

# 2. Build new images without stopping current containers
log "Building new images..."
$COMPOSE build --pull

# 3. Run migrations before switching traffic
# Spin up a temporary container that runs migrate only, then exits.
log "Running migrations..."
$COMPOSE run --rm --no-deps web python manage.py migrate --noinput

# 4. Collect static files
log "Collecting static files..."
$COMPOSE run --rm --no-deps web python manage.py collectstatic --noinput --clear

# 5. Reload services — Compose replaces containers one service at a time.
# web + celery + dicom restart with new image; db/redis/pgbouncer are unchanged.
log "Restarting application services..."
$COMPOSE up -d --no-deps --scale "web=${WEB_REPLICAS}" --scale "celery=${CELERY_REPLICAS}" web celery dicom

# 6. Restart the load balancer unconditionally. haproxy/haproxy.cfg is bind-mounted, so a
# `git pull` that changed it wouldn't otherwise take effect — Compose only recreates a
# container when the *service definition* changes, not when a bind-mounted file's contents do.
# Cheap: HAProxy holds no state, and web/celery/dicom above already introduce a brief blip.
log "Restarting load balancer..."
$COMPOSE up -d --no-deps --force-recreate lb

log "=== Update complete. Running revision: $(git rev-parse --short HEAD) ==="

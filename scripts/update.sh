#!/usr/bin/env bash
# NoctisPro zero-downtime update script
# Runs automatically via cron at 3 AM, or manually: sudo bash scripts/update.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="docker compose -f $APP_DIR/docker-compose.prod.yml"
LOGFILE="/var/log/noctispro-update.log"
BRANCH="${NOCTISPRO_BRANCH:-main}"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOGFILE"; }

cd "$APP_DIR"

# Auto-size each service's Docker `mem_limit` from this host's actual RAM (same approach as
# deploy-docker.sh — see the longer comment there). web/celery/dicom get recreated by this script
# on every run, so they pick up a fresh limit each time; db/redis/pgbouncer/nginx only pick up a
# changed limit the next time *they* happen to be recreated (this script deliberately leaves them
# running for zero-downtime updates), but exporting these now means a fresh `up` of the full stack
# always gets sane values without anyone hand-tuning them.
total_mb="$(awk '/MemTotal:/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 1024)"
allocatable_mb=$(( total_mb * 85 / 100 ))
DB_MEM_LIMIT="$(( allocatable_mb * 20 / 100 ))"; (( DB_MEM_LIMIT < 256 )) && DB_MEM_LIMIT=256
PGBOUNCER_MEM_LIMIT="$(( allocatable_mb * 3 / 100 ))"; (( PGBOUNCER_MEM_LIMIT < 32 )) && PGBOUNCER_MEM_LIMIT=32
REDIS_MEM_LIMIT="$(( allocatable_mb * 7 / 100 ))"; (( REDIS_MEM_LIMIT < 64 )) && REDIS_MEM_LIMIT=64
WEB_MEM_LIMIT="$(( allocatable_mb * 45 / 100 ))"; (( WEB_MEM_LIMIT < 256 )) && WEB_MEM_LIMIT=256
CELERY_MEM_LIMIT="$(( allocatable_mb * 17 / 100 ))"; (( CELERY_MEM_LIMIT < 192 )) && CELERY_MEM_LIMIT=192
DICOM_MEM_LIMIT="$(( allocatable_mb * 6 / 100 ))"; (( DICOM_MEM_LIMIT < 256 )) && DICOM_MEM_LIMIT=256
NGINX_MEM_LIMIT="$(( allocatable_mb * 2 / 100 ))"; (( NGINX_MEM_LIMIT < 64 )) && NGINX_MEM_LIMIT=64
export DB_MEM_LIMIT="${DB_MEM_LIMIT}m" PGBOUNCER_MEM_LIMIT="${PGBOUNCER_MEM_LIMIT}m" \
       REDIS_MEM_LIMIT="${REDIS_MEM_LIMIT}m" WEB_MEM_LIMIT="${WEB_MEM_LIMIT}m" \
       CELERY_MEM_LIMIT="${CELERY_MEM_LIMIT}m" DICOM_MEM_LIMIT="${DICOM_MEM_LIMIT}m" \
       NGINX_MEM_LIMIT="${NGINX_MEM_LIMIT}m"
log "Detected ${total_mb}MB host RAM -> mem_limit db=${DB_MEM_LIMIT} pgbouncer=${PGBOUNCER_MEM_LIMIT} redis=${REDIS_MEM_LIMIT} web=${WEB_MEM_LIMIT} celery=${CELERY_MEM_LIMIT} dicom=${DICOM_MEM_LIMIT} nginx=${NGINX_MEM_LIMIT}"

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
$COMPOSE up -d --no-deps web celery dicom

log "=== Update complete. Running revision: $(git rev-parse --short HEAD) ==="

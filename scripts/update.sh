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

log "=== NoctisPro update started ==="

# 1. Pull latest code
log "Pulling $BRANCH from origin..."
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    log "Already up to date ($LOCAL). Nothing to do."
    exit 0
fi

log "New commits available: $LOCAL -> $REMOTE"
git pull origin "$BRANCH"

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

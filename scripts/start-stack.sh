#!/usr/bin/env bash
# Starts the production stack with host-appropriate mem_limits. Used as the
# noctispro.service ExecStart (see scripts/install-server.sh) so the *first*
# boot/reboot gets the same sizing scripts/update.sh applies on every nightly
# update — without this, `docker compose up` alone falls back to the static
# defaults baked into docker-compose.prod.yml regardless of host RAM.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

# shellcheck source=./compute-prod-mem-limits.sh
source "$APP_DIR/scripts/compute-prod-mem-limits.sh"
echo "[start-stack] Detected ${total_mb}MB host RAM -> mem_limit db=${DB_MEM_LIMIT} pgbouncer=${PGBOUNCER_MEM_LIMIT} redis=${REDIS_MEM_LIMIT} web=${WEB_MEM_LIMIT} celery=${CELERY_MEM_LIMIT} dicom=${DICOM_MEM_LIMIT} nginx=${NGINX_MEM_LIMIT} lb=${HAPROXY_MEM_LIMIT}"

# shellcheck source=./read-replica-counts.sh
source "$APP_DIR/scripts/read-replica-counts.sh"
echo "[start-stack] Replica counts -> web=${WEB_REPLICAS} celery=${CELERY_REPLICAS}"

exec docker compose -f docker-compose.prod.yml --env-file .env.docker up -d --remove-orphans \
  --scale "web=${WEB_REPLICAS}" --scale "celery=${CELERY_REPLICAS}"

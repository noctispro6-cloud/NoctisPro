#!/usr/bin/env bash
# Shared by scripts/update.sh and scripts/start-stack.sh: auto-size each
# docker-compose.prod.yml service's `mem_limit` from this host's actual RAM,
# so a small VPS and a large one both get sane values without hand-tuning.
# Source this file (not exec) — it only exports variables, doesn't run anything.
#
# Proportions leave ~15% of host RAM for the OS/Docker daemon itself. Floors keep
# every service viable even on a very small instance; ${VAR:-fallback} in
# docker-compose.prod.yml covers the case this is skipped entirely (e.g. compose
# invoked directly without either wrapper script).

total_mb="$(awk '/MemTotal:/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 1024)"
allocatable_mb=$(( total_mb * 85 / 100 ))

DB_MEM_LIMIT="$(( allocatable_mb * 20 / 100 ))"; (( DB_MEM_LIMIT < 256 )) && DB_MEM_LIMIT=256
PGBOUNCER_MEM_LIMIT="$(( allocatable_mb * 3 / 100 ))"; (( PGBOUNCER_MEM_LIMIT < 32 )) && PGBOUNCER_MEM_LIMIT=32
REDIS_MEM_LIMIT="$(( allocatable_mb * 7 / 100 ))"; (( REDIS_MEM_LIMIT < 64 )) && REDIS_MEM_LIMIT=64
WEB_MEM_LIMIT="$(( allocatable_mb * 44 / 100 ))"; (( WEB_MEM_LIMIT < 256 )) && WEB_MEM_LIMIT=256
CELERY_MEM_LIMIT="$(( allocatable_mb * 17 / 100 ))"; (( CELERY_MEM_LIMIT < 192 )) && CELERY_MEM_LIMIT=192
DICOM_MEM_LIMIT="$(( allocatable_mb * 6 / 100 ))"; (( DICOM_MEM_LIMIT < 256 )) && DICOM_MEM_LIMIT=256
NGINX_MEM_LIMIT="$(( allocatable_mb * 2 / 100 ))"; (( NGINX_MEM_LIMIT < 64 )) && NGINX_MEM_LIMIT=64
# HAProxy is a thin L7 balancer in front of the web replicas — negligible per-connection cost.
HAPROXY_MEM_LIMIT="$(( allocatable_mb * 1 / 100 ))"; (( HAPROXY_MEM_LIMIT < 32 )) && HAPROXY_MEM_LIMIT=32

export DB_MEM_LIMIT="${DB_MEM_LIMIT}m" PGBOUNCER_MEM_LIMIT="${PGBOUNCER_MEM_LIMIT}m" \
       REDIS_MEM_LIMIT="${REDIS_MEM_LIMIT}m" WEB_MEM_LIMIT="${WEB_MEM_LIMIT}m" \
       CELERY_MEM_LIMIT="${CELERY_MEM_LIMIT}m" DICOM_MEM_LIMIT="${DICOM_MEM_LIMIT}m" \
       NGINX_MEM_LIMIT="${NGINX_MEM_LIMIT}m" HAPROXY_MEM_LIMIT="${HAPROXY_MEM_LIMIT}m"

# Callers: print a summary yourselves after sourcing (this file must not run in a subshell,
# e.g. via `$(...)` or a pipe, or the `export`s above never reach your shell). Example:
#   log "Detected ${total_mb}MB host RAM -> mem_limit db=${DB_MEM_LIMIT} web=${WEB_MEM_LIMIT} ..."

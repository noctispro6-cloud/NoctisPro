#!/usr/bin/env bash
# Shared by scripts/start-stack.sh and scripts/update.sh: read WEB_REPLICAS /
# CELERY_REPLICAS from .env.docker so a manual `docker compose --scale` survives
# reboots and the nightly auto-update instead of being silently reset to 1 (Compose
# does not persist an ad-hoc --scale count across separate `up` invocations).
# Source this file (not exec) from the repo root — it only exports variables.

_read_env_kv() {
  local key="${1:?}" file="${2:?}" line
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    if [[ "$line" == "${key}="* ]]; then
      printf '%s' "${line#${key}=}"
      return 0
    fi
  done < "$file"
}

WEB_REPLICAS="$(_read_env_kv WEB_REPLICAS .env.docker | xargs || true)"
CELERY_REPLICAS="$(_read_env_kv CELERY_REPLICAS .env.docker | xargs || true)"
[[ "$WEB_REPLICAS" =~ ^[0-9]+$ ]] || WEB_REPLICAS=1
[[ "$CELERY_REPLICAS" =~ ^[0-9]+$ ]] || CELERY_REPLICAS=1

export WEB_REPLICAS CELERY_REPLICAS

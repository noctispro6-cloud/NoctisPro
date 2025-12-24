#!/usr/bin/env bash
set -euo pipefail

cd /app

# If using Postgres, wait for it to be reachable.
if [[ "${DB_ENGINE:-}" == "django.db.backends.postgresql" || "${DB_ENGINE:-}" == "django.db.backends.postgresql_psycopg2" ]]; then
  /app/docker/entrypoint-wait-for-db.sh
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Run ASGI server
exec daphne -b 0.0.0.0 -p "${PORT:-8000}" noctis_pro.asgi:application

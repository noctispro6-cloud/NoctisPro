#!/usr/bin/env bash
set -euo pipefail

cd /app

# If using Postgres, wait for it to be reachable.
if [[ "${DB_ENGINE:-}" == "django.db.backends.postgresql" || "${DB_ENGINE:-}" == "django.db.backends.postgresql_psycopg2" ]]; then
  /app/docker/entrypoint-wait-for-db.sh
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Ensure exactly one superuser exists (idempotent).
# Defaults:
# - username: admin
# - email: noctis-pro6@gmail.com
# - password: must be provided via NOCTIS_ADMIN_PASSWORD (deploy script can generate it once)
if [[ "${NOCTIS_CREATE_SUPERUSER:-1}" != "0" && "${NOCTIS_CREATE_SUPERUSER:-}" != "false" ]]; then
  python manage.py shell -c "
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = (os.environ.get('NOCTIS_ADMIN_USERNAME') or 'admin').strip()
email = (os.environ.get('NOCTIS_ADMIN_EMAIL') or 'noctis-pro6@gmail.com').strip()
pw = (os.environ.get('NOCTIS_ADMIN_PASSWORD') or '').strip()

if not pw:
    raise SystemExit('ERROR: NOCTIS_ADMIN_PASSWORD is required to create the superuser.')

u, created = User.objects.get_or_create(username=username, defaults={'email': email})
changed = False

if created:
    u.set_password(pw)
    u.is_staff = True
    u.is_superuser = True
    changed = True
else:
    # Promote to superuser if needed; only reset password if not yet a superuser
    if not getattr(u, 'is_superuser', False):
        u.set_password(pw)
        u.is_staff = True
        u.is_superuser = True
        changed = True

try:
    if hasattr(u, 'role') and getattr(u, 'role', None) != 'admin':
        u.role = 'admin'
        changed = True
    if hasattr(u, 'is_verified') and not getattr(u, 'is_verified', False):
        u.is_verified = True
        changed = True
except Exception:
    pass

if hasattr(u, 'email') and email and getattr(u, 'email', '') != email:
    u.email = email
    changed = True

if changed:
    u.save()

print('SUPERUSER_CREATED' if created else 'SUPERUSER_OK')
"
fi

# Run ASGI server
exec daphne -b 0.0.0.0 -p "${PORT:-8000}" noctis_pro.asgi:application

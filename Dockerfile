FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for imaging + postgres + magic
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    libopenjp2-7 \
    libmagic1 \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.server.txt /app/requirements.server.txt
COPY requirements.optimized.txt /app/requirements.optimized.txt

RUN pip install --no-cache-dir --upgrade pip wheel setuptools \
  && pip install --no-cache-dir -r /app/requirements.server.txt

COPY . /app

EXPOSE 8000 11112

CMD ["bash", "-lc", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && (python manage.py shell -c \"from django.contrib.auth import get_user_model; U=get_user_model(); import sys; sys.exit(0 if U.objects.filter(is_superuser=True).exists() else 1)\" || (PW=\"${NOCTIS_ADMIN_PASSWORD:-}\"; if [ -z \"$PW\" ]; then PW=\"$(python - <<'PY'\nimport secrets\nprint(secrets.token_urlsafe(14))\nPY\n)\"; echo \"[INFO] No superuser found; generated NOCTIS_ADMIN_PASSWORD=$PW\" >&2; fi; python manage.py create_admin --username \"${NOCTIS_ADMIN_USERNAME:-admin}\" --email \"${NOCTIS_ADMIN_EMAIL:-}\" --password \"$PW\")) && exec daphne -b 0.0.0.0 -p 8000 noctis_pro.asgi:application"]

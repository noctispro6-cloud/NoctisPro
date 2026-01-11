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

# Auto-tune worker count (override with WEB_CONCURRENCY).
CMD ["bash", "-lc", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && WORKERS=\"${WEB_CONCURRENCY:-}\"; if [ -z \"$WORKERS\" ]; then WORKERS=\"$(python3 /app/tools/auto_concurrency.py web 2>/dev/null || true)\"; fi; case \"$WORKERS\" in (''|*[!0-9]*) WORKERS=2 ;; esac; exec gunicorn noctis_pro.asgi:application -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --workers \"$WORKERS\" --timeout ${GUNICORN_TIMEOUT:-3600} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} --keep-alive ${GUNICORN_KEEPALIVE:-5}"]

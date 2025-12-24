FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# OS deps for psycopg2, Pillow, pydicom tooling, etc.
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    libopenjp2-7 \
    libmagic1 \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.server.txt /app/requirements.server.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
  && pip install --no-cache-dir -r /app/requirements.server.txt

COPY . /app

RUN chmod +x /app/docker/entrypoint-web.sh /app/docker/entrypoint-wait-for-db.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint-web.sh"]

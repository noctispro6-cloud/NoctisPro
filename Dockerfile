FROM python:3.12-slim

# Basic runtime env
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps kept minimal; Pillow typically needs these.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libjpeg62-turbo \
      zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.docker.txt /app/requirements.docker.txt
RUN pip install --no-cache-dir -r /app/requirements.docker.txt

# Copy application code
COPY . /app

# Default: run migrations then start dev server
EXPOSE 8000
CMD ["bash", "-lc", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]


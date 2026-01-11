# Production deployment (Contabo Ubuntu 24.04 + Docker)

This repo can be deployed publicly **only over HTTPS**. The production setup uses:

- `docker-compose.prod.yml`
- `nginx` reverse proxy (TLS termination + static)
- Postgres + Redis (internal-only)

## 1) Create `.env.docker`

Copy the example and fill in **real values**:

```bash
cp .env.docker.example .env.docker
```

Minimum required keys:

- `SECRET_KEY`: required when `DEBUG=False`
- `DOMAIN_NAME`: your public domain (e.g. `pacs.example.com`)
- `ALLOWED_HOSTS`: include your domain
- `CSRF_TRUSTED_ORIGINS`: include `https://<your-domain>` (and `https://www.<your-domain>` if used)
- `DB_PASSWORD`: strong password

Recommended:

- `DEBUG=False`
- `SERVE_MEDIA_FILES=False` (keep uploads private; the app serves images via authenticated endpoints)
- If Celery logs show `FATAL: server login failed: wrong password type`, set `PGBOUNCER_AUTH_TYPE=plain`
  in `.env.docker` (or ensure your PgBouncer auth configuration matches `md5`/`scram` expectations).

## 2) DNS + firewall

- Point `DOMAIN_NAME` A/AAAA record to your Contabo VPS IP.
- Open only:
  - TCP `80` (Let’s Encrypt HTTP-01)
  - TCP `443` (HTTPS)
- **Do not expose DICOM C-STORE (11112) publicly.** Use DICOMweb STOW-RS over HTTPS or a VPN.

## 3) TLS certificates

This stack expects certificates at:

- `./nginx/letsencrypt/live/<DOMAIN_NAME>/fullchain.pem`
- `./nginx/letsencrypt/live/<DOMAIN_NAME>/privkey.pem`

The nginx container uses a template (`nginx/templates/noctis.conf.template`) rendered with `DOMAIN_NAME`.

You can obtain certificates using either:

- **Host certbot** (recommended for simplicity): install certbot on the VPS and write certs into `./nginx/letsencrypt/`
- **Traefik/Caddy** (recommended long-term): handle TLS automatically (outside this compose file)

## 4) Start the stack

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## 5) DICOM ingest (worldwide, safe)

Use **DICOMweb STOW-RS** (HTTPS) at:

- `POST /dicomweb/studies/`

It requires authentication (BasicAuth or SessionAuth). This is much safer than exposing DICOM port 11112.

## Security notes

- The legacy “C++ compat” endpoints are **disabled by default** (`ENABLE_CPP_COMPAT_API=false`).
- Public `/media/` serving is **disabled by default** (`SERVE_MEDIA_FILES=false`).


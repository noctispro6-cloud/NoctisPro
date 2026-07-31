# NoctisPro

A self-hosted PACS / DICOM platform: worklist, DICOM viewer (MPR/3D/bone reconstruction),
AI-assisted analysis and report generation, and a DICOM C-STORE receiver for ingesting
studies directly from modalities. Built on Django, Postgres, Redis, and Celery.

| App | Purpose |
|---|---|
| `worklist` | Studies/series/images, upload, core PACS data model |
| `dicom_viewer` | Web viewer — windowing, MPR, 3D, ML bone segmentation |
| `ai_analysis` | AI inference + auto-generated report drafting |
| `reports` | Radiology report authoring/signing |
| `chat`, `notifications` | In-app messaging and alerts |
| `accounts`, `admin_panel` | Users, facilities, roles, system administration |

This document is the practical index: how to deploy (automated or manual), and everything
that needs doing on an ongoing basis to keep a deployment healthy. It links out to deeper
guides rather than duplicating them, so those stay the single source of truth for the
details.

## Deployment options

| Path | Use case | Guide |
|---|---|---|
| `deploy-docker.sh` | Local machine / quick evaluation, Docker Compose | this doc, [§ Local Docker](#local-docker-quick-start-automated) |
| `scripts/install-server.sh` + `docker-compose.prod.yml` | Production on a fresh Ubuntu VPS, fully automated | [DEPLOY_AWS_CLOUDFLARE.md](DEPLOY_AWS_CLOUDFLARE.md) |
| `docker-compose.prod.yml` (manual steps) | Production on any Docker host, step by step | [DEPLOYMENT_PRODUCTION_DOCKER.md](DEPLOYMENT_PRODUCTION_DOCKER.md), [§ Manual production deploy](#manual-production-deploy-docker) |
| `deploy.sh` | Native systemd install, no Docker (sqlite or postgres) | `./deploy.sh --help` |
| `docker-compose.node.yml` | Add opportunistic secondary capacity (e.g. a laptop) to an existing prod deploy | [DEPLOY_OPPORTUNISTIC_NODE.md](DEPLOY_OPPORTUNISTIC_NODE.md) |

All Docker paths share one codebase and one `Dockerfile`; they differ only in which compose
file and which services are involved.

---

## Local Docker quick start (automated)

```bash
git clone <this-repo-url> && cd NoctisPro
./deploy-docker.sh
```

This builds and starts the full stack (db, pgbouncer, redis, web, celery, dicom) via
`docker-compose.yml`, auto-sizes each container's memory limit from the host's detected RAM,
and prints the URL to open. Data persists in named Docker volumes across rebuilds
(`docker compose up -d --build` is safe; `docker compose down -v` deletes them).

For a tunneled public HTTPS URL instead of `localhost` (e.g. to receive DICOMweb from a
remote modality during testing): `./deploy-docker.sh --ngrok` (requires `NGROK_AUTHTOKEN` in
`.env.docker`).

---

## Production deploy — automated

Full walkthrough (AWS EC2 + Cloudflare, but the same script targets any fresh Ubuntu
22.04/24.04 host): **[DEPLOY_AWS_CLOUDFLARE.md](DEPLOY_AWS_CLOUDFLARE.md)**. Short version:

```bash
git clone <this-repo-url> /opt/noctispro && cd /opt/noctispro
sudo bash scripts/install-server.sh   # Docker, UFW, fail2ban, systemd unit, nightly update cron
cp .env.docker.example .env.docker && $EDITOR .env.docker   # SECRET_KEY, DOMAIN_NAME, DB_PASSWORD, ...
sudo bash scripts/setup-tls.sh pacs.yourdomain.com           # or bring your own certs
sudo systemctl start noctispro
sudo docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

`scripts/install-server.sh` installs a systemd unit (`noctispro.service`, auto-starts on
reboot via `scripts/start-stack.sh`, which sizes container memory limits from host RAM) and a
3 AM nightly auto-update cron (`scripts/update.sh`) — from here on the box is
self-maintaining for code updates. See [§ Maintenance](#maintenance) for what's still manual
(backups, TLS renewal, monitoring).

## Manual production deploy (Docker)

If you're not on Ubuntu, not using the install script, or just want to see every step:
**[DEPLOYMENT_PRODUCTION_DOCKER.md](DEPLOYMENT_PRODUCTION_DOCKER.md)**. Short version:

```bash
cp .env.docker.example .env.docker && $EDITOR .env.docker
# TLS certs must exist at ./nginx/letsencrypt/live/<DOMAIN_NAME>/{fullchain,privkey}.pem
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

Required `.env.docker` values: `SECRET_KEY`, `DOMAIN_NAME`, `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS` (must include `https://`), `DB_PASSWORD`. Everything else has a
working default — see the comments in `.env.docker.example`.

DICOM C-STORE (port 11112) should generally **not** be exposed publicly; prefer DICOMweb
STOW-RS (`POST /dicomweb/studies/`, authenticated, over HTTPS) for internet-facing ingest,
and reserve 11112 for same-network/VPN modalities with per-facility IP allowlisting
(admin panel → Facilities).

---

## Scaling & load balancing

Everything below is opt-in — a default deploy is a single `web`/`celery`/`dicom` container
each, and stays that way until you scale.

**Single host, more capacity:**

```bash
docker compose -f docker-compose.prod.yml up -d --scale web=3 --scale celery=2
```

Safe because `web`/`celery` are stateless — sessions are DB-backed, media/static are shared
named volumes, DB access goes through the shared `pgbouncer`. An HAProxy tier
(`haproxy/haproxy.cfg`) sits in front of `web` doing real load balancing: active health
checks against `/health/simple/`, least-connections balancing, and automatic discovery of
however many replicas are running via Docker's embedded DNS — a dead/unhealthy replica gets
evicted instead of silently retried. `dicom` cannot be scaled this way (it binds a fixed host
port).

To make a manual scale survive reboots and the nightly auto-update (which would otherwise
reset it back to 1 each time), set in `.env.docker`:

```bash
WEB_REPLICAS=3
CELERY_REPLICAS=2
```

**Beyond one host:** add an opportunistic secondary node (e.g. a laptop, joined over
Tailscale) for extra capacity when it happens to be available — see
**[DEPLOY_OPPORTUNISTIC_NODE.md](DEPLOY_OPPORTUNISTIC_NODE.md)**. True redundancy (surviving
the primary host itself going down) needs a Postgres replica and redundant media storage,
which is a bigger, separate project — ask before assuming you need it; a single well-sized
host with HAProxy already handles a lot of traffic.

---

## Maintenance

### Updates

Automatic (installed by `scripts/install-server.sh`): every night at 3 AM,
`scripts/update.sh` runs via cron — `git fetch`, and if there are new commits: build new
images, run migrations, `collectstatic`, then restart `web`/`celery`/`dicom`/`lb` with
~2–5s downtime. `db`/`redis`/`pgbouncer`/`nginx` are left running. Logs:
`tail -f /var/log/noctispro-update.log`.

Manual, any time:

```bash
sudo bash scripts/update.sh            # only rebuilds if origin has new commits
sudo bash scripts/update.sh --force    # rebuild/restart even if already up to date
```

### Backups

Automatic, via Celery Beat (`noctis_pro/celery.py`): database-only backup daily at 2 AM,
full backup (database + media) Sunday at 3 AM. Output directory: `BACKUP_ROOT`
(default `<repo>/backups`); retention: `BACKUP_RETENTION_DAYS` (default 30) — both
overridable via `.env.docker`.

Manual:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py backup_system
docker compose -f docker-compose.prod.yml exec web python manage.py backup_system --db-only
docker compose -f docker-compose.prod.yml exec web python manage.py backup_system --media-only

# Or a direct pg_dump:
docker compose -f docker-compose.prod.yml exec db pg_dump -U noctispro noctispro | gzip > backup-$(date +%F).sql.gz
```

Restore procedures (database, media, full-system): **[RECOVERY.md](RECOVERY.md)**.

### Health checks / monitoring

- `GET /health/simple/` — dependency-free 200 OK, what HAProxy polls for load-balancing.
- `GET /health/ready/` — checks DB connectivity, 503 if not ready.
- `GET /health/live/` — bare liveness check.
- `GET /health/` — full report: DB + cache status, timing.
- HAProxy stats (internal only, not published to the host): `docker compose -f docker-compose.prod.yml exec lb sh -c "wget -qO- http://localhost:8404/"`.

### Logs

```bash
docker compose -f docker-compose.prod.yml logs -f            # everything
docker compose -f docker-compose.prod.yml logs -f web         # one service
```

App-level logs also land in `logs/noctis_pro.log` (rotated, 5 backups × 10MB) and
`logs/security.log` (rotated, 3 backups × 5MB) inside the `web` container.

### Resource sizing

Container memory limits (`*_MEM_LIMIT`) are auto-computed from host RAM by
`scripts/compute-prod-mem-limits.sh` (applied on boot via `scripts/start-stack.sh` and on
every update via `scripts/update.sh`) — no manual tuning needed on a fresh host. Worker
counts (`WEB_CONCURRENCY`, `CELERY_CONCURRENCY`) auto-detect from each container's own CPU/
memory limit (`tools/auto_concurrency.py`); override in `.env.docker` only if you need to.

PgBouncer pool size (`PGBOUNCER_DEFAULT_POOL_SIZE`, default 50) and Postgres
`max_connections` (default 200) are the first things to reach for if you see connection
exhaustion under load — raise both together.

### TLS certificates

Managed by `scripts/setup-tls.sh` (Let's Encrypt/certbot, or paste-in a Cloudflare Origin
Certificate — see [DEPLOY_AWS_CLOUDFLARE.md § Part 2–3](DEPLOY_AWS_CLOUDFLARE.md)). Cloudflare
Origin Certificates last 15 years; Let's Encrypt certs need renewal — re-run
`scripts/setup-tls.sh` and `docker compose -f docker-compose.prod.yml restart nginx`.

### Database

No read replica / load-balanced database by default — a single well-tuned Postgres instance
(via pgbouncer) handles substantial load on its own; don't add replica routing speculatively
for a clinical system where a stale read is a correctness bug, not just a performance
question. If you later have concrete evidence of DB-bound load, that's a real conversation to
have, not a checkbox to tick now.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| 502 Bad Gateway | `docker compose logs web` / `lb` — app may still be starting, or every `web` replica is unhealthy |
| CSRF errors | `CSRF_TRUSTED_ORIGINS` must include the `https://` prefix |
| Rate limiting blocks everyone | Redis down — `docker compose ps redis`; the limiter fails open only when `REDIS_URL` is unset |
| Celery: `wrong password type` | Set `PGBOUNCER_AUTH_TYPE=plain` in `.env.docker` |
| DICOM C-STORE rejected | Check the sending facility's allowed IP/CIDR in admin panel → Facilities; `docker compose logs dicom` |
| Images not loading | `SERVE_MEDIA_FILES` must be `False` — images are served via authenticated endpoints, never directly by nginx |
| A `--scale`d replica never gets traffic | Check its health: `docker compose exec lb sh -c "wget -qO- http://localhost:8404/"` — HAProxy shows DOWN reasons there |

## Docs index

- [DEPLOY_AWS_CLOUDFLARE.md](DEPLOY_AWS_CLOUDFLARE.md) — full automated production walkthrough
- [DEPLOYMENT_PRODUCTION_DOCKER.md](DEPLOYMENT_PRODUCTION_DOCKER.md) — manual production deploy, any Docker host
- [DEPLOY_OPPORTUNISTIC_NODE.md](DEPLOY_OPPORTUNISTIC_NODE.md) — add a secondary node over Tailscale
- [RECOVERY.md](RECOVERY.md) — restore database/media from backup
- `.env.docker.example` / `.env.docker.node.example` — every environment variable, documented inline
- `deploy.sh --help` — native (non-Docker) systemd install

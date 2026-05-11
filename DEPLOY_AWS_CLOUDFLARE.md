# NoctisPro — Production Deployment Guide
## AWS EC2 + Cloudflare + Docker

This guide takes you from a blank AWS account to a live, secured, auto-updating production system.

---

## Architecture overview

```
Browser / Modality
       │
       ├─ HTTPS (443) ──► Cloudflare (WAF, DDoS, CDN)
       │                       │ HTTPS (443)
       │                       ▼
       │                  nginx container  ──► web container (Gunicorn/Daphne)
       │                                   ──► static files
       │
       └─ DICOM (11112) ──► directly to EC2 Elastic IP ──► dicom container
```

The web app lives behind Cloudflare. DICOM traffic bypasses Cloudflare (TCP, not HTTP) and hits the server's public IP directly. Per-facility IP allowlists in the admin panel control who can push DICOM images.

---

## Part 1 — AWS EC2 instance

### 1.1 Create the instance

1. Open **EC2 → Launch Instance** in your chosen region.
2. **AMI**: Ubuntu Server 24.04 LTS (64-bit x86)
3. **Instance type**:
   - Minimum: `t3.medium` (2 vCPU, 4 GB RAM)
   - Recommended for active use: `t3.large` (2 vCPU, 8 GB RAM)
4. **Key pair**: create or select an existing key pair. Download the `.pem` file and keep it safe.
5. **Storage**:
   - Root volume: 30 GB gp3 (OS + Docker images)
   - Add a second EBS volume: **100 GB+ gp3** for patient data (`/data`)
   - Increase if you expect high study volume; you can expand gp3 volumes online later.
6. **Security Group** — create a new one named `noctispro-sg` with these inbound rules:

   | Type       | Protocol | Port  | Source            | Purpose                    |
   |------------|----------|-------|-------------------|----------------------------|
   | SSH        | TCP      | 22    | Your IP only      | Server management          |
   | HTTP       | TCP      | 80    | 0.0.0.0/0         | Cloudflare → nginx (redirect) |
   | HTTPS      | TCP      | 443   | 0.0.0.0/0         | Cloudflare → nginx         |
   | Custom TCP | TCP      | 11112 | 0.0.0.0/0         | DICOM from modalities      |

   > **Tip**: after setup you can restrict ports 80/443 to [Cloudflare's IP ranges](https://www.cloudflare.com/ips/) only, so the web app is unreachable except through Cloudflare.

7. Click **Launch**.

### 1.2 Assign an Elastic IP

A regular EC2 IP changes on stop/start. Elastic IP is static and free while assigned.

1. EC2 → **Elastic IPs → Allocate Elastic IP address** → Allocate.
2. Select the new IP → **Actions → Associate Elastic IP** → choose your instance → Associate.

Note the Elastic IP — you'll need it for DNS.

### 1.3 Mount the data volume

SSH to the server, then:

```bash
ssh -i your-key.pem ubuntu@<elastic-ip>

# Find the new volume (usually /dev/xvdf or /dev/nvme1n1)
lsblk

# Format (only once — skip if reusing an existing volume)
sudo mkfs.ext4 /dev/xvdf

# Mount permanently
sudo mkdir -p /data
echo '/dev/xvdf /data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a
df -h /data
```

---

## Part 2 — Cloudflare DNS

### 2.1 Add your domain to Cloudflare

1. Sign in to [dash.cloudflare.com](https://dash.cloudflare.com) → **Add a site** → enter your domain → Free plan.
2. Follow the instructions to update your registrar's nameservers to Cloudflare's.
3. Wait for propagation (usually under 30 minutes).

### 2.2 Create DNS records

In **DNS → Records**:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A    | pacs *(or @)* | `<your-elastic-ip>` | Proxied (orange cloud) ✓ |

The orange cloud means Cloudflare proxies the request — you get WAF, DDoS protection, and your real server IP is hidden.

### 2.3 SSL/TLS settings

Go to **SSL/TLS → Overview** and set mode to **Full (strict)**.

This means: Cloudflare ↔ browser is HTTPS, Cloudflare ↔ your server is also HTTPS with a valid cert. You'll provide that cert in the next step.

### 2.4 Create an Origin Certificate

Go to **SSL/TLS → Origin Server → Create Certificate**:
- Keep defaults (RSA 2048, 15 years)
- Hostnames: `pacs.yourdomain.com`, `*.pacs.yourdomain.com`
- Click **Create**

You'll see the **Origin Certificate** and **Private Key** — keep this window open for Part 3.

---

## Part 3 — Server setup

### 3.1 Bootstrap the server

```bash
ssh -i your-key.pem ubuntu@<elastic-ip>

# Clone the repo
sudo git clone https://github.com/your-org/noctispro /opt/noctispro
cd /opt/noctispro

# Run the bootstrap script (installs Docker, UFW, fail2ban, cron, systemd service)
sudo bash scripts/install-server.sh
```

The script:
- Installs Docker and Docker Compose plugin
- Configures UFW firewall (SSH, 80, 443, 11112)
- Hardens SSH (disables password auth)
- Installs fail2ban
- Enables automatic security updates
- Registers NoctisPro as a systemd service (auto-starts on reboot)
- Installs the 3 AM nightly update cron job

### 3.2 Install the TLS certificate

```bash
cd /opt/noctispro
sudo bash scripts/setup-tls.sh pacs.yourdomain.com
```

Paste the **Origin Certificate** when prompted, then the **Private Key**. The script writes them to `nginx/letsencrypt/live/pacs.yourdomain.com/`.

### 3.3 Configure the environment

```bash
cd /opt/noctispro
sudo cp .env.docker.example .env.docker
sudo nano .env.docker
```

Fill in these **required** values:

```bash
SECRET_KEY=<output of: python3 -c "import secrets; print(secrets.token_urlsafe(50))">
DOMAIN_NAME=pacs.yourdomain.com
ALLOWED_HOSTS=pacs.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://pacs.yourdomain.com
DB_PASSWORD=<strong random password>
```

Everything else has working defaults. Save and close.

### 3.4 Point Docker data volumes at the EBS volume (optional but recommended)

By default Docker volumes live in `/var/lib/docker/volumes`. To store patient data on the larger EBS volume:

```bash
sudo mkdir -p /data/docker-volumes
sudo bash -c 'cat > /etc/docker/daemon.json <<EOF
{
  "data-root": "/data/docker-volumes"
}
EOF'
sudo systemctl restart docker
```

---

## Part 4 — Start the stack

```bash
cd /opt/noctispro
sudo systemctl start noctispro
# Watch startup logs
sudo docker compose -f docker-compose.prod.yml logs -f
```

On first start the web container runs `migrate` and `collectstatic` automatically.

### 4.1 Create the superuser

```bash
sudo docker compose -f docker-compose.prod.yml \
  exec web python manage.py createsuperuser
```

### 4.2 Verify everything is running

```bash
sudo docker compose -f docker-compose.prod.yml ps
```

All six services should be `Up`:
`db`, `pgbouncer`, `redis`, `web`, `celery`, `dicom`, `nginx`

Open `https://pacs.yourdomain.com` — you should see the NoctisPro login page over HTTPS.

---

## Part 5 — Security hardening

### 5.1 Cloudflare WAF rate limiting

In Cloudflare → **Security → WAF → Rate limiting rules**, create:

| Rule | Expression | Action | Rate |
|------|-----------|--------|------|
| Login brute force | `http.request.uri.path contains "/accounts/login"` | Block | 10 req / 1 min per IP |
| API protection | `http.request.uri.path contains "/api/"` | Block | 100 req / 1 min per IP |
| DICOM upload | `http.request.uri.path contains "/dicomweb/"` | Block | 20 req / 1 min per IP |

These complement the Django-level `django-ratelimit` rate limiting already in the app.

### 5.2 Cloudflare → server: restrict ports 80/443 to Cloudflare IPs only

Once your domain is behind Cloudflare (orange cloud), only Cloudflare needs to reach port 80/443. Everything else is spoofing.

```bash
# Download Cloudflare IPv4 ranges and restrict UFW
curl -s https://www.cloudflare.com/ips-v4 | while read ip; do
  sudo ufw allow from "$ip" to any port 443 comment 'Cloudflare'
  sudo ufw allow from "$ip" to any port 80  comment 'Cloudflare'
done
# Remove the broad 0.0.0.0/0 rules you added earlier
sudo ufw delete allow 80/tcp
sudo ufw delete allow 443/tcp
sudo ufw reload
```

After this, direct IP access to the web app is blocked — only traffic through Cloudflare can reach nginx.

### 5.3 Django rate limiting (already wired up)

The app uses `django-ratelimit` on login and sensitive POST endpoints. In production (with Redis), all Gunicorn workers share the same counters via Redis, so the limit is enforced correctly regardless of worker count. This was fixed in `settings.py`:

```python
RATELIMIT_USE_CACHE = 'default'   # Redis in prod, LocMemCache in dev
RATELIMIT_FAIL_OPEN = not bool(REDIS_URL)
```

### 5.4 DICOM IP allowlist

For each facility, enter their public IP in the admin panel → **Facilities → Edit → Allowed IP / CIDR**. The DICOM receiver rejects connections from IPs not in any facility's allowlist.

---

## Part 6 — Auto-update (3 AM nightly)

The cron job installed by `install-server.sh` runs every night at 3 AM:

```
0 3 * * * root bash /opt/noctispro/scripts/update.sh
```

`scripts/update.sh` does the following without full downtime:

1. `git fetch` — checks for new commits; exits immediately if none.
2. `git pull` — applies new code.
3. `docker compose build` — builds new images in the background (current app still running).
4. `docker compose run --rm web python manage.py migrate` — runs migrations using the new image.
5. `docker compose run --rm web python manage.py collectstatic` — updates static files.
6. `docker compose up -d --no-deps web celery dicom` — replaces only the application containers. `db`, `pgbouncer`, `redis`, and `nginx` are untouched.

Typical downtime during step 6: **2–5 seconds** while Gunicorn restarts.

Logs: `tail -f /var/log/noctispro-update.log`

### Manual update at any time

```bash
sudo bash /opt/noctispro/scripts/update.sh
```

---

## Part 7 — Auto-start on reboot

The systemd service `noctispro.service` starts the Docker Compose stack on every boot:

```bash
# Check status
sudo systemctl status noctispro

# Start / stop manually
sudo systemctl start noctispro
sudo systemctl stop noctispro

# View startup logs
sudo journalctl -u noctispro -f
```

Because all services have `restart: unless-stopped` in the compose file, individual containers that crash will also self-heal without needing systemd intervention.

---

## Part 8 — Operations reference

### View live logs

```bash
# All services
sudo docker compose -f /opt/noctispro/docker-compose.prod.yml logs -f

# One service
sudo docker compose -f /opt/noctispro/docker-compose.prod.yml logs -f web
sudo docker compose -f /opt/noctispro/docker-compose.prod.yml logs -f dicom
```

### Run Django management commands

```bash
sudo docker compose -f /opt/noctispro/docker-compose.prod.yml \
  exec web python manage.py <command>
```

### Backup the database manually

```bash
sudo docker compose -f /opt/noctispro/docker-compose.prod.yml \
  exec db pg_dump -U noctispro noctispro | gzip > /data/backup-$(date +%F).sql.gz
```

### Expand the EBS data volume

AWS lets you expand a gp3 volume online:

1. EC2 → Volumes → select the `/data` volume → **Modify Volume** → increase size → Save.
2. On the server: `sudo resize2fs /dev/xvdf`

No reboot or container restart needed.

### Renew the Cloudflare Origin Certificate

Origin certificates last 15 years. If you ever need to renew:

```bash
sudo bash /opt/noctispro/scripts/setup-tls.sh pacs.yourdomain.com
sudo docker compose -f /opt/noctispro/docker-compose.prod.yml restart nginx
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| 502 Bad Gateway | `docker compose logs web` — app may still be starting |
| CSRF errors | Ensure `CSRF_TRUSTED_ORIGINS` includes `https://` prefix |
| Rate limit blocks everyone | Redis not running — `docker compose ps redis`; rate limiter falls back to per-worker cache |
| DICOM C-STORE rejected | Check facility's `dicom_host` field in admin; check `docker compose logs dicom` |
| Images not loading | `SERVE_MEDIA_FILES` must be `False`; images served via authenticated endpoints |
| Slow first load | Cloudflare cache is cold after a deploy — subsequent requests will be fast |

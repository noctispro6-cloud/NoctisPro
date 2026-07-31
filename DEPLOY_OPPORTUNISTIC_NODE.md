# Opportunistic secondary node (e.g. a laptop) over Tailscale

This adds a second, intermittently-available machine (a laptop, a VirtualBox VM, a spare
desktop) as extra `web`/`celery` capacity for a NoctisPro deployment that already follows
[DEPLOY_AWS_CLOUDFLARE.md](DEPLOY_AWS_CLOUDFLARE.md). It's opt-in and additive — nothing here
changes single-server behavior if you never run it.

**The model:** the cloud server is the always-on floor — it alone owns Postgres, Redis,
DICOM ingestion, and the canonical copy of media, and it runs its own `web`/`celery`
replicas that always work regardless of the secondary node. The secondary node adds
opportunistic extra HTTP-serving/report-generation capacity when it happens to be on, and
HAProxy (already running on the cloud server, see [`haproxy/haproxy.cfg`](haproxy/haproxy.cfg))
health-checks it like any other backend: up and healthy → gets traffic; off or unreachable →
quietly evicted, zero-downtime, zero manual intervention. When it comes back, HAProxy's
health check passes again and it resumes taking traffic automatically — that's the "in
theory, load sharing resumes when I switch the laptop back on" this was built for.

Why this works safely: Django sessions here are DB-backed
(`SESSION_ENGINE = django.contrib.sessions.backends.db`, `noctis_pro/settings.py:615`), not
cookie-only — so there's no sticky-session requirement. Any node can serve any request as
long as it can reach the same Postgres, same Redis, and same media.

## What you need before starting

- The cloud server already running `docker-compose.prod.yml` (the main deploy guide).
- A second machine — VirtualBox VM, laptop, whatever — with Docker installable (Ubuntu
  22.04/24.04 assumed, matching `scripts/install-server.sh`).
- A free [Tailscale](https://tailscale.com) account (or run your own WireGuard mesh if you
  prefer — the scripts below assume Tailscale specifically). Tailscale gives every device a
  stable private IP in `100.64.0.0/10` regardless of whatever NAT/home-network/dynamic-IP
  situation the laptop is actually behind, which is what makes "just switch it on and it
  rejoins" work without router configuration.

## Setup

**1. On the cloud server:**

```bash
sudo bash scripts/setup-cloud-node.sh
```

This installs Tailscale (prompts you to authenticate via a printed URL), opens the firewall
for exactly the tailnet subnet to reach NFS (2049), pgbouncer (6432), and redis (6379), and
NFS-exports the `noctis_media` Docker volume. It prints the values you need for step 2.

**2. On the secondary node:**

```bash
sudo bash scripts/setup-laptop-node.sh <cloud-tailscale-addr> <nfs-export-path>
```

(both values printed by step 1). This installs Tailscale + Docker, mounts the cloud's media
export over NFS, and prints the remaining manual steps: copy `.env.docker.node.example` to
`.env.docker.node`, fill in the values it flags (**`SECRET_KEY` must be copied byte-for-byte
from the cloud server's `.env.docker`** — a mismatch causes random logout/CSRF failures on
whichever requests happen to land on this node), then:

```bash
docker compose -f docker-compose.node.yml up -d --build
```

**3. Back on the cloud server, register the node with HAProxy:**

```bash
scripts/add-opportunistic-node.sh add laptop1 <secondary-tailscale-ip>:8000
```

This inserts a `server` line into `haproxy/haproxy.cfg` between the
`BEGIN/END-OPPORTUNISTIC-NODES` markers and restarts `lb`. From here on, whether this node
gets traffic is entirely a function of whether `/health/simple/` responds — turn the laptop
off, HAProxy notices within a few failed checks and stops routing to it; turn it back on and
bring the containers up again, HAProxy notices it's healthy again and resumes sending it
traffic. No re-running `add-opportunistic-node.sh` needed for routine on/off — only re-run it
if the node's Tailscale IP changes, or `remove` it if you're retiring it for good.

## Operational characteristics worth knowing before you rely on this

- **Media reads/writes cross your home internet connection.** The secondary node's
  containers read/write DICOM files over NFS to the cloud server, not to local disk. Opening
  a large study on a request this node handles will be slower than on the cloud server
  itself, bounded by your home upload/download speed, not by anything NoctisPro does. This
  is a capacity/latency tradeoff, not a bug.
- **DICOM ingestion never moves.** `docker-compose.node.yml` deliberately has no `dicom`
  service — modalities keep sending C-STORE to the cloud server's fixed port, always. The
  secondary node only ever adds HTTP-serving capacity.
- **Health-check timing.** The opportunistic node's `server` line uses `inter 10s fall 3
  rise 2` (vs. `inter 5s` for cloud-local replicas) — roughly 30s to notice it's gone, ~20s
  to notice it's back, tuned to tolerate brief home-internet hiccups without flapping it out
  of rotation constantly.
- **Security surface.** pgbouncer and redis become reachable from any device on your tailnet
  (not the public internet — Tailscale's WireGuard-based mesh only, and UFW only opens those
  ports to the `100.64.0.0/10` range). pgbouncer already requires `DB_USER`/`DB_PASSWORD`
  from any client; redis has no auth by default (see the comment on the `redis` service in
  `docker-compose.prod.yml`) — set `REDIS_PASSWORD` if your tailnet includes devices you
  don't fully trust. Tailscale's own [ACLs](https://tailscale.com/kb/1018/acls) are another
  layer worth using if you add more than one or two devices to the tailnet over time.
- **This is single-node-of-truth, not HA.** The cloud server is still a single point of
  failure for Postgres, Redis, and media — the secondary node adds capacity, not resilience
  against the cloud server itself going down. If you need that, you're looking at a Postgres
  streaming replica and a genuinely redundant media store, which is a different (and bigger)
  project.

## Removing a node

```bash
scripts/add-opportunistic-node.sh remove laptop1
```

On the secondary node itself: `docker compose -f docker-compose.node.yml down`, and
optionally `sudo umount /mnt/noctis-media-nfs` and remove its `/etc/fstab` line and
`tailscale down`/`tailscale logout` if you're retiring the machine from the tailnet entirely.

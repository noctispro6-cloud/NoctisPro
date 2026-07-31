# NoctisPro — Production Deployment Guide
## Contabo VPS + Cloudflare + Docker (automated)

Takes a fresh Contabo Ubuntu VPS to a live, secured, auto-updating production system using
the same automation as the AWS guide (`scripts/install-server.sh` + `docker-compose.prod.yml`
+ systemd + a nightly auto-update cron) — that tooling is plain Ubuntu + Docker underneath,
nothing AWS-specific about it. This guide only replaces the parts that actually differ: VPS
provisioning and disk expansion. Everything else (Cloudflare DNS, TLS, security hardening,
auto-update, ops reference, troubleshooting) is identical to
[DEPLOY_AWS_CLOUDFLARE.md](DEPLOY_AWS_CLOUDFLARE.md) and linked from here instead of
duplicated.

---

## Architecture overview

```
Browser / Modality
       │
       ├─ HTTPS (443) ──► Cloudflare (WAF, DDoS, CDN)
       │                       │ HTTPS (443)
       │                       ▼
       │                  nginx container  ──► HAProxy (lb)  ──► web container(s) (Gunicorn/uvicorn)
       │                                                      ──► static files
       │
       └─ DICOM (11112) ──► directly to the VPS's public IP ──► dicom container
```

Same as the AWS setup: the web app lives behind Cloudflare, DICOM bypasses it (TCP, not
HTTP) and hits the VPS's public IP directly, and per-facility IP allowlists in the admin
panel control who can push DICOM.

---

## Part 1 — Contabo VPS

Simpler than AWS here — no Elastic IP, no security groups, no separate cloud firewall layer
to configure. A Contabo VPS ships with a static public IPv4 (and IPv6) for the life of the
instance, and the OS's own firewall (UFW, set up by `install-server.sh` below) is what
actually governs access — there's no equivalent of an AWS security group to also configure.

1. Order a VPS from Contabo's control panel:
   - **Image**: Ubuntu 22.04 or 24.04 LTS (64-bit)
   - **Sizing**: match the AWS guide's guidance — 2 vCPU / 4GB RAM minimum, more for active
     use. Prefer a plan with dedicated (not oversubscribed) vCPUs if Contabo offers a choice;
     compressed-DICOM decoding, MPR/3D recon, and AI inference are sustained-CPU workloads,
     not bursty ones, so a burstable/shared-CPU plan will bottleneck under real use.
   - **Storage**: NVMe if available. A CT study is roughly 100–500MB, MRI 50–250MB —
     estimate total disk from expected studies/day and plan headroom; see
     [§ Expanding storage](#expanding-storage) below for what to do when you outgrow it.
2. Set your SSH key during VPS creation if Contabo's panel offers it; otherwise Contabo
   emails a root password on first provisioning — log in and immediately set up key-based
   auth (`ssh-copy-id`), since `install-server.sh` (next section) disables password auth.
3. Note the VPS's public IPv4 — that's what you'll point Cloudflare DNS at, and it doesn't
   change for the life of the VPS, so there's nothing further to do here (unlike AWS's
   Elastic IP step).

---

## Part 2 onward — identical to the AWS guide

From here, follow **[DEPLOY_AWS_CLOUDFLARE.md](DEPLOY_AWS_CLOUDFLARE.md) starting at Part 2**
verbatim, substituting your Contabo VPS's IP wherever it says "Elastic IP":

- [Part 2 — Cloudflare DNS](DEPLOY_AWS_CLOUDFLARE.md#part-2--cloudflare-dns)
- [Part 3 — Server setup](DEPLOY_AWS_CLOUDFLARE.md#part-3--server-setup) — skip
  **3.4 (point Docker volumes at the EBS volume)**, that's AWS-specific; everything else
  applies as-is
- [Part 4 — Start the stack](DEPLOY_AWS_CLOUDFLARE.md#part-4--start-the-stack)
- [Part 5 — Security hardening](DEPLOY_AWS_CLOUDFLARE.md#part-5--security-hardening)
- [Part 6 — Auto-update (3 AM nightly)](DEPLOY_AWS_CLOUDFLARE.md#part-6--auto-update-3-am-nightly)
- [Part 7 — Auto-start on reboot](DEPLOY_AWS_CLOUDFLARE.md#part-7--auto-start-on-reboot)
- [Part 8 — Operations reference](DEPLOY_AWS_CLOUDFLARE.md#part-8--operations-reference) —
  skip **"Expand the EBS data volume"**, see below instead
- [Troubleshooting](DEPLOY_AWS_CLOUDFLARE.md#troubleshooting)

## Expanding storage

Contabo doesn't have AWS's "modify a gp3 volume online" workflow. In Contabo's control
panel, check whether your VPS plan supports an in-place storage upgrade (varies by plan/
region — check current options there, this changes over time). Once the underlying disk is
actually bigger:

```bash
lsblk                      # confirm the kernel sees the new size
sudo growpart /dev/vda 1   # if the disk is partitioned — extend the partition first (device/number will vary; check lsblk)
sudo resize2fs /dev/vda1   # extend the filesystem to fill the partition (or xfs_growfs for XFS)
df -h /                    # confirm
```

If Contabo's plan doesn't support in-place expansion, the alternative is provisioning a
larger VPS and migrating (`scripts/update.sh`'s backup step + `RECOVERY.md` restore
procedure onto the new box), or moving `media/` to external object storage — ask before
assuming you need that; it's a bigger change than a storage bump.

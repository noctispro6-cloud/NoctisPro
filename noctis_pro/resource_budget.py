"""
Auto-detected memory/CPU budget for this process.

Every in-process image/volume cache in this codebase (dicom_viewer/views.py,
noctis_pro/fastapi_image_app.py) used to size itself with a fixed constant chosen
for a beefy dev machine. On a small cloud instance (e.g. a $5-10/mo VPS, or a
modest EC2 instance shared with Postgres/Redis/Celery containers), those fixed
sizes multiply across gunicorn/uvicorn workers and can OOM the box.

This module detects how much memory *this specific container/process* actually
has (cgroup limit if set, else host total) and how many sibling worker processes
are sharing it, then exposes a single "per-worker memory budget" that callers
scale their cache sizes from. Resize the instance (or set a Docker `mem_limit`)
and every cache downstream adjusts on the next process start — no manual tuning.

Mirrors the detection logic in tools/auto_concurrency.py (kept as a separate,
dependency-free copy here since that script isn't an importable package and is
invoked standalone from the Dockerfile CMD).
"""

from __future__ import annotations

import math
import os
from pathlib import Path


def _read_int(path: str) -> int | None:
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw or raw == "max":
        return None
    try:
        return int(raw)
    except Exception:
        return None


def detect_memory_limit_bytes() -> int:
    """Best-effort memory limit: cgroup v2 -> cgroup v1 -> host MemTotal -> 1GB fallback."""
    v2 = _read_int("/sys/fs/cgroup/memory.max")
    if v2 and v2 > 0:
        return v2

    v1 = _read_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if v1 and v1 > 0 and v1 < (1 << 60):  # ignore the "unlimited" sentinel value
        return v1

    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass

    return 1 * 1024**3  # conservative fallback if detection fails entirely


def detect_cpu_count() -> int:
    return int(os.cpu_count() or 1)


def detect_worker_count() -> int:
    """
    How many sibling worker processes (in this container) share the memory budget
    detected above. Prefers an explicit WEB_CONCURRENCY (what actually launches
    gunicorn, per the Dockerfile/systemd unit), then falls back to the same
    CPU/memory-based estimate tools/auto_concurrency.py would produce, so a
    process reading this before WEB_CONCURRENCY is finalized still gets a sane
    answer.
    """
    explicit = os.environ.get("WEB_CONCURRENCY", "").strip()
    if explicit.isdigit() and int(explicit) > 0:
        return int(explicit)

    cpu = detect_cpu_count()
    mem_gb = detect_memory_limit_bytes() / (1024**3)
    mem_cap = int(math.floor(mem_gb / 1.5)) or 1 if mem_gb < 6 else cpu
    total = max(1, min(cpu, mem_cap))
    return max(1, min(8, (total + 1) // 2))  # same ceil-half-of-total as auto_concurrency's "web" split


def per_worker_memory_budget_bytes() -> int:
    """
    This process's fair share of the container's memory limit, for sizing its
    OWN in-process caches (each worker process has independent caches — they
    are not shared across workers). Floored so a tiny box still gets a
    functional, if small, cache rather than being tuned to ~0.
    """
    limit = detect_memory_limit_bytes()
    workers = detect_worker_count()
    budget = limit // workers
    floor = 96 * 1024**2  # 96MB floor — enough for a handful of cached slices even on a tiny box
    return max(floor, budget)


def scaled(fraction: float, *, min_bytes: int, max_bytes: int | None = None) -> int:
    """Take `fraction` of the per-worker budget, clamped to [min_bytes, max_bytes]."""
    value = int(per_worker_memory_budget_bytes() * fraction)
    value = max(min_bytes, value)
    if max_bytes is not None:
        value = min(max_bytes, value)
    return value

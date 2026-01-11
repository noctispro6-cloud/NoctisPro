"""
Auto-tune process concurrency for Noctis Pro containers.

Goals:
- Use available CPU cores efficiently without oversubscribing.
- Respect container memory limits (cgroups) when present.
- Provide a stable default split between web workers and celery workers.

Usage:
  python3 tools/auto_concurrency.py web
  python3 tools/auto_concurrency.py celery

Environment overrides:
  - WEB_CONCURRENCY / CELERY_CONCURRENCY: if set and valid, caller should prefer them.
"""

from __future__ import annotations

import math
import os
import sys
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


def _detect_memory_limit_bytes() -> int | None:
    """
    Best-effort memory limit detection.

    Priority:
    - cgroup v2: /sys/fs/cgroup/memory.max
    - cgroup v1: /sys/fs/cgroup/memory/memory.limit_in_bytes
    - /proc/meminfo (MemTotal)
    """
    # cgroup v2
    v2 = _read_int("/sys/fs/cgroup/memory.max")
    if v2 and v2 > 0:
        return v2

    # cgroup v1
    v1 = _read_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if v1 and v1 > 0:
        # Some runtimes report a huge number when unlimited; ignore obviously bogus limits.
        if v1 < (1 << 60):
            return v1

    # host total (fallback)
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    # kB
                    return int(parts[1]) * 1024
    except Exception:
        return None
    return None


def _detect_cpu_count() -> int:
    return int(os.cpu_count() or 1)


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def recommend(role: str) -> int:
    """
    Recommend a worker count for a given role ('web' or 'celery').

    Default policy:
    - Total "compute workers" ~= CPU cores (cap)
    - Split roughly 50/50 between web and celery to avoid CPU oversubscription
    - Apply a conservative memory cap for very small containers
    """
    role = (role or "").strip().lower()
    if role not in {"web", "celery"}:
        raise SystemExit("usage: python3 tools/auto_concurrency.py [web|celery]")

    cpu = _detect_cpu_count()
    mem_b = _detect_memory_limit_bytes() or 0
    mem_gb = mem_b / (1024**3) if mem_b else 0.0

    # Memory cap (very conservative for small containers).
    # Assumption: Each process can spike due to DICOM parsing, ORM caching, etc.
    # For larger boxes, CPU is the binding constraint.
    if mem_gb and mem_gb < 6:
        # ~1 worker per ~1.5GB, but never exceed CPU.
        mem_cap = int(math.floor(mem_gb / 1.5)) or 1
    else:
        mem_cap = cpu

    total = _clamp(min(cpu, mem_cap), 1, cpu)

    # Split without oversubscribing CPU: web + celery ~= total
    web = max(1, (total + 1) // 2)  # ceil
    celery = max(1, total // 2)  # floor

    # Hard safety caps: very large core counts can overwhelm Postgres (too many DB clients)
    # and/or memory due to per-process overhead. Users can always override explicitly with
    # WEB_CONCURRENCY / CELERY_CONCURRENCY.
    web = min(web, 8)
    celery = min(celery, 8)

    return web if role == "web" else celery


def main(argv: list[str]) -> int:
    role = argv[1] if len(argv) > 1 else ""
    print(recommend(role))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


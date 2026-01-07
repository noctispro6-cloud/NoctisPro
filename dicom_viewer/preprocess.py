"""
Background preprocessing for DICOM viewer.

Goal: move expensive CPU work (pixel decode, MPR volume build) off request threads,
and keep it bounded to a single dedicated worker (one CPU core) by default.

This module is intentionally self-contained and safe to import in web processes.
It uses a lazy ProcessPoolExecutor so the pool is only created when actually used.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ProcessPoolExecutor
from typing import Iterable, Optional

from django.conf import settings


_EXECUTOR_LOCK = threading.Lock()
_EXECUTOR: Optional[ProcessPoolExecutor] = None


def _get_int_env(name: str, default: int) -> int:
    try:
        v = int(str(os.environ.get(name, default)).strip())
        return max(0, v)
    except Exception:
        return default


def _enabled() -> bool:
    # Default: enabled in production and dev (bounded), can be turned off explicitly.
    if hasattr(settings, "DICOM_VIEWER_ENABLE_PREPROCESSING"):
        return bool(getattr(settings, "DICOM_VIEWER_ENABLE_PREPROCESSING"))
    try:
        return bool(getattr(settings, "DICOM_VIEWER_SETTINGS", {}).get("ENABLE_PREPROCESSING", True))
    except Exception:
        return True


def _max_workers() -> int:
    if hasattr(settings, "DICOM_VIEWER_PREPROCESS_WORKERS"):
        try:
            return max(0, int(getattr(settings, "DICOM_VIEWER_PREPROCESS_WORKERS")))
        except Exception:
            pass
    return _get_int_env("DICOM_VIEWER_PREPROCESS_WORKERS", 1)


def _max_series_per_study() -> int:
    if hasattr(settings, "DICOM_VIEWER_PREPROCESS_MAX_SERIES"):
        try:
            return max(0, int(getattr(settings, "DICOM_VIEWER_PREPROCESS_MAX_SERIES")))
        except Exception:
            pass
    return _get_int_env("DICOM_VIEWER_PREPROCESS_MAX_SERIES", 4)


def _get_executor() -> Optional[ProcessPoolExecutor]:
    """
    Lazily create a bounded process pool.
    NOTE: In multi-worker deployments, each web worker process will create its own pool.
    """
    global _EXECUTOR
    if not _enabled():
        return None
    workers = _max_workers()
    if workers <= 0:
        return None
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ProcessPoolExecutor(max_workers=workers)
        return _EXECUTOR


def schedule_mpr_disk_cache(series_id: int, *, quality: str = "high") -> bool:
    """
    Schedule a best-effort build of the MPR volume + persist compressed disk cache.
    Returns True if queued.
    """
    ex = _get_executor()
    if ex is None:
        return False
    try:
        sid = int(series_id)
    except Exception:
        return False
    q = (quality or "high").strip().lower()
    if q not in ("high", "fast"):
        q = "high"
    try:
        ex.submit(_worker_build_mpr_disk_cache, sid, q)
        return True
    except Exception:
        return False


def schedule_study_preprocess(study_id: int, *, quality: str = "high") -> bool:
    """
    Schedule preprocessing for up to N series in the study (default N=4).
    Uses the MPR disk cache build as the primary "warm" step.
    """
    ex = _get_executor()
    if ex is None:
        return False
    try:
        sid = int(study_id)
    except Exception:
        return False

    # Resolve series IDs in the web process (cheap), then enqueue per-series jobs.
    try:
        from worklist.models import Series, Study

        study = Study.objects.filter(id=sid).only("id").first()
        if not study:
            return False
        max_n = _max_series_per_study()
        if max_n <= 0:
            return False
        series_ids = list(
            Series.objects.filter(study_id=sid).order_by("series_number").values_list("id", flat=True)[:max_n]
        )
    except Exception:
        return False

    queued_any = False
    for series_id in series_ids:
        try:
            if schedule_mpr_disk_cache(int(series_id), quality=quality):
                queued_any = True
        except Exception:
            continue
    return queued_any


def schedule_series_mpr_cache(series_ids: Iterable[int], *, quality: str = "high") -> int:
    """Convenience: enqueue MPR disk cache build for multiple series IDs."""
    count = 0
    for sid in series_ids:
        if schedule_mpr_disk_cache(int(sid), quality=quality):
            count += 1
    return count


def _worker_build_mpr_disk_cache(series_id: int, quality: str) -> None:
    """
    Runs inside the process pool.
    Import Django + viewer code lazily in the worker.
    """
    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "noctis_pro.settings")
        import django

        django.setup()
    except Exception:
        return

    try:
        from django.db import close_old_connections

        close_old_connections()
    except Exception:
        pass

    try:
        from worklist.models import Series

        s = Series.objects.get(id=int(series_id))

        # Reuse the existing, battle-tested MPR builder + disk cache writer.
        # NOTE: importing `dicom_viewer.views` is heavy, but it's isolated to the worker process.
        from dicom_viewer import views as viewer_views

        vol, sp = viewer_views._get_mpr_volume_and_spacing(s, quality=(quality or "high"))
        viewer_views._mpr_persist_disk_cache(s, (quality or "high"), vol, sp)
    except Exception:
        pass
    finally:
        try:
            from django.db import close_old_connections

            close_old_connections()
        except Exception:
            pass


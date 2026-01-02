"""
FastAPI image endpoints (mounted inside the existing ASGI stack).

Goal: speed up DICOM PNG rendering by using an async-friendly endpoint with
aggressive in-memory + on-disk caching, while preserving existing URLs and
permission behavior.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import OrderedDict
from importlib import import_module
from typing import Optional

import numpy as np
import pydicom
from fastapi import FastAPI, Request
from pydicom.pixel_data_handlers.util import apply_voi_lut
from starlette.responses import FileResponse, RedirectResponse, Response

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from worklist.models import DicomImage

logger = logging.getLogger(__name__)

fastapi_app = FastAPI(title="Noctis Pro FastAPI Image Service", docs_url=None, redoc_url=None)


class _BytesLRUCache:
    """A tiny thread-safe LRU cache for PNG bytes."""

    def __init__(self, *, max_items: int = 128, max_bytes: int = 256 * 1024 * 1024) -> None:
        self._max_items = int(max_items)
        self._max_bytes = int(max_bytes)
        self._lock = threading.Lock()
        self._data: "OrderedDict[str, bytes]" = OrderedDict()
        self._size = 0

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            val = self._data.get(key)
            if val is None:
                return None
            # refresh LRU
            self._data.move_to_end(key)
            return val

    def set(self, key: str, val: bytes) -> None:
        if not val:
            return
        with self._lock:
            prev = self._data.pop(key, None)
            if prev is not None:
                self._size -= len(prev)
            self._data[key] = val
            self._size += len(val)
            self._data.move_to_end(key)

            while self._data and (len(self._data) > self._max_items or self._size > self._max_bytes):
                _, evicted = self._data.popitem(last=False)
                self._size -= len(evicted)


_PNG_MEM_CACHE = _BytesLRUCache(max_items=128, max_bytes=256 * 1024 * 1024)
_RENDER_LOCKS: dict[str, threading.Lock] = {}
_RENDER_LOCKS_GUARD = threading.Lock()


def _get_render_lock(key: str) -> threading.Lock:
    with _RENDER_LOCKS_GUARD:
        lock = _RENDER_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _RENDER_LOCKS[key] = lock
        return lock


def _first_or_none(v):
    try:
        if hasattr(v, "__iter__") and not isinstance(v, str):
            return v[0]
    except Exception:
        pass
    return v


def _safe_float(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _render_cache_root() -> str:
    return os.path.join(settings.MEDIA_ROOT, "dicom", "render_cache_v1")


def _cache_key(image_id: int, ww: float, wl: float, inverted: bool) -> str:
    # Quantize floats a bit to avoid cache fragmentation on noisy query strings.
    ww_q = f"{float(ww):.3f}"
    wl_q = f"{float(wl):.3f}"
    return f"img:{int(image_id)}|ww:{ww_q}|wl:{wl_q}|inv:{1 if inverted else 0}"


def _cache_path(image_id: int, ww: float, wl: float, inverted: bool) -> str:
    key = _cache_key(image_id, ww, wl, inverted)
    # Use the key as filename; keep per-image subdir to avoid huge single directories.
    safe_name = key.replace(":", "_").replace("|", "__")
    return os.path.join(_render_cache_root(), f"image_{int(image_id)}", f"{safe_name}.png")


def _get_django_user_from_session_cookie(request: Request):
    """Resolve Django user from db-backed session cookie."""
    try:
        session_cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "sessionid")
        session_key = request.cookies.get(session_cookie_name)
        if not session_key:
            return AnonymousUser()

        engine = import_module(settings.SESSION_ENGINE)
        SessionStore = engine.SessionStore  # type: ignore[attr-defined]
        session = SessionStore(session_key=session_key)
        try:
            session.load()
        except Exception:
            return AnonymousUser()

        user_id = session.get("_auth_user_id")
        if not user_id:
            return AnonymousUser()

        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return AnonymousUser()
    except Exception:
        return AnonymousUser()


def _read_dicom_dataset(image: DicomImage):
    ds = None
    if not image.file_path:
        return None

    # Prefer storage-safe reads (works for local FS + S3-like backends).
    try:
        with image.file_path.open("rb") as f:
            try:
                ds = pydicom.dcmread(f, stop_before_pixels=False, force=False)
            except Exception:
                try:
                    f.seek(0)
                except Exception:
                    pass
                ds = pydicom.dcmread(f, stop_before_pixels=False, force=True)
    except Exception:
        ds = None

    # Last resort: local filesystem path (only for FileSystemStorage-like backends)
    if ds is None:
        try:
            if image.file_path and hasattr(image.file_path, "path"):
                ds = pydicom.dcmread(image.file_path.path, stop_before_pixels=False, force=True)
        except Exception:
            ds = None

    return ds


def _decode_pixel_array(image: DicomImage, ds):
    try:
        px = ds.pixel_array
        try:
            modality = str(getattr(ds, "Modality", "")).upper()
            if modality in ["DX", "CR", "XA", "RF", "MG"]:
                px = apply_voi_lut(px, ds)
        except Exception:
            pass
        return px.astype(np.float32)
    except Exception:
        # SimpleITK fallback needs local path
        try:
            import SimpleITK as sitk

            if image.file_path and hasattr(image.file_path, "path"):
                sitk_img = sitk.ReadImage(image.file_path.path)
                arr = sitk.GetArrayFromImage(sitk_img)
                if arr.ndim == 3 and arr.shape[0] == 1:
                    arr = arr[0]
                return arr.astype(np.float32)
        except Exception:
            return None

    return None


def _normalize_to_2d_grayscale(arr: np.ndarray) -> Optional[np.ndarray]:
    try:
        a = arr
        if getattr(a, "ndim", 0) == 4 and a.shape[0] == 1:
            a = a[0]
        if getattr(a, "ndim", 0) == 3:
            # (1, rows, cols) or (frames, rows, cols)
            if a.shape[0] == 1:
                a = a[0]
            elif a.shape[0] > 1 and a.shape[1] > 1 and a.shape[2] > 1:
                a = a[0]
        if getattr(a, "ndim", 0) == 3 and a.shape[-1] == 1:
            a = a[..., 0]
        if getattr(a, "ndim", 0) == 3 and a.shape[-1] in (3, 4):
            a = a[..., :3].mean(axis=-1)
        if getattr(a, "ndim", 0) != 2:
            return None
        return np.asarray(a, dtype=np.float32)
    except Exception:
        return None


def _apply_rescale_if_present(arr: np.ndarray, ds) -> np.ndarray:
    if hasattr(ds, "RescaleSlope") and hasattr(ds, "RescaleIntercept"):
        try:
            return arr * float(ds.RescaleSlope) + float(ds.RescaleIntercept)
        except Exception:
            return arr
    return arr


def _derive_default_window(arr: np.ndarray, ds) -> tuple[float, float]:
    default_ww = _first_or_none(getattr(ds, "WindowWidth", None))
    default_wl = _first_or_none(getattr(ds, "WindowCenter", None))
    try:
        if default_ww is not None and default_wl is not None:
            return float(default_ww), float(default_wl)
    except Exception:
        pass

    # Robust percentiles (fast enough for single-slice)
    try:
        flat = arr.astype(np.float32, copy=False).ravel()
        p2 = float(np.percentile(flat, 2))
        p98 = float(np.percentile(flat, 98))
        ww = max(1.0, p98 - p2)
        wl = (p98 + p2) / 2.0
        return ww, wl
    except Exception:
        return 400.0, 40.0


def _render_png_bytes(pixel_array: np.ndarray, window_width: float, window_level: float, inverted: bool) -> Optional[bytes]:
    # Reuse the existing renderer to preserve output parity.
    from dicom_viewer.views import _array_to_png_bytes  # local import avoids import-order issues

    try:
        return _array_to_png_bytes(pixel_array, window_width, window_level, inverted)
    except Exception:
        return None


def _compute_png_for_request(image_id: int, ww: Optional[float], wl: Optional[float], inverted: bool, user):
    try:
        image = DicomImage.objects.select_related("series__study__facility").get(id=image_id)
    except DicomImage.DoesNotExist:
        return None, 404, None, None

    # Permission parity with Django views
    if getattr(user, "is_facility_user", None) and user.is_facility_user():
        try:
            if getattr(user, "facility", None) and image.series.study.facility != user.facility:
                return None, 403, None, None
        except Exception:
            return None, 403, None, None

    ds = _read_dicom_dataset(image)
    if ds is None:
        return None, 404, None, None

    pixel = _decode_pixel_array(image, ds)
    if pixel is None:
        return None, 404, None, None

    pixel = _normalize_to_2d_grayscale(pixel)
    if pixel is None:
        return None, 404, None, None

    pixel = _apply_rescale_if_present(pixel, ds)

    if ww is None or wl is None:
        dww, dwl = _derive_default_window(pixel, ds)
        ww = dww if ww is None else ww
        wl = dwl if wl is None else wl

    png_bytes = _render_png_bytes(pixel, float(ww), float(wl), bool(inverted))
    if not png_bytes:
        return None, 404, None, None

    return png_bytes, 200, float(ww), float(wl)


@fastapi_app.get("/dicom-viewer/api/image/{image_id}/render.png")
async def dicom_image_render_png(request: Request, image_id: int):
    """
    Fast path for streaming a windowed DICOM slice as PNG bytes.
    URL matches existing Django endpoint to avoid breaking clients.
    """
    user = _get_django_user_from_session_cookie(request)
    if not getattr(user, "is_authenticated", False):
        login_url = getattr(settings, "LOGIN_URL", "/login/")
        return RedirectResponse(url=f"{login_url}?next={request.url.path}", status_code=302)

    ww = _safe_float(request.query_params.get("window_width") or request.query_params.get("ww"))
    wl = _safe_float(request.query_params.get("window_level") or request.query_params.get("wl"))
    inv_raw = request.query_params.get("inverted")
    if inv_raw is None:
        inv_raw = request.query_params.get("invert")
    inverted = (inv_raw or "false").strip().lower() == "true"

    # If no ww/wl provided, we still compute them, then cache using derived values.
    # This makes repeated "default window" requests fast.
    tmp_ww = ww if ww is not None else 0.0
    tmp_wl = wl if wl is not None else 0.0
    mem_key = _cache_key(image_id, tmp_ww, tmp_wl, inverted) if (ww is not None and wl is not None) else None

    # Memory cache only when the key is stable (caller provided ww+wl).
    if mem_key is not None:
        cached = _PNG_MEM_CACHE.get(mem_key)
        if cached is not None:
            return Response(content=cached, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

        disk_path = _cache_path(image_id, ww, wl, inverted)
        if os.path.exists(disk_path) and os.path.getsize(disk_path) > 0:
            return FileResponse(
                disk_path,
                media_type="image/png",
                headers={"Cache-Control": "private, max-age=3600"},
            )

    # Compute (in a thread) so we don't block the event loop.
    # We lock per cache key to avoid duplicate work during bursts.
    lock_key = mem_key or f"img:{int(image_id)}|default|inv:{1 if inverted else 0}"
    lock = _get_render_lock(lock_key)

    def _do_render_sync():
        with lock:
            return _compute_png_for_request(image_id, ww, wl, inverted, user)

    png_bytes, status, ww_used, wl_used = await asyncio.to_thread(_do_render_sync)

    if status != 200 or not png_bytes:
        return Response(status_code=int(status))

    # Persist cache using the actual ww/wl used (covers default-window requests too).
    try:
        ww_used = float(ww_used if ww_used is not None else ww or 0.0)
        wl_used = float(wl_used if wl_used is not None else wl or 0.0)
        stable_key = _cache_key(image_id, ww_used, wl_used, inverted)
        out_path = _cache_path(image_id, ww_used, wl_used, inverted)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            tmp_path = f"{out_path}.tmp"
            with open(tmp_path, "wb") as f:
                f.write(png_bytes)
            os.replace(tmp_path, out_path)
        _PNG_MEM_CACHE.set(stable_key, png_bytes)
    except Exception as e:
        logger.debug("FastAPI PNG cache write failed: %s", e)

    return Response(content=png_bytes, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


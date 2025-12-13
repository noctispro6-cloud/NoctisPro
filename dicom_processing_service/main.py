"""FastAPI DICOM processing service.

Purpose:
- Offload DICOM pixel decoding + window/level + inversion + PNG encoding from Django.
- Keep the web UI/annotations in Django/JS unchanged.

This service is designed to run on the same host and read DICOM files from MEDIA_ROOT.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pydicom
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydicom.pixel_data_handlers.util import apply_voi_lut
from PIL import Image


def _try_setup_django() -> None:
    """Optional: allow importing shared helpers that may touch django.conf.settings."""

    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "noctis_pro.settings"))
        import django  # type: ignore

        django.setup()
    except Exception:
        # Service can run without Django; we keep pure-Python fallbacks.
        return


_try_setup_django()

try:
    from dicom_viewer.dicom_utils import DicomProcessor  # type: ignore

    _processor: Any | None = DicomProcessor()
except Exception:
    _processor = None

try:
    from worklist.models import DicomImage, Series  # type: ignore

    _orm_available = True
except Exception:
    DicomImage = None  # type: ignore
    Series = None  # type: ignore
    _orm_available = False


app = FastAPI(title="Noctis Pro DICOM Processor", version="1.0")

#
# Small per-worker in-process caches (keep conservative; multiple workers OK)
#
_VOL_CACHE: dict[int, dict[str, Any]] = {}  # series_id -> {volume: np.ndarray, spacing: tuple[float,float,float]}
_VOL_CACHE_ORDER: list[int] = []
_MAX_VOL_CACHE = 4

_SLICE_CACHE: dict[str, str] = {}  # key -> base64 data URL
_SLICE_CACHE_ORDER: list[str] = []
_MAX_SLICE_CACHE = 800


def _require_orm() -> None:
    if not _orm_available:
        raise HTTPException(
            status_code=503,
            detail="Django ORM not available in processor service. Set DJANGO_SETTINGS_MODULE and ensure DB connectivity.",
        )


def _lru_get_slice(key: str) -> str | None:
    val = _SLICE_CACHE.get(key)
    if val is None:
        return None
    try:
        _SLICE_CACHE_ORDER.remove(key)
    except ValueError:
        pass
    _SLICE_CACHE_ORDER.append(key)
    return val


def _lru_set_slice(key: str, val: str) -> None:
    if key not in _SLICE_CACHE:
        while len(_SLICE_CACHE_ORDER) >= _MAX_SLICE_CACHE:
            evict = _SLICE_CACHE_ORDER.pop(0)
            _SLICE_CACHE.pop(evict, None)
    _SLICE_CACHE[key] = val
    try:
        _SLICE_CACHE_ORDER.remove(key)
    except ValueError:
        pass
    _SLICE_CACHE_ORDER.append(key)


def _media_root() -> Path:
    # Prefer explicit env var for service deployments.
    mr = os.environ.get("MEDIA_ROOT")
    if mr:
        return Path(mr).resolve()

    # Fall back to Django settings if available.
    try:
        from django.conf import settings as dj_settings  # type: ignore

        return Path(str(dj_settings.MEDIA_ROOT)).resolve()
    except Exception:
        # Reasonable repo-local default
        return Path("/workspace/media").resolve()


def _resolve_media_path(rel_path: str) -> Path:
    if not rel_path:
        raise HTTPException(status_code=400, detail="rel_path is required")

    # Normalize to a relative, POSIX-like path.
    rel_path = rel_path.lstrip("/\\")

    base = _media_root()
    target = (base / rel_path).resolve()

    # Prevent path traversal outside MEDIA_ROOT.
    base_str = str(base)
    target_str = str(target)
    if not (target_str == base_str or target_str.startswith(base_str + os.sep)):
        raise HTTPException(status_code=400, detail="Invalid rel_path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return target


def _derive_window(pixel_array: np.ndarray, modality: str) -> tuple[float, float]:
    if _processor is not None:
        try:
            return _processor.auto_window_from_data(pixel_array, percentile_range=(2, 98), modality=modality)
        except Exception:
            pass

    flat = pixel_array.astype(np.float32).ravel()
    p1 = float(np.percentile(flat, 1))
    p99 = float(np.percentile(flat, 99))
    ww = max(1.0, p99 - p1)
    wl = (p99 + p1) / 2.0
    return ww, wl


def _apply_windowing(pixel_array: np.ndarray, ww: float, wl: float, invert: bool) -> np.ndarray:
    if _processor is not None:
        try:
            return _processor.apply_windowing(pixel_array, ww, wl, invert=invert, enhanced_contrast=True)
        except Exception:
            pass

    # Fallback: linear windowing
    img = pixel_array.astype(np.float32)
    lo = wl - ww / 2.0
    hi = wl + ww / 2.0
    img = np.clip(img, lo, hi)
    denom = max(1e-6, hi - lo)
    img = (img - lo) / denom * 255.0
    if invert:
        img = 255.0 - img
    return np.clip(img, 0, 255).astype(np.uint8)


def _png_data_url(image_u8: np.ndarray) -> str:
    pil = Image.fromarray(image_u8, mode="L")
    buf = BytesIO()
    # Optimize for speed over size
    pil.save(buf, format="PNG", optimize=False, compress_level=1)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _decode_dicom_to_float32(dicom_path: Path) -> tuple[np.ndarray | None, Any | None, dict[str, str]]:
    """Decode pixels to float32, returning (pixel_array, ds, warnings)."""
    warnings: dict[str, str] = {}
    ds = None
    try:
        ds = pydicom.dcmread(str(dicom_path), stop_before_pixels=False)
    except Exception as e:
        warnings["dicom_read_error"] = str(e)
        return None, None, warnings

    try:
        arr = ds.pixel_array
        try:
            modality = str(getattr(ds, "Modality", "")).upper()
            if modality in {"DX", "CR", "XA", "RF", "MG"}:
                arr = apply_voi_lut(arr, ds)
        except Exception:
            pass
        arr = arr.astype(np.float32)
    except Exception:
        try:
            import SimpleITK as sitk  # type: ignore

            sitk_image = sitk.ReadImage(str(dicom_path))
            px = sitk.GetArrayFromImage(sitk_image)
            if px.ndim == 3 and px.shape[0] == 1:
                px = px[0]
            arr = px.astype(np.float32)
        except Exception as e:
            warnings["pixel_decode_error"] = str(e)
            return None, ds, warnings

    if hasattr(ds, "RescaleSlope") and hasattr(ds, "RescaleIntercept"):
        try:
            arr = arr * float(ds.RescaleSlope) + float(ds.RescaleIntercept)
        except Exception:
            pass

    return arr, ds, warnings


def _series_images(series_id: int) -> list[Any]:
    _require_orm()
    series = Series.objects.get(id=series_id)  # type: ignore[attr-defined]
    return list(series.images.all().order_by("slice_location", "instance_number"))  # type: ignore[union-attr]


def _get_series_volume(series_id: int) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Build (or cache) a float32 volume for the given series."""
    if series_id in _VOL_CACHE:
        try:
            _VOL_CACHE_ORDER.remove(series_id)
        except ValueError:
            pass
        _VOL_CACHE_ORDER.append(series_id)
        entry = _VOL_CACHE[series_id]
        return entry["volume"], entry["spacing"]

    imgs = _series_images(series_id)
    if len(imgs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 images for volume operations")

    volume_slices: list[np.ndarray] = []
    first_ds = None
    for img in imgs:
        rel = str(getattr(img, "file_path", ""))
        dicom_path = _resolve_media_path(rel)
        arr, ds, _warn = _decode_dicom_to_float32(dicom_path)
        if first_ds is None and ds is not None:
            first_ds = ds
        if arr is None:
            continue
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim != 2:
            continue
        volume_slices.append(arr)

    if len(volume_slices) < 2:
        raise HTTPException(status_code=400, detail="Could not read enough images to build volume")

    vol = np.stack(volume_slices, axis=0).astype(np.float32)

    # Spacing estimate
    sp_y, sp_x = 1.0, 1.0
    sp_z = 1.0
    try:
        if first_ds is not None and hasattr(first_ds, "PixelSpacing"):
            sp = first_ds.PixelSpacing
            sp_y, sp_x = float(sp[0]), float(sp[1])
    except Exception:
        pass
    try:
        if first_ds is not None and hasattr(first_ds, "SpacingBetweenSlices"):
            sp_z = float(first_ds.SpacingBetweenSlices)
        elif first_ds is not None and hasattr(first_ds, "SliceThickness"):
            sp_z = float(first_ds.SliceThickness)
    except Exception:
        pass

    spacing = (float(sp_z), float(sp_y), float(sp_x))

    while len(_VOL_CACHE_ORDER) >= _MAX_VOL_CACHE:
        evict = _VOL_CACHE_ORDER.pop(0)
        _VOL_CACHE.pop(evict, None)
    _VOL_CACHE[series_id] = {"volume": vol, "spacing": spacing}
    _VOL_CACHE_ORDER.append(series_id)
    return vol, spacing


def _mpr_counts(volume: np.ndarray) -> dict[str, int]:
    return {"axial": int(volume.shape[0]), "coronal": int(volume.shape[1]), "sagittal": int(volume.shape[2])}


def _mpr_slice_from_volume(volume: np.ndarray, plane: Literal["axial", "sagittal", "coronal"], slice_index: int) -> np.ndarray:
    if plane == "axial":
        return volume[slice_index, :, :]
    if plane == "sagittal":
        return volume[:, :, slice_index]
    return volume[:, slice_index, :]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/render")
def render_dicom(
    rel_path: str,
    window_width: float | None = None,
    window_level: float | None = None,
    inverted: bool | None = None,
    image_id: int | None = None,
    instance_number: int | None = None,
    slice_location: float | None = None,
) -> dict[str, Any]:
    """Render a single-frame DICOM into a PNG data URL.

    Notes:
    - The caller (Django) is responsible for access control.
    - This service only ensures path safety under MEDIA_ROOT.
    """

    dicom_path = _resolve_media_path(rel_path)

    warnings: dict[str, str] = {}

    ds = None
    try:
        ds = pydicom.dcmread(str(dicom_path), stop_before_pixels=False)
    except Exception as e:
        warnings["dicom_read_error"] = str(e)

    pixel_array = None
    pixel_decode_error = None

    if ds is not None:
        try:
            pixel_array = ds.pixel_array
            try:
                modality = str(getattr(ds, "Modality", "")).upper()
                if modality in {"DX", "CR", "XA", "RF", "MG"}:
                    pixel_array = apply_voi_lut(pixel_array, ds)
            except Exception:
                pass
            pixel_array = pixel_array.astype(np.float32)
        except Exception as e:
            # Fallback for compressed DICOMs: SimpleITK
            try:
                import SimpleITK as sitk  # type: ignore

                sitk_image = sitk.ReadImage(str(dicom_path))
                arr = sitk.GetArrayFromImage(sitk_image)
                if arr.ndim == 3 and arr.shape[0] == 1:
                    arr = arr[0]
                pixel_array = arr.astype(np.float32)
            except Exception as _e:
                pixel_decode_error = str(_e)
                warnings["pixel_decode_error"] = pixel_decode_error
                pixel_array = None

    # Apply slope/intercept to get HU-like values when present
    if pixel_array is not None and ds is not None and hasattr(ds, "RescaleSlope") and hasattr(ds, "RescaleIntercept"):
        try:
            pixel_array = pixel_array * float(ds.RescaleSlope) + float(ds.RescaleIntercept)
        except Exception:
            pass

    modality = str(getattr(ds, "Modality", "")) if ds is not None else ""
    photo = str(getattr(ds, "PhotometricInterpretation", "")).upper() if ds is not None else ""

    default_inverted = False
    if modality.upper() in {"DX", "CR", "XA", "RF"} and photo == "MONOCHROME1":
        default_inverted = True

    # Derive default WW/WL
    default_ww = None
    default_wl = None
    if ds is not None:
        default_ww = getattr(ds, "WindowWidth", None)
        default_wl = getattr(ds, "WindowCenter", None)
        if hasattr(default_ww, "__iter__") and not isinstance(default_ww, str):
            default_ww = default_ww[0]
        if hasattr(default_wl, "__iter__") and not isinstance(default_wl, str):
            default_wl = default_wl[0]

    if (default_ww is None or default_wl is None) and pixel_array is not None:
        dw, dl = _derive_window(pixel_array, modality or "CT")
        default_ww = default_ww or dw
        default_wl = default_wl or dl

    ww = float(window_width) if window_width is not None else float(default_ww or 400.0)
    wl = float(window_level) if window_level is not None else float(default_wl or 40.0)

    # If caller didn’t explicitly set inversion, apply modality default.
    invert = bool(default_inverted) if inverted is None else bool(inverted)

    image_data_url = None
    if pixel_array is not None:
        try:
            image_u8 = _apply_windowing(pixel_array, ww, wl, invert)
            image_data_url = _png_data_url(image_u8)
        except Exception as e:
            warnings["render_error"] = str(e)

    image_info: dict[str, Any] = {
        "id": image_id,
        "instance_number": instance_number,
        "slice_location": slice_location,
        "dimensions": [int(getattr(ds, "Rows", 0) or 0), int(getattr(ds, "Columns", 0) or 0)] if ds is not None else [0, 0],
        "pixel_spacing": getattr(ds, "PixelSpacing", [1.0, 1.0]) if ds is not None else [1.0, 1.0],
        "slice_thickness": float(getattr(ds, "SliceThickness", 1.0)) if ds is not None else 1.0,
        "default_window_width": float(default_ww) if default_ww is not None else 400.0,
        "default_window_level": float(default_wl) if default_wl is not None else 40.0,
        "modality": modality,
        "series_description": str(getattr(ds, "SeriesDescription", "")) if ds is not None else "",
        "patient_name": str(getattr(ds, "PatientName", "")) if ds is not None else "",
        "study_date": str(getattr(ds, "StudyDate", "")) if ds is not None else "",
        "bits_allocated": int(getattr(ds, "BitsAllocated", 16)) if ds is not None else 16,
        "bits_stored": int(getattr(ds, "BitsStored", 16)) if ds is not None else 16,
        "photometric_interpretation": str(getattr(ds, "PhotometricInterpretation", "")) if ds is not None else "",
    }

    payload: dict[str, Any] = {
        "image_data": image_data_url,
        "image_info": image_info,
        "windowing": {"window_width": ww, "window_level": wl, "inverted": invert},
        "warnings": (warnings or None),
    }

    return payload


@app.get("/v1/auto-window")
def auto_window(image_id: int) -> dict[str, Any]:
    """Compute optimal WW/WL (and CT suggested preset) for an image."""
    _require_orm()
    img = DicomImage.objects.get(id=image_id)  # type: ignore[attr-defined]
    dicom_path = _resolve_media_path(str(getattr(img, "file_path", "")))
    arr, ds, warnings = _decode_dicom_to_float32(dicom_path)
    if arr is None or ds is None:
        raise HTTPException(status_code=400, detail={"error": "Could not read pixel data", "warnings": warnings})

    modality = str(getattr(ds, "Modality", "")).upper()
    ww, wl = _derive_window(arr, modality or "CT")

    suggested = None
    if _processor is not None:
        try:
            ww, wl = _processor.auto_window_from_data(arr, percentile_range=(2, 98), modality=modality)
            if modality == "CT":
                suggested = _processor.get_optimal_preset_for_hu_range(float(arr.min()), float(arr.max()), modality)
                if suggested in getattr(_processor, "window_presets", {}):
                    preset = _processor.window_presets[suggested]
                    ww, wl = preset["ww"], preset["wl"]
        except Exception:
            pass

    return {
        "success": True,
        "window_width": float(ww),
        "window_level": float(wl),
        "suggested_preset": suggested,
        "modality": modality,
        "hu_range": {"min": float(arr.min()), "max": float(arr.max()), "mean": float(np.mean(arr))},
        "warnings": (warnings or None),
    }


@app.get("/v1/hu")
def hu_value(
    mode: Literal["series", "mpr"],
    x: int,
    y: int,
    image_id: int | None = None,
    series_id: int | None = None,
    plane: Literal["axial", "sagittal", "coronal"] | None = None,
    slice: int | None = None,
    shape: Literal["ellipse"] | None = None,
    cx: int | None = None,
    cy: int | None = None,
    rx: int | None = None,
    ry: int | None = None,
) -> dict[str, Any]:
    """HU sampling for series images or MPR slices (includes ellipse ROI stats)."""
    if mode == "series":
        if image_id is None:
            raise HTTPException(status_code=400, detail="image_id is required for mode=series")
        _require_orm()
        img = DicomImage.objects.get(id=image_id)  # type: ignore[attr-defined]
        dicom_path = _resolve_media_path(str(getattr(img, "file_path", "")))
        arr, _ds, warnings = _decode_dicom_to_float32(dicom_path)
        if arr is None:
            raise HTTPException(status_code=400, detail={"error": "Could not read pixel data", "warnings": warnings})
        h, w = arr.shape[:2]
        if shape == "ellipse":
            cx0 = int(cx if cx is not None else x)
            cy0 = int(cy if cy is not None else y)
            rx0 = max(1, int(rx if rx is not None else 1))
            ry0 = max(1, int(ry if ry is not None else 1))
            yy, xx = np.ogrid[:h, :w]
            mask = ((xx - cx0) ** 2) / (rx0**2) + ((yy - cy0) ** 2) / (ry0**2) <= 1.0
            roi = arr[mask]
            if roi.size == 0:
                raise HTTPException(status_code=400, detail="Empty ROI")
            return {
                "mode": "series",
                "image_id": image_id,
                "stats": {"mean": float(np.mean(roi)), "std": float(np.std(roi)), "min": float(np.min(roi)), "max": float(np.max(roi)), "n": int(roi.size)},
                "warnings": (warnings or None),
            }
        if x < 0 or y < 0 or x >= w or y >= h:
            raise HTTPException(status_code=400, detail="Out of bounds")
        return {"mode": "series", "image_id": image_id, "x": x, "y": y, "hu": round(float(arr[y, x]), 2), "warnings": (warnings or None)}

    if series_id is None or plane is None or slice is None:
        raise HTTPException(status_code=400, detail="series_id, plane, and slice are required for mode=mpr")

    vol, _spacing = _get_series_volume(series_id)
    counts = _mpr_counts(vol)
    if plane not in counts:
        raise HTTPException(status_code=400, detail="Invalid plane")
    si = max(0, min(counts[plane] - 1, int(slice)))
    sl = _mpr_slice_from_volume(vol, plane, si)
    h, w = sl.shape[:2]

    if shape == "ellipse":
        cx0 = int(cx if cx is not None else x)
        cy0 = int(cy if cy is not None else y)
        rx0 = max(1, int(rx if rx is not None else 1))
        ry0 = max(1, int(ry if ry is not None else 1))
        yy, xx = np.ogrid[:h, :w]
        mask = ((xx - cx0) ** 2) / (rx0**2) + ((yy - cy0) ** 2) / (ry0**2) <= 1.0
        roi = sl[mask]
        if roi.size == 0:
            raise HTTPException(status_code=400, detail="Empty ROI")
        return {
            "mode": "mpr",
            "series_id": series_id,
            "plane": plane,
            "slice": si,
            "stats": {"mean": float(np.mean(roi)), "std": float(np.std(roi)), "min": float(np.min(roi)), "max": float(np.max(roi)), "n": int(roi.size)},
        }

    if x < 0 or y < 0 or x >= w or y >= h:
        raise HTTPException(status_code=400, detail="Out of bounds")
    return {"mode": "mpr", "series_id": series_id, "plane": plane, "slice": si, "x": x, "y": y, "hu": round(float(sl[y, x]), 2)}


@app.get("/v1/mpr")
def mpr(
    series_id: int,
    plane: Literal["axial", "sagittal", "coronal"] | None = None,
    slice: int | None = None,
    window_width: float | None = None,
    window_level: float | None = None,
    inverted: bool = False,
) -> dict[str, Any]:
    """MPR JSON endpoint compatible with Django's `api_mpr_reconstruction` behavior."""
    vol, spacing = _get_series_volume(series_id)
    counts = _mpr_counts(vol)

    def _render(plane_name: Literal["axial", "sagittal", "coronal"], idx: int) -> str:
        ww = float(window_width) if window_width is not None else 400.0
        wl = float(window_level) if window_level is not None else 40.0
        key = f"{series_id}|{plane_name}|{int(idx)}|{int(round(ww))}|{int(round(wl))}|{1 if inverted else 0}"
        cached = _lru_get_slice(key)
        if cached is not None:
            return cached
        sl = _mpr_slice_from_volume(vol, plane_name, idx)
        img_u8 = _apply_windowing(sl, ww, wl, invert=inverted)
        url = _png_data_url(img_u8)
        _lru_set_slice(key, url)
        return url

    if plane is not None:
        idx = int(slice if slice is not None else counts[plane] // 2)
        idx = max(0, min(counts[plane] - 1, idx))
        return {
            "plane": plane,
            "slice_index": idx,
            "counts": counts,
            "spacing": [float(spacing[0]), float(spacing[1]), float(spacing[2])],
            "image_data": _render(plane, idx),
        }

    previews: dict[str, Any] = {}
    for p in ("axial", "sagittal", "coronal"):
        mid = counts[p] // 2
        previews[p] = {"slice_index": int(mid), "image_data": _render(p, int(mid))}
    return {"mpr_views": previews, "counts": counts, "spacing": [float(spacing[0]), float(spacing[1]), float(spacing[2])]}


@app.get("/v1/mpr/slice.png")
def mpr_slice_png(
    series_id: int,
    plane: Literal["axial", "sagittal", "coronal"],
    slice: int,
    ww: float = 400.0,
    wl: float = 40.0,
    inverted: bool = False,
) -> Response:
    """Direct PNG response for a single MPR slice."""
    vol, _spacing = _get_series_volume(series_id)
    counts = _mpr_counts(vol)
    idx = max(0, min(counts[plane] - 1, int(slice)))
    sl = _mpr_slice_from_volume(vol, plane, idx)
    img_u8 = _apply_windowing(sl, float(ww), float(wl), invert=inverted)
    pil = Image.fromarray(img_u8, mode="L")
    buf = BytesIO()
    pil.save(buf, format="PNG", optimize=False, compress_level=1)
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/v1/series/volume_uint8")
def series_volume_uint8(series_id: int, ww: float = 400.0, wl: float = 40.0, max_dim: int = 256) -> dict[str, Any]:
    """Return downsampled uint8 volume for GPU VR: {shape, spacing, data(base64 raw)}."""
    vol, spacing = _get_series_volume(series_id)
    lo = float(wl) - float(ww) / 2.0
    hi = float(wl) + float(ww) / 2.0
    v = np.clip(vol, lo, hi)
    denom = max(1e-6, hi - lo)
    v = (v - lo) / denom * 255.0
    v = np.clip(v, 0, 255).astype(np.uint8)

    z, y, x = v.shape
    scale = min(1.0, float(max_dim) / float(max(z, y, x)))
    if scale < 0.999:
        try:
            from scipy import ndimage  # type: ignore

            v = ndimage.zoom(v, (scale, scale, scale), order=1)
        except Exception:
            pass

    b64 = base64.b64encode(v.tobytes()).decode("ascii")
    return {
        "shape": [int(v.shape[0]), int(v.shape[1]), int(v.shape[2])],
        "spacing": [float(spacing[0]), float(spacing[1]), float(spacing[2])],
        "data": b64,
    }


def _maybe_interpolate_thin_stack(volume: np.ndarray, min_slices: int = 32) -> np.ndarray:
    """Upsample along Z for thin stacks to improve MIP/bone quality (best-effort)."""
    try:
        z = int(volume.shape[0])
        if z >= min_slices:
            return volume
        target_slices = max(min_slices, z * 3)
        factor = float(target_slices) / float(max(1, z))
        from scipy import ndimage  # type: ignore

        return ndimage.zoom(volume, (factor, 1, 1), order=3, prefilter=True)
    except Exception:
        return volume


@app.get("/v1/mip")
def mip_reconstruction(
    series_id: int,
    window_width: float = 400.0,
    window_level: float = 40.0,
    inverted: bool = False,
) -> dict[str, Any]:
    """Maximum Intensity Projection (MIP) compatible with Django `api_mip_reconstruction`."""
    vol, _spacing = _get_series_volume(series_id)
    vol = _maybe_interpolate_thin_stack(vol, min_slices=32)

    mip_axial = np.max(vol, axis=0)
    mip_sagittal = np.max(vol, axis=1)
    mip_coronal = np.max(vol, axis=2)

    views = {
        "axial": _png_data_url(_apply_windowing(mip_axial, float(window_width), float(window_level), invert=inverted)),
        "sagittal": _png_data_url(_apply_windowing(mip_sagittal, float(window_width), float(window_level), invert=inverted)),
        "coronal": _png_data_url(_apply_windowing(mip_coronal, float(window_width), float(window_level), invert=inverted)),
    }

    series_info = {"id": series_id, "description": "", "modality": ""}
    try:
        _require_orm()
        s = Series.objects.get(id=series_id)  # type: ignore[attr-defined]
        series_info = {
            "id": int(getattr(s, "id", series_id)),
            "description": str(getattr(s, "series_description", "")),
            "modality": str(getattr(s, "modality", "")),
        }
    except Exception:
        pass

    return {
        "mip_views": views,
        "volume_shape": [int(x) for x in vol.shape],
        "counts": {"axial": int(vol.shape[0]), "sagittal": int(vol.shape[2]), "coronal": int(vol.shape[1])},
        "series_info": series_info,
    }


@app.get("/v1/bone")
def bone_reconstruction(
    series_id: int,
    threshold: int = 300,
    window_width: float = 2000.0,
    window_level: float = 300.0,
    inverted: bool = False,
    mesh: bool = False,
    quality: str = "",
) -> dict[str, Any]:
    """Bone reconstruction compatible with Django `api_bone_reconstruction`."""
    vol, _spacing = _get_series_volume(series_id)
    vol = _maybe_interpolate_thin_stack(vol, min_slices=32)

    bone_mask = vol >= int(threshold)
    bone_vol = vol * bone_mask

    axial_idx = int(bone_vol.shape[0] // 2)
    sag_idx = int(bone_vol.shape[2] // 2)
    cor_idx = int(bone_vol.shape[1] // 2)

    bone_views = {
        "axial": _png_data_url(_apply_windowing(bone_vol[axial_idx], float(window_width), float(window_level), invert=inverted)),
        "sagittal": _png_data_url(_apply_windowing(bone_vol[:, :, sag_idx], float(window_width), float(window_level), invert=inverted)),
        "coronal": _png_data_url(_apply_windowing(bone_vol[:, cor_idx, :], float(window_width), float(window_level), invert=inverted)),
    }

    mesh_payload = None
    if mesh:
        try:
            from skimage import measure as _measure  # type: ignore

            if str(quality).lower() == "high":
                vol_for_mesh = (bone_vol > 0).astype(np.float32)
            else:
                ds_factor = max(1, int(np.ceil(max(1, bone_vol.shape[0]) / 128)))
                vol_for_mesh = (bone_vol[::ds_factor, ::2, ::2] > 0).astype(np.float32)
            verts, faces, _normals, _values = _measure.marching_cubes(vol_for_mesh, level=0.5)
            mesh_payload = {"vertices": verts.tolist(), "faces": faces.tolist()}
        except Exception:
            mesh_payload = None

    series_info = {"id": series_id, "description": "", "modality": ""}
    try:
        _require_orm()
        s = Series.objects.get(id=series_id)  # type: ignore[attr-defined]
        series_info = {
            "id": int(getattr(s, "id", series_id)),
            "description": str(getattr(s, "series_description", "")),
            "modality": str(getattr(s, "modality", "")),
        }
    except Exception:
        pass

    return {
        "bone_views": bone_views,
        "volume_shape": [int(x) for x in bone_vol.shape],
        "counts": {"axial": int(bone_vol.shape[0]), "sagittal": int(bone_vol.shape[2]), "coronal": int(bone_vol.shape[1])},
        "series_info": series_info,
        "mesh": mesh_payload,
    }

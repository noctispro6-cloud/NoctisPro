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
from typing import Any

import numpy as np
import pydicom
from fastapi import FastAPI, HTTPException
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


app = FastAPI(title="Noctis Pro DICOM Processor", version="1.0")


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

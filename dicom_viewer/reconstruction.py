import os
import shutil
import tempfile
import zipfile
import json
import logging

import numpy as np
import pydicom
from PIL import Image
from scipy import ndimage
from skimage import measure, morphology

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# BUG 3 FIX: _normalize_slice and _normalize_volume previously used per-slice
# min/max stretching which destroys relative HU relationships and produces
# wildly inconsistent window levels across slices. Now accepts explicit
# window_center / window_width so callers can apply a consistent CT window
# (e.g. soft-tissue W:400/L:40, bone W:1500/L:300). Falls back to full-range
# stretch only when no window is supplied (preview / non-diagnostic use).

def _apply_window(data: np.ndarray, window_center: float | None,
                  window_width: float | None) -> np.ndarray:
    """Map *data* to uint8 using a window/level transform.

    If *window_center* and *window_width* are both None the function falls
    back to a simple min/max stretch (acceptable for non-diagnostic previews).
    """
    if window_center is not None and window_width is not None:
        low  = window_center - window_width / 2.0
        high = window_center + window_width / 2.0
        clipped = np.clip(data, low, high)
        normalized = (clipped - low) / (window_width) * 255.0
    else:
        min_val = np.min(data)
        max_val = np.max(data)
        if max_val > min_val:
            normalized = (data - min_val) / (max_val - min_val) * 255.0
        else:
            return np.zeros_like(data, dtype=np.uint8)
    return normalized.astype(np.uint8)


def _normalize_slice(slice_data: np.ndarray,
                     window_center: float | None = None,
                     window_width: float | None = None) -> np.ndarray:
    """Normalize a 2-D array to uint8 [0, 255] using window/level.

    Pass *window_center* / *window_width* for consistent multi-slice display.
    Omit both for single-image previews where relative HU values don't matter.
    """
    return _apply_window(slice_data, window_center, window_width)


def _normalize_volume(volume: np.ndarray,
                      window_center: float | None = None,
                      window_width: float | None = None) -> np.ndarray:
    """Normalize a 3-D array to uint8 [0, 255] using window/level."""
    return _apply_window(volume, window_center, window_width)


def _create_vtk_mesh(vertices: np.ndarray, faces: np.ndarray,
                     normals: np.ndarray, title: str = "Mesh") -> str:
    """Serialize a triangle mesh to VTK ASCII PolyData format."""
    lines = [
        "# vtk DataFile Version 3.0",
        title,
        "ASCII",
        "DATASET POLYDATA",
        f"POINTS {len(vertices)} float",
    ]
    for v in vertices:
        lines.append(f"{v[0]} {v[1]} {v[2]}")

    lines.append(f"POLYGONS {len(faces)} {len(faces) * 4}")
    for f in faces:
        lines.append(f"3 {f[0]} {f[1]} {f[2]}")

    if normals is not None and len(normals) == len(vertices):
        lines.append(f"POINT_DATA {len(vertices)}")
        lines.append("NORMALS normals float")
        for n in normals:
            lines.append(f"{n[0]} {n[1]} {n[2]}")

    return "\n".join(lines)


def _safe_media_path(relative_name: str) -> str:
    """Return an absolute path inside MEDIA_ROOT, raising if it escapes."""
    media_root = os.path.realpath(settings.MEDIA_ROOT)
    full_path = os.path.realpath(os.path.join(media_root, relative_name))
    if not full_path.startswith(media_root + os.sep) and full_path != media_root:
        raise ValueError(
            f"Path traversal detected: {relative_name!r} resolves outside MEDIA_ROOT"
        )
    return full_path


# ---------------------------------------------------------------------------
# Base processor
# ---------------------------------------------------------------------------

class BaseProcessor:
    """Base class for all reconstruction processors."""

    MAX_SLICES = 2000

    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cleanup()

    def cleanup(self):
        if self.temp_dir and os.path.isdir(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def resample_isotropic(volume: np.ndarray, spacing: list) -> tuple:
        """Resample volume to isotropic voxel spacing to eliminate elongation.

        Returns (resampled_volume, isotropic_spacing).  When spacing is already
        near-isotropic (ratio < 1.5) the volume is returned unchanged.
        """
        min_sp = min(spacing)
        ratios = [s / min_sp for s in spacing]
        if max(ratios) <= 1.5:
            return volume, spacing
        resampled = ndimage.zoom(
            volume.astype(np.float32), ratios, order=1, prefilter=False
        )
        return resampled, [min_sp, min_sp, min_sp]

    @staticmethod
    def laplacian_smooth(vertices: np.ndarray, faces: np.ndarray,
                         iterations: int = 10, lam: float = 0.5) -> np.ndarray:
        """Vectorised Laplacian mesh smoothing.

        Averages each vertex with its face-adjacent neighbours, weighted by
        *lam*.  Iterations=10 / lam=0.5 gives a good balance between
        staircase reduction and shape preservation.
        """
        n = len(vertices)
        verts = vertices.copy()
        for _ in range(iterations):
            neighbor_sum = np.zeros_like(verts)
            neighbor_cnt = np.zeros(n, dtype=np.float32)
            for a, b in ((0, 1), (1, 2), (2, 0)):
                np.add.at(neighbor_sum, faces[:, a], verts[faces[:, b]])
                np.add.at(neighbor_sum, faces[:, b], verts[faces[:, a]])
                np.add.at(neighbor_cnt, faces[:, a], 1.0)
                np.add.at(neighbor_cnt, faces[:, b], 1.0)
            mask = neighbor_cnt > 0
            avg = np.where(mask[:, None], neighbor_sum / np.maximum(neighbor_cnt[:, None], 1), verts)
            verts = verts + lam * (avg - verts)
        return verts

    def load_series_volume(self, series):
        """Load all DICOM slices of *series* into a float32 NumPy volume.

        Returns
        -------
        volume  : np.ndarray, shape (slices, rows, cols), dtype float32
        spacing : list[float]  [slice_thickness, row_spacing, col_spacing]
        """
        images = list(series.images.all().order_by("instance_number"))
        if not images:
            raise ValueError("No images found in series")

        if len(images) > self.MAX_SLICES:
            raise ValueError(
                f"Series contains {len(images)} slices which exceeds the "
                f"safety limit of {self.MAX_SLICES}. Refusing to load."
            )

        first_path = _safe_media_path(images[0].file_path.name)
        first_ds = pydicom.dcmread(first_path)
        rows, cols = first_ds.Rows, first_ds.Columns

        volume = np.zeros((len(images), rows, cols), dtype=np.float32)
        spacing = [1.0, 1.0, 1.0]

        for i, image in enumerate(images):
            dicom_path = _safe_media_path(image.file_path.name)
            ds = pydicom.dcmread(dicom_path)
            pixel_array = ds.pixel_array.astype(np.float32)
            slope = float(getattr(ds, "RescaleSlope", 1.0))
            intercept = float(getattr(ds, "RescaleIntercept", 0.0))
            volume[i] = pixel_array * slope + intercept

            if i == 0:
                pixel_spacing = getattr(ds, "PixelSpacing", [1.0, 1.0])
                slice_thickness = float(getattr(ds, "SliceThickness", 1.0))
                spacing = [
                    slice_thickness,
                    float(pixel_spacing[0]),
                    float(pixel_spacing[1]),
                ]

        return volume, spacing

    def save_result(self, result_data, filename: str) -> str:
        result_path = os.path.join(self.temp_dir, filename)

        if isinstance(result_data, dict):
            zip_path = result_path + ".zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for name, data in result_data.items():
                    temp_file = os.path.join(self.temp_dir, name)
                    if isinstance(data, np.ndarray):
                        if data.ndim == 2:
                            Image.fromarray(data.astype(np.uint8)).save(temp_file)
                        else:
                            if not temp_file.endswith(".npy"):
                                temp_file_npy = temp_file + ".npy"
                            else:
                                temp_file_npy = temp_file
                            np.save(temp_file_npy, data)
                            temp_file = temp_file_npy
                    elif isinstance(data, (dict, list)):
                        with open(temp_file, "w") as fh:
                            json.dump(data, fh, indent=2)
                    else:
                        with open(temp_file, "w") as fh:
                            fh.write(str(data))
                    zipf.write(temp_file, arcname=name)
            return zip_path

        if isinstance(result_data, np.ndarray):
            if not result_path.endswith(".npy"):
                result_path += ".npy"
            np.save(result_path, result_data)
        elif isinstance(result_data, (dict, list)):
            with open(result_path, "w") as fh:
                json.dump(result_data, fh, indent=2)
        else:
            with open(result_path, "w") as fh:
                fh.write(str(result_data))
        return result_path


# ---------------------------------------------------------------------------
# MPR processor
# ---------------------------------------------------------------------------

class MPRProcessor(BaseProcessor):

    # Default output resolution for all MPR planes — ensures consistent quality
    # regardless of native DICOM matrix size.
    DEFAULT_OUTPUT_SIZE = (512, 512)

    def process_series(self, series, parameters: dict) -> str:
        try:
            volume, spacing = self.load_series_volume(series)
            slice_thickness = parameters.get("slice_thickness", 1.0)
            interpolation = parameters.get("interpolation", "cubic")
            output_size = parameters.get("output_size", self.DEFAULT_OUTPUT_SIZE)
            window_center = parameters.get("window_center", None)
            window_width  = parameters.get("window_width",  None)
            mpr_results = self.generate_mpr_views(
                volume, spacing, slice_thickness, interpolation, output_size,
                window_center, window_width,
            )
            return self.save_result(mpr_results, f"mpr_reconstruction_{series.id}")
        except Exception:
            logger.exception("MPR reconstruction failed")
            raise

    def generate_mpr_views(self, volume, spacing, slice_thickness,
                           interpolation, output_size,
                           window_center=None, window_width=None):
        depth, height, width = volume.shape
        results = {}
        step = max(1, int(slice_thickness))

        # Interpolation order: cubic (3) for high quality, linear (1) as fallback
        interp_order = 3 if interpolation in ("cubic", "linear", True) else 1

        # --- Axial ---
        # Axial slices are native in-plane; just normalize and resize.
        axial_slices = []
        for i in range(0, depth, step):
            sl = _normalize_slice(volume[i], window_center, window_width).astype(np.float32)
            if output_size is not None:
                sl = self._resize_slice(sl, output_size, order=interp_order)
            axial_slices.append(sl.astype(np.uint8))
        results["axial"] = np.array(axial_slices)

        # --- Sagittal ---
        # Sagittal slice: volume[:, :, i] → shape (depth, height).
        # Correct for Z anisotropy: zoom_z = slice_thickness / row_spacing.
        sagittal_slices = []
        zoom_z_sag = spacing[0] / max(spacing[1], 1e-6)
        for i in range(0, width, step):
            sl = volume[:, :, i].astype(np.float32)
            sl = ndimage.zoom(sl, [zoom_z_sag, 1.0], order=interp_order, prefilter=True)
            if output_size is not None:
                sl = self._resize_slice(sl, output_size, order=interp_order)
            sagittal_slices.append(_normalize_slice(sl, window_center, window_width))
        results["sagittal"] = np.array(sagittal_slices)

        # --- Coronal ---
        # Coronal slice: volume[:, i, :] → shape (depth, width).
        # Correct for Z anisotropy: zoom_z = slice_thickness / col_spacing.
        coronal_slices = []
        zoom_z_cor = spacing[0] / max(spacing[2], 1e-6)
        for i in range(0, height, step):
            sl = volume[:, i, :].astype(np.float32)
            sl = ndimage.zoom(sl, [zoom_z_cor, 1.0], order=interp_order, prefilter=True)
            if output_size is not None:
                sl = self._resize_slice(sl, output_size, order=interp_order)
            coronal_slices.append(_normalize_slice(sl, window_center, window_width))
        results["coronal"] = np.array(coronal_slices)

        results["metadata.json"] = {
            "original_spacing": spacing,
            "slice_thickness": slice_thickness,
            "interpolation": interpolation,
            "output_size": list(output_size) if output_size else None,
            "volume_shape": list(volume.shape),
            "axial_slices": len(axial_slices),
            "sagittal_slices": len(sagittal_slices),
            "coronal_slices": len(coronal_slices),
            "window_center": window_center,
            "window_width": window_width,
        }
        return results

    @staticmethod
    def _resize_slice(sl: np.ndarray, output_size, order: int = 3) -> np.ndarray:
        target_h, target_w = output_size
        zoom_factors = (target_h / sl.shape[0], target_w / sl.shape[1])
        return ndimage.zoom(sl, zoom_factors, order=order, prefilter=(order > 1))


# ---------------------------------------------------------------------------
# MIP processor
# ---------------------------------------------------------------------------

class MIPProcessor(BaseProcessor):

    def process_series(self, series, parameters: dict) -> str:
        try:
            volume, spacing = self.load_series_volume(series)
            projection_type = parameters.get("projection_type", "maximum")
            slab_thickness  = parameters.get("slab_thickness", None)
            angle_step      = parameters.get("angle_step", 10)
            window_center   = parameters.get("window_center", None)
            window_width    = parameters.get("window_width",  None)
            mip_results = self.generate_mip_views(
                volume, spacing, projection_type, slab_thickness, angle_step,
                window_center, window_width,
            )
            return self.save_result(mip_results, f"mip_reconstruction_{series.id}")
        except Exception:
            logger.exception("MIP reconstruction failed")
            raise

    def generate_mip_views(self, volume, spacing, projection_type,
                           slab_thickness, angle_step,
                           window_center=None, window_width=None):
        proj_func = {
            "maximum": np.max,
            "minimum": np.min,
            "mean":    np.mean,
        }.get(projection_type, np.max)

        results = {
            "axial_mip":    _normalize_slice(proj_func(volume, axis=0), window_center, window_width),
            "sagittal_mip": _normalize_slice(proj_func(volume, axis=2), window_center, window_width),
            "coronal_mip":  _normalize_slice(proj_func(volume, axis=1), window_center, window_width),
        }

        if angle_step and angle_step > 0:
            results.update(self._generate_rotating_mip(
                volume, angle_step, proj_func, window_center, window_width
            ))

        if slab_thickness:
            results.update(self._generate_slab_mip(
                volume, int(slab_thickness), proj_func, window_center, window_width
            ))

        results["metadata.json"] = {
            "projection_type": projection_type,
            "slab_thickness": slab_thickness,
            "angle_step": angle_step,
            "volume_shape": list(volume.shape),
            "spacing": spacing,
            "window_center": window_center,
            "window_width": window_width,
        }
        return results

    @staticmethod
    def _generate_rotating_mip(volume, angle_step: int, proj_func,
                                window_center=None, window_width=None):
        # BUG 4 FIX: original code projected on axis=2 (sagittal collapse →
        # shape depth×height) and called the result a "coronal MIP". The
        # coronal projection collapses axis=1 (→ shape depth×width). Using the
        # wrong axis produces a transposed view that looks correct only for
        # square FOVs, and labels the images incorrectly everywhere else.
        results = {}
        base_mip = proj_func(volume, axis=1)   # FIX: was axis=2 (sagittal)
        for angle in range(0, 360, angle_step):
            rotated = ndimage.rotate(base_mip, angle, reshape=False, order=1)
            results[f"rotating_mip_{angle:03d}"] = _normalize_slice(
                rotated, window_center, window_width
            )
        return results

    @staticmethod
    def _generate_slab_mip(volume, slab_thickness: int, proj_func,
                           window_center=None, window_width=None):
        results = {}
        depth = volume.shape[0]
        step = max(1, slab_thickness // 2)
        for i in range(0, depth - slab_thickness + 1, step):
            slab_mip = proj_func(volume[i : i + slab_thickness], axis=0)
            results[f"slab_mip_{i:03d}"] = _normalize_slice(
                slab_mip, window_center, window_width
            )
        return results


# ---------------------------------------------------------------------------
# Bone 3-D processor
# ---------------------------------------------------------------------------

class Bone3DProcessor(BaseProcessor):

    def process_series(self, series, parameters: dict) -> str:
        try:
            modality = (getattr(series, 'modality', None) or '').upper().strip()
            if modality and modality != 'CT':
                raise ValueError(
                    f"Bone 3D reconstruction requires CT data; series modality is '{modality}'"
                )
            volume, spacing = self.load_series_volume(series)
            # Default threshold 400 HU — captures cortical and dense spongy bone,
            # avoids soft tissue (< 100 HU) and fat (< -50 HU).
            threshold      = parameters.get("threshold", 400)
            smoothing      = parameters.get("smoothing", True)
            decimation     = parameters.get("decimation", 0.8)
            window_center  = parameters.get("window_center", 400)
            window_width   = parameters.get("window_width", 2000)
            bone_results = self.generate_bone_reconstruction(
                volume, spacing, threshold, smoothing, decimation,
                window_center, window_width,
            )
            return self.save_result(bone_results, f"bone_3d_reconstruction_{series.id}")
        except Exception:
            logger.exception("Bone 3D reconstruction failed")
            raise

    def generate_bone_reconstruction(self, volume, spacing, threshold,
                                     smoothing, decimation,
                                     window_center=400, window_width=2000):
        results = {}

        # ── Step 1: Resample to isotropic voxels to eliminate elongation ──────
        volume_iso, iso_spacing = self.resample_isotropic(volume, spacing)

        # ── Step 2: Pre-smooth the volume to reduce noise before segmentation ──
        # sigma proportional to the degree of anisotropy before resampling
        pre_sigma = max(0.5, spacing[0] / max(spacing[1], spacing[2], 1e-6) * 0.5)
        vol_smooth = ndimage.gaussian_filter(volume_iso.astype(np.float32),
                                             sigma=pre_sigma)

        # ── Step 3: Binary bone mask + morphological cleanup ─────────────────
        bone_mask = vol_smooth > threshold
        if smoothing:
            bone_mask = morphology.binary_closing(bone_mask, morphology.ball(2))
            bone_mask = morphology.binary_opening(bone_mask, morphology.ball(1))

        # ── Step 4: Build a SMOOTH scalar field for marching cubes ────────────
        # Gaussian-blur the binary mask so the 0→1 transition has a gradient
        # instead of an infinite step — this is what eliminates staircase
        # artifacts.  The isosurface at level=0.5 is at the original boundary.
        soft_field = ndimage.gaussian_filter(bone_mask.astype(np.float32),
                                             sigma=1.5)

        try:
            verts, faces, normals, _ = measure.marching_cubes(
                soft_field, level=0.5, spacing=iso_spacing,
                allow_degenerate=False
            )

            # ── Step 5: Laplacian mesh smoothing (removes residual facets) ───
            verts = self.laplacian_smooth(verts, faces, iterations=10, lam=0.5)

            if decimation < 1.0:
                verts, faces = self._decimate_mesh(verts, faces, decimation)
            normals = self._compute_vertex_normals(verts, faces)

            results["vertices.npy"] = verts
            results["faces.npy"]    = faces
            results["normals.npy"]  = normals
            results["bone_mesh.vtk"] = _create_vtk_mesh(
                verts, faces, normals, title="Bone 3D Reconstruction"
            )
            results.update(self._generate_preview_images(
                bone_mask, volume_iso, iso_spacing, window_center, window_width
            ))

        except Exception:
            logger.exception("Marching cubes failed – falling back to volume rendering")
            results.update(self._generate_volume_rendering(bone_mask))

        results["metadata.json"] = {
            "threshold":      threshold,
            "smoothing":      smoothing,
            "decimation":     decimation,
            "window_center":  window_center,
            "window_width":   window_width,
            "volume_shape":   list(volume.shape),
            "iso_shape":      list(volume_iso.shape),
            "spacing":        spacing,
            "iso_spacing":    iso_spacing,
            "num_vertices":   int(len(results.get("vertices.npy", []))),
            "num_faces":      int(len(results.get("faces.npy",    []))),
        }
        return results

    @staticmethod
    def _decimate_mesh(vertices: np.ndarray, faces: np.ndarray,
                       reduction_factor: float):
        """Deterministic face decimation with vectorised index remapping.

        BUG 5 FIX: original used np.random.choice which produces a different
        mesh every run from the same DICOM series, breaking caching, diff-based
        QA, and reproducibility. Replaced with a stride-based selection that
        is deterministic and produces a spatially uniform sample (every N-th
        face rather than a random subset).
        """
        num_keep = max(1, int(len(faces) * reduction_factor))
        # Deterministic: take every k-th face so the sample is spatially uniform
        stride = max(1, len(faces) // num_keep)
        keep_indices = np.arange(0, len(faces), stride)[:num_keep]
        decimated_faces = faces[keep_indices].copy()

        unique_verts = np.unique(decimated_faces)
        inv_map = np.zeros(unique_verts.max() + 1, dtype=np.int64)
        inv_map[unique_verts] = np.arange(len(unique_verts), dtype=np.int64)

        decimated_faces    = inv_map[decimated_faces]
        decimated_vertices = vertices[unique_verts]
        return decimated_vertices, decimated_faces

    @staticmethod
    def _compute_vertex_normals(vertices: np.ndarray,
                                faces: np.ndarray) -> np.ndarray:
        """Compute area-weighted vertex normals for a triangle mesh."""
        normals = np.zeros_like(vertices)
        v0 = vertices[faces[:, 0]]
        v1 = vertices[faces[:, 1]]
        v2 = vertices[faces[:, 2]]
        face_normals = np.cross(v1 - v0, v2 - v0)   # area-weighted
        for i in range(3):
            np.add.at(normals, faces[:, i], face_normals)
        norms = np.linalg.norm(normals, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return normals / norms

    @staticmethod
    def _generate_preview_images(bone_mask: np.ndarray,
                                  volume: np.ndarray = None,
                                  spacing: list = None,
                                  window_center: float = 400,
                                  window_width: float = 2000) -> dict:
        """Generate max-intensity projection previews with correct aspect ratio.

        When *spacing* is provided the sagittal and coronal projections are
        zoomed so one screen pixel corresponds to one physical mm in both axes,
        producing anatomically correct proportions.
        """
        if volume is not None:
            windowed = _apply_window(volume, window_center, window_width).astype(np.float32)
            masked = windowed * bone_mask
        else:
            masked = (bone_mask.astype(np.float32) * 255)

        axial    = np.max(masked, axis=0).astype(np.uint8)   # (height, width)
        sagittal = np.max(masked, axis=2).astype(np.uint8)   # (depth, height)
        coronal  = np.max(masked, axis=1).astype(np.uint8)   # (depth, width)

        # Apply spacing-aware aspect ratio correction to non-axial projections
        if spacing and len(spacing) == 3:
            dz, dy, dx = [max(s, 1e-6) for s in spacing]
            # Sagittal (depth×height): Z stretch = dz/dy (if isotropic, =1)
            zoom_sag_z = dz / dy
            if abs(zoom_sag_z - 1.0) > 0.05:
                sagittal = ndimage.zoom(
                    sagittal.astype(np.float32), [zoom_sag_z, 1.0], order=3
                ).astype(np.uint8)
            # Coronal (depth×width): Z stretch = dz/dx
            zoom_cor_z = dz / dx
            if abs(zoom_cor_z - 1.0) > 0.05:
                coronal = ndimage.zoom(
                    coronal.astype(np.float32), [zoom_cor_z, 1.0], order=3
                ).astype(np.uint8)

        return {
            "bone_axial_preview":    axial,
            "bone_sagittal_preview": sagittal,
            "bone_coronal_preview":  coronal,
        }

    @staticmethod
    def _generate_volume_rendering(volume_mask: np.ndarray) -> dict:
        renderings = {}
        for angle in (0, 45, 90, 135):
            rotated = ndimage.rotate(
                volume_mask.astype(np.float32), angle, axes=(0, 2), reshape=False
            )
            renderings[f"volume_render_{angle}"] = (
                np.max(rotated, axis=0) * 255
            ).astype(np.uint8)
        return renderings


# ---------------------------------------------------------------------------
# MRI 3-D processor
# ---------------------------------------------------------------------------

class MRI3DProcessor(BaseProcessor):

    def process_series(self, series, parameters: dict) -> str:
        try:
            modality = (getattr(series, 'modality', None) or '').upper().strip()
            if modality and modality not in ('MR', 'MRI'):
                raise ValueError(
                    f"MRI 3D reconstruction requires MR data; series modality is '{modality}'"
                )
            volume, spacing = self.load_series_volume(series)
            segmentation_method = parameters.get("segmentation_method", "threshold")
            tissue_type         = parameters.get("tissue_type", "brain")
            smoothing           = parameters.get("smoothing", True)
            window_center       = parameters.get("window_center", None)
            window_width        = parameters.get("window_width",  None)
            mri_results = self.generate_mri_reconstruction(
                volume, spacing, segmentation_method, tissue_type, smoothing,
                window_center, window_width,
            )
            return self.save_result(mri_results, f"mri_3d_reconstruction_{series.id}")
        except Exception:
            logger.exception("MRI 3D reconstruction failed")
            raise

    def generate_mri_reconstruction(self, volume, spacing, segmentation_method,
                                    tissue_type, smoothing,
                                    window_center=None, window_width=None):
        results = {}

        # ── Step 1: Resample to isotropic voxels ─────────────────────────────
        volume_iso, iso_spacing = self.resample_isotropic(volume, spacing)

        # ── Step 2: Segment tissue from isotropic volume ─────────────────────
        segment_fn = {
            "brain":       self._segment_brain_tissue,
            "soft_tissue": self._segment_soft_tissue,
        }.get(tissue_type, self._segment_generic_tissue)
        tissue_mask = segment_fn(volume_iso, segmentation_method)

        # ── Step 3: Build smooth scalar field for marching cubes ──────────────
        # Gaussian on the binary mask eliminates staircase artifacts at boundary
        sigma = 1.5 if smoothing else 0.5
        soft_field = ndimage.gaussian_filter(tissue_mask.astype(np.float32),
                                             sigma=sigma)

        try:
            verts, faces, normals, _ = measure.marching_cubes(
                soft_field, level=0.5, spacing=iso_spacing,
                allow_degenerate=False
            )

            # ── Step 4: Laplacian smoothing ───────────────────────────────────
            verts = self.laplacian_smooth(verts, faces, iterations=8, lam=0.5)
            normals = Bone3DProcessor._compute_vertex_normals(verts, faces)

            results["vertices.npy"] = verts
            results["faces.npy"]    = faces
            results["normals.npy"]  = normals
            results["mri_mesh.vtk"] = _create_vtk_mesh(
                verts, faces, normals, title="MRI 3D Reconstruction"
            )
        except Exception:
            logger.exception("MRI mesh generation failed")

        results.update(self._generate_contrast_views(
            volume_iso, tissue_mask, window_center, window_width
        ))
        results.update(self._generate_preview_images(tissue_mask, volume_iso,
                                                      window_center, window_width))

        results["metadata.json"] = {
            "segmentation_method": segmentation_method,
            "tissue_type":   tissue_type,
            "smoothing":     smoothing,
            "volume_shape":  list(volume.shape),
            "iso_shape":     list(volume_iso.shape),
            "spacing":       spacing,
            "iso_spacing":   iso_spacing,
            "window_center": window_center,
            "window_width":  window_width,
            "num_vertices":  int(len(results.get("vertices.npy", []))),
            "num_faces":     int(len(results.get("faces.npy",    []))),
        }
        return results

    # ------------------------------------------------------------------
    # Segmentation helpers (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def _segment_brain_tissue(volume: np.ndarray, method: str) -> np.ndarray:
        if method == "threshold":
            threshold = np.mean(volume) + 0.5 * np.std(volume)
            return volume > threshold
        if method == "otsu":
            from skimage.filters import threshold_otsu
            return volume > threshold_otsu(volume)
        if method == "watershed":
            from skimage.feature import peak_local_max
            from skimage.segmentation import watershed
            local_maxima = peak_local_max(
                volume,
                min_distance=10,
                threshold_abs=0.3 * np.max(volume),
            )
            markers = np.zeros(volume.shape, dtype=np.int32)
            for idx, coords in enumerate(local_maxima):
                markers[tuple(coords)] = idx + 1
            segmented = watershed(
                -volume, markers, mask=volume > 0.1 * np.max(volume)
            )
            return segmented > 0
        return volume > 0.3 * np.max(volume)

    @staticmethod
    def _segment_soft_tissue(volume: np.ndarray, method: str) -> np.ndarray:
        low  = 0.2 * np.max(volume)
        high = 0.8 * np.max(volume)
        return (volume > low) & (volume < high)

    @staticmethod
    def _segment_generic_tissue(volume: np.ndarray, method: str) -> np.ndarray:
        return volume > 0.3 * np.max(volume)

    # ------------------------------------------------------------------
    # Visualisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_contrast_views(volume: np.ndarray, tissue_mask: np.ndarray,
                                  window_center=None, window_width=None) -> dict:
        results = {}

        t1 = volume.copy()
        t1[tissue_mask] *= 1.2
        results["t1_simulation"]   = _normalize_volume(t1, window_center, window_width)

        t2 = np.max(volume) - volume
        t2[tissue_mask] *= 0.8
        results["t2_simulation"]   = _normalize_volume(t2, window_center, window_width)

        flair = volume.copy()
        flair[volume > 0.8 * np.max(volume)] *= 0.3
        results["flair_simulation"] = _normalize_volume(flair, window_center, window_width)

        return results

    @staticmethod
    def _generate_preview_images(tissue_mask: np.ndarray,
                                  original_volume: np.ndarray,
                                  window_center=None,
                                  window_width=None) -> dict:
        depth, height, width = tissue_mask.shape
        mid_axial    = depth  // 2
        mid_sagittal = width  // 2
        mid_coronal  = height // 2

        def overlay(bg, mask):
            bg_norm = _normalize_slice(bg, window_center, window_width)
            rgb = np.stack([bg_norm, bg_norm, bg_norm], axis=-1)
            tint = (mask > 0).astype(np.float32) * 100
            rgb[:, :, 0] = np.clip(
                rgb[:, :, 0].astype(np.float32) + tint, 0, 255
            ).astype(np.uint8)
            return rgb.astype(np.uint8)

        return {
            "axial_overlay":    overlay(original_volume[mid_axial],
                                        tissue_mask[mid_axial]),
            "sagittal_overlay": overlay(original_volume[:, :, mid_sagittal],
                                        tissue_mask[:, :, mid_sagittal]),
            "coronal_overlay":  overlay(original_volume[:, mid_coronal, :],
                                        tissue_mask[:, mid_coronal, :]),
            "tissue_axial_projection":    (np.max(tissue_mask, axis=0) * 255).astype(np.uint8),
            "tissue_sagittal_projection": (np.max(tissue_mask, axis=2) * 255).astype(np.uint8),
            "tissue_coronal_projection":  (np.max(tissue_mask, axis=1) * 255).astype(np.uint8),
        }
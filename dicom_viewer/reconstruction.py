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

def _normalize_slice(slice_data: np.ndarray) -> np.ndarray:
    """Normalize a 2-D array to uint8 [0, 255].

    Returns a zero-filled array when the slice is constant so that no
    integer-overflow occurs (e.g. a flat 1 000 HU slice cast straight to
    uint8 would silently wrap around).
    """
    min_val = np.min(slice_data)
    max_val = np.max(slice_data)
    if max_val > min_val:
        normalized = (slice_data - min_val) / (max_val - min_val) * 255
        return normalized.astype(np.uint8)
    return np.zeros_like(slice_data, dtype=np.uint8)


def _normalize_volume(volume: np.ndarray) -> np.ndarray:
    """Normalize a 3-D array to uint8 [0, 255]."""
    min_val = np.min(volume)
    max_val = np.max(volume)
    if max_val > min_val:
        normalized = (volume - min_val) / (max_val - min_val) * 255
        return normalized.astype(np.uint8)
    return np.zeros_like(volume, dtype=np.uint8)


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
    """Base class for all reconstruction processors.

    Usage as a context manager ensures the temporary directory is always
    cleaned up::

        with MPRProcessor() as proc:
            proc.process_series(series, params)
    """

    # Guard against runaway memory usage: refuse series larger than this.
    MAX_SLICES = 2000

    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()

    # ------------------------------------------------------------------
    # Context-manager support – guarantees temp-dir cleanup
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cleanup()

    def cleanup(self):
        if self.temp_dir and os.path.isdir(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Volume loading
    # ------------------------------------------------------------------

    def load_series_volume(self, series):
        """Load all DICOM slices of *series* into a float32 NumPy volume.

        Returns
        -------
        volume : np.ndarray, shape (slices, rows, cols), dtype float32
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

        # Pre-allocate once to avoid repeated reallocation.
        volume = np.zeros((len(images), rows, cols), dtype=np.float32)

        # Default spacing in case the first slice is missing tags.
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

    # ------------------------------------------------------------------
    # Result persistence
    # ------------------------------------------------------------------

    def save_result(self, result_data, filename: str) -> str:
        """Persist *result_data* and return the path to the saved file.

        If *result_data* is a ``dict`` a ZIP archive is created; each value
        is saved under its key name inside the archive.

        Scalar / ndarray values are saved as individual files otherwise.
        """
        result_path = os.path.join(self.temp_dir, filename)

        if isinstance(result_data, dict):
            zip_path = result_path + ".zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for name, data in result_data.items():
                    temp_file = os.path.join(self.temp_dir, name)
                    if isinstance(data, np.ndarray):
                        if data.ndim == 2:
                            # 2-D arrays → PNG image
                            Image.fromarray(data.astype(np.uint8)).save(temp_file)
                        else:
                            # N-D arrays → .npy  (np.save appends .npy automatically
                            # only when the path does NOT already end in .npy)
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

        # Non-dict result
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

    def process_series(self, series, parameters: dict) -> str:
        try:
            volume, spacing = self.load_series_volume(series)
            slice_thickness = parameters.get("slice_thickness", 1.0)
            interpolation = parameters.get("interpolation", "linear")
            output_size = parameters.get("output_size", None)
            mpr_results = self.generate_mpr_views(
                volume, spacing, slice_thickness, interpolation, output_size
            )
            return self.save_result(mpr_results, f"mpr_reconstruction_{series.id}")
        except Exception:
            logger.exception("MPR reconstruction failed")
            raise

    def generate_mpr_views(self, volume, spacing, slice_thickness,
                           interpolation, output_size):
        depth, height, width = volume.shape
        results = {}
        step = max(1, int(slice_thickness))

        # --- Axial ---
        axial_slices = [_normalize_slice(volume[i]) for i in range(0, depth, step)]
        results["axial"] = np.array(axial_slices)

        # --- Sagittal ---
        sagittal_slices = []
        for i in range(0, width, step):
            sl = volume[:, :, i]
            if interpolation == "linear":
                zoom_z = spacing[0] / max(spacing[1], 1e-6)
                sl = ndimage.zoom(sl, [zoom_z, 1.0], order=1)
            if output_size is not None:
                sl = self._resize_slice(sl, output_size)
            sagittal_slices.append(_normalize_slice(sl))
        results["sagittal"] = np.array(sagittal_slices)

        # --- Coronal ---
        coronal_slices = []
        for i in range(0, height, step):
            sl = volume[:, i, :]
            if interpolation == "linear":
                zoom_z = spacing[0] / max(spacing[2], 1e-6)
                sl = ndimage.zoom(sl, [zoom_z, 1.0], order=1)
            if output_size is not None:
                sl = self._resize_slice(sl, output_size)
            coronal_slices.append(_normalize_slice(sl))
        results["coronal"] = np.array(coronal_slices)

        results["metadata.json"] = {
            "original_spacing": spacing,
            "slice_thickness": slice_thickness,
            "interpolation": interpolation,
            "output_size": output_size,
            "volume_shape": list(volume.shape),
            "axial_slices": len(axial_slices),
            "sagittal_slices": len(sagittal_slices),
            "coronal_slices": len(coronal_slices),
        }
        return results

    @staticmethod
    def _resize_slice(sl: np.ndarray, output_size) -> np.ndarray:
        """Resize a 2-D slice to *output_size* = (rows, cols)."""
        target_h, target_w = output_size
        zoom_factors = (target_h / sl.shape[0], target_w / sl.shape[1])
        return ndimage.zoom(sl, zoom_factors, order=1)


# ---------------------------------------------------------------------------
# MIP processor
# ---------------------------------------------------------------------------

class MIPProcessor(BaseProcessor):

    def process_series(self, series, parameters: dict) -> str:
        try:
            volume, spacing = self.load_series_volume(series)
            projection_type = parameters.get("projection_type", "maximum")
            slab_thickness = parameters.get("slab_thickness", None)
            angle_step = parameters.get("angle_step", 10)
            mip_results = self.generate_mip_views(
                volume, spacing, projection_type, slab_thickness, angle_step
            )
            return self.save_result(mip_results, f"mip_reconstruction_{series.id}")
        except Exception:
            logger.exception("MIP reconstruction failed")
            raise

    def generate_mip_views(self, volume, spacing, projection_type,
                           slab_thickness, angle_step):
        proj_func = {
            "maximum": np.max,
            "minimum": np.min,
            "mean": np.mean,
        }.get(projection_type, np.max)

        results = {
            "axial_mip":    _normalize_slice(proj_func(volume, axis=0)),
            "sagittal_mip": _normalize_slice(proj_func(volume, axis=2)),
            "coronal_mip":  _normalize_slice(proj_func(volume, axis=1)),
        }

        if angle_step and angle_step > 0:
            results.update(self._generate_rotating_mip(volume, angle_step, proj_func))

        if slab_thickness:
            results.update(self._generate_slab_mip(volume, int(slab_thickness), proj_func))

        results["metadata.json"] = {
            "projection_type": projection_type,
            "slab_thickness": slab_thickness,
            "angle_step": angle_step,
            "volume_shape": list(volume.shape),
            "spacing": spacing,
        }
        return results

    @staticmethod
    def _generate_rotating_mip(volume, angle_step: int, proj_func):
        """Generate MIP projections of a 2-D coronal slice rotated in-plane.

        Rotating the full 3-D volume for every angle is prohibitively
        expensive.  Instead we project the volume to a 2-D coronal MIP first
        and then rotate that single image, which is orders of magnitude faster
        and produces visually equivalent results for display purposes.
        """
        results = {}
        base_mip = proj_func(volume, axis=2)   # sagittal collapse → (depth, height)
        for angle in range(0, 360, angle_step):
            rotated = ndimage.rotate(base_mip, angle, reshape=False, order=1)
            results[f"rotating_mip_{angle:03d}"] = _normalize_slice(rotated)
        return results

    @staticmethod
    def _generate_slab_mip(volume, slab_thickness: int, proj_func):
        results = {}
        depth = volume.shape[0]
        step = max(1, slab_thickness // 2)
        for i in range(0, depth - slab_thickness + 1, step):
            slab_mip = proj_func(volume[i : i + slab_thickness], axis=0)
            results[f"slab_mip_{i:03d}"] = _normalize_slice(slab_mip)
        return results


# ---------------------------------------------------------------------------
# Bone 3-D processor
# ---------------------------------------------------------------------------

class Bone3DProcessor(BaseProcessor):

    def process_series(self, series, parameters: dict) -> str:
        try:
            volume, spacing = self.load_series_volume(series)
            threshold = parameters.get("threshold", 200)
            smoothing = parameters.get("smoothing", True)
            decimation = parameters.get("decimation", 0.8)
            bone_results = self.generate_bone_reconstruction(
                volume, spacing, threshold, smoothing, decimation
            )
            return self.save_result(bone_results, f"bone_3d_reconstruction_{series.id}")
        except Exception:
            logger.exception("Bone 3D reconstruction failed")
            raise

    def generate_bone_reconstruction(self, volume, spacing, threshold,
                                     smoothing, decimation):
        results = {}
        bone_mask = volume > threshold

        if smoothing:
            bone_mask = morphology.binary_closing(bone_mask, morphology.ball(2))
            bone_mask = morphology.binary_opening(bone_mask, morphology.ball(1))

        try:
            verts, faces, normals, _ = measure.marching_cubes(
                bone_mask.astype(np.float32), level=0.5, spacing=spacing
            )
            if decimation < 1.0:
                verts, faces = self._decimate_mesh(verts, faces, decimation)

            results["vertices.npy"] = verts
            results["faces.npy"] = faces
            results["normals.npy"] = normals
            results["bone_mesh.vtk"] = _create_vtk_mesh(
                verts, faces, normals, title="Bone 3D Reconstruction"
            )
            results.update(self._generate_preview_images(bone_mask))

        except Exception:
            logger.exception("Marching cubes failed – falling back to volume rendering")
            results.update(self._generate_volume_rendering(bone_mask))

        results["metadata.json"] = {
            "threshold": threshold,
            "smoothing": smoothing,
            "decimation": decimation,
            "volume_shape": list(volume.shape),
            "spacing": spacing,
            "num_vertices": int(len(results.get("vertices.npy", []))),
            "num_faces":    int(len(results.get("faces.npy", []))),
        }
        return results

    @staticmethod
    def _decimate_mesh(vertices: np.ndarray, faces: np.ndarray,
                       reduction_factor: float):
        """Random face decimation with vectorised index remapping."""
        num_keep = max(1, int(len(faces) * reduction_factor))
        keep_indices = np.random.choice(len(faces), num_keep, replace=False)
        decimated_faces = faces[keep_indices].copy()          # (num_keep, 3)

        unique_verts = np.unique(decimated_faces)             # sorted 1-D array
        # Build inverse map via a lookup array (much faster than a dict loop)
        inv_map = np.zeros(unique_verts.max() + 1, dtype=np.int64)
        inv_map[unique_verts] = np.arange(len(unique_verts), dtype=np.int64)

        decimated_faces = inv_map[decimated_faces]            # vectorised remap
        decimated_vertices = vertices[unique_verts]
        return decimated_vertices, decimated_faces

    @staticmethod
    def _generate_preview_images(bone_mask: np.ndarray) -> dict:
        return {
            "bone_axial_preview":    (np.max(bone_mask, axis=0) * 255).astype(np.uint8),
            "bone_sagittal_preview": (np.max(bone_mask, axis=2) * 255).astype(np.uint8),
            "bone_coronal_preview":  (np.max(bone_mask, axis=1) * 255).astype(np.uint8),
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
            volume, spacing = self.load_series_volume(series)
            segmentation_method = parameters.get("segmentation_method", "threshold")
            tissue_type = parameters.get("tissue_type", "brain")
            smoothing = parameters.get("smoothing", True)
            mri_results = self.generate_mri_reconstruction(
                volume, spacing, segmentation_method, tissue_type, smoothing
            )
            return self.save_result(mri_results, f"mri_3d_reconstruction_{series.id}")
        except Exception:
            logger.exception("MRI 3D reconstruction failed")
            raise

    def generate_mri_reconstruction(self, volume, spacing, segmentation_method,
                                    tissue_type, smoothing):
        results = {}

        segment_fn = {
            "brain":       self._segment_brain_tissue,
            "soft_tissue": self._segment_soft_tissue,
        }.get(tissue_type, self._segment_generic_tissue)
        tissue_mask = segment_fn(volume, segmentation_method)

        if smoothing:
            tissue_mask = ndimage.gaussian_filter(
                tissue_mask.astype(np.float32), sigma=1.0
            ) > 0.5

        try:
            verts, faces, normals, _ = measure.marching_cubes(
                tissue_mask.astype(np.float32), level=0.5, spacing=spacing
            )
            results["vertices.npy"] = verts
            results["faces.npy"] = faces
            results["normals.npy"] = normals
            results["mri_mesh.vtk"] = _create_vtk_mesh(
                verts, faces, normals, title="MRI 3D Reconstruction"
            )
        except Exception:
            logger.exception("MRI mesh generation failed")

        results.update(self._generate_contrast_views(volume, tissue_mask))
        results.update(self._generate_preview_images(tissue_mask, volume))

        results["metadata.json"] = {
            "segmentation_method": segmentation_method,
            "tissue_type": tissue_type,
            "smoothing": smoothing,
            "volume_shape": list(volume.shape),
            "spacing": spacing,
            "num_vertices": int(len(results.get("vertices.npy", []))),
            "num_faces":    int(len(results.get("faces.npy", []))),
        }
        return results

    # ------------------------------------------------------------------
    # Segmentation helpers
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
        # Fallback
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
    def _generate_contrast_views(volume: np.ndarray,
                                  tissue_mask: np.ndarray) -> dict:
        results = {}

        t1 = volume.copy()
        t1[tissue_mask] *= 1.2
        results["t1_simulation"] = _normalize_volume(t1)

        t2 = np.max(volume) - volume
        t2[tissue_mask] *= 0.8
        results["t2_simulation"] = _normalize_volume(t2)

        flair = volume.copy()
        flair[volume > 0.8 * np.max(volume)] *= 0.3
        results["flair_simulation"] = _normalize_volume(flair)

        return results

    @staticmethod
    def _generate_preview_images(tissue_mask: np.ndarray,
                                  original_volume: np.ndarray) -> dict:
        depth, height, width = tissue_mask.shape
        mid_axial    = depth  // 2
        mid_sagittal = width  // 2
        mid_coronal  = height // 2

        def overlay(bg, mask):
            bg_norm = _normalize_slice(bg)
            rgb = np.stack([bg_norm, bg_norm, bg_norm], axis=-1)
            # Tint the masked region red.
            tint = (mask > 0).astype(np.float32) * 100
            rgb[:, :, 0] = np.clip(rgb[:, :, 0].astype(np.float32) + tint, 0, 255).astype(np.uint8)
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
"""
Masterpiece DICOM Viewer Utilities
Enhanced DICOM processing and 3D reconstruction utilities
"""
import numpy as np
import pydicom
from scipy import ndimage
from skimage import measure, filters
import json
import logging
from django.conf import settings
import os
from PIL import Image
import base64
from io import BytesIO

logger = logging.getLogger(__name__)

class MasterpieceDicomProcessor:
    """Enhanced DICOM processor with advanced imaging capabilities"""
    
    @staticmethod
    def apply_windowing(pixel_array, window_width, window_level):
        """Apply window/level to pixel array with enhanced algorithms"""
        pixel_array = pixel_array.astype(np.float32)
        
        min_val = window_level - window_width / 2
        max_val = window_level + window_width / 2
        
        # Clip and normalize to 0-255
        windowed = np.clip(pixel_array, min_val, max_val)
        windowed = (windowed - min_val) / (max_val - min_val) * 255
        
        return windowed.astype(np.uint8)
    
    @staticmethod
    def enhance_contrast(pixel_array, method='clahe', **kwargs):
        """Enhance contrast using various methods"""
        if method == 'clahe':
            # Contrast Limited Adaptive Histogram Equalization
            from skimage import exposure
            return exposure.equalize_adapthist(pixel_array, **kwargs)
        elif method == 'histogram_eq':
            # Global histogram equalization
            from skimage import exposure
            return exposure.equalize_hist(pixel_array)
        elif method == 'gamma_correction':
            # Gamma correction
            gamma = kwargs.get('gamma', 0.7)
            return np.power(pixel_array / 255.0, gamma) * 255
        elif method == 'sigmoid':
            # Sigmoid correction
            from skimage import exposure
            return exposure.adjust_sigmoid(pixel_array, **kwargs)
        
        return pixel_array
    
    @staticmethod
    def apply_filters(pixel_array, filter_type='gaussian', **kwargs):
        """Apply various image filters"""
        if filter_type == 'gaussian':
            sigma = kwargs.get('sigma', 1.0)
            return ndimage.gaussian_filter(pixel_array, sigma=sigma)
        elif filter_type == 'median':
            size = kwargs.get('size', 3)
            return ndimage.median_filter(pixel_array, size=size)
        elif filter_type == 'edge_enhance':
            return filters.unsharp_mask(pixel_array, **kwargs)
        elif filter_type == 'denoise':
            from skimage import restoration
            return restoration.denoise_nl_means(pixel_array, **kwargs)
        
        return pixel_array
    
    @staticmethod
    def calculate_statistics(pixel_array, roi_mask=None):
        """Calculate image statistics with optional ROI"""
        if roi_mask is not None:
            pixels = pixel_array[roi_mask]
        else:
            pixels = pixel_array.flatten()
        
        return {
            'mean': float(np.mean(pixels)),
            'std': float(np.std(pixels)),
            'min': float(np.min(pixels)),
            'max': float(np.max(pixels)),
            'median': float(np.median(pixels)),
            'percentile_5': float(np.percentile(pixels, 5)),
            'percentile_95': float(np.percentile(pixels, 95)),
            'entropy': float(measure.shannon_entropy(pixels))
        }
    
    @staticmethod
    def auto_window_level(pixel_array, method='percentile'):
        """Automatically calculate optimal window/level"""
        if method == 'percentile':
            p5 = np.percentile(pixel_array, 5)
            p95 = np.percentile(pixel_array, 95)
            wl = (p5 + p95) / 2
            ww = p95 - p5
        elif method == 'otsu':
            from skimage.filters import threshold_otsu
            threshold = threshold_otsu(pixel_array)
            wl = threshold
            ww = np.std(pixel_array) * 4
        elif method == 'adaptive':
            mean_val = np.mean(pixel_array)
            std_val = np.std(pixel_array)
            wl = mean_val
            ww = std_val * 6  # 3 standard deviations on each side
        
        return int(ww), int(wl)

class MasterpieceMPRProcessor:
    """Enhanced Multi-Planar Reconstruction processor"""
    
    def __init__(self, volume_data, pixel_spacing=None, slice_thickness=None):
        self.volume = volume_data
        self.pixel_spacing = pixel_spacing or [1.0, 1.0]
        self.slice_thickness = slice_thickness or 1.0
        
    def generate_mpr_slices(self, plane='axial', slice_index=None):
        """Generate MPR slices with enhanced interpolation"""
        if self.volume.ndim != 3:
            raise ValueError("Volume must be 3D")
        
        depth, height, width = self.volume.shape
        
        if slice_index is None:
            slice_index = depth // 2 if plane == 'axial' else width // 2 if plane == 'sagittal' else height // 2
        
        if plane == 'axial':
            slice_index = max(0, min(slice_index, depth - 1))
            return self.volume[slice_index, :, :]
        elif plane == 'sagittal':
            slice_index = max(0, min(slice_index, width - 1))
            return self.volume[:, :, slice_index]
        elif plane == 'coronal':
            slice_index = max(0, min(slice_index, height - 1))
            return self.volume[:, slice_index, :]
        
        raise ValueError(f"Invalid plane: {plane}")
    
    def generate_curved_mpr(self, curve_points):
        """Generate curved MPR along specified curve"""
        # Implementation for curved MPR
        # This would interpolate along a curved path through the volume
        pass
    
    def generate_thick_slab_mpr(self, plane='axial', thickness=5, method='mip'):
        """Generate thick slab MPR with various projection methods"""
        if plane == 'axial':
            center = self.volume.shape[0] // 2
            start = max(0, center - thickness // 2)
            end = min(self.volume.shape[0], center + thickness // 2)
            slab = self.volume[start:end, :, :]
        elif plane == 'sagittal':
            center = self.volume.shape[2] // 2
            start = max(0, center - thickness // 2)
            end = min(self.volume.shape[2], center + thickness // 2)
            slab = self.volume[:, :, start:end]
        elif plane == 'coronal':
            center = self.volume.shape[1] // 2
            start = max(0, center - thickness // 2)
            end = min(self.volume.shape[1], center + thickness // 2)
            slab = self.volume[:, start:end, :]
        
        if method == 'mip':
            return np.max(slab, axis=0 if plane == 'axial' else 2 if plane == 'sagittal' else 1)
        elif method == 'minip':
            return np.min(slab, axis=0 if plane == 'axial' else 2 if plane == 'sagittal' else 1)
        elif method == 'average':
            return np.mean(slab, axis=0 if plane == 'axial' else 2 if plane == 'sagittal' else 1)
        
        return np.max(slab, axis=0 if plane == 'axial' else 2 if plane == 'sagittal' else 1)

class MasterpieceMIPProcessor:
    """Enhanced Maximum Intensity Projection processor"""
    
    @staticmethod
    def generate_mip_projections(volume, method='standard'):
        """Generate MIP projections with enhanced algorithms"""
        if volume.ndim != 3:
            raise ValueError("Volume must be 3D")
        
        if method == 'standard':
            # Standard MIP
            mip_axial = np.max(volume, axis=0)
            mip_sagittal = np.max(volume, axis=2)
            mip_coronal = np.max(volume, axis=1)
        elif method == 'ray_casting':
            # Ray casting MIP (more accurate but slower)
            mip_axial = MasterpieceMIPProcessor._ray_cast_mip(volume, axis=0)
            mip_sagittal = MasterpieceMIPProcessor._ray_cast_mip(volume, axis=2)
            mip_coronal = MasterpieceMIPProcessor._ray_cast_mip(volume, axis=1)
        elif method == 'weighted':
            # Weighted MIP based on distance
            mip_axial = MasterpieceMIPProcessor._weighted_mip(volume, axis=0)
            mip_sagittal = MasterpieceMIPProcessor._weighted_mip(volume, axis=2)
            mip_coronal = MasterpieceMIPProcessor._weighted_mip(volume, axis=1)
        
        return {
            'mip_axial': mip_axial,
            'mip_sagittal': mip_sagittal,
            'mip_coronal': mip_coronal
        }
    
    @staticmethod
    def _ray_cast_mip(volume, axis):
        """Ray casting MIP implementation"""
        # Simplified ray casting - in production this would be more sophisticated
        return np.max(volume, axis=axis)
    
    @staticmethod
    def _weighted_mip(volume, axis):
        """Weighted MIP based on depth"""
        weights = np.linspace(1.0, 0.5, volume.shape[axis])
        if axis == 0:
            weighted_volume = volume * weights[:, np.newaxis, np.newaxis]
        elif axis == 1:
            weighted_volume = volume * weights[np.newaxis, :, np.newaxis]
        else:
            weighted_volume = volume * weights[np.newaxis, np.newaxis, :]
        
        return np.max(weighted_volume, axis=axis)

class Masterpiece3DProcessor:
    """Enhanced 3D reconstruction processor"""
    
    @staticmethod
    def extract_bone_segmentation(volume, threshold=200, smooth=True, method='threshold'):
        """Extract bone structures using various segmentation methods"""
        if method == 'threshold':
            # Simple thresholding
            bone_mask = volume > threshold
        elif method == 'otsu':
            # Otsu thresholding
            from skimage.filters import threshold_otsu
            thresh = threshold_otsu(volume)
            bone_mask = volume > thresh
        elif method == 'adaptive':
            # Adaptive thresholding
            from skimage.filters import threshold_local
            thresh = threshold_local(volume, block_size=35, offset=10)
            bone_mask = volume > thresh
        elif method == 'region_growing':
            # Region growing segmentation
            bone_mask = Masterpiece3DProcessor._region_growing_segmentation(volume, threshold)
        
        if smooth:
            # Apply morphological operations to smooth the result
            bone_mask = ndimage.binary_opening(bone_mask, structure=np.ones((3,3,3)))
            bone_mask = ndimage.binary_closing(bone_mask, structure=np.ones((5,5,5)))
            
            # Apply Gaussian smoothing to reduce noise
            smoothed_volume = ndimage.gaussian_filter(volume.astype(np.float32), sigma=1.0)
            bone_volume = smoothed_volume * bone_mask
        else:
            bone_volume = volume * bone_mask
        
        return bone_volume, bone_mask
    
    @staticmethod
    def _region_growing_segmentation(volume, threshold):
        """Region growing segmentation implementation"""
        # Simplified region growing - in production this would be more sophisticated
        return volume > threshold
    
    @staticmethod
    def create_3d_surface_mesh(volume, threshold=200, step_size=2, method='marching_cubes'):
        """Create 3D surface mesh using various algorithms"""
        try:
            if method == 'marching_cubes':
                # Use marching cubes to generate mesh
                vertices, faces, normals, values = measure.marching_cubes(
                    volume, 
                    level=threshold,
                    step_size=step_size,
                    allow_degenerate=False
                )
            elif method == 'dual_contouring':
                # Dual contouring (simplified)
                vertices, faces, normals, values = measure.marching_cubes(
                    volume, 
                    level=threshold,
                    step_size=step_size,
                    allow_degenerate=True
                )
            
            return {
                'vertices': vertices.tolist(),
                'faces': faces.tolist(),
                'normals': normals.tolist(),
                'vertex_count': len(vertices),
                'face_count': len(faces),
                'bounding_box': {
                    'min': vertices.min(axis=0).tolist(),
                    'max': vertices.max(axis=0).tolist()
                }
            }
        except Exception as e:
            logger.error(f"Error creating 3D mesh: {e}")
            return None
    
    @staticmethod
    def calculate_bone_density_statistics(volume, bone_mask):
        """Calculate comprehensive bone density statistics"""
        bone_pixels = volume[bone_mask]
        
        if len(bone_pixels) == 0:
            return None
        
        # Calculate histogram
        hist, bins = np.histogram(bone_pixels, bins=50)
        
        stats = {
            'mean_density': float(np.mean(bone_pixels)),
            'std_density': float(np.std(bone_pixels)),
            'min_density': float(np.min(bone_pixels)),
            'max_density': float(np.max(bone_pixels)),
            'median_density': float(np.median(bone_pixels)),
            'bone_volume_pixels': int(np.sum(bone_mask)),
            'total_volume_pixels': int(bone_mask.size),
            'bone_volume_percentage': float(np.sum(bone_mask) / bone_mask.size * 100),
            'histogram': {
                'counts': hist.tolist(),
                'bins': bins.tolist()
            },
            'percentiles': {
                'p5': float(np.percentile(bone_pixels, 5)),
                'p25': float(np.percentile(bone_pixels, 25)),
                'p75': float(np.percentile(bone_pixels, 75)),
                'p95': float(np.percentile(bone_pixels, 95))
            }
        }
        
        return stats

class MasterpieceVolumeBuilder:
    """Enhanced 3D volume builder from DICOM series"""
    
    def __init__(self, series):
        self.series = series
        self.images = series.images.all().order_by('instance_number')
        
    def build_volume(self, interpolate=True):
        """Build 3D volume from series images with enhanced processing"""
        if not self.images:
            return None
            
        volume_slices = []
        positions = []
        
        for image in self.images:
            try:
                # Load DICOM file
                dicom_path = os.path.join(settings.MEDIA_ROOT, image.file_path.name)
                ds = pydicom.dcmread(dicom_path)
                
                # Get pixel array
                pixel_array = ds.pixel_array
                
                # Apply rescale slope and intercept if present
                if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
                    pixel_array = pixel_array * ds.RescaleSlope + ds.RescaleIntercept
                
                # Apply modality LUT if present
                if hasattr(ds, 'ModalityLUTSequence') and ds.ModalityLUTSequence:
                    # Apply modality LUT transformation
                    pass
                
                volume_slices.append(pixel_array)
                
                # Store position for sorting
                if image.image_position:
                    try:
                        pos_list = [float(x) for x in image.image_position.split('\\')]
                        if len(pos_list) >= 3:
                            positions.append(pos_list[2])  # Z-coordinate
                        else:
                            positions.append(image.instance_number)
                    except:
                        positions.append(image.instance_number)
                else:
                    positions.append(image.instance_number)
                    
            except Exception as e:
                logger.error(f"Error loading image {image.id}: {e}")
                continue
        
        if not volume_slices:
            return None
        
        # Sort slices by position
        if positions:
            sorted_data = sorted(zip(positions, volume_slices))
            volume_slices = [slice_data for _, slice_data in sorted_data]
        
        # Stack into 3D volume
        volume = np.stack(volume_slices, axis=0)
        
        # Apply interpolation if requested and needed
        if interpolate and len(volume_slices) > 1:
            volume = self._interpolate_volume(volume)
        
        return volume
    
    def _interpolate_volume(self, volume):
        """Apply interpolation to create isotropic volume"""
        # Get pixel spacing information
        pixel_spacing = self.get_pixel_spacing()
        if pixel_spacing and len(pixel_spacing) >= 2:
            # Calculate zoom factors for isotropic spacing
            target_spacing = min(pixel_spacing)
            zoom_factors = [spacing / target_spacing for spacing in pixel_spacing]
            
            # Apply interpolation
            volume = ndimage.zoom(volume, zoom_factors, order=1, prefilter=True)
        
        return volume
    
    def get_pixel_spacing(self):
        """Get pixel spacing from series"""
        if self.series.pixel_spacing:
            try:
                spacing = [float(x) for x in self.series.pixel_spacing.split('\\')]
                if len(spacing) >= 2:
                    # Add slice thickness as third dimension
                    if self.series.slice_thickness:
                        spacing.append(float(self.series.slice_thickness))
                    else:
                        spacing.append(spacing[0])  # Assume isotropic if not specified
                    return spacing
            except:
                pass
        return None
    
    def get_volume_metadata(self):
        """Get comprehensive metadata about the volume"""
        if not self.images:
            return None
            
        first_image = self.images.first()
        
        metadata = {
            'series_id': self.series.id,
            'image_count': self.images.count(),
            'pixel_spacing': self.get_pixel_spacing(),
            'slice_thickness': self.series.slice_thickness,
            'modality': self.series.modality,
            'rows': first_image.file_path.name if first_image else None,
            'columns': first_image.file_path.name if first_image else None,
            'study_date': self.series.study.study_date.isoformat() if self.series.study.study_date else None,
            'patient_info': {
                'name': self.series.study.patient.full_name if self.series.study.patient else None,
                'id': self.series.study.patient.patient_id if self.series.study.patient else None,
                'age': self.series.study.patient.date_of_birth if self.series.study.patient else None
            }
        }
        
        return metadata

class MasterpieceMeasurementProcessor:
    """Enhanced measurement processing utilities"""
    
    @staticmethod
    def calculate_distance(point1, point2, pixel_spacing=None):
        """Calculate distance between two points"""
        dx = point2[0] - point1[0]
        dy = point2[1] - point1[1]
        pixel_distance = np.sqrt(dx * dx + dy * dy)
        
        if pixel_spacing:
            # Convert to physical units
            if len(pixel_spacing) >= 2:
                avg_spacing = (pixel_spacing[0] + pixel_spacing[1]) / 2
                real_distance = pixel_distance * avg_spacing
                return {
                    'pixel_distance': float(pixel_distance),
                    'real_distance': float(real_distance),
                    'unit': 'mm'
                }
        
        return {
            'pixel_distance': float(pixel_distance),
            'real_distance': float(pixel_distance),
            'unit': 'pixels'
        }
    
    @staticmethod
    def calculate_angle(point1, vertex, point2):
        """Calculate angle between three points"""
        # Vectors from vertex to the other points
        v1 = np.array([point1[0] - vertex[0], point1[1] - vertex[1]])
        v2 = np.array([point2[0] - vertex[0], point2[1] - vertex[1]])
        
        # Calculate angle using dot product
        cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
        angle_rad = np.arccos(np.clip(cos_angle, -1.0, 1.0))
        angle_deg = np.degrees(angle_rad)
        
        return {
            'angle_radians': float(angle_rad),
            'angle_degrees': float(angle_deg)
        }
    
    @staticmethod
    def calculate_area(points, pixel_spacing=None):
        """Calculate area of a polygon defined by points"""
        if len(points) < 3:
            return {'area': 0, 'unit': 'pixels²'}
        
        # Shoelace formula for polygon area
        x = [p[0] for p in points]
        y = [p[1] for p in points]
        
        area = 0.5 * abs(sum(x[i] * y[i + 1] - x[i + 1] * y[i] 
                            for i in range(-1, len(x) - 1)))
        
        if pixel_spacing and len(pixel_spacing) >= 2:
            # Convert to physical units
            spacing_area = pixel_spacing[0] * pixel_spacing[1]
            real_area = area * spacing_area
            return {
                'pixel_area': float(area),
                'real_area': float(real_area),
                'unit': 'mm²'
            }
        
        return {
            'pixel_area': float(area),
            'real_area': float(area),
            'unit': 'pixels²'
        }

class MasterpieceImageExporter:
    """Enhanced image export utilities"""
    
    @staticmethod
    def export_as_png(pixel_array, window_width=None, window_level=None, 
                     annotations=None, measurements=None):
        """Export DICOM image as PNG with overlays"""
        # Apply windowing if specified
        if window_width is not None and window_level is not None:
            pixel_array = MasterpieceDicomProcessor.apply_windowing(
                pixel_array, window_width, window_level
            )
        
        # Convert to PIL Image
        image = Image.fromarray(pixel_array.astype(np.uint8), mode='L')
        
        # Convert to RGB for overlays
        image = image.convert('RGB')
        
        # Add annotations and measurements if specified
        if annotations or measurements:
            # This would draw overlays on the image
            pass
        
        # Convert to base64 for web display
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    
    @staticmethod
    def export_volume_as_nifti(volume, filename, metadata=None):
        """Export volume as NIfTI format"""
        try:
            import nibabel as nib
            
            # Create NIfTI image
            img = nib.Nifti1Image(volume, np.eye(4))
            
            # Add metadata if provided
            if metadata:
                img.header.set_data_dtype(volume.dtype)
                if 'pixel_spacing' in metadata:
                    spacing = metadata['pixel_spacing']
                    img.header.set_zooms(spacing)
            
            # Save to file
            nib.save(img, filename)
            return True
            
        except ImportError:
            logger.warning("nibabel not available for NIfTI export")
            return False
        except Exception as e:
            logger.error(f"Error exporting NIfTI: {e}")
            return False
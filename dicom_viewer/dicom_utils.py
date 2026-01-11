import numpy as np
import pydicom
from PIL import Image
import os
import json
import logging
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def safe_dicom_str(value):
    """Safely convert DICOM values to string, handling MultiValue objects."""
    if value is None or value == "":
        return ""
    
    # Handle MultiValue objects (like PixelSpacing, WindowCenter, WindowWidth)
    if hasattr(value, '__iter__') and not isinstance(value, str):
        try:
            # Convert to list and join with backslash (DICOM standard separator)
            return '\\'.join(map(str, value))
        except Exception:
            return str(value)
    
    return str(value)


class DicomProcessor:
    """Utility class for DICOM image processing"""

    def __init__(self):
        # Professional medical imaging window/level presets
        # Based on American College of Radiology (ACR) recommendations
        self.window_presets = {
            # CT Presets
            'lung': {'ww': 1600, 'wl': -600, 'description': 'Lung parenchyma and airways'},
            'bone': {'ww': 2000, 'wl': 300, 'description': 'Bone structures and fractures'},
            'soft': {'ww': 350, 'wl': 40, 'description': 'Soft tissue contrast'},
            'brain': {'ww': 80, 'wl': 40, 'description': 'Brain tissue differentiation'},
            'abdomen': {'ww': 350, 'wl': 50, 'description': 'Abdominal organs'},
            'liver': {'ww': 160, 'wl': 60, 'description': 'Hepatic parenchyma'},
            'mediastinum': {'ww': 350, 'wl': 50, 'description': 'Mediastinal structures'},
            'spine': {'ww': 400, 'wl': 50, 'description': 'Spinal structures'},
            'pelvis': {'ww': 400, 'wl': 40, 'description': 'Pelvic anatomy'},
            'chest': {'ww': 400, 'wl': 40, 'description': 'Chest soft tissue'},
            
            # Enhanced tissue-specific presets
            'muscle': {'ww': 400, 'wl': 50, 'description': 'Muscle tissue contrast'},
            'fat': {'ww': 200, 'wl': -100, 'description': 'Adipose tissue'},
            
            # X-ray specific presets for optimal visualization
            'xray_chest': {'ww': 2000, 'wl': 0, 'description': 'Chest X-ray - lungs and mediastinum'},
            'xray_bone': {'ww': 3000, 'wl': 500, 'description': 'X-ray bone structures'},
            'xray_soft': {'ww': 400, 'wl': 50, 'description': 'X-ray soft tissue detail'},
            'xray_pediatric': {'ww': 1500, 'wl': 0, 'description': 'Pediatric X-ray imaging'},
            'xray_extremity': {'ww': 2500, 'wl': 300, 'description': 'Extremity X-rays'},
            'xray_spine': {'ww': 2000, 'wl': 200, 'description': 'Spine X-ray imaging'},
            'xray_abdomen': {'ww': 1000, 'wl': 50, 'description': 'Abdominal X-ray'},
            'vessels': {'ww': 600, 'wl': 100, 'description': 'Vascular structures'},
            'kidney': {'ww': 400, 'wl': 30, 'description': 'Renal parenchyma'},
            'pancreas': {'ww': 200, 'wl': 30, 'description': 'Pancreatic tissue'},
            
            # Specialized CT presets
            'pe_study': {'ww': 700, 'wl': 100, 'description': 'Pulmonary embolism'},
            'angio': {'ww': 600, 'wl': 150, 'description': 'CT angiography'},
            'stroke': {'ww': 40, 'wl': 40, 'description': 'Acute stroke imaging'},
            'trauma': {'ww': 400, 'wl': 40, 'description': 'Trauma assessment'},
            
            # MR-equivalent presets for CT
            't1_like': {'ww': 400, 'wl': 40, 'description': 'T1-weighted appearance'},
            't2_like': {'ww': 200, 'wl': 20, 'description': 'T2-weighted appearance'},
            
            # Projection radiography presets
            'xray_chest': {'ww': 2000, 'wl': 500, 'description': 'Chest X-ray'},
            'xray_bone': {'ww': 4000, 'wl': 2000, 'description': 'Bone X-ray'},
            'mammo': {'ww': 4000, 'wl': 2000, 'description': 'Mammography'},
        }
        
        # Standard Hounsfield Unit reference values (NIST recommendations)
        self.hu_reference_values = {
            'air': -1000,
            'lung': -500,
            'fat': -100,
            'water': 0,
            'blood': 40,
            'muscle': 50,
            'grey_matter': 40,
            'white_matter': 25,
            'liver': 60,
            'bone_spongy': 300,
            'bone_cortical': 1000,
            'metal': 3000
        }
        
        # Quality assurance thresholds
        self.qa_thresholds = {
            'water_tolerance': 5,  # HU units
            'air_tolerance': 50,   # HU units
            'linearity_tolerance': 0.02,  # 2%
            'noise_threshold': 10  # HU units standard deviation
        }

    def apply_windowing(self, pixel_array, window_width, window_level, invert=False, enhanced_contrast=True):
        """Apply advanced windowing to DICOM pixel array with enhanced tissue contrast"""
        image_data = pixel_array.astype(np.float32)

        # Calculate window bounds
        min_val = window_level - window_width / 2.0
        max_val = window_level + window_width / 2.0

        if enhanced_contrast:
            # Enhanced windowing with improved tissue differentiation
            # Apply multi-stage enhancement for better X-ray visualization
            
            # Stage 1: Noise reduction with edge preservation
            image_data = self._apply_edge_preserving_filter(image_data)
            
            # Stage 2: Adaptive histogram equalization for local contrast
            image_data = self._apply_adaptive_histogram_equalization(image_data, min_val, max_val)
            
            # Stage 3: Normalize to window range
            normalized = np.clip((image_data - min_val) / max(1.0, max_val - min_val), 0.0, 1.0)
            
            # Stage 4: Apply contrast enhancement curve
            # This provides better tissue differentiation by stretching contrast in mid-range
            enhanced = self._apply_contrast_curve(normalized, window_width, window_level)
            
            # Stage 5: Apply unsharp masking for edge enhancement
            enhanced = self._apply_unsharp_masking(enhanced)
            
            # Scale to display range
            image_data = enhanced * 255.0
        else:
            # Standard linear windowing
            image_data = np.clip(image_data, min_val, max_val)
            if max_val > min_val:
                image_data = (image_data - min_val) / (max_val - min_val) * 255
            else:
                image_data = np.zeros_like(image_data)

        # Apply gamma correction for medical displays (optional)
        if enhanced_contrast:
            gamma = self._get_optimal_gamma(window_width, window_level)
            image_data = np.power(image_data / 255.0, gamma) * 255.0

        if invert:
            image_data = 255 - image_data

        # Ensure proper range and type
        image_data = np.clip(image_data, 0, 255)
        return image_data.astype(np.uint8)

    def _apply_contrast_curve(self, normalized_data, window_width, window_level):
        """Apply contrast enhancement curve for better tissue differentiation"""
        # Adaptive contrast enhancement based on window settings
        if window_width > 1000:  # Wide window (e.g., lung, bone)
            # Use moderate S-curve for wide windows
            contrast_factor = 1.2
        elif window_width < 200:  # Narrow window (e.g., brain)
            # Use stronger enhancement for narrow windows
            contrast_factor = 1.8
        else:  # Medium window (soft tissue)
            contrast_factor = 1.5
        
        # Apply sigmoid-based contrast enhancement
        # This creates an S-curve that enhances mid-range contrast
        center = 0.5
        steepness = contrast_factor * 4.0
        
        # Sigmoid function: 1 / (1 + exp(-steepness * (x - center)))
        enhanced = 1.0 / (1.0 + np.exp(-steepness * (normalized_data - center)))
        
        # Normalize to 0-1 range
        enhanced = (enhanced - enhanced.min()) / (enhanced.max() - enhanced.min() + 1e-8)
        
        return enhanced

    def _get_optimal_gamma(self, window_width, window_level):
        """Get optimal gamma correction for medical imaging display"""
        # Adaptive gamma based on window settings
        if window_level < -200:  # Lung window
            return 0.8  # Brighten dark areas
        elif window_level > 200:  # Bone window  
            return 1.2  # Darken bright areas slightly
        else:  # Soft tissue
            return 1.0  # Standard gamma
    
    def _apply_edge_preserving_filter(self, image_data):
        """Apply edge-preserving noise reduction filter for better image quality"""
        try:
            from scipy import ndimage
            from scipy.ndimage import gaussian_filter
            
            # Apply bilateral filter approximation using multiple Gaussian filters
            # This reduces noise while preserving edges - critical for X-ray images
            
            # Calculate noise level
            noise_level = np.std(image_data) * 0.1
            
            # Apply edge-preserving smoothing
            # Use a small kernel to preserve fine details
            smoothed = gaussian_filter(image_data, sigma=0.8)
            
            # Blend original and smoothed based on local gradient
            gradient_magnitude = np.sqrt(
                ndimage.sobel(image_data, axis=0)**2 + 
                ndimage.sobel(image_data, axis=1)**2
            )
            
            # Normalize gradient
            gradient_norm = gradient_magnitude / (np.max(gradient_magnitude) + 1e-8)
            
            # Preserve edges (high gradient areas), smooth flat areas
            edge_weight = np.clip(gradient_norm * 2.0, 0, 1)
            result = edge_weight * image_data + (1 - edge_weight) * smoothed
            
            return result.astype(np.float32)
            
        except ImportError:
            # Fallback: simple noise reduction
            kernel = np.ones((3,3)) / 9
            return ndimage.convolve(image_data, kernel, mode='reflect')
    
    def _apply_adaptive_histogram_equalization(self, image_data, min_val, max_val):
        """Apply adaptive histogram equalization for improved local contrast"""
        try:
            # Clip to window range first
            windowed_data = np.clip(image_data, min_val, max_val)
            
            # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) approximation
            # This enhances local contrast while preventing over-amplification
            
            # Divide image into tiles
            tile_size = min(64, min(image_data.shape) // 4)
            if tile_size < 8:
                tile_size = 8
                
            rows, cols = image_data.shape
            
            # Create enhanced image
            enhanced = np.copy(windowed_data)
            
            # Process each tile
            for i in range(0, rows - tile_size + 1, tile_size // 2):
                for j in range(0, cols - tile_size + 1, tile_size // 2):
                    # Extract tile
                    tile = windowed_data[i:i+tile_size, j:j+tile_size]
                    
                    # Apply local histogram equalization
                    tile_min, tile_max = np.min(tile), np.max(tile)
                    if tile_max > tile_min:
                        # Normalize tile
                        tile_norm = (tile - tile_min) / (tile_max - tile_min)
                        
                        # Apply contrast stretching
                        tile_enhanced = np.power(tile_norm, 0.8)  # Slight gamma correction
                        
                        # Scale back to original range
                        tile_enhanced = tile_enhanced * (tile_max - tile_min) + tile_min
                        
                        # Blend with original (prevent over-enhancement)
                        alpha = 0.6  # Blend factor
                        tile_final = alpha * tile_enhanced + (1 - alpha) * tile
                        
                        # Update enhanced image
                        enhanced[i:i+tile_size, j:j+tile_size] = tile_final
            
            return enhanced
            
        except Exception as e:
            logger.warning(f"Adaptive histogram equalization failed: {e}")
            return image_data
    
    def _apply_unsharp_masking(self, normalized_data):
        """Apply unsharp masking for edge enhancement"""
        try:
            from scipy.ndimage import gaussian_filter
            
            # Create blurred version
            sigma = 1.0  # Blur radius
            blurred = gaussian_filter(normalized_data, sigma=sigma)
            
            # Create unsharp mask
            mask = normalized_data - blurred
            
            # Apply sharpening
            amount = 0.5  # Sharpening strength
            threshold = 0.02  # Threshold to prevent noise amplification
            
            # Only sharpen where the mask is above threshold
            mask_strong = np.abs(mask) > threshold
            sharpened = normalized_data + amount * mask * mask_strong
            
            # Ensure values stay in valid range
            return np.clip(sharpened, 0.0, 1.0)
            
        except ImportError:
            # Fallback: simple edge enhancement
            kernel = np.array([[-1, -1, -1],
                              [-1,  9, -1],
                              [-1, -1, -1]]) / 9
            try:
                from scipy import ndimage
                enhanced = ndimage.convolve(normalized_data, kernel, mode='reflect')
                return np.clip(enhanced, 0.0, 1.0)
            except:
                return normalized_data
    
    def get_optimal_preset_for_hu_range(self, hu_min, hu_max, modality='CT'):
        """Automatically suggest optimal window preset based on HU range"""
        hu_range = hu_max - hu_min
        hu_center = (hu_max + hu_min) / 2
        
        if modality == 'CT':
            if hu_min < -800 and hu_max > 200:  # Wide range including air and bone
                return 'chest'
            elif hu_min < -800:  # Includes air/lung
                return 'lung' 
            elif hu_max > 400:  # High attenuation (bone/contrast)
                return 'bone'
            elif hu_center < 0:  # Centered below water
                return 'lung'
            elif hu_center > 100:  # High attenuation center
                return 'bone'
            elif hu_range < 100:  # Narrow range
                return 'brain'
            else:
                return 'soft'
        else:
            return 'soft'  # Default for non-CT
    
    def auto_window_from_data(self, pixel_array, percentile_range=(1, 99), modality='CT'):
        """Automatically calculate optimal window/level from image data with X-ray optimization"""
        try:
            # Remove extreme outliers
            p_low, p_high = np.percentile(pixel_array.flatten(), percentile_range)
            
            # Special handling for X-ray images (typically have different characteristics)
            if modality.upper() in ['CR', 'DX', 'DR']:  # Digital radiography modalities
                # X-ray images often have inverted intensity values
                # Use wider percentile range for better contrast
                percentile_range = (0.5, 99.5)
                p_low, p_high = np.percentile(pixel_array.flatten(), percentile_range)
                
                # Calculate optimal window for X-ray
                window_width = (p_high - p_low) * 1.5  # Wider window for X-rays
                window_level = (p_high + p_low) / 2
                
                # Ensure minimum window width for X-rays
                if window_width < 1000:
                    window_width = 1500
                    
                return float(window_width), float(window_level)
            
            # Calculate window width and level for CT and other modalities
            window_width = max(50, p_high - p_low)  # Minimum width of 50 HU
            window_level = (p_high + p_low) / 2
            
            return float(window_width), float(window_level)
        except:
            return 400.0, 40.0  # Safe defaults

    def get_pixel_spacing(self, dicom_data):
        try:
            if hasattr(dicom_data, 'PixelSpacing'):
                spacing = dicom_data.PixelSpacing
                return float(spacing[0]), float(spacing[1])
            elif hasattr(dicom_data, 'ImagerPixelSpacing'):
                spacing = dicom_data.ImagerPixelSpacing
                return float(spacing[0]), float(spacing[1])
            else:
                return 1.0, 1.0
        except (ValueError, IndexError, AttributeError):
            return 1.0, 1.0

    def get_slice_thickness(self, dicom_data):
        try:
            if hasattr(dicom_data, 'SliceThickness'):
                return float(dicom_data.SliceThickness)
            elif hasattr(dicom_data, 'SpacingBetweenSlices'):
                return float(dicom_data.SpacingBetweenSlices)
            else:
                return 1.0
        except (ValueError, AttributeError):
            return 1.0

    def get_image_position(self, dicom_data):
        try:
            if hasattr(dicom_data, 'ImagePositionPatient'):
                pos = dicom_data.ImagePositionPatient
                return float(pos[0]), float(pos[1]), float(pos[2])
            else:
                return 0.0, 0.0, 0.0
        except (ValueError, IndexError, AttributeError):
            return 0.0, 0.0, 0.0

    def get_image_orientation(self, dicom_data):
        try:
            if hasattr(dicom_data, 'ImageOrientationPatient'):
                return list(map(float, dicom_data.ImageOrientationPatient))
            else:
                return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        except (ValueError, AttributeError):
            return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]

    def calculate_distance(self, point1, point2, pixel_spacing=(1.0, 1.0)):
        dx = (point2[0] - point1[0]) * pixel_spacing[0]
        dy = (point2[1] - point1[1]) * pixel_spacing[1]
        return float(np.sqrt(dx * dx + dy * dy))

    def calculate_area(self, points, pixel_spacing=(1.0, 1.0)):
        if len(points) < 3:
            return 0.0
        mm_points = [(p[0] * pixel_spacing[0], p[1] * pixel_spacing[1]) for p in points]
        area = 0.0
        n = len(mm_points)
        for i in range(n):
            j = (i + 1) % n
            area += mm_points[i][0] * mm_points[j][1]
            area -= mm_points[j][0] * mm_points[i][1]
        return abs(area) / 2.0

    def calculate_angle(self, point1, point2, point3):
        v1 = np.array([point1[0] - point2[0], point1[1] - point2[1]])
        v2 = np.array([point3[0] - point2[0], point3[1] - point2[1]])
        denom = (np.linalg.norm(v1) * np.linalg.norm(v2))
        if denom == 0:
            return 0.0
        cos_angle = np.dot(v1, v2) / denom
        angle = np.arccos(np.clip(cos_angle, -1.0, 1.0))
        return float(np.degrees(angle))

    def convert_to_hounsfield_units(self, pixel_array, dicom_data):
        """Convert pixel values to Hounsfield Units using DICOM rescale parameters"""
        try:
            # Get rescale parameters
            slope_attr = getattr(dicom_data, 'RescaleSlope', None)
            intercept_attr = getattr(dicom_data, 'RescaleIntercept', None)
            slope = float(slope_attr) if slope_attr not in (None, "") else 1.0
            intercept = float(intercept_attr) if intercept_attr not in (None, "") else 0.0
            
            # Convert to HU
            hu_array = pixel_array.astype(np.float32) * slope + intercept
            
            return hu_array
        except Exception as e:
            logger.error(f"Error converting to Hounsfield units: {str(e)}")
            return pixel_array.astype(np.float32)

    def validate_hounsfield_calibration(self, dicom_data, pixel_array=None):
        """Validate Hounsfield unit calibration according to international standards"""
        validation_results = {
            'is_valid': True,
            'issues': [],
            'warnings': [],
            'calibration_status': 'unknown',
            'water_hu': None,
            'air_hu': None,
            'noise_level': None
        }
        
        try:
            # Check if CT modality
            modality = getattr(dicom_data, 'Modality', '')
            if modality != 'CT':
                validation_results['calibration_status'] = 'not_applicable'
                validation_results['warnings'].append('Hounsfield units only applicable to CT images')
                return validation_results
            
            # Check rescale parameters
            slope = getattr(dicom_data, 'RescaleSlope', None)
            intercept = getattr(dicom_data, 'RescaleIntercept', None)
            
            if slope is None or intercept is None:
                validation_results['is_valid'] = False
                validation_results['issues'].append('Missing rescale parameters (slope/intercept)')
                validation_results['calibration_status'] = 'invalid'
                return validation_results
            
            # Validate rescale parameters
            slope = float(slope)
            intercept = float(intercept)
            
            if abs(slope - 1.0) > 0.01:  # Slope should typically be 1.0 for CT
                validation_results['warnings'].append(f'Unusual rescale slope: {slope}')
            
            # Check rescale type
            rescale_type = getattr(dicom_data, 'RescaleType', '')
            if rescale_type and rescale_type != 'HU':
                validation_results['warnings'].append(f'Rescale type is "{rescale_type}", not "HU"')
            
            # If pixel array provided, perform phantom validation
            if pixel_array is not None:
                hu_array = self.convert_to_hounsfield_units(pixel_array, dicom_data)
                
                # Estimate water and air HU values (simplified approach)
                # This would need actual phantom ROI coordinates in practice
                water_hu = self._estimate_water_hu(hu_array)
                air_hu = self._estimate_air_hu(hu_array)
                noise_level = self._calculate_noise_level(hu_array)
                
                validation_results['water_hu'] = water_hu
                validation_results['air_hu'] = air_hu
                validation_results['noise_level'] = noise_level
                
                # Validate against reference values
                if water_hu is not None:
                    water_deviation = abs(water_hu - self.hu_reference_values['water'])
                    if water_deviation > self.qa_thresholds['water_tolerance']:
                        validation_results['is_valid'] = False
                        validation_results['issues'].append(
                            f'Water HU deviation too high: {water_deviation:.1f} HU '
                            f'(expected: 0 ± {self.qa_thresholds["water_tolerance"]} HU)'
                        )
                
                if air_hu is not None:
                    air_deviation = abs(air_hu - self.hu_reference_values['air'])
                    if air_deviation > self.qa_thresholds['air_tolerance']:
                        validation_results['is_valid'] = False
                        validation_results['issues'].append(
                            f'Air HU deviation too high: {air_deviation:.1f} HU '
                            f'(expected: -1000 ± {self.qa_thresholds["air_tolerance"]} HU)'
                        )
                
                if noise_level is not None and noise_level > self.qa_thresholds['noise_threshold']:
                    validation_results['warnings'].append(
                        f'High noise level detected: {noise_level:.1f} HU std dev'
                    )
            
            # Set calibration status
            if validation_results['is_valid']:
                validation_results['calibration_status'] = 'valid'
            else:
                validation_results['calibration_status'] = 'invalid'
                
        except Exception as e:
            logger.error(f"Error validating Hounsfield calibration: {str(e)}")
            validation_results['is_valid'] = False
            validation_results['issues'].append(f'Validation error: {str(e)}')
            validation_results['calibration_status'] = 'error'
        
        return validation_results

    def _estimate_water_hu(self, hu_array):
        """Estimate water HU value from image (simplified approach)"""
        try:
            # Look for values near water HU (0)
            water_candidates = hu_array[(hu_array > -50) & (hu_array < 50)]
            if len(water_candidates) > 100:  # Need sufficient samples
                return float(np.median(water_candidates))
        except:
            pass
        return None

    def _estimate_air_hu(self, hu_array):
        """Estimate air HU value from image (simplified approach)"""
        try:
            # Look for values near air HU (-1000)
            air_candidates = hu_array[hu_array < -900]
            if len(air_candidates) > 100:  # Need sufficient samples
                return float(np.median(air_candidates))
        except:
            pass
        return None

    def _calculate_noise_level(self, hu_array):
        """Calculate noise level in Hounsfield units"""
        try:
            # Use standard deviation of a uniform region (simplified)
            # In practice, this would use a specific phantom ROI
            center_region = self._get_center_region(hu_array)
            if center_region is not None and len(center_region) > 100:
                return float(np.std(center_region))
        except:
            pass
        return None

    def _get_center_region(self, hu_array, fraction=0.1):
        """Get center region of image for noise analysis"""
        try:
            h, w = hu_array.shape[:2]
            center_h, center_w = h // 2, w // 2
            region_h, region_w = int(h * fraction), int(w * fraction)
            
            start_h = center_h - region_h // 2
            end_h = center_h + region_h // 2
            start_w = center_w - region_w // 2
            end_w = center_w + region_w // 2
            
            return hu_array[start_h:end_h, start_w:end_w].flatten()
        except:
            return None

    def generate_hu_calibration_report(self, dicom_data, pixel_array=None):
        """Generate comprehensive HU calibration report"""
        validation = self.validate_hounsfield_calibration(dicom_data, pixel_array)
        
        report = {
            'timestamp': timezone.now().isoformat(),
            'modality': getattr(dicom_data, 'Modality', 'Unknown'),
            'manufacturer': getattr(dicom_data, 'Manufacturer', 'Unknown'),
            'model': getattr(dicom_data, 'ManufacturerModelName', 'Unknown'),
            'station_name': getattr(dicom_data, 'StationName', 'Unknown'),
            'calibration_date': getattr(dicom_data, 'CalibrationDate', 'Unknown'),
            'validation_results': validation,
            'recommendations': []
        }
        
        # Add recommendations based on validation results
        if not validation['is_valid']:
            report['recommendations'].append(
                'Recalibrate CT scanner using appropriate phantom'
            )
            report['recommendations'].append(
                'Contact service engineer for calibration verification'
            )
        
        if validation['warnings']:
            report['recommendations'].append(
                'Monitor calibration stability with regular QA measurements'
            )
        
        if validation['noise_level'] and validation['noise_level'] > self.qa_thresholds['noise_threshold']:
            report['recommendations'].append(
                'Consider increasing reconstruction parameters to reduce noise'
            )
        
        return report


class DicomFileHandler:
    """Handle DICOM file operations"""

    @staticmethod
    def load_dicom_series(file_paths):
        dicom_files = []
        for file_path in file_paths:
            try:
                ds = pydicom.dcmread(file_path)
                dicom_files.append({
                    'file_path': file_path,
                    'dicom_data': ds,
                    'instance_number': getattr(ds, 'InstanceNumber', 0),
                })
            except Exception as e:
                logger.error(f"Error loading DICOM file {file_path}: {str(e)}")
                continue
        dicom_files.sort(key=lambda x: x['instance_number'])
        return dicom_files

    @staticmethod
    def validate_dicom_file(file_path):
        try:
            pydicom.dcmread(file_path, stop_before_pixels=True)
            return True
        except Exception:
            return False

    @staticmethod
    def extract_dicom_metadata(dicom_data):
        metadata = {}
        metadata['patient_id'] = getattr(dicom_data, 'PatientID', '')
        metadata['patient_name'] = str(getattr(dicom_data, 'PatientName', ''))
        metadata['patient_birth_date'] = getattr(dicom_data, 'PatientBirthDate', '')
        metadata['patient_sex'] = getattr(dicom_data, 'PatientSex', '')
        metadata['study_instance_uid'] = getattr(dicom_data, 'StudyInstanceUID', '')
        metadata['study_date'] = getattr(dicom_data, 'StudyDate', '')
        metadata['study_time'] = getattr(dicom_data, 'StudyTime', '')
        metadata['study_description'] = getattr(dicom_data, 'StudyDescription', '')
        metadata['referring_physician'] = getattr(dicom_data, 'ReferringPhysicianName', '')
        metadata['institution_name'] = getattr(dicom_data, 'InstitutionName', '')
        metadata['series_instance_uid'] = getattr(dicom_data, 'SeriesInstanceUID', '')
        metadata['series_number'] = getattr(dicom_data, 'SeriesNumber', None)
        metadata['series_description'] = getattr(dicom_data, 'SeriesDescription', '')
        metadata['modality'] = getattr(dicom_data, 'Modality', '')
        metadata['body_part_examined'] = getattr(dicom_data, 'BodyPartExamined', '')
        metadata['sop_instance_uid'] = getattr(dicom_data, 'SOPInstanceUID', '')
        metadata['instance_number'] = getattr(dicom_data, 'InstanceNumber', None)
        metadata['rows'] = getattr(dicom_data, 'Rows', None)
        metadata['columns'] = getattr(dicom_data, 'Columns', None)
        metadata['bits_stored'] = getattr(dicom_data, 'BitsStored', None)
        window_center = getattr(dicom_data, 'WindowCenter', None)
        window_width = getattr(dicom_data, 'WindowWidth', None)
        if window_center is not None:
            try:
                metadata['window_center'] = float(window_center[0]) if hasattr(window_center, '__iter__') and not isinstance(window_center, str) else float(window_center)
            except Exception:
                pass
        if window_width is not None:
            try:
                metadata['window_width'] = float(window_width[0]) if hasattr(window_width, '__iter__') and not isinstance(window_width, str) else float(window_width)
            except Exception:
                pass
        if hasattr(dicom_data, 'PixelSpacing'):
            metadata['pixel_spacing'] = '\\'.join(map(str, dicom_data.PixelSpacing))
        if hasattr(dicom_data, 'SliceThickness'):
            metadata['slice_thickness'] = float(dicom_data.SliceThickness)
        if hasattr(dicom_data, 'ImagePositionPatient'):
            metadata['image_position'] = '\\'.join(map(str, dicom_data.ImagePositionPatient))
        if hasattr(dicom_data, 'ImageOrientationPatient'):
            metadata['image_orientation'] = '\\'.join(map(str, dicom_data.ImageOrientationPatient))
        return metadata


class VolumeRenderer:
    """3D volume rendering utilities"""

    def __init__(self):
        self.volume_data = None
        self.spacing = None
        self.origin = None

    def load_volume_from_series(self, dicom_files):
        if not dicom_files:
            raise ValueError("No DICOM files provided")
        first_dicom = dicom_files[0]['dicom_data']
        rows = first_dicom.Rows
        cols = first_dicom.Columns
        volume_shape = (len(dicom_files), rows, cols)
        self.volume_data = np.zeros(volume_shape, dtype=np.float32)
        for i, dicom_file in enumerate(dicom_files):
            ds = dicom_file['dicom_data']
            pixel_array = ds.pixel_array.astype(np.float32)
            slope = getattr(ds, 'RescaleSlope', 1.0)
            intercept = getattr(ds, 'RescaleIntercept', 0.0)
            pixel_array = pixel_array * slope + intercept
            self.volume_data[i] = pixel_array
        processor = DicomProcessor()
        pixel_spacing = processor.get_pixel_spacing(first_dicom)
        slice_thickness = processor.get_slice_thickness(first_dicom)
        self.spacing = (slice_thickness, pixel_spacing[0], pixel_spacing[1])
        self.origin = processor.get_image_position(first_dicom)
        return self.volume_data

    def get_orthogonal_slices(self, volume_data, slice_indices):
        if volume_data is None:
            raise ValueError("No volume data loaded")
        depth, height, width = volume_data.shape
        axial_idx = min(slice_indices.get('axial', depth // 2), depth - 1)
        axial_slice = volume_data[axial_idx, :, :]
        sagittal_idx = min(slice_indices.get('sagittal', width // 2), width - 1)
        sagittal_slice = volume_data[:, :, sagittal_idx]
        coronal_idx = min(slice_indices.get('coronal', height // 2), height - 1)
        coronal_slice = volume_data[:, coronal_idx, :]
        return {
            'axial': axial_slice,
            'sagittal': sagittal_slice,
            'coronal': coronal_slice,
        }

    def apply_lut(self, image_data, lut_type='linear'):
        if lut_type == 'linear':
            return image_data
        elif lut_type == 'log':
            return np.log1p(image_data)
        elif lut_type == 'sqrt':
            return np.sqrt(np.abs(image_data))
        elif lut_type == 'inverse':
            max_val = np.max(image_data)
            return max_val - image_data
        else:
            return image_data


class ImageCache:
    """Simple image caching system"""

    def __init__(self, max_size=200):
        self.cache = {}
        self.max_size = max_size
        self.access_order = []

    def _make_key(self, image_id, window_width, window_level, invert):
        return f"{image_id}_{window_width}_{window_level}_{invert}"

    def get(self, image_id, window_width, window_level, invert=False):
        key = self._make_key(image_id, window_width, window_level, invert)
        if key in self.cache:
            if key in self.access_order:
                self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        return None

    def put(self, image_id, window_width, window_level, image_data, invert=False):
        key = self._make_key(image_id, window_width, window_level, invert)
        if len(self.cache) >= self.max_size and key not in self.cache:
            oldest_key = self.access_order.pop(0)
            del self.cache[oldest_key]
        self.cache[key] = image_data
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

    def clear(self):
        self.cache.clear()
        self.access_order.clear()


image_cache = ImageCache(max_size=200)
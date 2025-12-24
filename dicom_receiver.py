#!/usr/bin/env python3
"""
DICOM Receiver Service - Completely Rewritten
Handles incoming DICOM images from remote imaging modalities with enhanced
error handling, logging, and performance optimizations.

Features:
- Robust DICOM C-STORE and C-ECHO handling
- Facility-based access control via AE titles
- Comprehensive metadata extraction
- Real-time notifications
- HU calibration validation for CT images
- Automatic thumbnail generation
- Memory-efficient processing
"""

import os
import sys
import logging
import threading
import time
import signal
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import json
import ipaddress

# Resolve project base directory dynamically
from pathlib import Path
BASE_DIR = Path(os.environ.get('NOCTIS_PROJECT_DIR', Path(__file__).resolve().parent))

# Add Django project to path
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'noctis_pro.settings')

import django
django.setup()

from django.conf import settings
from pynetdicom import AE, evt, AllStoragePresentationContexts, VerificationPresentationContexts
from pynetdicom.sop_class import Verification
from pydicom import dcmread
from pydicom.errors import InvalidDicomError
import numpy as np
from PIL import Image

from worklist.models import Patient, Study, Series, DicomImage, Modality, Facility
from accounts.models import User
from django.utils import timezone
from django.db import transaction, connection
from notifications.models import Notification, NotificationType
from django.db import models
from django.core.files.base import ContentFile

# Setup logging with rotation
from logging.handlers import RotatingFileHandler

class DicomReceiverLogger:
    """Enhanced logging setup for DICOM receiver"""
    
    @staticmethod
    def setup_logger():
        logger = logging.getLogger('dicom_receiver')
        logger.setLevel(logging.INFO)
        
        # Remove existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # File handler with rotation
        logs_dir = BASE_DIR / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(logs_dir / 'dicom_receiver.log'),
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger


class DicomImageProcessor:
    """Enhanced DICOM image processing utilities"""
    
    @staticmethod
    def generate_thumbnail(dicom_dataset, max_size: Tuple[int, int] = (256, 256)) -> Optional[bytes]:
        """Generate thumbnail from DICOM image"""
        try:
            # Get pixel array
            pixel_array = dicom_dataset.pixel_array
            
            # Apply basic windowing for display
            if hasattr(dicom_dataset, 'WindowCenter') and hasattr(dicom_dataset, 'WindowWidth'):
                try:
                    window_center = float(dicom_dataset.WindowCenter[0] if hasattr(dicom_dataset.WindowCenter, '__iter__') else dicom_dataset.WindowCenter)
                    window_width = float(dicom_dataset.WindowWidth[0] if hasattr(dicom_dataset.WindowWidth, '__iter__') else dicom_dataset.WindowWidth)
                except (IndexError, TypeError, ValueError):
                    window_center = np.mean(pixel_array)
                    window_width = np.std(pixel_array) * 4
            else:
                window_center = np.mean(pixel_array)
                window_width = np.std(pixel_array) * 4
            
            # Apply windowing
            min_val = window_center - window_width / 2
            max_val = window_center + window_width / 2
            windowed = np.clip(pixel_array, min_val, max_val)
            
            # Normalize to 0-255
            if max_val > min_val:
                windowed = ((windowed - min_val) / (max_val - min_val) * 255).astype(np.uint8)
            else:
                windowed = np.zeros_like(windowed, dtype=np.uint8)
            
            # Convert to PIL Image
            pil_image = Image.fromarray(windowed)
            
            # Resize to thumbnail size
            pil_image.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Convert to bytes
            from io import BytesIO
            buffer = BytesIO()
            pil_image.save(buffer, format='JPEG', quality=85)
            return buffer.getvalue()
            
        except Exception as e:
            logging.getLogger('dicom_receiver').warning(f"Failed to generate thumbnail: {str(e)}")
            return None
    
    @staticmethod
    def extract_enhanced_metadata(dicom_dataset) -> Dict[str, Any]:
        """Extract comprehensive metadata from DICOM dataset"""
        metadata = {}
        
        # Patient information
        metadata['patient_id'] = getattr(dicom_dataset, 'PatientID', 'UNKNOWN')
        patient_name = str(getattr(dicom_dataset, 'PatientName', 'UNKNOWN'))
        metadata['patient_name'] = patient_name.replace('^', ' ').strip()
        metadata['patient_birth_date'] = getattr(dicom_dataset, 'PatientBirthDate', None)
        metadata['patient_sex'] = getattr(dicom_dataset, 'PatientSex', 'O')
        metadata['patient_age'] = getattr(dicom_dataset, 'PatientAge', None)
        metadata['patient_weight'] = getattr(dicom_dataset, 'PatientWeight', None)
        
        # Study information
        metadata['study_instance_uid'] = getattr(dicom_dataset, 'StudyInstanceUID', None)
        metadata['study_date'] = getattr(dicom_dataset, 'StudyDate', None)
        metadata['study_time'] = getattr(dicom_dataset, 'StudyTime', '000000')
        metadata['study_description'] = getattr(dicom_dataset, 'StudyDescription', 'DICOM Study')
        metadata['referring_physician'] = str(getattr(dicom_dataset, 'ReferringPhysicianName', 'UNKNOWN')).replace('^', ' ')
        metadata['accession_number'] = getattr(dicom_dataset, 'AccessionNumber', f"ACC_{int(time.time())}")
        metadata['study_id'] = getattr(dicom_dataset, 'StudyID', '')
        
        # Series information
        metadata['series_instance_uid'] = getattr(dicom_dataset, 'SeriesInstanceUID', None)
        metadata['series_number'] = getattr(dicom_dataset, 'SeriesNumber', 1)
        metadata['series_description'] = getattr(dicom_dataset, 'SeriesDescription', f'Series {metadata["series_number"]}')
        metadata['modality'] = getattr(dicom_dataset, 'Modality', 'OT')
        metadata['body_part_examined'] = getattr(dicom_dataset, 'BodyPartExamined', '')
        metadata['protocol_name'] = getattr(dicom_dataset, 'ProtocolName', '')
        
        # Image information
        metadata['sop_instance_uid'] = getattr(dicom_dataset, 'SOPInstanceUID', None)
        metadata['instance_number'] = getattr(dicom_dataset, 'InstanceNumber', 1)
        metadata['rows'] = getattr(dicom_dataset, 'Rows', None)
        metadata['columns'] = getattr(dicom_dataset, 'Columns', None)
        metadata['bits_stored'] = getattr(dicom_dataset, 'BitsStored', None)
        metadata['bits_allocated'] = getattr(dicom_dataset, 'BitsAllocated', None)
        
        # Geometric information
        metadata['slice_thickness'] = getattr(dicom_dataset, 'SliceThickness', None)
        metadata['slice_location'] = getattr(dicom_dataset, 'SliceLocation', None)
        
        if hasattr(dicom_dataset, 'PixelSpacing'):
            metadata['pixel_spacing'] = '\\'.join(map(str, dicom_dataset.PixelSpacing))
        
        if hasattr(dicom_dataset, 'ImagePositionPatient'):
            metadata['image_position'] = '\\'.join(map(str, dicom_dataset.ImagePositionPatient))
        
        if hasattr(dicom_dataset, 'ImageOrientationPatient'):
            metadata['image_orientation'] = '\\'.join(map(str, dicom_dataset.ImageOrientationPatient))
        
        # Equipment information
        metadata['manufacturer'] = getattr(dicom_dataset, 'Manufacturer', '')
        metadata['manufacturer_model_name'] = getattr(dicom_dataset, 'ManufacturerModelName', '')
        metadata['station_name'] = getattr(dicom_dataset, 'StationName', '')
        metadata['device_serial_number'] = getattr(dicom_dataset, 'DeviceSerialNumber', '')
        metadata['software_versions'] = getattr(dicom_dataset, 'SoftwareVersions', '')
        
        # CT-specific information
        if metadata['modality'] == 'CT':
            metadata['kvp'] = getattr(dicom_dataset, 'KVP', None)
            metadata['exposure_time'] = getattr(dicom_dataset, 'ExposureTime', None)
            metadata['x_ray_tube_current'] = getattr(dicom_dataset, 'XRayTubeCurrent', None)
            metadata['exposure'] = getattr(dicom_dataset, 'Exposure', None)
            metadata['filter_type'] = getattr(dicom_dataset, 'FilterType', '')
            metadata['convolution_kernel'] = getattr(dicom_dataset, 'ConvolutionKernel', '')
            metadata['reconstruction_diameter'] = getattr(dicom_dataset, 'ReconstructionDiameter', None)
            metadata['slice_thickness'] = getattr(dicom_dataset, 'SliceThickness', None)
            metadata['table_height'] = getattr(dicom_dataset, 'TableHeight', None)
            metadata['gantry_detector_tilt'] = getattr(dicom_dataset, 'GantryDetectorTilt', None)
            
            # HU calibration parameters
            metadata['rescale_slope'] = getattr(dicom_dataset, 'RescaleSlope', 1.0)
            metadata['rescale_intercept'] = getattr(dicom_dataset, 'RescaleIntercept', 0.0)
            metadata['rescale_type'] = getattr(dicom_dataset, 'RescaleType', '')
        
        # MR-specific information
        elif metadata['modality'] == 'MR':
            metadata['repetition_time'] = getattr(dicom_dataset, 'RepetitionTime', None)
            metadata['echo_time'] = getattr(dicom_dataset, 'EchoTime', None)
            metadata['flip_angle'] = getattr(dicom_dataset, 'FlipAngle', None)
            metadata['magnetic_field_strength'] = getattr(dicom_dataset, 'MagneticFieldStrength', None)
            metadata['echo_train_length'] = getattr(dicom_dataset, 'EchoTrainLength', None)
            metadata['inversion_time'] = getattr(dicom_dataset, 'InversionTime', None)
        
        # Window/Level information
        if hasattr(dicom_dataset, 'WindowCenter'):
            try:
                window_center = dicom_dataset.WindowCenter
                metadata['window_center'] = float(window_center[0] if hasattr(window_center, '__iter__') else window_center)
            except (IndexError, TypeError, ValueError):
                pass
        
        if hasattr(dicom_dataset, 'WindowWidth'):
            try:
                window_width = dicom_dataset.WindowWidth
                metadata['window_width'] = float(window_width[0] if hasattr(window_width, '__iter__') else window_width)
            except (IndexError, TypeError, ValueError):
                pass
        
        return metadata


class DicomReceiver:
    """Enhanced DICOM SCP (Service Class Provider) for receiving DICOM images"""
    
    def __init__(self, port: int = 11112, aet: str = 'NOCTIS_SCP', max_pdu_size: int = 16384):
        self.port = port
        self.aet = aet
        self.max_pdu_size = max_pdu_size
        self.is_running = False
        self.ae = None

        # Optional network allowlist (recommended if exposing port 11112 publicly)
        # Examples:
        #   DICOM_ALLOWED_NETS="41.90.0.0/16,102.0.0.0/8"
        #   DICOM_ALLOWED_NETS="196.201.0.10,196.201.0.11"
        self.allowed_nets = self._parse_allowed_nets(os.environ.get("DICOM_ALLOWED_NETS", ""))
        
        # Statistics
        self.stats = {
            'total_received': 0,
            'total_stored': 0,
            'total_errors': 0,
            'start_time': None,
            'last_received': None
        }
        
        # Storage directory rooted at Django MEDIA_ROOT (supports persistent storage in production)
        media_root = Path(getattr(settings, "MEDIA_ROOT", BASE_DIR / "media"))
        self.storage_dir = media_root / 'dicom' / 'received'
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Thumbnail directory rooted at Django MEDIA_ROOT (supports persistent storage in production)
        self.thumbnail_dir = media_root / 'dicom' / 'thumbnails'
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = DicomReceiverLogger.setup_logger()
        
        # Initialize processors
        self.image_processor = DicomImageProcessor()
        
        self.logger.info(f"DICOM Receiver initialized - AET: {aet}, Port: {port}, Max PDU: {max_pdu_size}")
        if self.allowed_nets:
            self.logger.info(
                f"DICOM Receiver network allowlist enabled: {', '.join(str(n) for n in self.allowed_nets)}"
            )

    @staticmethod
    def _parse_allowed_nets(value: str):
        nets = []
        for raw in (value or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                # Accept both IPs and CIDRs
                if "/" in raw:
                    nets.append(ipaddress.ip_network(raw, strict=False))
                else:
                    nets.append(ipaddress.ip_network(f"{raw}/32", strict=False))
            except ValueError:
                # Ignore invalid entries (but don't crash receiver)
                logging.getLogger('dicom_receiver').warning(f"Ignoring invalid DICOM_ALLOWED_NETS entry: '{raw}'")
        return nets

    def _peer_allowed(self, peer_ip: str) -> bool:
        if not self.allowed_nets:
            return True
        try:
            ip = ipaddress.ip_address(peer_ip)
        except ValueError:
            return False
        return any(ip in net for net in self.allowed_nets)
    
    def setup_ae(self):
        """Setup Application Entity with optimized settings"""
        self.ae = AE(ae_title=self.aet)
        
        # Add supported presentation contexts
        self.ae.supported_contexts = AllStoragePresentationContexts
        self.ae.supported_contexts.extend(VerificationPresentationContexts)
        
        # Optimize network settings
        self.ae.maximum_pdu_size = self.max_pdu_size
        self.ae.network_timeout = 30
        self.ae.acse_timeout = 30
        self.ae.dimse_timeout = 30
        
        # Allow any Called AE Title (facilities identify via Calling AE)
        if hasattr(self.ae, 'require_called_aet'):
            try:
                self.ae.require_called_aet = False
            except Exception:
                pass
        
        # Event handlers
        self.ae.on_c_store = self.handle_store
        self.ae.on_c_echo = self.handle_echo
        
        self.logger.info("Application Entity configured successfully")
    
    def handle_echo(self, event):
        """Handle C-ECHO requests (DICOM ping) with enhanced logging"""
        try:
            calling_aet = event.assoc.requestor.ae_title.decode(errors='ignore').strip()
            peer_ip = getattr(event.assoc.requestor, 'address', 'unknown')

            if not self._peer_allowed(peer_ip):
                self.logger.warning(f"C-ECHO rejected (IP not allowed): '{calling_aet}' from {peer_ip}")
                return 0x0000  # Keep success to avoid noisy connectivity failures; C-STORE will still reject.
            
            # Log the echo request
            self.logger.info(f"C-ECHO received from '{calling_aet}' at {peer_ip}")
            
            # Check if facility exists (optional warning)
            facility = Facility.objects.filter(ae_title__iexact=calling_aet, is_active=True).first()
            if not facility:
                self.logger.warning(f"C-ECHO from unknown AE Title '{calling_aet}' - facility not registered")
            
            return 0x0000  # Success
            
        except Exception as e:
            self.logger.error(f"Error handling C-ECHO: {str(e)}")
            return 0x0000  # Still return success for basic connectivity
    
    def handle_store(self, event):
        """Handle C-STORE requests with comprehensive error handling"""
        calling_aet = None
        peer_ip = None
        
        try:
            # Update statistics
            self.stats['total_received'] += 1
            self.stats['last_received'] = timezone.now()
            
            # Extract connection information
            calling_aet = event.assoc.requestor.ae_title.decode(errors='ignore').strip()
            peer_ip = getattr(event.assoc.requestor, 'address', 'unknown')

            # Optional network allowlist check
            if not self._peer_allowed(peer_ip):
                self.logger.warning(f"C-STORE rejected (IP not allowed): '{calling_aet}' from {peer_ip}")
                self.stats['total_errors'] += 1
                return 0xC000
            
            # Validate facility authorization
            facility = Facility.objects.filter(ae_title__iexact=calling_aet, is_active=True).first()
            if not facility:
                self.logger.warning(f"C-STORE rejected: Unknown Calling AET '{calling_aet}' from {peer_ip}")
                self.stats['total_errors'] += 1
                return 0xC000  # Refused: Out of Resources - A400?
            
            # Get the dataset
            try:
                ds = event.dataset
                if ds is None:
                    raise ValueError("Empty dataset received")
            except Exception as e:
                self.logger.error(f"Failed to retrieve dataset: {str(e)}")
                self.stats['total_errors'] += 1
                return 0xA700  # Out of Resources
            
            # Extract basic identifiers for logging
            study_uid = getattr(ds, 'StudyInstanceUID', 'Unknown')
            series_uid = getattr(ds, 'SeriesInstanceUID', 'Unknown')
            sop_instance_uid = getattr(ds, 'SOPInstanceUID', 'Unknown')
            
            self.logger.info(
                f"C-STORE from '{calling_aet}' ({peer_ip}): "
                f"Study={study_uid}, Series={series_uid}, SOP={sop_instance_uid}"
            )
            
            # Process the DICOM object in a transaction
            with transaction.atomic():
                success = self.process_dicom_object(ds, calling_aet, facility, peer_ip)
                
            if success:
                self.stats['total_stored'] += 1
                self.logger.info(f"DICOM object stored successfully: {sop_instance_uid}")
                return 0x0000  # Success
            else:
                self.stats['total_errors'] += 1
                self.logger.error(f"Failed to store DICOM object: {sop_instance_uid}")
                return 0xA700  # Out of Resources
                
        except Exception as e:
            self.stats['total_errors'] += 1
            error_msg = f"Critical error in C-STORE handler: {str(e)}"
            if calling_aet and peer_ip:
                error_msg += f" (from {calling_aet} at {peer_ip})"
            
            self.logger.error(error_msg)
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return 0xA700  # Out of Resources
    
    def process_dicom_object(self, ds, calling_aet: str, facility, peer_ip: str) -> bool:
        """Process and store DICOM object with enhanced metadata extraction"""
        try:
            # Extract comprehensive metadata
            metadata = self.image_processor.extract_enhanced_metadata(ds)
            
            # Validate required UIDs
            if not all([metadata['study_instance_uid'], metadata['series_instance_uid'], metadata['sop_instance_uid']]):
                self.logger.error("Missing required DICOM UIDs")
                return False
            
            # Process patient information
            patient = self._get_or_create_patient(metadata)
            if not patient:
                self.logger.error("Failed to create/retrieve patient")
                return False
            
            # Process modality
            modality = self._get_or_create_modality(metadata['modality'])
            
            # Process study
            study = self._get_or_create_study(metadata, patient, facility, modality)
            if not study:
                self.logger.error("Failed to create/retrieve study")
                return False
            
            # Process series
            series = self._get_or_create_series(metadata, study, modality)
            if not series:
                self.logger.error("Failed to create/retrieve series")
                return False
            
            # Save DICOM file
            file_path = self._save_dicom_file(ds, metadata)
            if not file_path:
                self.logger.error("Failed to save DICOM file")
                return False
            
            # Generate thumbnail
            thumbnail_data = self.image_processor.generate_thumbnail(ds)
            
            # Create DICOM image record
            dicom_image = self._create_dicom_image(metadata, series, file_path, thumbnail_data)
            if not dicom_image:
                self.logger.error("Failed to create DICOM image record")
                return False
            
            # Send notifications for new studies
            if hasattr(study, '_created') and study._created:
                self._send_new_study_notifications(study, facility, modality)
            
            # Log success with details
            self.logger.info(
                f"Successfully processed DICOM: Patient={patient.patient_id}, "
                f"Study={study.accession_number}, Series={series.series_number}, "
                f"Instance={dicom_image.instance_number}"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing DICOM object: {str(e)}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def _get_or_create_patient(self, metadata: Dict[str, Any]) -> Optional[Patient]:
        """Get or create patient with enhanced name parsing"""
        try:
            # Parse patient name
            patient_name = metadata['patient_name']
            name_parts = [part.strip() for part in patient_name.split(' ') if part.strip()]
            
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = ' '.join(name_parts[1:])
            elif len(name_parts) == 1:
                first_name = name_parts[0]
                last_name = ''
            else:
                first_name = 'Unknown'
                last_name = ''
            
            # Parse birth date
            birth_date = timezone.now().date()
            if metadata['patient_birth_date']:
                try:
                    birth_date = datetime.strptime(metadata['patient_birth_date'], '%Y%m%d').date()
                except ValueError:
                    self.logger.warning(f"Invalid birth date format: {metadata['patient_birth_date']}")
            
            # Get or create patient
            patient, created = Patient.objects.get_or_create(
                patient_id=metadata['patient_id'],
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'date_of_birth': birth_date,
                    'gender': metadata['patient_sex'] if metadata['patient_sex'] in ['M', 'F'] else 'O'
                }
            )
            
            if created:
                self.logger.info(f"Created new patient: {patient}")
            
            return patient
            
        except Exception as e:
            self.logger.error(f"Error creating patient: {str(e)}")
            return None
    
    def _get_or_create_modality(self, modality_code: str) -> Modality:
        """Get or create modality"""
        modality, created = Modality.objects.get_or_create(
            code=modality_code,
            defaults={
                'name': modality_code,
                'description': f'{modality_code} Modality'
            }
        )
        return modality
    
    def _get_or_create_study(self, metadata: Dict[str, Any], patient: Patient, 
                           facility: Facility, modality: Modality) -> Optional[Study]:
        """Get or create study with comprehensive metadata"""
        try:
            # Parse study datetime
            study_datetime = timezone.now()
            if metadata['study_date']:
                try:
                    study_time = metadata['study_time'][:6].ljust(6, '0')  # Ensure 6 digits
                    study_datetime = datetime.strptime(f"{metadata['study_date']}{study_time}", '%Y%m%d%H%M%S')
                    study_datetime = timezone.make_aware(study_datetime)
                except ValueError as e:
                    self.logger.warning(f"Invalid study date/time: {metadata['study_date']}, {metadata['study_time']} - {e}")
            
            # Get or create study
            study, created = Study.objects.get_or_create(
                study_instance_uid=metadata['study_instance_uid'],
                defaults={
                    'accession_number': metadata['accession_number'],
                    'patient': patient,
                    'facility': facility,
                    'modality': modality,
                    'study_description': metadata['study_description'],
                    'study_date': study_datetime,
                    'referring_physician': metadata['referring_physician'],
                    'body_part': metadata.get('body_part_examined', ''),
                    'status': 'scheduled',
                    'priority': 'normal'
                }
            )
            
            # Mark if newly created for notification purposes
            study._created = created
            
            if created:
                self.logger.info(f"Created new study: {study}")
            
            return study
            
        except Exception as e:
            self.logger.error(f"Error creating study: {str(e)}")
            return None
    
    def _get_or_create_series(self, metadata: Dict[str, Any], study: Study, modality: Modality) -> Optional[Series]:
        """Get or create series with enhanced metadata"""
        try:
            series, created = Series.objects.get_or_create(
                series_instance_uid=metadata['series_instance_uid'],
                defaults={
                    'study': study,
                    'series_number': metadata['series_number'],
                    'series_description': metadata['series_description'],
                    'modality': metadata['modality'],
                    'body_part': metadata.get('body_part_examined', ''),
                    'slice_thickness': metadata.get('slice_thickness'),
                    'pixel_spacing': metadata.get('pixel_spacing', ''),
                    'image_orientation': metadata.get('image_orientation', '')
                }
            )
            
            if created:
                self.logger.info(f"Created new series: {series}")
            
            return series
            
        except Exception as e:
            self.logger.error(f"Error creating series: {str(e)}")
            return None
    
    def _save_dicom_file(self, ds, metadata: Dict[str, Any]) -> Optional[Path]:
        """Save DICOM file with organized directory structure"""
        try:
            # Create directory structure: study_uid/series_uid/
            study_uid = metadata['study_instance_uid']
            series_uid = metadata['series_instance_uid']
            sop_instance_uid = metadata['sop_instance_uid']
            
            file_dir = self.storage_dir / study_uid / series_uid
            file_dir.mkdir(parents=True, exist_ok=True)
            
            file_path = file_dir / f"{sop_instance_uid}.dcm"
            
            # Save DICOM file
            ds.save_as(file_path, write_like_original=False)
            
            # Verify file was saved correctly
            if not file_path.exists() or file_path.stat().st_size == 0:
                raise ValueError("DICOM file was not saved correctly")
            
            return file_path
            
        except Exception as e:
            self.logger.error(f"Error saving DICOM file: {str(e)}")
            return None
    
    def _create_dicom_image(self, metadata: Dict[str, Any], series: Series, 
                          file_path: Path, thumbnail_data: Optional[bytes]) -> Optional[DicomImage]:
        """Create DICOM image database record"""
        try:
            # Create relative path for database storage
            media_root = Path(getattr(settings, "MEDIA_ROOT", BASE_DIR / "media"))
            relative_path = str(file_path.relative_to(media_root))
            file_size = file_path.stat().st_size
            
            # Create DICOM image record
            dicom_image, created = DicomImage.objects.get_or_create(
                sop_instance_uid=metadata['sop_instance_uid'],
                defaults={
                    'series': series,
                    'instance_number': metadata['instance_number'],
                    'image_position': metadata.get('image_position', ''),
                    'slice_location': metadata.get('slice_location'),
                    'file_path': relative_path,
                    'file_size': file_size,
                    'processed': False
                }
            )
            
            # Save thumbnail if generated
            if created and thumbnail_data:
                try:
                    thumbnail_filename = f"{metadata['sop_instance_uid']}_thumb.jpg"
                    thumbnail_content = ContentFile(thumbnail_data, name=thumbnail_filename)
                    dicom_image.thumbnail.save(thumbnail_filename, thumbnail_content, save=True)
                except Exception as e:
                    self.logger.warning(f"Failed to save thumbnail: {str(e)}")
            
            if created:
                self.logger.info(f"Created new DICOM image: {dicom_image}")
            
            return dicom_image
            
        except Exception as e:
            self.logger.error(f"Error creating DICOM image record: {str(e)}")
            return None
    
    def _send_new_study_notifications(self, study: Study, facility: Facility, modality: Modality):
        """Send notifications for new studies"""
        try:
            notif_type, _ = NotificationType.objects.get_or_create(
                code='new_study',
                defaults={
                    'name': 'New Study Uploaded',
                    'description': 'A new study has been uploaded',
                    'is_system': True
                }
            )
            
            # Get recipients (radiologists, admins, facility users)
            recipients = User.objects.filter(
                models.Q(role='radiologist') | 
                models.Q(role='admin') | 
                models.Q(facility=facility),
                is_active=True
            ).distinct()
            
            for recipient in recipients:
                try:
                    Notification.objects.create(
                        type=notif_type,
                        recipient=recipient,
                        sender=None,
                        title=f"New {modality.code} study for {study.patient.full_name}",
                        message=f"Study {study.accession_number} uploaded from {facility.name}",
                        priority='normal',
                        study=study,
                        facility=facility,
                        data={
                            'study_id': study.id,
                            'accession_number': study.accession_number,
                            'modality': modality.code,
                            'patient_name': study.patient.full_name
                        }
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to create notification for user {recipient.username}: {str(e)}")
            
            self.logger.info(f"Sent notifications for new study {study.accession_number} to {recipients.count()} users")
            
        except Exception as e:
            self.logger.warning(f"Failed to send notifications for new study: {str(e)}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get receiver statistics"""
        runtime = None
        if self.stats['start_time']:
            runtime = (timezone.now() - self.stats['start_time']).total_seconds()
        
        return {
            'is_running': self.is_running,
            'port': self.port,
            'aet': self.aet,
            'total_received': self.stats['total_received'],
            'total_stored': self.stats['total_stored'],
            'total_errors': self.stats['total_errors'],
            'success_rate': (self.stats['total_stored'] / max(1, self.stats['total_received'])) * 100,
            'runtime_seconds': runtime,
            'last_received': self.stats['last_received'],
            'start_time': self.stats['start_time']
        }
    
    def start(self):
        """Start the DICOM receiver service"""
        self.logger.info(f"Starting DICOM receiver on port {self.port}")
        
        try:
            self.setup_ae()
            self.is_running = True
            self.stats['start_time'] = timezone.now()
            
            # Print startup banner
            self.logger.info("=" * 60)
            self.logger.info("NOCTIS PRO DICOM RECEIVER SERVICE")
            self.logger.info("=" * 60)
            self.logger.info(f"Application Entity Title: {self.aet}")
            self.logger.info(f"Listening on port: {self.port}")
            self.logger.info(f"Maximum PDU size: {self.max_pdu_size}")
            self.logger.info(f"Storage directory: {self.storage_dir}")
            self.logger.info("Waiting for DICOM connections...")
            self.logger.info("=" * 60)
            
            # Start the server (blocking)
            self.ae.start_server(('', self.port), block=True)
            
        except KeyboardInterrupt:
            self.logger.info("DICOM receiver stopped by user (Ctrl+C)")
        except Exception as e:
            self.logger.error(f"Error starting DICOM receiver: {str(e)}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
        finally:
            self.is_running = False
            self.logger.info("DICOM receiver service stopped")
            
            # Print final statistics
            stats = self.get_statistics()
            self.logger.info("Final Statistics:")
            self.logger.info(f"  Total received: {stats['total_received']}")
            self.logger.info(f"  Total stored: {stats['total_stored']}")
            self.logger.info(f"  Total errors: {stats['total_errors']}")
            self.logger.info(f"  Success rate: {stats['success_rate']:.1f}%")
            if stats['runtime_seconds']:
                self.logger.info(f"  Runtime: {stats['runtime_seconds']:.0f} seconds")
    
    def stop(self):
        """Stop the DICOM receiver service"""
        self.logger.info("Stopping DICOM receiver...")
        self.is_running = False
        if self.ae:
            self.ae.shutdown()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger = logging.getLogger('dicom_receiver')
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    # The receiver will be stopped in the main function


def main():
    """Main function to run the DICOM receiver"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='NOCTIS PRO DICOM Receiver Service',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--port', type=int, default=11112, 
                       help='Port to listen on')
    parser.add_argument('--aet', default='NOCTIS_SCP', 
                       help='Application Entity Title')
    parser.add_argument('--max-pdu', type=int, default=16384,
                       help='Maximum PDU size in bytes')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Ensure logs directory exists under project base directory
    (BASE_DIR / 'logs').mkdir(parents=True, exist_ok=True)
    
    # Create receiver instance
    receiver = DicomReceiver(port=args.port, aet=args.aet, max_pdu_size=args.max_pdu)
    
    # Set debug logging if requested
    if args.debug:
        logging.getLogger('dicom_receiver').setLevel(logging.DEBUG)
        logging.getLogger('pynetdicom').setLevel(logging.DEBUG)
    
    try:
        receiver.start()
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()


if __name__ == '__main__':
    main()
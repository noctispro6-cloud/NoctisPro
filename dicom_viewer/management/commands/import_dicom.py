"""
Enhanced DICOM Import Management Command
Imports DICOM files into the database with advanced processing capabilities
"""
import os
import sys
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone
import pydicom
from worklist.models import Study, Series, DicomImage, Patient, Modality
from accounts.models import User, Facility
from datetime import datetime
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import DICOM files into the database with enhanced processing'

    def add_arguments(self, parser):
        parser.add_argument('source_dir', type=str, help='Directory containing DICOM files')
        parser.add_argument('--recursive', '-r', action='store_true', 
                          help='Search for DICOM files recursively')
        parser.add_argument('--move', action='store_true',
                          help='Move files instead of copying')
        parser.add_argument('--dry-run', action='store_true',
                          help='Show what would be imported without actually importing')
        parser.add_argument('--facility', type=str, default=None,
                          help='Facility name or ID to associate with imported studies')
        parser.add_argument('--user', type=str, default=None,
                          help='Username to set as uploader')
        parser.add_argument('--overwrite', action='store_true',
                          help='Overwrite existing studies')
        parser.add_argument('--validate-only', action='store_true',
                          help='Only validate DICOM files without importing')
        parser.add_argument('--batch-size', type=int, default=100,
                          help='Number of files to process in each batch')

    def handle(self, *args, **options):
        source_dir = options['source_dir']
        
        if not os.path.exists(source_dir):
            raise CommandError(f'Directory "{source_dir}" does not exist.')
        
        # Setup logging
        self.setup_logging()
        
        # Get facility and user if specified
        facility = self.get_facility(options.get('facility'))
        user = self.get_user(options.get('user'))
        
        # Find all DICOM files
        self.stdout.write(self.style.SUCCESS('🔍 Scanning for DICOM files...'))
        dicom_files = self.find_dicom_files(source_dir, options['recursive'])
        
        if not dicom_files:
            self.stdout.write(self.style.WARNING('⚠️  No DICOM files found.'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'✅ Found {len(dicom_files)} DICOM files.'))
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('🔥 DRY RUN MODE - No files will be imported'))
            self.preview_import(dicom_files[:20])  # Show first 20
            return
        
        if options['validate_only']:
            self.stdout.write(self.style.WARNING('🔍 VALIDATION MODE - Only validating files'))
            self.validate_dicom_files(dicom_files)
            return
        
        # Import files
        self.import_dicom_files(dicom_files, options, facility, user)

    def setup_logging(self):
        """Setup enhanced logging for import process"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('dicom_import.log'),
                logging.StreamHandler()
            ]
        )

    def get_facility(self, facility_str):
        """Get facility object from string"""
        if not facility_str:
            return None
        
        try:
            # Try by ID first
            if facility_str.isdigit():
                return Facility.objects.get(id=int(facility_str))
            # Then by name
            return Facility.objects.get(name__icontains=facility_str)
        except Facility.DoesNotExist:
            self.stdout.write(self.style.WARNING(f'⚠️  Facility "{facility_str}" not found. Using default.'))
            return None

    def get_user(self, username):
        """Get user object from username"""
        if not username:
            return None
        
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.WARNING(f'⚠️  User "{username}" not found. Using system user.'))
            return None

    def find_dicom_files(self, directory, recursive=False):
        """Find all DICOM files in directory with enhanced detection"""
        dicom_files = []
        
        def scan_directory(path):
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                
                if os.path.isfile(item_path):
                    if self.is_dicom_file(item_path):
                        dicom_files.append(item_path)
                elif os.path.isdir(item_path) and recursive:
                    scan_directory(item_path)
        
        scan_directory(directory)
        return sorted(dicom_files)

    def is_dicom_file(self, file_path):
        """Enhanced DICOM file detection"""
        try:
            # Check file extension first
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.dcm', '.dicom', '.dic']:
                return True
            
            # Check DICOM magic number
            with open(file_path, 'rb') as f:
                f.seek(128)
                magic = f.read(4)
                if magic == b'DICM':
                    return True
            
            # Try to read as DICOM
            pydicom.dcmread(file_path, stop_before_pixels=True)
            return True
            
        except Exception:
            return False

    def preview_import(self, sample_files):
        """Preview what would be imported"""
        studies_preview = {}
        
        for file_path in sample_files:
            try:
                ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                study_uid = ds.StudyInstanceUID
                
                if study_uid not in studies_preview:
                    studies_preview[study_uid] = {
                        'patient_name': str(getattr(ds, 'PatientName', 'Unknown')),
                        'patient_id': getattr(ds, 'PatientID', 'Unknown'),
                        'study_date': getattr(ds, 'StudyDate', 'Unknown'),
                        'modality': getattr(ds, 'Modality', 'Unknown'),
                        'series_count': set(),
                        'file_count': 0
                    }
                
                studies_preview[study_uid]['series_count'].add(ds.SeriesInstanceUID)
                studies_preview[study_uid]['file_count'] += 1
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'❌ Error reading {file_path}: {e}'))
        
        # Display preview
        self.stdout.write(self.style.SUCCESS('\n📋 IMPORT PREVIEW:'))
        for study_uid, info in studies_preview.items():
            self.stdout.write(f"  📁 Study: {info['patient_name']} ({info['patient_id']})")
            self.stdout.write(f"     Date: {info['study_date']} | Modality: {info['modality']}")
            self.stdout.write(f"     Series: {len(info['series_count'])} | Files: {info['file_count']}")
            self.stdout.write("")

    def validate_dicom_files(self, dicom_files):
        """Validate DICOM files without importing"""
        valid_count = 0
        invalid_count = 0
        
        self.stdout.write(self.style.SUCCESS('🔍 Validating DICOM files...'))
        
        for i, file_path in enumerate(dicom_files, 1):
            try:
                ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                
                # Check required tags
                required_tags = ['StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID']
                missing_tags = [tag for tag in required_tags if not hasattr(ds, tag)]
                
                if missing_tags:
                    self.stdout.write(self.style.WARNING(f'⚠️  {file_path}: Missing tags: {missing_tags}'))
                    invalid_count += 1
                else:
                    valid_count += 1
                
                if i % 100 == 0:
                    self.stdout.write(f'   Processed {i}/{len(dicom_files)} files...')
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'❌ {file_path}: {e}'))
                invalid_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Validation complete:'))
        self.stdout.write(f'   Valid files: {valid_count}')
        self.stdout.write(f'   Invalid files: {invalid_count}')

    def import_dicom_files(self, dicom_files, options, facility, user):
        """Import DICOM files with enhanced processing"""
        imported_count = 0
        skipped_count = 0
        error_count = 0
        batch_size = options['batch_size']
        
        self.stdout.write(self.style.SUCCESS('🚀 Starting DICOM import...'))
        
        # Process files in batches
        for i in range(0, len(dicom_files), batch_size):
            batch = dicom_files[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(dicom_files) + batch_size - 1) // batch_size
            
            self.stdout.write(f'📦 Processing batch {batch_num}/{total_batches} ({len(batch)} files)...')
            
            for file_path in batch:
                try:
                    result = self.import_dicom_file(file_path, options, facility, user)
                    if result == 'imported':
                        imported_count += 1
                    elif result == 'skipped':
                        skipped_count += 1
                        
                except Exception as e:
                    error_count += 1
                    logger.error(f'Error importing {file_path}: {str(e)}')
                    self.stdout.write(self.style.ERROR(f'❌ Error importing {file_path}: {str(e)}'))
            
            # Progress update
            total_processed = imported_count + skipped_count + error_count
            self.stdout.write(f'   Progress: {total_processed}/{len(dicom_files)} files processed')
        
        # Final summary
        self.stdout.write(self.style.SUCCESS('\n🎉 Import complete!'))
        self.stdout.write(f'   ✅ Imported: {imported_count}')
        self.stdout.write(f'   ⏭️  Skipped: {skipped_count}')
        self.stdout.write(f'   ❌ Errors: {error_count}')

    def import_dicom_file(self, file_path, options, facility, user):
        """Import a single DICOM file with enhanced processing"""
        try:
            # Read DICOM file
            ds = pydicom.dcmread(file_path)
            
            # Check if already imported
            if DicomImage.objects.filter(sop_instance_uid=ds.SOPInstanceUID).exists():
                if not options.get('overwrite'):
                    return 'skipped'
                else:
                    # Delete existing
                    DicomImage.objects.filter(sop_instance_uid=ds.SOPInstanceUID).delete()
            
            # Get or create patient
            patient = self.get_or_create_patient(ds)
            
            # Get or create modality
            modality = self.get_or_create_modality(ds)
            
            # Get or create study
            study = self.get_or_create_study(ds, patient, modality, facility, user)
            
            # Get or create series
            series = self.get_or_create_series(ds, study)
            
            # Create storage directory
            storage_dir = self.create_storage_path(patient, study, series)
            
            # Copy/move file
            filename = f"{ds.SOPInstanceUID}.dcm"
            dest_path = os.path.join(storage_dir, filename)
            
            if options.get('move'):
                shutil.move(file_path, dest_path)
            else:
                shutil.copy2(file_path, dest_path)
            
            # Create relative path for database storage
            relative_path = os.path.relpath(dest_path, settings.MEDIA_ROOT)
            
            # Create DicomImage record
            image = DicomImage.objects.create(
                sop_instance_uid=ds.SOPInstanceUID,
                series=series,
                instance_number=getattr(ds, 'InstanceNumber', 0),
                image_position=str(getattr(ds, 'ImagePositionPatient', '')),
                slice_location=getattr(ds, 'SliceLocation', None),
                file_path=relative_path,
                file_size=os.path.getsize(dest_path),
                processed=True
            )
            
            return 'imported'
            
        except Exception as e:
            logger.error(f'Failed to import {file_path}: {str(e)}')
            raise

    def get_or_create_patient(self, ds):
        """Get or create patient record with enhanced data extraction"""
        patient_id = getattr(ds, 'PatientID', 'Unknown')
        patient_name = str(getattr(ds, 'PatientName', 'Unknown'))
        
        # Split name into first and last
        name_parts = patient_name.replace('^', ' ').split()
        first_name = name_parts[0] if name_parts else 'Unknown'
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        
        # Parse birth date
        birth_date = None
        if hasattr(ds, 'PatientBirthDate') and ds.PatientBirthDate:
            try:
                birth_date = datetime.strptime(ds.PatientBirthDate, '%Y%m%d').date()
            except:
                pass
        
        # Get gender
        gender = getattr(ds, 'PatientSex', None)
        if gender and gender.upper() in ['M', 'F', 'O']:
            gender = gender.upper()
        else:
            gender = 'M'  # Default
        
        patient, created = Patient.objects.get_or_create(
            patient_id=patient_id,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
                'date_of_birth': birth_date or datetime.now().date(),
                'gender': gender
            }
        )
        
        return patient

    def get_or_create_modality(self, ds):
        """Get or create modality record"""
        modality_code = getattr(ds, 'Modality', 'OT')
        
        modality, created = Modality.objects.get_or_create(
            code=modality_code,
            defaults={
                'name': self.get_modality_name(modality_code),
                'description': f'{modality_code} imaging modality',
                'is_active': True
            }
        )
        
        return modality

    def get_modality_name(self, code):
        """Get full modality name from code"""
        modality_names = {
            'CT': 'Computed Tomography',
            'MR': 'Magnetic Resonance',
            'XR': 'X-Ray',
            'US': 'Ultrasound',
            'NM': 'Nuclear Medicine',
            'PT': 'Positron Emission Tomography',
            'CR': 'Computed Radiography',
            'DR': 'Digital Radiography',
            'DX': 'Digital X-Ray',
            'MG': 'Mammography',
            'RF': 'Radio Fluoroscopy',
            'OT': 'Other'
        }
        return modality_names.get(code, code)

    def get_or_create_study(self, ds, patient, modality, facility, user):
        """Get or create study record with enhanced data extraction"""
        study_uid = ds.StudyInstanceUID
        
        # Parse study date
        study_date = None
        if hasattr(ds, 'StudyDate') and ds.StudyDate:
            try:
                study_date = datetime.strptime(ds.StudyDate, '%Y%m%d')
            except:
                study_date = timezone.now()
        else:
            study_date = timezone.now()
        
        study, created = Study.objects.get_or_create(
            study_instance_uid=study_uid,
            defaults={
                'patient': patient,
                'facility': facility or Facility.objects.first(),
                'modality': modality,
                'accession_number': getattr(ds, 'AccessionNumber', f'ACC_{study_uid[:8]}'),
                'study_description': getattr(ds, 'StudyDescription', ''),
                'study_date': study_date,
                'referring_physician': getattr(ds, 'ReferringPhysicianName', ''),
                'status': 'completed',
                'priority': 'normal',
                'body_part': getattr(ds, 'BodyPartExamined', ''),
                'uploaded_by': user
            }
        )
        
        return study

    def get_or_create_series(self, ds, study):
        """Get or create series record with enhanced data extraction"""
        series_uid = ds.SeriesInstanceUID
        
        # Get pixel spacing
        pixel_spacing = ''
        if hasattr(ds, 'PixelSpacing'):
            pixel_spacing = '\\'.join([str(x) for x in ds.PixelSpacing])
        
        series, created = Series.objects.get_or_create(
            series_instance_uid=series_uid,
            defaults={
                'study': study,
                'series_number': getattr(ds, 'SeriesNumber', 0),
                'series_description': getattr(ds, 'SeriesDescription', ''),
                'modality': getattr(ds, 'Modality', ''),
                'body_part': getattr(ds, 'BodyPartExamined', ''),
                'slice_thickness': getattr(ds, 'SliceThickness', None),
                'pixel_spacing': pixel_spacing,
                'image_orientation': str(getattr(ds, 'ImageOrientationPatient', ''))
            }
        )
        
        return series

    def create_storage_path(self, patient, study, series):
        """Create organized storage directory structure"""
        base_dir = os.path.join(settings.MEDIA_ROOT, 'dicom', 'images')
        
        # Create organized directory structure
        storage_path = os.path.join(
            base_dir,
            f"patient_{patient.patient_id}",
            f"study_{study.id}_{study.study_date.strftime('%Y%m%d')}",
            f"series_{series.series_number}_{series.modality}"
        )
        
        os.makedirs(storage_path, exist_ok=True)
        return storage_path
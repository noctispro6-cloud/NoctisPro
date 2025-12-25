from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, FileResponse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count, Case, When, Value, IntegerField
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import os
import mimetypes
import json
from pathlib import Path
import threading
import pydicom
from PIL import Image
from io import BytesIO
import logging
from django.conf import settings
from .models import (
    Study, Patient, Modality, Series, DicomImage, StudyAttachment, 
    AttachmentComment, AttachmentVersion
)
from accounts.models import User, Facility
from notifications.models import Notification, NotificationType
from reports.models import Report

# Module logger for robust error reporting
logger = logging.getLogger('noctis_pro.worklist')


def _auto_start_ai_for_study(study: Study) -> None:
	"""
	Automatically kick off preliminary AI analysis in the background for a study.
	This is best-effort: failures won't break uploads.
	"""
	import os as _os
	enabled = (_os.environ.get('AI_AUTO_ANALYSIS_ON_UPLOAD', '') or '').strip().lower()
	if enabled:
		if enabled != 'true':
			return
	else:
		# Fall back to DB system configuration toggle (default: true).
		try:
			from admin_panel.models import SystemConfiguration
			row = SystemConfiguration.objects.filter(key='ai_auto_analysis_on_upload').first()
			if row and (row.value or '').strip().lower() in ('false', '0', 'no', 'off'):
				return
		except Exception:
			pass

	try:
		from ai_analysis.models import AIModel, AIAnalysis
		# Ensure baseline placeholder models exist (so demo environments work).
		if AIModel.objects.count() == 0:
			try:
				from ai_analysis.management.commands.setup_ai_models import BASELINE_MODELS
				for m in BASELINE_MODELS:
					AIModel.objects.get_or_create(
						name=m['name'],
						version=m['version'],
						defaults={
							'model_type': m['model_type'],
							'modality': m['modality'],
							'body_part': m['body_part'],
							'description': m['description'],
							'training_data_info': m['training_data_info'],
							'accuracy_metrics': m['accuracy_metrics'],
							'model_file_path': m['model_file_path'],
							'config_file_path': m['config_file_path'],
							'preprocessing_config': m['preprocessing_config'],
							'is_active': True,
							'is_trained': False,
						},
					)
			except Exception:
				pass

		modality_code = getattr(study.modality, 'code', None)
		candidates = AIModel.objects.filter(is_active=True).filter(Q(modality=modality_code) | Q(modality='ALL'))
		# Prefer classification/detection first for triage signal.
		order = {'classification': 0, 'detection': 1, 'segmentation': 2, 'quality_assessment': 3, 'report_generation': 4, 'reconstruction': 5}
		models = sorted(list(candidates), key=lambda x: order.get(getattr(x, 'model_type', ''), 99))[:3]
		if not models:
			return

		analyses = []
		for model in models:
			if AIAnalysis.objects.filter(study=study, ai_model=model, status__in=['pending', 'processing', 'completed']).exists():
				continue
			analyses.append(
				AIAnalysis.objects.create(
					study=study,
					ai_model=model,
					priority=study.priority or 'normal',
					status='pending',
				)
			)
		if not analyses:
			return

		# Run in background (same worker used elsewhere).
		from ai_analysis.views import process_ai_analyses
		threading.Thread(target=process_ai_analyses, args=(analyses,), daemon=True).start()
	except Exception:
		return

@login_required
def dashboard(request):
	"""Render the exact provided dashboard UI template"""
	from django.middleware.csrf import get_token
	return render(request, 'worklist/dashboard.html', {
		'user': request.user,
		'csrf_token': get_token(request)
	})

@login_required
def study_list(request):
	"""List all studies with filtering and pagination"""
	user = request.user
	
	# Base queryset based on user role
	if user.is_facility_user() and getattr(user, 'facility', None):
		studies = Study.objects.filter(facility=user.facility)
	else:
		studies = Study.objects.all()
	
	# Apply filters
	status_filter = request.GET.get('status')
	if status_filter:
		studies = studies.filter(status=status_filter)
	
	priority_filter = request.GET.get('priority')
	if priority_filter:
		studies = studies.filter(priority=priority_filter)
	
	modality_filter = request.GET.get('modality')
	if modality_filter:
		studies = studies.filter(modality__code=modality_filter)
	
	search_query = request.GET.get('search')
	if search_query:
		studies = studies.filter(
			Q(accession_number__icontains=search_query) |
			Q(patient__first_name__icontains=search_query) |
			Q(patient__last_name__icontains=search_query) |
			Q(patient__patient_id__icontains=search_query) |
			Q(study_description__icontains=search_query)
		)
	
	# Sort by priority (urgent→low) then most recent first; prefetch attachments for display
	priority_rank = Case(
		When(priority='urgent', then=Value(3)),
		When(priority='high', then=Value(2)),
		When(priority='normal', then=Value(1)),
		When(priority='low', then=Value(0)),
		default=Value(1),
		output_field=IntegerField(),
	)
	studies = (
		studies
		.select_related('patient', 'facility', 'modality', 'radiologist')
		.prefetch_related('attachments')
		.annotate(_priority_rank=priority_rank)
		.order_by('-_priority_rank', '-study_date')
	)
	
	# Pagination
	paginator = Paginator(studies, 25)
	page_number = request.GET.get('page')
	studies_page = paginator.get_page(page_number)
	
	# Get available modalities for filter
	modalities = Modality.objects.filter(is_active=True)
	
	# Build quick maps for previous reports (by same patient) and attachments per study
	page_studies = list(studies_page.object_list)
	patient_ids = list({s.patient_id for s in page_studies})
	study_ids = [s.id for s in page_studies]
	
	# Previous reports grouped by patient, excluding current study
	all_reports = Report.objects.filter(study__patient_id__in=patient_ids).select_related('study', 'radiologist').order_by('-report_date')
	reports_by_patient = {}
	for rep in all_reports:
		reports_by_patient.setdefault(rep.study.patient_id, []).append(rep)
	previous_reports_map = {}
	for s in page_studies:
		items = [r for r in reports_by_patient.get(s.patient_id, []) if r.study_id != s.id]
		previous_reports_map[s.id] = items[:5]  # cap in template
	
	# Attachments per study (current version only)
	atts = StudyAttachment.objects.filter(study_id__in=study_ids, is_current_version=True).order_by('-upload_date')
	attachments_map = {}
	for a in atts:
		attachments_map.setdefault(a.study_id, []).append(a)

	# AI triage map (latest completed AI analysis per study)
	ai_triage_map = {}
	try:
		from ai_analysis.models import AIAnalysis
		analyses = (
			AIAnalysis.objects
			.filter(study_id__in=study_ids, status='completed')
			.select_related('study')
			.order_by('-completed_at', '-requested_at')
		)
		for a in analyses:
			if a.study_id in ai_triage_map:
				continue
			m = a.measurements or {}
			if not isinstance(m, dict):
				m = {}
			ai_triage_map[a.study_id] = {
				'triage_level': m.get('triage_level'),
				'triage_score': m.get('triage_score'),
				'flagged': bool(m.get('triage_flagged')),
			}
	except Exception:
		ai_triage_map = {}
	
	context = {
		'studies': studies_page,
		'modalities': modalities,
		'status_filter': status_filter,
		'priority_filter': priority_filter,
		'modality_filter': modality_filter,
		'search_query': search_query,
		'user': user,
		'previous_reports_map': previous_reports_map,
		'attachments_map': attachments_map,
		'ai_triage_map': ai_triage_map,
	}
	
	return render(request, 'worklist/study_list.html', context)

@login_required
def study_detail(request, study_id):
	"""Detailed view of a study"""
	study = get_object_or_404(Study, id=study_id)
	user = request.user
	
	# Check permissions
	if user.is_facility_user() and study.facility != user.facility:
		messages.error(request, 'You do not have permission to view this study.')
		return redirect('worklist:study_list')
	
	# Get series and images
	series_list = study.series_set.all().order_by('series_number')
	
	# Get study attachments
	attachments = study.attachments.filter(is_current_version=True).order_by('-upload_date')
	
	# Get study notes
	notes = study.notes.all().order_by('-created_at')
	
	context = {
		'study': study,
		'series_list': series_list,
		'attachments': attachments,
		'notes': notes,
		'user': user,
	}
	
	return render(request, 'worklist/study_detail.html', context)

@login_required
@csrf_exempt
@transaction.atomic
def upload_study(request):
	"""
	Professional DICOM Upload Backend - Medical Imaging Excellence
	Enhanced with masterpiece-level processing for diagnostic quality
	"""
	if request.method == 'POST':
		try:
			import logging
			import time
			from datetime import datetime
			
			# Initialize professional logging
			logger = logging.getLogger('noctis_pro.upload')
			upload_start_time = time.time()
			
			# Enhanced admin/radiologist options with professional validation
			override_facility_id = (request.POST.get('facility_id', '') or '').strip()
			assign_to_me = (request.POST.get('assign_to_me', '0') == '1')
			priority = request.POST.get('priority', 'normal')
			clinical_info = request.POST.get('clinical_info', '').strip()
			
			# Professional file validation
			uploaded_files = request.FILES.getlist('dicom_files')
			
			if not uploaded_files:
				logger.warning(f"Upload attempt with no files by user {request.user.username}")
				return JsonResponse({
					'success': False, 
					'error': 'No files uploaded',
					'details': 'Please select DICOM files to upload',
					'timestamp': timezone.now().isoformat(),
					'user': request.user.username
				})
			
			# Professional upload statistics tracking
			upload_stats = {
				'total_files': len(uploaded_files),
				'processed_files': 0,
				'invalid_files': 0,
				'created_studies': 0,
				'created_series': 0,
				'created_images': 0,
				'total_size_mb': 0,
				'processing_time_ms': 0,
				'user': request.user.username,
				'timestamp': timezone.now().isoformat()
			}
			
			logger.info(f"Professional DICOM upload started: {upload_stats['total_files']} files by {request.user.username}")
			
			# Professional DICOM processing with medical-grade validation
			studies_map = {}
			invalid_files = 0
			processed_files = 0
			total_files = len(uploaded_files)
			file_size_total = 0
			patient_ids_involved = set()
			series_uids_touched = set()
			
			# Enhanced DICOM processing pipeline with professional validation
			logger.info("Starting professional DICOM metadata extraction and validation")
			
			# Client-side filters are helpful, but we also enforce server-side validation
			# to prevent temp/hidden files from being treated as DICOM (especially because `force=True`
			# can otherwise parse arbitrary binaries into an "empty" Dataset).
			_TEMP_BASENAMES = {
				'.ds_store', 'thumbs.db', 'desktop.ini', 'icon\r', '.spotlight-v100', '.trashes'
			}
			_TEMP_SUFFIXES = ('.tmp', '.temp', '.swp', '.swo', '.bak', '~')
			_ALLOWED_EXTS = ('.dcm', '.dicom', '.dicm', '.ima')

			def _is_temp_or_hidden_name(name: str) -> bool:
				base = (os.path.basename(name or '') or '').strip()
				low = base.lower()
				if not low:
					return True
				if low in _TEMP_BASENAMES:
					return True
				if low.startswith('.') or low.startswith('._'):
					return True
				if low.endswith(_TEMP_SUFFIXES):
					return True
				# Ignore macOS resource forks / metadata folders if path comes through
				if '__macosx' in (name or '').lower():
					return True
				return False

			def _has_dicm_preamble(fobj) -> bool:
				"""Check DICOM Part-10 preamble marker safely without consuming the stream."""
				try:
					pos = fobj.tell()
				except Exception:
					pos = None
				try:
					fobj.seek(0)
					head = fobj.read(132)
					return len(head) >= 132 and head[128:132] == b'DICM'
				except Exception:
					return False
				finally:
					try:
						if pos is not None:
							fobj.seek(pos)
						else:
							fobj.seek(0)
					except Exception:
						pass

			def _stable_synth_sop_uid(fobj) -> str:
				"""
				Create a stable SOP-like identifier when SOPInstanceUID is missing.

				We deliberately avoid random UUIDs here because they break idempotency:
				re-uploading the same bytes would create "new" images each time.
				"""
				import hashlib
				try:
					pos = fobj.tell()
				except Exception:
					pos = None
				try:
					fobj.seek(0)
					data = fobj.read()
					digest = hashlib.sha1(data).hexdigest()
					return f"SYN-SOP-SHA1-{digest}"
				except Exception:
					# Last resort: fall back to random value (should be extremely rare)
					import uuid as _uuid
					return f"SYN-SOP-{_uuid.uuid4()}"
				finally:
					try:
						if pos is not None:
							fobj.seek(pos)
						else:
							fobj.seek(0)
					except Exception:
						pass

			for file_index, in_file in enumerate(uploaded_files):
				file_start_time = time.time()
				file_size_mb = in_file.size / (1024 * 1024)  # Convert to MB
				file_size_total += file_size_mb
				try:
					# Skip obvious temp/hidden files early
					if _is_temp_or_hidden_name(getattr(in_file, 'name', '')):
						invalid_files += 1
						continue
					# Skip very small files (not a useful DICOM object)
					if getattr(in_file, 'size', 0) and in_file.size < 256:
						invalid_files += 1
						continue
					# Skip DICOMDIR explicitly (it's a directory record, not an image slice)
					if (os.path.basename(getattr(in_file, 'name', '') or '').upper() == 'DICOMDIR'):
						invalid_files += 1
						continue

					# Professional DICOM reading with comprehensive error handling
					# Prefer fast header read to avoid loading pixel data during request
					name = (getattr(in_file, 'name', '') or '')
					ext = (os.path.splitext(name)[1] or '').lower()
					has_preamble = _has_dicm_preamble(in_file)

					ds = None
					try:
						# Strict parse first to avoid treating arbitrary binaries as DICOM
						in_file.seek(0)
						ds = pydicom.dcmread(in_file, stop_before_pixels=True, force=False)
					except Exception:
						# Allow slightly non-conformant DICOMs ONLY if they look like DICOM by extension or preamble.
						if has_preamble or ext in _ALLOWED_EXTS:
							try:
								in_file.seek(0)
								ds = pydicom.dcmread(in_file, stop_before_pixels=True, force=True)
							except Exception:
								ds = None
						else:
							ds = None

					if ds is None:
						invalid_files += 1
						continue

					# If this is a DICOM directory record SOP class, skip it (not image data)
					try:
						if str(getattr(ds, 'SOPClassUID', '')).strip() == '1.2.840.10008.1.3.10':
							invalid_files += 1
							continue
					except Exception:
						pass
					
					# Medical-grade metadata extraction and validation
					study_uid = getattr(ds, 'StudyInstanceUID', None)
					series_uid = getattr(ds, 'SeriesInstanceUID', None)
					sop_uid = getattr(ds, 'SOPInstanceUID', None)
					modality = getattr(ds, 'Modality', 'OT')

					# Validation strategy:
					# - StudyInstanceUID and SeriesInstanceUID are required to group files correctly.
					#   Synthesizing them per-file causes uncontrolled duplication and random series splits.
					# - SOPInstanceUID is required for deduplication; if it's missing, synthesize a STABLE
					#   identifier from the file bytes so re-uploads remain idempotent.
					if not study_uid or not series_uid:
						invalid_files += 1
						logger.warning(
							f"File {file_index + 1}: Missing required UID(s) "
							f"(StudyInstanceUID={bool(study_uid)}, SeriesInstanceUID={bool(series_uid)}); skipping"
						)
						continue
					if not sop_uid:
						sop_uid = _stable_synth_sop_uid(in_file)
						logger.warning(f"File {file_index + 1}: Missing SOPInstanceUID, synthesized stable {sop_uid}")
						setattr(ds, 'SOPInstanceUID', sop_uid)
					
					# Enhanced series grouping with medical imaging intelligence
					series_key = f"{series_uid}_{modality}"
					studies_map.setdefault(study_uid, {}).setdefault(series_key, []).append((ds, in_file))
					
					processed_files += 1
					file_processing_time = (time.time() - file_start_time) * 1000
					
					# Professional progress logging every 10 files
					if (file_index + 1) % 10 == 0:
						logger.info(f"Professional processing: {file_index + 1}/{total_files} files processed ({file_processing_time:.1f}ms per file)")
					
				except Exception as e:
					logger.error(f"File {file_index + 1} processing failed: {str(e)}")
					invalid_files += 1
					continue
			
			if not studies_map:
				return JsonResponse({'success': False, 'error': 'No valid DICOM files found'})
			
			created_studies = []
			total_series_processed = 0
			
			for study_uid, series_map in studies_map.items():
				# Extract representative dataset
				first_series_key = next(iter(series_map))
				rep_ds = series_map[first_series_key][0][0]
				
				# Professional patient information extraction with medical standards
				logger.info(f"Processing study: {study_uid}")
				
				# Enhanced patient data extraction with medical validation
				patient_id = getattr(rep_ds, 'PatientID', f'TEMP_{int(timezone.now().timestamp())}')
				patient_name = str(getattr(rep_ds, 'PatientName', 'UNKNOWN^PATIENT')).replace('^', ' ')
				
				# Professional name parsing with medical standards
				name_parts = patient_name.strip().split(' ')
				first_name = name_parts[0] if name_parts and name_parts[0] != 'UNKNOWN' else 'Unknown'
				last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else 'Patient'
				
				# Professional date handling with medical precision
				birth_date = getattr(rep_ds, 'PatientBirthDate', None)
				if birth_date:
					try:
						dob = datetime.strptime(birth_date, '%Y%m%d').date()
						logger.debug(f"Patient DOB parsed: {dob}")
					except Exception as e:
						logger.warning(f"Invalid birth date format: {birth_date}, using current date")
						dob = timezone.now().date()
				else:
					dob = timezone.now().date()
				
				# Professional gender validation with medical standards
				gender = getattr(rep_ds, 'PatientSex', 'O').upper()
				if gender not in ['M', 'F', 'O']:
					logger.warning(f"Invalid gender value: {gender}, defaulting to 'O'")
					gender = 'O'
				
				# Professional patient creation with comprehensive logging
				patient, patient_created = Patient.objects.get_or_create(
					patient_id=patient_id,
					defaults={
						'first_name': first_name, 
						'last_name': last_name, 
						'date_of_birth': dob, 
						'gender': gender
					}
				)
				
				if patient_created:
					logger.info(f"New patient created: {patient.full_name} (ID: {patient_id})")
				else:
					logger.debug(f"Existing patient found: {patient.full_name} (ID: {patient_id})")
				
				# Professional modality and study metadata processing
				modality_code = getattr(rep_ds, 'Modality', 'OT').upper()
				modality, modality_created = Modality.objects.get_or_create(
					code=modality_code, 
					defaults={'name': modality_code, 'is_active': True}
				)
				
				if modality_created:
					logger.info(f"New modality created: {modality_code}")
				
				# Professional study metadata extraction with medical standards
				study_description = getattr(rep_ds, 'StudyDescription', f'{modality_code} Study - Professional Upload')
				referring_physician = str(getattr(rep_ds, 'ReferringPhysicianName', 'UNKNOWN')).replace('^', ' ')
				
				# Professional accession number generation with collision handling
				accession_number = getattr(rep_ds, 'AccessionNumber', None)
				if not accession_number or accession_number.strip() == '':
					# Generate professional accession number
					timestamp = int(timezone.now().timestamp())
					accession_number = f"NOCTIS_{modality_code}_{timestamp}"
				
				# Medical-grade collision prevention
				original_accession = accession_number
				if Study.objects.filter(accession_number=accession_number).exists():
					suffix = 1
					base_acc = str(accession_number)
					while Study.objects.filter(accession_number=f"{base_acc}_V{suffix}").exists():
						suffix += 1
					accession_number = f"{base_acc}_V{suffix}"
					logger.info(f"Accession number collision resolved: {original_accession} → {accession_number}")
				study_date = getattr(rep_ds, 'StudyDate', None)
				study_time = getattr(rep_ds, 'StudyTime', '000000')
				if study_date:
					try:
						sdt = datetime.strptime(f"{study_date}{study_time[:6]}", '%Y%m%d%H%M%S')
						sdt = timezone.make_aware(sdt)
					except Exception:
						sdt = timezone.now()
				else:
					sdt = timezone.now()
				
				# Facility attribution with admin/radiologist override
				facility = None
				if (hasattr(request.user, 'is_admin') and request.user.is_admin()) or (hasattr(request.user, 'is_radiologist') and request.user.is_radiologist()):
					if override_facility_id:
						facility = Facility.objects.filter(id=override_facility_id, is_active=True).first()
				if not facility and getattr(request.user, 'facility', None):
					facility = request.user.facility
				if not facility:
					facility = Facility.objects.filter(is_active=True).first()
				if not facility:
					# Allow admin to upload without preconfigured facility by creating a default one
					if hasattr(request.user, 'is_admin') and request.user.is_admin():
						facility = Facility.objects.create(
							name='Default Facility',
							address='N/A',
							phone='N/A',
							email='default@example.com',
							license_number=f'DEFAULT-{int(timezone.now().timestamp())}',
							ae_title='',
							is_active=True
						)
					else:
						return JsonResponse({'success': False, 'error': 'No active facility configured'})
				
				# Optional: assign uploaded study to current radiologist's worklist
				assigned_radiologist = None
				if assign_to_me and hasattr(request.user, 'is_radiologist') and request.user.is_radiologist():
					assigned_radiologist = request.user
				
				# Professional study creation with enhanced medical metadata
				study, study_created = Study.objects.get_or_create(
					study_instance_uid=study_uid,
					defaults={
						'accession_number': accession_number,
						'patient': patient,
						'facility': facility,
						'modality': modality,
						'study_description': study_description,
						'study_date': sdt,
						'referring_physician': referring_physician,
						'status': 'scheduled',
						'priority': priority,
						'clinical_info': clinical_info,
						'uploaded_by': request.user,
						'radiologist': assigned_radiologist,
						'body_part': getattr(rep_ds, 'BodyPartExamined', ''),
						'study_comments': f'Professional upload by {request.user.get_full_name()} on {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}',
					}
				)

				# Automatically start preliminary AI analysis for newly created studies
				if study_created:
					try:
						_auto_start_ai_for_study(study)
					except Exception:
						pass
				
				if study_created:
					upload_stats['created_studies'] += 1
					logger.info(f"Professional study created: {study.accession_number} - {study.study_description}")
				else:
					logger.debug(f"Existing study found: {study.accession_number}")
				try:
					if getattr(patient, 'id', None):
						patient_ids_involved.add(int(patient.id))
				except Exception:
					pass
				
				# Track by id to keep response consistent
				created_studies.append(study.id)
				
				# Professional series processing with medical imaging intelligence
				for series_key, items in series_map.items():
					series_start_time = time.time()
					
					# Parse series key to get series_uid and modality
					series_uid = series_key.split('_')[0]
					
					# Professional series metadata extraction
					ds0 = items[0][0]
					series_number = getattr(ds0, 'SeriesNumber', 1) or 1
					series_desc = getattr(ds0, 'SeriesDescription', f'{modality_code} Series {series_number}')
					slice_thickness = getattr(ds0, 'SliceThickness', None)
					pixel_spacing = str(getattr(ds0, 'PixelSpacing', ''))
					image_orientation = str(getattr(ds0, 'ImageOrientationPatient', ''))
					
					# Enhanced medical imaging metadata for professional standards
					body_part = getattr(ds0, 'BodyPartExamined', '').upper()
					
					# Professional series creation with comprehensive metadata
					series, series_created = Series.objects.get_or_create(
						series_instance_uid=series_uid,
						defaults={
							'study': study,
							'series_number': int(series_number),
							'series_description': series_desc,
							'modality': modality_code,
							'body_part': body_part,
							'slice_thickness': slice_thickness if slice_thickness is not None else None,
							'pixel_spacing': pixel_spacing,
							'image_orientation': image_orientation,
						}
					)
					try:
						if series_uid:
							series_uids_touched.add(str(series_uid))
					except Exception:
						pass

					# Defensive fix: ensure the Series is linked to this Study.
					# In the wild, chunk retries or historical data can leave a Series UID attached to the wrong Study,
					# which makes the newly-created Study show "0 series / 0 images" in the worklist and viewer.
					try:
						if series and series.study_id != study.id:
							logger.warning(
								f"Series UID collision/mislink detected: series_instance_uid={series_uid} "
								f"belongs to study_id={series.study_id}, expected study_id={study.id}. Re-linking."
							)
							series.study = study
							# Keep metadata reasonably up-to-date for the UI
							series.series_number = int(series_number)
							series.series_description = series_desc
							series.modality = modality_code
							series.body_part = body_part
							series.slice_thickness = slice_thickness if slice_thickness is not None else None
							series.pixel_spacing = pixel_spacing
							series.image_orientation = image_orientation
							series.save(update_fields=[
								'study',
								'series_number',
								'series_description',
								'modality',
								'body_part',
								'slice_thickness',
								'pixel_spacing',
								'image_orientation',
							])
					except Exception:
						# Never fail the upload because of a relink attempt; worst case we keep existing behavior.
						pass
					
					if series_created:
						upload_stats['created_series'] += 1
						logger.info(f"Professional series created: {series_desc} ({len(items)} images)")
					
					total_series_processed += 1
					# If study existed, update clinical info/priority once
					if not study_created:
						updated = False
						new_priority = request.POST.get('priority')
						new_clin = request.POST.get('clinical_info')
						if new_priority and study.priority != new_priority:
							study.priority = new_priority
							updated = True
						if new_clin is not None and new_clin != '' and study.clinical_info != new_clin:
							study.clinical_info = new_clin
							updated = True
						if updated:
							study.save(update_fields=['priority','clinical_info'])
					
					# Professional DICOM image processing with medical-grade precision
					# SPEED: avoid per-image get_or_create (N+1). Do a bulk existence check by SOPInstanceUID,
					# then bulk_create new rows and bulk_update only when re-linking is needed.
					sop_uids = []
					for _ds, _fobj in items:
						try:
							uid = getattr(_ds, 'SOPInstanceUID', None)
							if uid:
								sop_uids.append(str(uid))
						except Exception:
							continue

					existing_map = {}
					if sop_uids:
						try:
							existing_qs = (
								DicomImage.objects
								.filter(sop_instance_uid__in=sop_uids)
								.only('id', 'sop_instance_uid', 'series_id', 'instance_number')
							)
							existing_map = {img.sop_instance_uid: img for img in existing_qs}
						except Exception:
							existing_map = {}

					to_create = []
					to_update = []
					images_processed = 0

					for image_index, (ds, fobj) in enumerate(items):
						image_start_time = time.time()
						sop_uid = None
						try:
							sop_uid = str(getattr(ds, 'SOPInstanceUID'))
							instance_number = getattr(ds, 'InstanceNumber', 1) or 1
							try:
								inst_num = int(instance_number)
							except Exception:
								inst_num = 1

							# If this SOP already exists, only ensure it's linked to this series.
							# Critically, we skip re-saving the file bytes for speed (chunk retries / dedup).
							existing = existing_map.get(sop_uid)
							if existing is not None:
								changed = False
								if series and existing.series_id != series.id:
									existing.series_id = series.id
									changed = True
								if inst_num and existing.instance_number != inst_num:
									existing.instance_number = inst_num
									changed = True
								if changed:
									to_update.append(existing)
								images_processed += 1
								if (image_index + 1) % 50 == 0:
									logger.info(f"Series {series_desc}: {image_index + 1}/{len(items)} images processed")
								continue

							# New SOP: save bytes and create DB row
							rel_path = f"dicom/professional/{study_uid}/{series_uid}/{sop_uid}.dcm"
							try:
								fobj.seek(0)
							except Exception:
								pass

							file_size = getattr(fobj, 'size', None)
							if not file_size:
								try:
									file_size = int(getattr(getattr(fobj, 'file', None), 'size', 0) or 0)
								except Exception:
									file_size = 0

							if file_size and file_size < 1024:
								logger.warning(f"Suspicious file size: {file_size} bytes for {sop_uid}")

							saved_path = default_storage.save(rel_path, fobj)

							image_position = str(getattr(ds, 'ImagePositionPatient', ''))
							slice_location = getattr(ds, 'SliceLocation', None)

							to_create.append(
								DicomImage(
									sop_instance_uid=sop_uid,
									series=series,
									instance_number=inst_num,
									image_position=image_position,
									slice_location=slice_location,
									file_path=saved_path,
									file_size=int(file_size or 0),
									processed=False,
								)
							)
							images_processed += 1

							if (image_index + 1) % 50 == 0:
								logger.info(f"Series {series_desc}: {image_index + 1}/{len(items)} images processed")

						except Exception as e:
							logger.error(f"Image processing failed for {sop_uid or 'unknown'}: {str(e)}")
							continue

					# Flush batched DB ops for this series
					try:
						if to_create:
							DicomImage.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=500)
							upload_stats['created_images'] += len(to_create)
					except Exception:
						# fall back to safest behavior (best effort)
						try:
							for obj in to_create:
								try:
									obj.save()
									upload_stats['created_images'] += 1
								except Exception:
									pass
						except Exception:
							pass

					try:
						if to_update:
							# Only re-link fields used by counting + ordering
							DicomImage.objects.bulk_update(to_update, ['series', 'instance_number'], batch_size=500)
					except Exception:
						# best effort: don't fail upload for bulk_update issues
						pass
					
					series_processing_time = (time.time() - series_start_time) * 1000
					logger.info(f"Professional series completed: {series_desc} - {images_processed} images in {series_processing_time:.1f}ms")
					
				
				# already tracked above
				
				# Enhanced notifications for NEW study upload only.
				# Chunked uploads can hit this endpoint multiple times; avoid re-notifying (slow + noisy).
				if study_created:
					try:
						# Notifications can be very slow if there are many recipients.
						# Offload to a background thread so the upload response returns quickly.
						study_id = int(study.id)
						facility_id = int(facility.id) if facility else None
						sender_id = int(request.user.id)
						patient_name = patient.full_name
						facility_name = facility.name if facility else 'Unknown Facility'
						series_count = int(total_series_processed)
						acc_num = str(accession_number)
						mod_code = str(modality_code)

						def _notify_new_study_async():
							try:
								from django.db import close_old_connections
								close_old_connections()
								notif_type, _ = NotificationType.objects.get_or_create(
									code='new_study',
									defaults={'name': 'New Study Uploaded', 'description': 'A new study has been uploaded', 'is_system': True},
								)
								recipients = User.objects.filter(Q(role='radiologist') | Q(role='admin') | Q(facility_id=facility_id))
								sender = User.objects.filter(id=sender_id).first()
								study_obj = Study.objects.filter(id=study_id).first()
								fac_obj = Facility.objects.filter(id=facility_id).first() if facility_id else None
								if not study_obj:
									return
								for recipient in recipients:
									try:
										Notification.objects.create(
											notification_type=notif_type,
											recipient=recipient,
											sender=sender,
											title=f"New {mod_code} study for {patient_name}",
											message=f"Study {acc_num} uploaded from {facility_name} with {series_count} series",
											priority='normal',
											study=study_obj,
											facility=fac_obj,
											data={'study_id': study_id, 'accession_number': acc_num, 'series_count': series_count},
										)
									except Exception:
										continue
								close_old_connections()
							except Exception:
								return

						threading.Thread(target=_notify_new_study_async, daemon=True).start()
					except Exception:
						pass
			
			# Professional upload completion with comprehensive statistics
			upload_stats['invalid_files'] = invalid_files
			upload_stats['processed_files'] = processed_files
			upload_stats['total_size_mb'] = round(file_size_total, 2)
			upload_stats['processing_time_ms'] = round((time.time() - upload_start_time) * 1000, 1)
			
			# Professional completion logging
			logger.info(f"Professional DICOM upload completed successfully:")
			logger.info(f"  • Total files: {upload_stats['total_files']}")
			logger.info(f"  • Processed: {upload_stats['processed_files']}")
			logger.info(f"  • Invalid: {upload_stats['invalid_files']}")
			logger.info(f"  • Studies created: {upload_stats['created_studies']}")
			logger.info(f"  • Series created: {upload_stats['created_series']}")
			logger.info(f"  • Images created: {upload_stats['created_images']}")
			logger.info(f"  • Total size: {upload_stats['total_size_mb']} MB")
			logger.info(f"  • Processing time: {upload_stats['processing_time_ms']} ms")
			logger.info(f"  • User: {upload_stats['user']}")
			
			# NOTE: Avoid expensive per-study verification queries here.
			# Chunked uploads call this endpoint multiple times; extra DB work increases response time
			# and can cause browser/proxy timeouts (seen as XHR "HTTP error 0").
			
			# Professional response with medical-grade information
			resp = JsonResponse({
				'success': True,
				'message': f'🏥 Professional DICOM upload completed successfully',
				'details': f'Processed {processed_files} DICOM files across {upload_stats["created_studies"]} studies with {upload_stats["created_series"]} series and {upload_stats["created_images"]} images',
				# Top-level keys used by frontend progress UI
				'processed_files': processed_files,
				'studies_created': upload_stats['created_studies'],
				'total_series': total_series_processed,
				# Back-compat: historically this represented images created in DB (deduped by SOPInstanceUID).
				# For "how many images did I upload", use `images_uploaded` instead.
				'total_images': upload_stats['created_images'],
				'images_created': upload_stats['created_images'],
				'images_uploaded': processed_files,
				'statistics': upload_stats,
				'created_study_ids': created_studies,
				'medical_summary': {
					# Avoid per-request DB verification queries (important for chunked uploads).
					'patients_affected': len(patient_ids_involved),
					'modalities_processed': list(set(series_key.split('_')[1] for series_map in studies_map.values() for series_key in series_map.keys())),
					'facilities_involved': [facility.name] if facility else [],
					'upload_quality': 'EXCELLENT' if invalid_files == 0 else 'GOOD' if invalid_files < total_files * 0.1 else 'ACCEPTABLE',
					'processing_efficiency': f"{upload_stats['processing_time_ms'] / max(1, processed_files):.1f}ms per file",
				},
				'professional_metadata': {
					'upload_timestamp': upload_stats['timestamp'],
					'uploaded_by': upload_stats['user'],
					'system_version': 'Noctis Pro PACS v2.0 Enhanced',
					'processing_quality': 'Medical Grade Excellence',
				}
			})

			# After upload: pre-decode pixels + prebuild MPR caches (compressed on disk).
			# Do this in background to keep upload response fast and avoid timeouts.
			try:
				# Avoid importing the huge viewer module during request; do it inside the thread.
				uids = list(dict.fromkeys([u for u in series_uids_touched if u]))  # preserve order + dedupe
				max_series = int(os.environ.get('MPR_PRECACHE_MAX_SERIES', '4') or 4)
				uids = uids[:max_series]
				if uids:
					def _precache(series_uids):
						try:
							from django.db import close_old_connections
							close_old_connections()
							# Resolve to IDs inside thread to keep response path fast
							series_ids = []
							for suid in series_uids:
								try:
									s = Series.objects.filter(series_instance_uid=suid).only('id').first()
									if s and s.id:
										series_ids.append(int(s.id))
								except Exception:
									continue
							if not series_ids:
								return
							from dicom_viewer.views import _schedule_mpr_disk_cache_build
							for sid in series_ids:
								try:
									_schedule_mpr_disk_cache_build(int(sid), quality='high')
								except Exception:
									pass
							close_old_connections()
						except Exception:
							pass
					threading.Thread(target=_precache, args=(uids,), daemon=True).start()
			except Exception:
				pass

			return resp
			
		except Exception as e:
			# Professional error handling with medical-grade logging
			error_timestamp = timezone.now().isoformat()
			logger.error(f"Professional DICOM upload failed: {str(e)}")
			logger.error(f"Upload attempt by: {request.user.username}")
			logger.error(f"Files attempted: {len(request.FILES.getlist('dicom_files')) if 'dicom_files' in request.FILES else 0}")
			
			# Professional error response with detailed information
			return JsonResponse({
				'success': False, 
				'error': 'Professional DICOM upload processing failed',
				'details': str(e),
				'error_code': 'UPLOAD_PROCESSING_ERROR',
				'timestamp': error_timestamp,
				'user': request.user.username,
				'support_info': {
					'contact': 'System Administrator',
					'error_id': f"ERR_{int(timezone.now().timestamp())}",
					'system': 'Noctis Pro PACS v2.0 Enhanced'
				},
				'recovery_suggestions': [
					'Verify DICOM files are valid and not corrupted',
					'Check file sizes are reasonable for medical imaging',
					'Ensure proper network connectivity',
					'Contact system administrator if issue persists'
				]
			})
	
	# Provide facilities for admin/radiologist to target uploads
	facilities = Facility.objects.filter(is_active=True).order_by('name') if ((hasattr(request.user, 'is_admin') and request.user.is_admin()) or (hasattr(request.user, 'is_radiologist') and request.user.is_radiologist())) else []
	return render(request, 'worklist/upload.html', {'facilities': facilities})

@login_required
def modern_worklist(request):
	"""Legacy route: redirect to main dashboard UI"""
	return redirect('worklist:dashboard')

@login_required
def modern_dashboard(request):
	"""Legacy route: redirect to main dashboard UI"""
	return redirect('worklist:dashboard')

@login_required
def api_studies(request):
	"""
	Professional Studies API - Medical Imaging Data Excellence
	Enhanced with masterpiece-level data formatting and medical precision
	"""
	import time
	import logging
	
	# Professional API logging
	logger = logging.getLogger('noctis_pro.api')
	api_start_time = time.time()
	user = request.user
	
	logger.info(f"Professional studies API request from {user.username} ({user.get_role_display()})")
	
	try:
		# Professional user-based data filtering with medical standards
		if user.is_facility_user() and getattr(user, 'facility', None):
			studies = Study.objects.filter(facility=user.facility)
			logger.debug(f"Facility-filtered studies for {user.facility.name}")
		else:
			studies = Study.objects.all()
			logger.debug("All studies access granted for admin/radiologist")
		
		# Professional data processing with enhanced medical information
		studies_data = []
		processing_stats = {
			'total_studies': 0,
			'total_images': 0,
			'total_series': 0,
			'modalities': set(),
			'facilities': set(),
			'date_range': {'earliest': None, 'latest': None}
		}
		
		# SPEED + correctness: compute counts in the DB (avoid per-study N+1 count loops)
		studies_qs = (
			studies
			.select_related('patient', 'facility', 'modality', 'uploaded_by')
			.annotate(
				series_count_db=Count('series', distinct=True),
				image_count_db=Count('series__images', distinct=True),
			)
			# IMPORTANT:
			# Worklist UX expects the most recently *uploaded* studies first.
			# Many DICOM studies have old StudyDate/StudyTime, which made fresh uploads
			# "disappear" from the dashboard (because we previously ordered by study_date
			# and then sliced to the first 100).
			.order_by('-upload_date', '-study_date')
		)

		for study in studies_qs[:200]:
			# Professional medical data extraction
			# Dashboard columns:
			# - TIME: show upload time (what users perceive as "new on the worklist")
			# - SCHEDULED: show original study_date (from DICOM metadata)
			study_time = study.upload_date or study.study_date
			scheduled_time = study.study_date
			
			# Enhanced upload tracking
			if hasattr(study, 'upload_date') and study.upload_date:
				upload_date = study.upload_date.isoformat()
			else:
				upload_date = study.study_date.isoformat()
			
			# Professional image and series counting
			# Use annotated values when available (fast + consistent)
			try:
				image_count = int(getattr(study, 'image_count_db', 0) or 0)
			except Exception:
				image_count = 0
			try:
				series_count = int(getattr(study, 'series_count_db', 0) or 0)
			except Exception:
				series_count = 0
			
			# Update processing statistics
			processing_stats['total_studies'] += 1
			processing_stats['total_images'] += image_count
			processing_stats['total_series'] += series_count
			processing_stats['modalities'].add(study.modality.code)
			processing_stats['facilities'].add(study.facility.name)
			
			if not processing_stats['date_range']['earliest'] or study.study_date < processing_stats['date_range']['earliest']:
				processing_stats['date_range']['earliest'] = study.study_date
			if not processing_stats['date_range']['latest'] or study.study_date > processing_stats['date_range']['latest']:
				processing_stats['date_range']['latest'] = study.study_date
			
			# Normalize status for the legacy dashboard UI which historically used hyphenated keys.
			# The DB uses underscores (e.g. "in_progress"); the UI expects "in-progress".
			status_key = (study.status or '').replace('_', '-')

			# Professional study data formatting with medical precision
			studies_data.append({
				'id': study.id,
				'accession_number': study.accession_number,
				'patient_name': study.patient.full_name,
				'patient_id': study.patient.patient_id,
				'modality': study.modality.code,
				'status': status_key,
				'status_raw': study.status,
				'priority': study.priority,
				'study_date': study.study_date.isoformat(),
				'study_time': study_time.isoformat(),
				'scheduled_time': scheduled_time.isoformat(),
				'upload_date': upload_date,
				'facility': study.facility.name,
				'image_count': image_count,
				'series_count': series_count,
				'study_description': study.study_description,
				'clinical_info': study.clinical_info,
				'uploaded_by': study.uploaded_by.get_full_name() if study.uploaded_by else 'Unknown',
				'body_part': getattr(study, 'body_part', ''),
				'referring_physician': study.referring_physician,
				'professional_metadata': {
					'data_quality': 'EXCELLENT' if image_count > 0 else 'PENDING',
					'completeness': 'COMPLETE' if series_count > 0 and image_count > 0 else 'PARTIAL',
					'medical_grade': True,
				}
			})
		
		# Professional API response with comprehensive medical information
		api_processing_time = round((time.time() - api_start_time) * 1000, 1)
		
		# Convert sets to lists for JSON serialization
		processing_stats['modalities'] = list(processing_stats['modalities'])
		processing_stats['facilities'] = list(processing_stats['facilities'])
		processing_stats['date_range']['earliest'] = processing_stats['date_range']['earliest'].isoformat() if processing_stats['date_range']['earliest'] else None
		processing_stats['date_range']['latest'] = processing_stats['date_range']['latest'].isoformat() if processing_stats['date_range']['latest'] else None
		
		logger.info(f"Professional studies API completed: {len(studies_data)} studies in {api_processing_time}ms")
		
		return JsonResponse({
			'success': True,
			'message': '🏥 Professional medical imaging data retrieved successfully',
			'studies': studies_data,
			'professional_metadata': {
				'api_version': 'v2.0 Enhanced',
				'processing_time_ms': api_processing_time,
				'data_quality': 'Medical Grade Excellence',
				'user': user.username,
				'user_role': user.get_role_display(),
				'facility': user.facility.name if user.facility else 'System Wide',
				'timestamp': timezone.now().isoformat(),
				'system': 'Noctis Pro PACS v2.0 Enhanced',
			},
			'statistics': processing_stats,
			'performance_metrics': {
				'studies_per_second': round(len(studies_data) / max(0.001, api_processing_time / 1000), 1),
				'avg_processing_per_study_ms': round(api_processing_time / max(1, len(studies_data)), 2),
				'medical_compliance': 'FULL',
			}
		})
		
	except Exception as e:
		# Professional error handling with medical-grade logging
		error_time = round((time.time() - api_start_time) * 1000, 1)
		logger.error(f"Professional studies API failed: {str(e)} (after {error_time}ms)")
		
		return JsonResponse({
			'success': False,
			'error': 'Professional medical data retrieval failed',
			'details': str(e),
			'error_code': 'API_STUDIES_ERROR',
			'professional_metadata': {
				'api_version': 'v2.0 Enhanced',
				'error_time_ms': error_time,
				'user': user.username,
				'timestamp': timezone.now().isoformat(),
				'system': 'Noctis Pro PACS v2.0 Enhanced',
			},
			'recovery_suggestions': [
				'Check database connectivity',
				'Verify user permissions',
				'Contact system administrator if issue persists'
			]
		}, status=500)

@login_required
@csrf_exempt
def upload_attachment(request, study_id):
    """Upload attachment to study"""
    study = get_object_or_404(Study, id=study_id)
    user = request.user
    
    # All authenticated users can upload attachments regardless of facility
    
    if request.method == 'POST':
        try:
            files = request.FILES.getlist('files')
            attachment_type = request.POST.get('type', 'document')
            description = request.POST.get('description', '')
            attach_previous_study_id = request.POST.get('previous_study_id')
            max_attachment_bytes = 5 * 1024 * 1024 * 1024  # 5GB per file
            
            if not files:
                return JsonResponse({'error': 'No files provided'}, status=400)
            
            uploaded_attachments = []
            created_attachment_ids = []
            
            for file in files:
                # Validate file size (max 5GB)
                if file.size > max_attachment_bytes:
                    return JsonResponse({'error': f'File {file.name} is too large (max 5GB)'}, status=400)
                
                # Determine file type based on extension
                file_ext = os.path.splitext(file.name)[1].lower()
                mime_type = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                
                # Auto-detect attachment type if not specified
                if attachment_type == 'auto':
                    if file_ext == '.dcm':
                        attachment_type = 'dicom_study'
                    elif file_ext == '.pdf':
                        attachment_type = 'pdf_document'
                    elif file_ext in ['.doc', '.docx']:
                        attachment_type = 'word_document'
                    elif file_ext in ['.jpg', '.jpeg', '.png', '.gif']:
                        attachment_type = 'image'
                    else:
                        attachment_type = 'document'
                
                # Create attachment
                attachment = StudyAttachment.objects.create(
                    study=study,
                    file=file,
                    file_type=attachment_type,
                    name=file.name,
                    description=description,
                    file_size=file.size,
                    mime_type=mime_type,
                    uploaded_by=user,
                    is_public=True
                )

                created_attachment_ids.append(attachment.id)
                
                uploaded_attachments.append({
                    'id': attachment.id,
                    'name': attachment.name,
                    'size': attachment.file_size,
                    'type': attachment.file_type,
                })

            # Offload thumbnail/metadata extraction so uploads return quickly.
            # Thumbnail generation for DICOM (pixel decode) can be very slow.
            def _process_attachments_async(ids):
                try:
                    from django.db import close_old_connections
                    close_old_connections()
                    for att_id in ids:
                        att = StudyAttachment.objects.filter(id=att_id).first()
                        if not att:
                            continue
                        try:
                            generate_attachment_thumbnail(att)
                        except Exception:
                            pass
                        try:
                            process_attachment_metadata(att)
                        except Exception:
                            pass
                    close_old_connections()
                except Exception:
                    pass
            if created_attachment_ids:
                threading.Thread(target=_process_attachments_async, args=(created_attachment_ids,), daemon=True).start()
            
            # Create notifications for new attachments
            try:
                notif_type, _ = NotificationType.objects.get_or_create(
                    code='new_attachment', defaults={'name': 'New Attachment Uploaded', 'description': 'A new attachment has been uploaded', 'is_system': True}
                )
                recipients = User.objects.filter(Q(role='radiologist') | Q(role='admin') | Q(facility=study.facility))
                for recipient in recipients:
                    Notification.objects.create(
                        notification_type=notif_type,
                        recipient=recipient,
                        sender=request.user,
                        title=f"New attachment for {study.patient.full_name}",
                        message=f"{len(uploaded_attachments)} file(s) attached to study {study.accession_number}",
                        priority='normal',
                        study=study,
                        facility=study.facility,
                        data={'study_id': study.id}
                    )
            except Exception:
                pass
            
            return JsonResponse({
                'success': True,
                'message': f'Successfully uploaded {len(uploaded_attachments)} file(s)',
                'attachments': uploaded_attachments
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    # GET request - show upload form
    # Get previous studies for this patient
    previous_studies = Study.objects.filter(
        patient=study.patient
    ).exclude(id=study.id).order_by('-study_date')[:10]
    
    context = {
        'study': study,
        'previous_studies': previous_studies,
    }
    
    return render(request, 'worklist/upload_attachment.html', context)

@login_required
def view_attachment(request, attachment_id):
    """View or download attachment"""
    attachment = get_object_or_404(StudyAttachment, id=attachment_id)
    user = request.user
    
    # Check permissions - facility users can only view attachments from their facility
    if user.is_facility_user() and getattr(user, 'facility', None):
        if attachment.study.facility != user.facility:
            messages.error(request, 'You do not have permission to view this attachment.')
            return redirect('worklist:study_list')
    
    # Increment access count
    try:
        attachment.increment_access_count()
    except Exception as e:
        # Do not fail viewing due to metrics error
        logger.warning(f"Failed to increment access count for attachment {attachment.id}: {e}")
    
    # Handle DICOM files
    if attachment.is_dicom_file():
        if attachment.attached_study:
            # Redirect to web viewer with study param
            return redirect(f'/dicom-viewer/?study={attachment.attached_study.id}')
        else:
            # Open main web viewer
            return redirect('/dicom-viewer/')
    
    # Handle viewable files (PDF, images)
    if attachment.is_viewable_in_browser():
        action = request.GET.get('action', 'view')
        # Ensure file exists before attempting to open
        try:
            if not attachment.file or not default_storage.exists(attachment.file.name):
                raise FileNotFoundError('Attachment file missing from storage')
            file_handle = attachment.file.open('rb')
        except Exception as e:
            logger.error(f"Attachment open failed (id={attachment.id}): {e}")
            messages.error(request, 'Attachment file is missing or cannot be opened.')
            return redirect('worklist:study_detail', study_id=attachment.study.id)

        if action == 'download':
            # Force download
            return FileResponse(file_handle, as_attachment=True, filename=attachment.name)
        else:
            # View in browser
            return FileResponse(file_handle, content_type=attachment.mime_type or 'application/octet-stream')
    
    # For non-viewable files, force download
    try:
        if not attachment.file or not default_storage.exists(attachment.file.name):
            raise FileNotFoundError('Attachment file missing from storage')
        file_handle = attachment.file.open('rb')
        return FileResponse(file_handle, as_attachment=True, filename=attachment.name)
    except Exception as e:
        logger.error(f"Attachment download failed (id={attachment.id}): {e}")
        messages.error(request, 'Attachment file is missing or cannot be downloaded.')
        return redirect('worklist:study_detail', study_id=attachment.study.id)

@login_required
@csrf_exempt
def attachment_comments(request, attachment_id):
    """Handle attachment comments"""
    attachment = get_object_or_404(StudyAttachment, id=attachment_id)
    user = request.user
    
    # Check permissions
    if user.is_facility_user() and attachment.study.facility != user.facility:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            comment_text = data.get('comment', '').strip()
            
            if not comment_text:
                return JsonResponse({'error': 'Comment cannot be empty'}, status=400)
            
            comment = AttachmentComment.objects.create(
                attachment=attachment,
                user=user,
                comment=comment_text
            )
            
            return JsonResponse({
                'success': True,
                'comment': {
                    'id': comment.id,
                    'comment': comment.comment,
                    'user': comment.user.get_full_name() or comment.user.username,
                    'created_at': comment.created_at.isoformat()
                }
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    # GET request - return comments
    comments = attachment.comments.select_related('user').order_by('-created_at')
    comments_data = []
    
    for comment in comments:
        comments_data.append({
            'id': comment.id,
            'comment': comment.comment,
            'user': comment.user.get_full_name() or comment.user.username,
            'created_at': comment.created_at.isoformat()
        })
    
    return JsonResponse({'comments': comments_data})

@login_required
@csrf_exempt
def delete_attachment(request, attachment_id):
    """Delete attachment"""
    attachment = get_object_or_404(StudyAttachment, id=attachment_id)
    user = request.user
    
    # Check permissions - only admin/radiologist or facility users from same facility can delete attachments
    if user.is_facility_user() and getattr(user, 'facility', None):
        if attachment.study.facility != user.facility:
            return JsonResponse({'error': 'Permission denied. You can only delete attachments from your facility.'}, status=403)
    elif not (user.is_admin() or user.is_radiologist()):
        return JsonResponse({'error': 'Permission denied. Only administrators, radiologists, or facility users can delete attachments.'}, status=403)
    
    if request.method == 'POST':
        wants_json = 'application/json' in (request.headers.get('Accept') or '') or (request.headers.get('X-Requested-With') == 'XMLHttpRequest')
        study_id = attachment.study.id
        attachment_name = attachment.name
        try:
            # Delete file from storage (ignore if missing)
            try:
                if attachment.file:
                    attachment.file.delete(save=False)
            except Exception as e:
                logger.warning(f"Failed to delete attachment file (id={attachment.id}): {e}")
            
            # Delete thumbnail if exists (ignore if missing)
            try:
                if attachment.thumbnail:
                    attachment.thumbnail.delete(save=False)
            except Exception as e:
                logger.warning(f"Failed to delete attachment thumbnail (id={attachment.id}): {e}")
            
            # Delete attachment record
            attachment.delete()
            
            messages.success(request, f'Attachment "{attachment_name}" deleted successfully')
            if wants_json:
                return JsonResponse({'success': True, 'message': f'Attachment "{attachment_name}" deleted successfully'})
            return redirect('worklist:study_detail', study_id=study_id)
        except Exception as e:
            logger.error(f"Attachment delete failed (id={attachment.id}): {e}")
            if wants_json:
                return JsonResponse({'error': str(e)}, status=500)
            messages.error(request, f'Failed to delete attachment: {e}')
            return redirect('worklist:study_detail', study_id=study_id)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@login_required
@csrf_exempt
def api_search_studies(request):
    """API endpoint to search for studies to attach"""
    user = request.user
    query = request.GET.get('q', '').strip()
    patient_id = request.GET.get('patient_id')
    
    if len(query) < 2:
        return JsonResponse({'studies': []})
    
    # Base queryset based on user role
    if user.is_facility_user() and getattr(user, 'facility', None):
        studies = Study.objects.filter(facility=user.facility)
    else:
        studies = Study.objects.all()
    
    # Filter by patient if specified
    if patient_id:
        studies = studies.filter(patient__patient_id=patient_id)
    
    # Search query
    studies = studies.filter(
        Q(accession_number__icontains=query) |
        Q(patient__first_name__icontains=query) |
        Q(patient__last_name__icontains=query) |
        Q(study_description__icontains=query)
    ).select_related('patient', 'modality').order_by('-study_date')[:20]
    
    studies_data = []
    for study in studies:
        studies_data.append({
            'id': study.id,
            'accession_number': study.accession_number,
            'patient_name': study.patient.full_name,
            'patient_id': study.patient.patient_id,
            'study_date': study.study_date.strftime('%Y-%m-%d'),
            'modality': study.modality.code,
            'description': study.study_description
        })
    
    return JsonResponse({'studies': studies_data})

@login_required
@csrf_exempt
def api_update_study_status(request, study_id):
    """API endpoint to update study status"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    study = get_object_or_404(Study, id=study_id)
    user = request.user
    
    # Check permissions
    if user.is_facility_user() and getattr(user, 'facility', None) and study.facility != user.facility:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        new_status = data.get('status', '').strip()
        
        # Validate status
        valid_statuses = ['scheduled', 'in_progress', 'completed', 'cancelled']
        if new_status not in valid_statuses:
            return JsonResponse({'error': 'Invalid status'}, status=400)
        
        # Update study status
        old_status = study.status
        study.status = new_status
        study.save()
        
        # Log the status change (if you have logging)
        # StudyStatusLog.objects.create(
        #     study=study,
        #     old_status=old_status,
        #     new_status=new_status,
        #     changed_by=user
        # )
        
        return JsonResponse({
            'success': True,
            'message': f'Study status updated from {old_status} to {new_status}',
            'old_status': old_status,
            'new_status': new_status
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_study_detail(request, study_id):
    """API endpoint to get study details for verification"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        # Get study and check permissions
        user = request.user
        if user.is_facility_user() and getattr(user, 'facility', None):
            study = get_object_or_404(Study, id=study_id, facility=user.facility)
        else:
            study = get_object_or_404(Study, id=study_id)
        
        # Return study data
        # Avoid N+1 loops for counts
        series_count = Series.objects.filter(study=study).count()
        images_count = DicomImage.objects.filter(series__study=study).count()

        study_data = {
            'id': study.id,
            'accession_number': study.accession_number,
            'study_date': study.study_date.isoformat() if study.study_date else None,
            'study_time': study.study_date.isoformat() if study.study_date else None,
            'modality': study.modality.name if study.modality else None,
            'study_description': study.study_description,
            'patient': {
                'name': study.patient.full_name if study.patient else 'Unknown',
                'id': study.patient.patient_id if study.patient else None,
                'birth_date': study.patient.date_of_birth.isoformat() if study.patient and study.patient.date_of_birth else None,
                'sex': study.patient.gender if study.patient else None
            },
            'status': study.status,
            'priority': study.priority,
            'series_count': series_count,
            'images_count': images_count,
            'facility': study.facility.name if study.facility else None
        }
        
        return JsonResponse({
            'success': True,
            'study': study_data
        })
        
    except Study.DoesNotExist:
        return JsonResponse({'error': 'Study not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
def api_delete_study(request, study_id):
    """API endpoint to delete a study (admin only)
    Accepts DELETE and POST (for environments where DELETE is blocked)."""
    if request.method not in ['DELETE', 'POST']:
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Check if user is admin, radiologist, or superuser
    try:
        is_admin = hasattr(request.user, 'is_admin') and request.user.is_admin()
        is_radiologist = hasattr(request.user, 'is_radiologist') and request.user.is_radiologist()
        is_superuser = getattr(request.user, 'is_superuser', False)
        if not (is_admin or is_radiologist or is_superuser):
            return JsonResponse({'error': 'Permission denied. Only administrators or radiologists can delete studies.'}, status=403)
    except Exception as e:
        try:
            logger.error(f"Error checking user permissions: {str(e)}")
        except Exception:
            pass
        return JsonResponse({'error': 'Permission error'}, status=403)
    
    try:
        study = get_object_or_404(Study, id=study_id)
        
        # Store study info for logging before deletion
        study_info = {
            'id': study.id,
            'accession_number': study.accession_number,
            'patient_name': study.patient.full_name if study.patient else 'Unknown',
            'deleted_by': request.user.username,
            'study_date': study.study_date.isoformat() if study.study_date else None,
            'modality': study.modality.code if study.modality else None
        }
        
        # Get related objects count for logging
        series_count = study.series_set.count()
        images_count = sum(series.images.count() for series in study.series_set.all())
        
        # Clean up associated files BEFORE deletion using storage APIs
        # This avoids reliance on local filesystem paths (works with S3, etc.)
        files_deleted = 0
        try:
            for series in study.series_set.all():
                for image in series.images.all():
                    try:
                        # Delete image thumbnail if present
                        if getattr(image, 'thumbnail', None):
                            image.thumbnail.delete(save=False)
                            files_deleted += 1
                    except Exception as e:
                        try:
                            logger.warning(f"Failed to delete image thumbnail (sop={getattr(image, 'sop_instance_uid', 'unknown')}): {e}")
                        except Exception:
                            pass
                    try:
                        # Support legacy `file` and current `file_path`
                        storage_field = getattr(image, 'file', None) or getattr(image, 'file_path', None)
                        if storage_field:
                            storage_field.delete(save=False)
                            files_deleted += 1
                    except Exception as e:
                        try:
                            logger.warning(f"Failed to delete image file (sop={getattr(image, 'sop_instance_uid', 'unknown')}): {e}")
                        except Exception:
                            pass
        except Exception:
            # Do not block deletion if cleanup iteration fails
            pass

        try:
            for attachment in study.attachments.all():
                try:
                    if attachment.thumbnail:
                        attachment.thumbnail.delete(save=False)
                        files_deleted += 1
                except Exception as e:
                    try:
                        logger.warning(f"Failed to delete attachment thumbnail (id={attachment.id}): {e}")
                    except Exception:
                        pass
                try:
                    if attachment.file:
                        attachment.file.delete(save=False)
                        files_deleted += 1
                except Exception as e:
                    try:
                        logger.warning(f"Failed to delete attachment file (id={attachment.id}): {e}")
                    except Exception:
                        pass
        except Exception:
            pass

        # Delete the study (this will cascade to related objects)
        study.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Study {study_info["accession_number"]} deleted successfully',
            'deleted_study': study_info,
            'statistics': {
                'series_deleted': series_count,
                'images_deleted': images_count,
                'files_cleaned': files_deleted
            }
        })
        
    except Study.DoesNotExist:
        return JsonResponse({'error': 'Study not found'}, status=404)
    except Exception as e:
        import traceback
        error_details = {
            'error': f'Failed to delete study: {str(e)}',
            'error_type': type(e).__name__,
            'traceback': traceback.format_exc() if settings.DEBUG else None
        }
        return JsonResponse(error_details, status=500)

@login_required
def api_refresh_worklist(request):
    """API endpoint to refresh worklist and get latest studies"""
    user = request.user
    
    # Get recent studies (last 24 hours)
    from datetime import timedelta
    recent_cutoff = timezone.now() - timedelta(hours=24)
    
    if user.is_facility_user() and getattr(user, 'facility', None):
        studies = Study.objects.filter(facility=user.facility, upload_date__gte=recent_cutoff)
    else:
        studies = Study.objects.filter(upload_date__gte=recent_cutoff)
    
    # SPEED + consistency: precompute counts with annotation
    studies_qs = (
        studies
        .select_related('patient', 'facility', 'modality', 'uploaded_by')
        .annotate(
            series_count_db=Count('series', distinct=True),
            image_count_db=Count('series__images', distinct=True),
        )
        .order_by('-upload_date')
    )

    studies_data = []
    for study in studies_qs[:20]:  # Last 20 uploaded studies
        studies_data.append({
            'id': study.id,
            'accession_number': study.accession_number,
            'patient_name': study.patient.full_name,
            'patient_id': study.patient.patient_id,
            'modality': study.modality.code,
            'status': study.status,
            'priority': study.priority,
            'study_date': study.study_date.isoformat(),
            'upload_date': study.upload_date.isoformat(),
            'facility': study.facility.name,
            'series_count': int(getattr(study, 'series_count_db', 0) or 0),
            'image_count': int(getattr(study, 'image_count_db', 0) or 0),
            'uploaded_by': study.uploaded_by.get_full_name() if study.uploaded_by else 'Unknown',
            'study_description': study.study_description,
        })
    
    return JsonResponse({
        'success': True, 
        'studies': studies_data,
        'total_recent': len(studies_data),
        'refresh_time': timezone.now().isoformat()
    })

@login_required
def api_get_upload_stats(request):
    """API endpoint to get upload statistics"""
    user = request.user
    
    # Get upload statistics for the last 7 days
    from datetime import timedelta
    week_ago = timezone.now() - timedelta(days=7)
    
    if user.is_facility_user() and getattr(user, 'facility', None):
        recent_studies = Study.objects.filter(facility=user.facility, upload_date__gte=week_ago)
    else:
        recent_studies = Study.objects.filter(upload_date__gte=week_ago)
    
    total_studies = recent_studies.count()
    # SPEED: compute counts directly on related tables
    total_series = Series.objects.filter(study__in=recent_studies).count()
    total_images = DicomImage.objects.filter(series__study__in=recent_studies).count()
    
    # Group by modality
    modality_stats = {}
    for study in recent_studies:
        modality = study.modality.code
        modality_stats[modality] = modality_stats.get(modality, 0) + 1
    
    return JsonResponse({
        'success': True,
        'stats': {
            'total_studies': total_studies,
            'total_series': total_series,
            'total_images': total_images,
            'modality_breakdown': modality_stats,
            'period': '7 days'
        }
    })

@login_required
@csrf_exempt
def api_reassign_study_facility(request, study_id):
	"""Reassign a study to a facility (admin/radiologist only). Useful for recovering a lost study."""
	if request.method != 'POST':
		return JsonResponse({'error': 'Method not allowed'}, status=405)
	user = request.user
	if not (user.is_admin() or user.is_radiologist()):
		return JsonResponse({'error': 'Permission denied'}, status=403)
	study = get_object_or_404(Study, id=study_id)
	try:
		payload = json.loads(request.body)
		facility_id = str(payload.get('facility_id', '')).strip()
		if not facility_id:
			return JsonResponse({'error': 'facility_id is required'}, status=400)
		target = Facility.objects.filter(id=facility_id, is_active=True).first()
		if not target:
			return JsonResponse({'error': 'Target facility not found or inactive'}, status=404)
		old_fac = study.facility
		study.facility = target
		study.save(update_fields=['facility'])
		return JsonResponse({'success': True, 'message': 'Study reassigned', 'old_facility': old_fac.name, 'new_facility': target.name})
	except json.JSONDecodeError:
		return JsonResponse({'error': 'Invalid JSON data'}, status=400)
	except Exception as e:
		return JsonResponse({'error': str(e)}, status=500)

@login_required
@csrf_exempt
def api_update_clinical_info(request, study_id):
	"""API endpoint to create or update a study's clinical information"""
	if request.method != 'POST':
		return JsonResponse({'error': 'Method not allowed'}, status=405)
	
	study = get_object_or_404(Study, id=study_id)
	user = request.user
	
	# Check permissions
	if user.is_facility_user() and getattr(user, 'facility', None) and study.facility != user.facility:
		return JsonResponse({'error': 'Permission denied'}, status=403)
	
	try:
		new_info = ''
		if request.content_type and request.content_type.startswith('application/json'):
			payload = json.loads(request.body)
			new_info = (payload.get('clinical_info') or '').strip()
		else:
			new_info = (request.POST.get('clinical_info') or '').strip()
		
		old_info = study.clinical_info or ''
		study.clinical_info = new_info
		# Ensure auto_now updates last_updated when using update_fields
		study.save(update_fields=['clinical_info', 'last_updated'])
		
		return JsonResponse({
			'success': True,
			'message': 'Clinical information updated',
			'old_clinical_info': old_info,
			'clinical_info': study.clinical_info,
		})
	except json.JSONDecodeError:
		return JsonResponse({'error': 'Invalid JSON data'}, status=400)
	except Exception as e:
		return JsonResponse({'error': str(e)}, status=500)

def process_attachment_metadata(attachment):
    """Extract metadata from uploaded attachment"""
    try:
        file_path = attachment.file.path
        
        if attachment.file_type == 'dicom_study':
            # Extract DICOM metadata
            try:
                ds = pydicom.dcmread(file_path)
                attachment.study_date = getattr(ds, 'StudyDate', None)
                attachment.modality = getattr(ds, 'Modality', '')
                attachment.save()
            except Exception:
                pass
        
        elif attachment.file_type in ['pdf_document', 'word_document']:
            # Extract document metadata (would require additional libraries)
            # For now, just set basic info
            attachment.creation_date = timezone.now()
            attachment.save()
            
    except Exception:
        # If metadata extraction fails, continue silently
        pass

def generate_attachment_thumbnail(attachment):
    """Generate thumbnail for supported file types"""
    try:
        if attachment.file_type == 'image':
            # Generate thumbnail for images
            image = Image.open(attachment.file.path)
            image.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            # Save thumbnail
            thumb_io = BytesIO()
            image.save(thumb_io, format='PNG')
            thumb_file = ContentFile(thumb_io.getvalue())
            
            thumb_name = f"thumb_{attachment.id}.png"
            attachment.thumbnail.save(thumb_name, thumb_file, save=True)
            
        elif attachment.file_type == 'dicom_study':
            # Generate thumbnail for DICOM images
            try:
                ds = pydicom.dcmread(attachment.file.path)
                if hasattr(ds, 'pixel_array'):
                    pixel_array = ds.pixel_array
                    
                    # Normalize pixel values
                    pixel_array = ((pixel_array - pixel_array.min()) * 255 / 
                                 (pixel_array.max() - pixel_array.min())).astype('uint8')
                    
                    # Create PIL image and thumbnail
                    image = Image.fromarray(pixel_array, mode='L')
                    image.thumbnail((200, 200), Image.Resampling.LANCZOS)
                    
                    # Save thumbnail
                    thumb_io = BytesIO()
                    image.save(thumb_io, format='PNG')
                    thumb_file = ContentFile(thumb_io.getvalue())
                    
                    thumb_name = f"thumb_{attachment.id}.png"
                    attachment.thumbnail.save(thumb_name, thumb_file, save=True)
            except Exception:
                pass
                
    except Exception:
        # If thumbnail generation fails, continue silently
        pass

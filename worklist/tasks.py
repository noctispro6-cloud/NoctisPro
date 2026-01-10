from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import pydicom
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import Facility, User
from .models import DicomImage, Modality, Patient, Series, Study

logger = logging.getLogger("noctis_pro.upload")


_UID_RE = re.compile(r"^[0-9.]+$")
_MODALITY_CODE_RE = re.compile(r"^[A-Z0-9_]{2,10}$")

_KNOWN_MODALITY_CODES = {
    "CR",
    "CT",
    "MR",
    "US",
    "NM",
    "PT",
    "DX",
    "DR",
    "MG",
    "RF",
    "XA",
    "OT",
    "SC",
    "PR",
    "KO",
    "SR",
    "ECG",
    "EPS",
    "HD",
    "IVUS",
    "OCT",
    "RTIMAGE",
    "RTDOSE",
    "RTPLAN",
    "RTSTRUCT",
    "REG",
    "SEG",
    "IO",
    "ES",
    "SM",
    "TG",
    "OP",
    "XC",
}

_SOP_CLASS_UID_TO_MODALITY = {
    "1.2.840.10008.5.1.4.1.1.2": "CT",  # CT Image Storage
    "1.2.840.10008.5.1.4.1.1.2.1": "CT",  # Enhanced CT Image Storage
    "1.2.840.10008.5.1.4.1.1.4": "MR",  # MR Image Storage
    "1.2.840.10008.5.1.4.1.1.4.1": "MR",  # Enhanced MR Image Storage
    "1.2.840.10008.5.1.4.1.1.1": "CR",  # Computed Radiography Image Storage
    "1.2.840.10008.5.1.4.1.1.1.1": "DX",  # Digital X-Ray Image Storage - for Presentation
    "1.2.840.10008.5.1.4.1.1.1.1.1": "DX",  # Digital X-Ray Image Storage - for Processing
    "1.2.840.10008.5.1.4.1.1.1.2": "DX",  # Digital Mammography X-Ray Image Storage - for Presentation
    "1.2.840.10008.5.1.4.1.1.1.2.1": "DX",  # Digital Mammography X-Ray Image Storage - for Processing
    "1.2.840.10008.5.1.4.1.1.6.1": "US",  # Ultrasound Image Storage
    "1.2.840.10008.5.1.4.1.1.6.2": "US",  # Enhanced US Volume Storage
    "1.2.840.10008.5.1.4.1.1.20": "NM",  # Nuclear Medicine Image Storage
    "1.2.840.10008.5.1.4.1.1.128": "PT",  # PET Image Storage
    "1.2.840.10008.5.1.4.1.1.7": "SC",  # Secondary Capture Image Storage
    "1.2.840.10008.5.1.4.1.1.88.11": "SR",  # Basic Text SR
    "1.2.840.10008.5.1.4.1.1.88.22": "SR",  # Enhanced SR
    "1.2.840.10008.5.1.4.1.1.88.33": "SR",  # Comprehensive SR
}


def _sanitize_session_id(v: str) -> str:
    v = (v or "").strip()
    v = re.sub(r"[^a-zA-Z0-9_-]+", "", v)
    if not v:
        return uuid.uuid4().hex
    return v[:128]


def _infer_modality_from_sop_class(ds) -> str | None:
    try:
        sop = str(getattr(ds, "SOPClassUID", "") or "").strip()
        if not sop:
            try:
                sop = str(getattr(getattr(ds, "file_meta", None), "MediaStorageSOPClassUID", "") or "").strip()
            except Exception:
                sop = ""
        return _SOP_CLASS_UID_TO_MODALITY.get(sop)
    except Exception:
        return None


def _normalize_modality_code(ds) -> str:
    try:
        raw = str(getattr(ds, "Modality", "") or "").strip().upper()
        raw = raw.split()[0] if raw else ""
        if raw and _MODALITY_CODE_RE.match(raw) and raw in _KNOWN_MODALITY_CODES:
            return raw
    except Exception:
        pass

    inferred = _infer_modality_from_sop_class(ds)
    if inferred:
        return inferred
    return "OT"


def _parse_patient_name(ds) -> tuple[str, str]:
    try:
        raw = str(getattr(ds, "PatientName", "") or "").strip()
    except Exception:
        raw = ""

    if not raw or raw.upper().startswith("UNKNOWN"):
        return ("Unknown", "Patient")

    if "^" in raw:
        parts = [p.strip() for p in raw.split("^")]
        family = parts[0] if len(parts) > 0 else ""
        given = parts[1] if len(parts) > 1 else ""
        middle = parts[2] if len(parts) > 2 else ""
        first = " ".join([p for p in (given, middle) if p]).strip() or "Unknown"
        last = family.strip() or "Patient"
        return (first, last)

    if "," in raw:
        last, first = [p.strip() for p in raw.split(",", 1)]
        return (first or "Unknown", last or "Patient")

    parts = [p for p in raw.replace("\t", " ").split(" ") if p]
    if len(parts) == 1:
        return (parts[0], "Patient")
    return (parts[0], " ".join(parts[1:]))


def _looks_like_real_dicom(ds) -> bool:
    try:
        study_uid = str(getattr(ds, "StudyInstanceUID", "") or "").strip()
        series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "").strip()
        sop_class_uid = str(getattr(ds, "SOPClassUID", "") or "").strip()
        if not study_uid or not series_uid:
            return False
        if not _UID_RE.match(study_uid) or not _UID_RE.match(series_uid):
            return False
        if sop_class_uid and not _UID_RE.match(sop_class_uid):
            return False
        return True
    except Exception:
        return False


def _stable_synth_sop_uid_from_path(path: str) -> str:
    """
    Stable SOP-like identifier when SOPInstanceUID is missing.
    (Expensive, but runs in background and preserves idempotency.)
    """
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return f"SYN-SOP-SHA1-{h.hexdigest()}"


def _incoming_dir(session_id: str) -> str:
    return str(Path(settings.MEDIA_ROOT) / "dicom" / "incoming" / session_id)


def _media_abs(rel_path: str) -> str:
    return str(Path(settings.MEDIA_ROOT) / rel_path)


@shared_task(bind=True, acks_late=True)
def process_upload_session(
    self,
    session_id: str,
    user_id: int,
    override_facility_id: str = "",
    assign_to_me: bool = False,
    priority: str = "normal",
    clinical_info: str = "",
) -> dict:
    """
    Background DICOM ingestion:
    - Parse headers
    - Create Patient/Study/Series/DicomImage records
    - Move incoming files to final storage paths under media/dicom/images/
    """
    session_id = _sanitize_session_id(session_id)
    start = time_start = timezone.now()
    src_dir = _incoming_dir(session_id)
    if not os.path.isdir(src_dir):
        return {"success": False, "error": "missing upload session directory", "session_id": session_id}

    try:
        user = User.objects.get(id=user_id)
    except Exception:
        user = None

    # Collect file paths
    paths: list[str] = []
    for root, _dirs, files in os.walk(src_dir):
        for fn in files:
            p = os.path.join(root, fn)
            paths.append(p)

    if not paths:
        return {"success": False, "error": "no files in session", "session_id": session_id}

    studies_map: dict[str, dict[str, list[tuple[dict, str]]]] = {}
    study_meta_map: dict[str, dict] = {}
    series_meta_map: dict[str, dict[str, dict]] = {}
    invalid_files = 0
    processed_files = 0
    series_uids_touched: set[str] = set()
    patient_ids_involved: set[int] = set()

    for p in paths:
        try:
            # Parse header (fast path)
            ds = None
            try:
                ds = pydicom.dcmread(p, stop_before_pixels=True, force=False)
            except Exception:
                try:
                    ds = pydicom.dcmread(p, stop_before_pixels=True, force=True)
                except Exception:
                    ds = None

            if ds is None or (not _looks_like_real_dicom(ds)):
                invalid_files += 1
                continue

            # Skip DICOMDIR / directory record SOP class
            try:
                if str(getattr(ds, "SOPClassUID", "")).strip() == "1.2.840.10008.1.3.10":
                    invalid_files += 1
                    continue
            except Exception:
                pass

            study_uid = getattr(ds, "StudyInstanceUID", None)
            series_uid = getattr(ds, "SeriesInstanceUID", None)
            sop_uid = getattr(ds, "SOPInstanceUID", None)

            if not study_uid or not series_uid:
                invalid_files += 1
                continue

            modality = _normalize_modality_code(ds)
            try:
                setattr(ds, "Modality", modality)
            except Exception:
                pass

            if not sop_uid:
                sop_uid = _stable_synth_sop_uid_from_path(p)
                try:
                    setattr(ds, "SOPInstanceUID", sop_uid)
                except Exception:
                    pass

            study_uid = str(study_uid).strip()
            series_uid = str(series_uid).strip()
            sop_uid = str(sop_uid).strip()
            series_key = f"{series_uid}_{modality}"

            if study_uid not in study_meta_map:
                first_name, last_name = _parse_patient_name(ds)
                facility_candidates: list[str] = []
                try:
                    for attr in (
                        "ScheduledStationAETitle",
                        "StationAETitle",
                        "InstitutionName",
                        "InstitutionalDepartmentName",
                    ):
                        val = str(getattr(ds, attr, "") or "").strip()
                        if val:
                            facility_candidates.append(val)
                except Exception:
                    facility_candidates = []

                study_meta_map[study_uid] = {
                    "patient_id": getattr(ds, "PatientID", None),
                    "first_name": first_name,
                    "last_name": last_name,
                    "patient_birth_date": getattr(ds, "PatientBirthDate", None),
                    "patient_sex": getattr(ds, "PatientSex", None),
                    "accession_number": getattr(ds, "AccessionNumber", None),
                    "study_description": getattr(ds, "StudyDescription", None),
                    "referring_physician": getattr(ds, "ReferringPhysicianName", None),
                    "study_date": getattr(ds, "StudyDate", None),
                    "study_time": getattr(ds, "StudyTime", None),
                    "body_part": getattr(ds, "BodyPartExamined", None),
                    "default_modality": modality,
                    "facility_candidates": facility_candidates,
                }

            series_meta_map.setdefault(study_uid, {})
            if series_key not in series_meta_map[study_uid]:
                try:
                    series_number = int(getattr(ds, "SeriesNumber", 1) or 1)
                except Exception:
                    series_number = 1
                series_desc = getattr(ds, "SeriesDescription", None) or f"{modality} Series {series_number}"
                series_meta_map[study_uid][series_key] = {
                    "series_instance_uid": series_uid,
                    "modality": modality,
                    "series_number": series_number,
                    "series_description": str(series_desc),
                    "slice_thickness": getattr(ds, "SliceThickness", None),
                    "pixel_spacing": str(getattr(ds, "PixelSpacing", "") or ""),
                    "image_orientation": str(getattr(ds, "ImageOrientationPatient", "") or ""),
                    "body_part": str(getattr(ds, "BodyPartExamined", "") or "").upper(),
                }

            try:
                inst_num = int(getattr(ds, "InstanceNumber", 1) or 1)
            except Exception:
                inst_num = 1

            image_meta = {
                "sop_instance_uid": sop_uid,
                "instance_number": inst_num,
                "image_position": str(getattr(ds, "ImagePositionPatient", "") or ""),
                "slice_location": getattr(ds, "SliceLocation", None),
                "src_path": p,
            }
            studies_map.setdefault(study_uid, {}).setdefault(series_key, []).append((image_meta, p))
            processed_files += 1
        except Exception:
            invalid_files += 1
            continue

    if not studies_map:
        return {"success": False, "error": "no valid dicom files", "session_id": session_id}

    stats = {
        "total_files": len(paths),
        "processed_files": processed_files,
        "invalid_files": invalid_files,
        "created_studies": 0,
        "created_series": 0,
        "created_images": 0,
        "updated_images": 0,
        "session_id": session_id,
    }

    def _infer_facility_from_meta(meta: dict) -> Facility | None:
        try:
            candidates = list(meta.get("facility_candidates") or [])
            for c in candidates:
                f = Facility.objects.filter(is_active=True).filter(ae_title__iexact=c).first()
                if f:
                    return f
            for c in candidates:
                f = Facility.objects.filter(is_active=True).filter(name__iexact=c).first()
                if f:
                    return f
            for c in candidates:
                if len(c) >= 4:
                    f = Facility.objects.filter(is_active=True).filter(name__icontains=c).first()
                    if f:
                        return f
            return None
        except Exception:
            return None

    created_study_ids: list[int] = []

    for study_uid, series_map in studies_map.items():
        rep_meta = study_meta_map.get(study_uid, {}) or {}

        patient_id = (str(rep_meta.get("patient_id") or "").strip()) or f"TEMP_{int(timezone.now().timestamp())}"
        first_name = (str(rep_meta.get("first_name") or "Unknown").strip()) or "Unknown"
        last_name = (str(rep_meta.get("last_name") or "Patient").strip()) or "Patient"

        birth_date = rep_meta.get("patient_birth_date")
        if birth_date:
            try:
                dob = datetime.strptime(str(birth_date), "%Y%m%d").date()
            except Exception:
                dob = timezone.now().date()
        else:
            dob = timezone.now().date()

        gender = str(rep_meta.get("patient_sex") or "O").upper()
        if gender not in ["M", "F", "O"]:
            gender = "O"

        with transaction.atomic():
            patient, patient_created = Patient.objects.get_or_create(
                patient_id=patient_id,
                defaults={"first_name": first_name, "last_name": last_name, "date_of_birth": dob, "gender": gender},
            )

        try:
            if not patient_created:
                is_placeholder = (
                    (not (patient.first_name or "").strip())
                    or (not (patient.last_name or "").strip())
                    or (patient.first_name.strip().lower() in ("unknown", "unk"))
                    or (patient.last_name.strip().lower() in ("patient", "unknown", "unk"))
                )
                has_better = (first_name.strip().lower() not in ("unknown", "unk")) and (
                    last_name.strip().lower() not in ("patient", "unknown", "unk")
                )
                if is_placeholder and has_better:
                    patient.first_name = first_name
                    patient.last_name = last_name
                    patient.save(update_fields=["first_name", "last_name"])
        except Exception:
            pass

        try:
            if getattr(patient, "id", None):
                patient_ids_involved.add(int(patient.id))
        except Exception:
            pass

        # Decide study modality
        study_modalities = set()
        try:
            for _k in series_map.keys():
                parts = str(_k).split("_", 1)
                if len(parts) == 2 and parts[1]:
                    study_modalities.add(parts[1].strip().upper())
        except Exception:
            study_modalities = set()
        non_ot = [m for m in study_modalities if m and m != "OT"]
        if len(non_ot) == 1:
            modality_code = non_ot[0]
        elif len(non_ot) == 0:
            modality_code = str(rep_meta.get("default_modality") or "OT").strip().upper() or "OT"
        else:
            modality_code = "OT"

        with transaction.atomic():
            modality, modality_created = Modality.objects.get_or_create(
                code=modality_code, defaults={"name": modality_code, "is_active": True}
            )

            study_description = rep_meta.get("study_description") or f"{modality_code} Study - Upload"
            referring_physician = str(rep_meta.get("referring_physician") or "UNKNOWN").replace("^", " ")
            accession_number = rep_meta.get("accession_number")
            if not accession_number or not str(accession_number).strip():
                accession_number = f"NOCTIS_{modality_code}_{int(timezone.now().timestamp())}"

            # prevent collisions (accession unique-ish)
            original_accession = str(accession_number)
            if Study.objects.filter(accession_number=original_accession).exists():
                suffix = 1
                base_acc = original_accession
                while Study.objects.filter(accession_number=f"{base_acc}_V{suffix}").exists():
                    suffix += 1
                accession_number = f"{base_acc}_V{suffix}"

            study_date = rep_meta.get("study_date")
            study_time = rep_meta.get("study_time") or "000000"
            if study_date:
                try:
                    sdt = datetime.strptime(f"{study_date}{str(study_time)[:6]}", "%Y%m%d%H%M%S")
                    sdt = timezone.make_aware(sdt)
                except Exception:
                    sdt = timezone.now()
            else:
                sdt = timezone.now()

            facility = None
            try:
                if user and ((hasattr(user, "is_admin") and user.is_admin()) or (hasattr(user, "is_radiologist") and user.is_radiologist())):
                    if override_facility_id:
                        facility = Facility.objects.filter(id=override_facility_id, is_active=True).first()
            except Exception:
                facility = None
            if not facility:
                facility = _infer_facility_from_meta(rep_meta)
            if not facility and user and getattr(user, "facility", None):
                facility = user.facility
            if not facility:
                facility = Facility.objects.filter(is_active=True).first()
            if not facility:
                # last-resort default facility
                facility = Facility.objects.create(
                    name="Default Facility",
                    address="N/A",
                    phone="N/A",
                    email="default@example.com",
                    license_number=f"DEFAULT-{int(timezone.now().timestamp())}",
                    ae_title="",
                    is_active=True,
                )

            assigned_radiologist = None
            try:
                if assign_to_me and user and hasattr(user, "is_radiologist") and user.is_radiologist():
                    assigned_radiologist = user
            except Exception:
                assigned_radiologist = None

            study, study_created = Study.objects.get_or_create(
                study_instance_uid=study_uid,
                defaults={
                    "accession_number": accession_number,
                    "patient": patient,
                    "facility": facility,
                    "modality": modality,
                    "study_description": study_description,
                    "study_date": sdt,
                    "referring_physician": referring_physician,
                    "status": "scheduled",
                    "priority": priority,
                    "clinical_info": clinical_info,
                    "uploaded_by": user,
                    "radiologist": assigned_radiologist,
                    "body_part": str(rep_meta.get("body_part") or ""),
                    "study_comments": f"Upload by {(user.get_full_name() if user else 'unknown')} on {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
                },
            )

        if modality_created:
            logger.info("New modality created: %s", modality_code)

        if study_created:
            stats["created_studies"] += 1
            created_study_ids.append(int(study.id))
            # Best-effort AI start (keep errors isolated)
            try:
                from .views import _auto_start_ai_for_study  # local import to avoid import-time side effects

                _auto_start_ai_for_study(study)
            except Exception:
                pass

        # If study existed, optionally refresh priority/clinical info (best-effort)
        if not study_created:
            updated = False
            if priority and study.priority != priority:
                study.priority = priority
                updated = True
            if clinical_info and study.clinical_info != clinical_info:
                study.clinical_info = clinical_info
                updated = True
            if updated:
                try:
                    study.save(update_fields=["priority", "clinical_info"])
                except Exception:
                    pass

        for series_key, items in series_map.items():
            series_uid, _series_mod_from_key = (str(series_key).split("_", 1) + [""])[:2]
            smeta = (series_meta_map.get(study_uid, {}) or {}).get(series_key) or {}
            series_modality_code = str(smeta.get("modality") or _series_mod_from_key or modality_code).strip().upper() or modality_code
            try:
                series_number = int(smeta.get("series_number") or 1)
            except Exception:
                series_number = 1
            series_desc = str(smeta.get("series_description") or f"{series_modality_code} Series {series_number}")
            slice_thickness = smeta.get("slice_thickness", None)
            pixel_spacing = str(smeta.get("pixel_spacing", "") or "")
            image_orientation = str(smeta.get("image_orientation", "") or "")
            body_part = str(smeta.get("body_part", "") or "").upper()

            with transaction.atomic():
                series, series_created = Series.objects.get_or_create(
                    series_instance_uid=series_uid,
                    defaults={
                        "study": study,
                        "series_number": int(series_number),
                        "series_description": series_desc,
                        "modality": series_modality_code,
                        "body_part": body_part,
                        "slice_thickness": slice_thickness if slice_thickness is not None else None,
                        "pixel_spacing": pixel_spacing,
                        "image_orientation": image_orientation,
                    },
                )

            if series_created:
                stats["created_series"] += 1

            try:
                if series_uid:
                    series_uids_touched.add(str(series_uid))
            except Exception:
                pass

            sop_uids: list[str] = []
            for meta, _p in items:
                uid = (meta or {}).get("sop_instance_uid")
                if uid:
                    sop_uids.append(str(uid))

            existing_map: dict[str, DicomImage] = {}
            if sop_uids:
                try:
                    qs = DicomImage.objects.filter(sop_instance_uid__in=sop_uids).only(
                        "id", "sop_instance_uid", "series_id", "instance_number"
                    )
                    existing_map = {img.sop_instance_uid: img for img in qs}
                except Exception:
                    existing_map = {}

            to_create: list[DicomImage] = []
            to_update: list[DicomImage] = []

            for meta, src_path in items:
                sop_uid = str((meta or {}).get("sop_instance_uid") or "").strip()
                if not sop_uid:
                    continue
                try:
                    inst_num = int((meta or {}).get("instance_number") or 1)
                except Exception:
                    inst_num = 1

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
                        stats["updated_images"] += 1
                    # Source file is a duplicate / retry; delete to keep incoming clean
                    try:
                        os.remove(src_path)
                    except Exception:
                        pass
                    continue

                rel_path = f"dicom/images/{study_uid}/{series_uid}/{sop_uid}.dcm"
                dest_abs = _media_abs(rel_path)
                os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
                try:
                    # Move (cheap) instead of re-saving bytes
                    os.replace(src_path, dest_abs)
                except FileNotFoundError:
                    # already moved by a retry; ignore
                    pass
                except Exception:
                    # last resort: copy then remove
                    try:
                        shutil.copyfile(src_path, dest_abs)
                        os.remove(src_path)
                    except Exception:
                        pass

                image_position = str((meta or {}).get("image_position") or "")
                slice_location = (meta or {}).get("slice_location", None)
                try:
                    file_size = int(os.path.getsize(dest_abs))
                except Exception:
                    file_size = 0

                to_create.append(
                    DicomImage(
                        sop_instance_uid=sop_uid,
                        series=series,
                        instance_number=inst_num,
                        image_position=image_position,
                        slice_location=slice_location,
                        file_path=rel_path,
                        file_size=file_size,
                        processed=False,
                    )
                )

            try:
                with transaction.atomic():
                    if to_create:
                        DicomImage.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=500)
                        stats["created_images"] += len(to_create)
                    if to_update:
                        DicomImage.objects.bulk_update(to_update, ["series", "instance_number"], batch_size=500)
            except Exception:
                # best-effort fallback
                for obj in to_create:
                    try:
                        obj.save()
                        stats["created_images"] += 1
                    except Exception:
                        pass

    # Best-effort MPR precache (now in background, safe)
    try:
        uids = list(series_uids_touched)
        max_series = int(os.environ.get("MPR_PRECACHE_MAX_SERIES", "4") or 4)
        uids = uids[: max(0, max_series)]
        if uids:
            series_ids: list[int] = []
            for suid in uids:
                s = Series.objects.filter(series_instance_uid=suid).only("id").first()
                if s and s.id:
                    series_ids.append(int(s.id))
            if series_ids:
                from dicom_viewer.views import _schedule_mpr_disk_cache_build

                for sid in series_ids:
                    try:
                        _schedule_mpr_disk_cache_build(int(sid), quality="high")
                    except Exception:
                        pass
    except Exception:
        pass

    # Cleanup incoming session dir
    try:
        shutil.rmtree(src_dir, ignore_errors=True)
    except Exception:
        pass

    end = timezone.now()
    stats["processing_time_ms"] = int((end - start).total_seconds() * 1000)
    stats["patients_affected"] = len(patient_ids_involved)
    stats["created_study_ids"] = created_study_ids
    return {"success": True, **stats}


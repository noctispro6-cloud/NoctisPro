from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Tuple

import pydicom
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Facility
from worklist.models import DicomImage, Modality, Patient, Series, Study


@dataclass(frozen=True)
class _StoredInstanceResult:
    sop_instance_uid: str
    status: str  # "stored" | "skipped"
    study_instance_uid: Optional[str] = None
    series_instance_uid: Optional[str] = None
    instance_number: Optional[int] = None


def _get_request_ip(request) -> str:
    # Best-effort; if behind a proxy, configure X-Forwarded-For handling in nginx.
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _parse_boundary(content_type: str) -> Optional[str]:
    # Example: multipart/related; type="application/dicom"; boundary=abcd
    parts = [p.strip() for p in (content_type or "").split(";")]
    for p in parts:
        if p.lower().startswith("boundary="):
            b = p.split("=", 1)[1].strip()
            if b.startswith('"') and b.endswith('"'):
                b = b[1:-1]
            return b or None
    return None


def _split_headers_and_body(part: bytes) -> Tuple[bytes, bytes]:
    # RFC822-ish: headers \r\n\r\n body
    marker = b"\r\n\r\n"
    idx = part.find(marker)
    if idx == -1:
        return b"", part
    return part[:idx], part[idx + len(marker) :]


def _extract_content_type(headers_blob: bytes) -> str:
    # Minimal header parsing; case-insensitive.
    for raw_line in headers_blob.split(b"\r\n"):
        line = raw_line.decode("latin-1", errors="ignore")
        if line.lower().startswith("content-type:"):
            return line.split(":", 1)[1].strip()
    return ""


def _parse_multipart_related(body: bytes, boundary: str) -> List[bytes]:
    """
    Parse multipart/related payload and return a list of DICOM part bodies (bytes).
    This is intentionally small and tolerant (enough for typical STOW-RS senders).
    """
    if not boundary:
        return []

    delim = b"--" + boundary.encode("utf-8")
    end_delim = delim + b"--"

    parts: List[bytes] = []
    # Split by boundary delimiter; body commonly starts with delim + \r\n
    for chunk in body.split(delim):
        chunk = chunk.strip()
        if not chunk or chunk == b"--" or chunk == end_delim:
            continue
        if chunk.endswith(b"--"):
            chunk = chunk[:-2].strip()

        headers_blob, content = _split_headers_and_body(chunk)
        ctype = _extract_content_type(headers_blob).lower()

        # Accept typical DICOMweb content types
        if "application/dicom" in ctype or ctype == "" or "application/octet-stream" in ctype:
            parts.append(content.strip(b"\r\n"))

    return parts


def _get_or_create_patient(ds) -> Patient:
    patient_id = getattr(ds, "PatientID", "Unknown")
    patient_name = str(getattr(ds, "PatientName", "Unknown")).replace("^", " ").strip()
    name_parts = [p for p in patient_name.split() if p]
    first_name = name_parts[0] if name_parts else "Unknown"
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    birth_date = None
    if getattr(ds, "PatientBirthDate", None):
        try:
            from datetime import datetime

            birth_date = datetime.strptime(ds.PatientBirthDate, "%Y%m%d").date()
        except Exception:
            birth_date = None

    gender = getattr(ds, "PatientSex", "O")
    gender = gender.upper() if isinstance(gender, str) else "O"
    if gender not in {"M", "F", "O"}:
        gender = "O"

    patient, _ = Patient.objects.get_or_create(
        patient_id=patient_id,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": birth_date or timezone.now().date(),
            "gender": gender,
        },
    )
    return patient


def _get_or_create_modality(ds) -> Modality:
    modality_code = getattr(ds, "Modality", "OT")
    modality, _ = Modality.objects.get_or_create(
        code=modality_code,
        defaults={
            "name": modality_code,
            "description": f"{modality_code} Modality",
            "is_active": True,
        },
    )
    return modality


def _get_or_create_study(ds, patient: Patient, modality: Modality, facility: Facility, user) -> Study:
    study_uid = getattr(ds, "StudyInstanceUID", None)
    if not study_uid:
        raise ValueError("Missing StudyInstanceUID")

    study_date = timezone.now()
    if getattr(ds, "StudyDate", None):
        try:
            from datetime import datetime

            study_date = datetime.strptime(ds.StudyDate, "%Y%m%d")
            study_date = timezone.make_aware(study_date)
        except Exception:
            study_date = timezone.now()

    study, _ = Study.objects.get_or_create(
        study_instance_uid=study_uid,
        defaults={
            "patient": patient,
            "facility": facility,
            "modality": modality,
            "accession_number": getattr(ds, "AccessionNumber", f"ACC_{study_uid[:8]}"),
            "study_description": getattr(ds, "StudyDescription", ""),
            "study_date": study_date,
            "referring_physician": str(getattr(ds, "ReferringPhysicianName", "")),
            "status": "completed",
            "priority": "normal",
            "body_part": getattr(ds, "BodyPartExamined", ""),
            "uploaded_by": user,
        },
    )
    return study


def _get_or_create_series(ds, study: Study) -> Series:
    series_uid = getattr(ds, "SeriesInstanceUID", None)
    if not series_uid:
        raise ValueError("Missing SeriesInstanceUID")

    pixel_spacing = ""
    if hasattr(ds, "PixelSpacing"):
        try:
            pixel_spacing = "\\".join([str(x) for x in ds.PixelSpacing])
        except Exception:
            pixel_spacing = ""

    series, _ = Series.objects.get_or_create(
        series_instance_uid=series_uid,
        defaults={
            "study": study,
            "series_number": getattr(ds, "SeriesNumber", 0),
            "series_description": getattr(ds, "SeriesDescription", ""),
            "modality": getattr(ds, "Modality", ""),
            "body_part": getattr(ds, "BodyPartExamined", ""),
            "slice_thickness": getattr(ds, "SliceThickness", None),
            "pixel_spacing": pixel_spacing,
            "image_orientation": str(getattr(ds, "ImageOrientationPatient", "")),
        },
    )
    return series


def _storage_dir(patient: Patient, study: Study, series: Series) -> str:
    import os

    base_dir = str(settings.MEDIA_ROOT)
    # Keep same structure as your management command: media/dicom/images/...
    dicom_base = os.path.join(base_dir, "dicom", "images")
    study_date = study.study_date.strftime("%Y%m%d") if getattr(study, "study_date", None) else "unknown"
    return os.path.join(
        dicom_base,
        f"patient_{patient.patient_id}",
        f"study_{study.id}_{study_date}",
        f"series_{series.series_number}_{series.modality}",
    )


def _ensure_dir(path: str) -> None:
    import os

    os.makedirs(path, exist_ok=True)


def _write_instance_file(ds, dest_path: str) -> int:
    ds.save_as(dest_path, write_like_original=False)
    import os

    return os.path.getsize(dest_path)


def _store_one_instance(ds, *, facility: Facility, user, overwrite: bool) -> _StoredInstanceResult:
    sop_uid = getattr(ds, "SOPInstanceUID", None)
    if not sop_uid:
        raise ValueError("Missing SOPInstanceUID")

    if DicomImage.objects.filter(sop_instance_uid=sop_uid).exists():
        if not overwrite:
            return _StoredInstanceResult(
                sop_instance_uid=str(sop_uid),
                status="skipped",
                study_instance_uid=getattr(ds, "StudyInstanceUID", None),
                series_instance_uid=getattr(ds, "SeriesInstanceUID", None),
                instance_number=getattr(ds, "InstanceNumber", None),
            )
        DicomImage.objects.filter(sop_instance_uid=sop_uid).delete()

    patient = _get_or_create_patient(ds)
    modality = _get_or_create_modality(ds)
    study = _get_or_create_study(ds, patient, modality, facility, user)
    series = _get_or_create_series(ds, study)

    storage_dir = _storage_dir(patient, study, series)
    _ensure_dir(storage_dir)

    filename = f"{sop_uid}.dcm"
    import os

    dest_path = os.path.join(storage_dir, filename)
    file_size = _write_instance_file(ds, dest_path)

    relative_path = os.path.relpath(dest_path, settings.MEDIA_ROOT)

    DicomImage.objects.create(
        sop_instance_uid=str(sop_uid),
        series=series,
        instance_number=getattr(ds, "InstanceNumber", 0) or 0,
        image_position=str(getattr(ds, "ImagePositionPatient", "")),
        slice_location=getattr(ds, "SliceLocation", None),
        file_path=relative_path,
        file_size=file_size,
        processed=True,
    )

    return _StoredInstanceResult(
        sop_instance_uid=str(sop_uid),
        status="stored",
        study_instance_uid=getattr(ds, "StudyInstanceUID", None),
        series_instance_uid=getattr(ds, "SeriesInstanceUID", None),
        instance_number=getattr(ds, "InstanceNumber", None),
    )


class DicomWebStowView(APIView):
    """
    Minimal DICOMweb STOW-RS style endpoint.

    - POST /dicomweb/studies/
    - Accepts:
      - Content-Type: application/dicom (single instance)
      - Content-Type: multipart/related; type="application/dicom"; boundary=... (multiple instances)
    - Authentication:
      - HTTP Basic (recommended for automated senders)
      - Session (for browser use)
    """

    authentication_classes = [BasicAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        content_type = (request.META.get("CONTENT_TYPE") or "").lower()
        overwrite = str(request.query_params.get("overwrite", "false")).lower() in {"1", "true", "yes"}

        # Facility selection:
        # - If user has facility, use it
        # - Else fall back to first facility (admin can create one)
        facility = getattr(request.user, "facility", None) or Facility.objects.first()
        if facility is None:
            return Response(
                {
                    "detail": "No Facility exists. Create a Facility first, then retry.",
                },
                status=400,
            )

        raw_body = request.body or b""
        if not raw_body:
            return Response({"detail": "Empty request body"}, status=400)

        dicom_blobs: List[bytes] = []
        if content_type.startswith("application/dicom"):
            dicom_blobs = [raw_body]
        elif content_type.startswith("multipart/related"):
            boundary = _parse_boundary(content_type)
            if not boundary:
                return Response({"detail": "Missing multipart boundary"}, status=400)
            dicom_blobs = _parse_multipart_related(raw_body, boundary)
        else:
            return Response(
                {
                    "detail": "Unsupported Content-Type",
                    "supported": [
                        "application/dicom",
                        "multipart/related; type=application/dicom; boundary=...",
                    ],
                },
                status=415,
            )

        if not dicom_blobs:
            return Response({"detail": "No DICOM parts found"}, status=400)

        stored: List[_StoredInstanceResult] = []
        errors: List[dict] = []
        client_ip = _get_request_ip(request)

        with transaction.atomic():
            for idx, blob in enumerate(dicom_blobs):
                try:
                    ds = pydicom.dcmread(BytesIO(blob), force=True)
                    result = _store_one_instance(ds, facility=facility, user=request.user, overwrite=overwrite)
                    stored.append(result)
                except Exception as e:
                    errors.append({"index": idx, "error": str(e), "client_ip": client_ip})

        return Response(
            {
                "stored": [r.__dict__ for r in stored if r.status == "stored"],
                "skipped": [r.__dict__ for r in stored if r.status == "skipped"],
                "errors": errors,
                "counts": {
                    "received_instances": len(dicom_blobs),
                    "stored": len([r for r in stored if r.status == "stored"]),
                    "skipped": len([r for r in stored if r.status == "skipped"]),
                    "errors": len(errors),
                },
            },
            status=200 if not errors else 207,  # 207 Multi-Status when partial failures
        )


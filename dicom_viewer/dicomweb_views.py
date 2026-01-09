from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Tuple

import pydicom
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponse
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Facility
from accounts.audit import log_audit
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

    def get(self, request, *args, **kwargs):
        """
        Minimal QIDO-RS:
          - GET /dicomweb/studies/

        Returns a list of study attribute objects (DICOM JSON model) for basic interop.
        """
        user = request.user
        qs = Study.objects.select_related("patient", "facility", "modality")
        if getattr(user, "is_facility_user", None) and user.is_facility_user() and getattr(user, "facility", None):
            qs = qs.filter(facility=user.facility)

        # Common QIDO query parameters
        patient_id = (request.query_params.get("PatientID") or "").strip()
        study_uid = (request.query_params.get("StudyInstanceUID") or "").strip()
        accession = (request.query_params.get("AccessionNumber") or "").strip()
        modality = (request.query_params.get("ModalitiesInStudy") or request.query_params.get("Modality") or "").strip()

        if patient_id:
            qs = qs.filter(patient__patient_id__icontains=patient_id)
        if study_uid:
            qs = qs.filter(study_instance_uid=study_uid)
        if accession:
            qs = qs.filter(accession_number__icontains=accession)
        if modality:
            qs = qs.filter(modality__code__iexact=modality)

        # Paging (best-effort)
        try:
            limit = int(request.query_params.get("limit", "200"))
        except Exception:
            limit = 200
        try:
            offset = int(request.query_params.get("offset", "0"))
        except Exception:
            offset = 0
        limit = max(1, min(2000, limit))
        offset = max(0, offset)

        qs = qs.order_by("-study_date")[offset : offset + limit]

        def _attr(tag: str, vr: str, value):
            if value is None or value == "":
                return {tag: {"vr": vr}}
            if isinstance(value, list):
                return {tag: {"vr": vr, "Value": value}}
            return {tag: {"vr": vr, "Value": [value]}}

        def _study_item(study: Study) -> dict:
            patient = getattr(study, "patient", None)
            modality_obj = getattr(study, "modality", None)
            mod_code = getattr(modality_obj, "code", "") if modality_obj else ""
            mod_code = mod_code or ""
            # DICOM JSON model expects DICOM-formatted values; keep it minimal and predictable
            d = {}
            d.update(_attr("0020000D", "UI", getattr(study, "study_instance_uid", "") or ""))  # StudyInstanceUID
            d.update(_attr("00080050", "SH", getattr(study, "accession_number", "") or ""))  # AccessionNumber
            d.update(_attr("00081030", "LO", getattr(study, "study_description", "") or ""))  # StudyDescription
            if getattr(study, "study_date", None):
                d.update(_attr("00080020", "DA", study.study_date.strftime("%Y%m%d")))  # StudyDate
                d.update(_attr("00080030", "TM", study.study_date.strftime("%H%M%S")))  # StudyTime
            if patient:
                d.update(_attr("00100020", "LO", getattr(patient, "patient_id", "") or ""))  # PatientID
                d.update(_attr("00100010", "PN", getattr(patient, "full_name", "") or ""))  # PatientName
            d.update(_attr("00080061", "CS", [mod_code] if mod_code else []))  # ModalitiesInStudy
            return d

        items = [_study_item(s) for s in qs]
        try:
            log_audit(
                request=request,
                action="dicomweb_qido",
                user=user,
                facility=getattr(user, "facility", None),
                extra={
                    "level": "studies",
                    "query": dict(request.query_params),
                    "count": len(items),
                },
            )
        except Exception:
            pass
        return Response(items, status=200)

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

        try:
            log_audit(
                request=request,
                action="dicomweb_stow",
                user=request.user,
                facility=facility,
                extra={
                    "overwrite": bool(overwrite),
                    "client_ip": client_ip,
                    "received_instances": len(dicom_blobs),
                    "stored": len([r for r in stored if r.status == "stored"]),
                    "skipped": len([r for r in stored if r.status == "skipped"]),
                    "errors": len(errors),
                },
            )
        except Exception:
            pass

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


class DicomWebSeriesView(APIView):
    """
    Minimal QIDO-RS Series:
      - GET /dicomweb/studies/{StudyInstanceUID}/series/
    """

    authentication_classes = [BasicAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, study_uid: str, *args, **kwargs):
        user = request.user
        study = Study.objects.select_related("facility").filter(study_instance_uid=study_uid).first()
        if not study:
            return Response({"detail": "Study not found"}, status=404)
        if getattr(user, "is_facility_user", None) and user.is_facility_user() and getattr(user, "facility", None):
            if study.facility != user.facility:
                return Response({"detail": "Permission denied"}, status=403)

        qs = Series.objects.filter(study=study).order_by("series_number", "id")
        modality = (request.query_params.get("Modality") or "").strip()
        if modality:
            qs = qs.filter(modality__iexact=modality)

        def _attr(tag: str, vr: str, value):
            if value is None or value == "":
                return {tag: {"vr": vr}}
            if isinstance(value, list):
                return {tag: {"vr": vr, "Value": value}}
            return {tag: {"vr": vr, "Value": [value]}}

        items = []
        for s in qs:
            d = {}
            d.update(_attr("0020000D", "UI", getattr(study, "study_instance_uid", "") or ""))  # StudyInstanceUID
            d.update(_attr("0020000E", "UI", getattr(s, "series_instance_uid", "") or ""))  # SeriesInstanceUID
            d.update(_attr("00200011", "IS", str(getattr(s, "series_number", 0) or 0)))  # SeriesNumber
            d.update(_attr("00080060", "CS", getattr(s, "modality", "") or ""))  # Modality
            d.update(_attr("0008103E", "LO", getattr(s, "series_description", "") or ""))  # SeriesDescription
            try:
                d.update(_attr("00201209", "IS", str(s.images.count())))  # NumberOfSeriesRelatedInstances
            except Exception:
                pass
            items.append(d)

        try:
            log_audit(
                request=request,
                action="dicomweb_qido",
                user=user,
                facility=getattr(study, "facility", None),
                study_instance_uid=getattr(study, "study_instance_uid", "") or "",
                study_id=int(study.id),
                extra={"level": "series", "query": dict(request.query_params), "count": len(items)},
            )
        except Exception:
            pass

        return Response(items, status=200)


class DicomWebInstancesView(APIView):
    """
    Minimal QIDO-RS Instances:
      - GET /dicomweb/studies/{StudyInstanceUID}/series/{SeriesInstanceUID}/instances/
    """

    authentication_classes = [BasicAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, study_uid: str, series_uid: str, *args, **kwargs):
        user = request.user
        study = Study.objects.select_related("facility").filter(study_instance_uid=study_uid).first()
        if not study:
            return Response({"detail": "Study not found"}, status=404)
        if getattr(user, "is_facility_user", None) and user.is_facility_user() and getattr(user, "facility", None):
            if study.facility != user.facility:
                return Response({"detail": "Permission denied"}, status=403)

        series = Series.objects.filter(study=study, series_instance_uid=series_uid).first()
        if not series:
            return Response({"detail": "Series not found"}, status=404)

        qs = DicomImage.objects.filter(series=series).order_by("instance_number", "id")

        def _attr(tag: str, vr: str, value):
            if value is None or value == "":
                return {tag: {"vr": vr}}
            if isinstance(value, list):
                return {tag: {"vr": vr, "Value": value}}
            return {tag: {"vr": vr, "Value": [value]}}

        items = []
        for img in qs:
            d = {}
            d.update(_attr("0020000D", "UI", getattr(study, "study_instance_uid", "") or ""))  # StudyInstanceUID
            d.update(_attr("0020000E", "UI", getattr(series, "series_instance_uid", "") or ""))  # SeriesInstanceUID
            d.update(_attr("00080018", "UI", getattr(img, "sop_instance_uid", "") or ""))  # SOPInstanceUID
            d.update(_attr("00200013", "IS", str(getattr(img, "instance_number", 0) or 0)))  # InstanceNumber
            items.append(d)

        try:
            log_audit(
                request=request,
                action="dicomweb_qido",
                user=user,
                facility=getattr(study, "facility", None),
                study_instance_uid=getattr(study, "study_instance_uid", "") or "",
                series_instance_uid=getattr(series, "series_instance_uid", "") or "",
                study_id=int(study.id),
                series_id=int(series.id),
                extra={"level": "instances", "query": dict(request.query_params), "count": len(items)},
            )
        except Exception:
            pass

        return Response(items, status=200)


class DicomWebWadoInstanceView(APIView):
    """
    Minimal WADO-RS Retrieve:
      - GET /dicomweb/studies/{StudyInstanceUID}/series/{SeriesInstanceUID}/instances/{SOPInstanceUID}
      - GET /dicomweb/studies/{StudyInstanceUID}/series/{SeriesInstanceUID}/instances/{SOPInstanceUID}/metadata
    """

    authentication_classes = [BasicAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, study_uid: str, series_uid: str, instance_uid: str, *args, **kwargs):
        user = request.user
        study = Study.objects.select_related("facility").filter(study_instance_uid=study_uid).first()
        if not study:
            return Response({"detail": "Study not found"}, status=404)
        if getattr(user, "is_facility_user", None) and user.is_facility_user() and getattr(user, "facility", None):
            if study.facility != user.facility:
                return Response({"detail": "Permission denied"}, status=403)

        series = Series.objects.filter(study=study, series_instance_uid=series_uid).first()
        if not series:
            return Response({"detail": "Series not found"}, status=404)

        img = DicomImage.objects.filter(series=series, sop_instance_uid=instance_uid).first()
        if not img or not getattr(img, "file_path", None):
            return Response({"detail": "Instance not found"}, status=404)

        # If the URL ends with /metadata, return metadata JSON.
        if request.path.rstrip("/").endswith("/metadata"):
            try:
                with img.file_path.open("rb") as f:
                    ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
                try:
                    payload = [ds.to_json_dict()]  # pydicom>=2
                except Exception:
                    payload = []
                try:
                    log_audit(
                        request=request,
                        action="dicomweb_wado",
                        user=user,
                        facility=getattr(study, "facility", None),
                        study_instance_uid=study_uid,
                        series_instance_uid=series_uid,
                        sop_instance_uid=instance_uid,
                        study_id=int(study.id),
                        series_id=int(series.id),
                        image_id=int(img.id),
                        extra={"mode": "metadata"},
                    )
                except Exception:
                    pass
                return Response(payload, status=200)
            except Exception as e:
                return Response({"detail": f"Failed to read metadata: {str(e)}"}, status=500)

        # Default: return raw DICOM bytes
        try:
            with img.file_path.open("rb") as f:
                blob = f.read()
            resp = HttpResponse(blob, content_type="application/dicom")
            resp["Content-Disposition"] = f'inline; filename="{instance_uid}.dcm"'
            resp["Cache-Control"] = "private, max-age=0, no-store"
            try:
                log_audit(
                    request=request,
                    action="dicomweb_wado",
                    user=user,
                    facility=getattr(study, "facility", None),
                    study_instance_uid=study_uid,
                    series_instance_uid=series_uid,
                    sop_instance_uid=instance_uid,
                    study_id=int(study.id),
                    series_id=int(series.id),
                    image_id=int(img.id),
                    extra={"mode": "dicom"},
                )
            except Exception:
                pass
            return resp
        except Exception as e:
            return Response({"detail": f"Failed to read instance: {str(e)}"}, status=500)


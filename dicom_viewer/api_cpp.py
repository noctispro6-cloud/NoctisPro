from django.http import Http404
from django.http.response import FileResponse
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.urls import reverse
from worklist.models import Study, Series, DicomImage
from .dicom_utils import safe_dicom_str
import os
import pydicom

from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


def _cpp_compat_enabled() -> bool:
    """
    Legacy C++ desktop viewer compatibility endpoints.

    Production default: disabled (these endpoints historically exposed server filesystem paths).
    Enable explicitly via env: DICOM_VIEWER_ENABLE_CPP_COMPAT_API=true
    """
    return bool(getattr(settings, "DICOM_VIEWER_ENABLE_CPP_COMPAT_API", False)) or bool(
        getattr(settings, "DICOM_VIEWER_SETTINGS", {}).get("ENABLE_CPP_COMPAT_API", False)
    )


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_cpp_worklist(request):
    # Return a simple array of worklist-like items expected by the C++ app
    if not _cpp_compat_enabled():
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    items = []
    studies = Study.objects.select_related("patient", "modality").order_by("-study_date")[:50]
    for study in studies:
        items.append({
            "study_id": study.id,
            "study_instance_uid": getattr(study, "study_instance_uid", ""),
            "patient_name": getattr(study.patient, "full_name", str(study.patient)),
            "study_description": study.study_description,
            # Do NOT return server filesystem paths. Provide an API URL instead.
            "series_url": reverse("dicom_viewer:api_cpp_series", kwargs={"study_id": getattr(study, "study_instance_uid", "")}),
        })
    return Response(items, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_cpp_study_status(request):
    if not _cpp_compat_enabled():
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    study_uid = request.data.get("study_id")
    status_value = request.data.get("status")
    if not study_uid or not status_value:
        return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

    study = Study.objects.filter(study_instance_uid=study_uid).first()
    if not study:
        return Response({"error": "Study not found"}, status=status.HTTP_404_NOT_FOUND)

    # Map incoming statuses to our Study.status choices
    mapped = {
        "viewing": "in_progress",
        "completed": "completed",
    }.get(status_value)
    if mapped:
        study.status = mapped
        study.save(update_fields=["status"])

    return Response({"success": True, "message": f"Study status set to {study.status}"}, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_cpp_series(request, study_id: str):
    if not _cpp_compat_enabled():
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    study = get_object_or_404(Study, study_instance_uid=study_id)
    series_list = study.series_set.order_by("series_number")
    payload = {"study_id": study_id, "series": []}
    for s in series_list:
        images = s.images.order_by("instance_number")
        files = []
        for img in images:
            files.append({
                "instance_uid": img.sop_instance_uid,
                "instance_number": img.instance_number,
                "dicom_url": reverse("dicom_viewer:api_cpp_dicom_file", kwargs={"instance_uid": img.sop_instance_uid}),
                "file_size": getattr(img, "file_size", 0) or 0,
            })
        payload["series"].append({
            "id": s.id,
            "series_instance_uid": s.series_instance_uid,
            "series_number": s.series_number,
            "series_description": s.series_description,
            "modality": s.modality,
            "instance_count": images.count(),
            "dicom_files": files,
        })
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_cpp_dicom_file(request, instance_uid: str):
    if not _cpp_compat_enabled():
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    img = get_object_or_404(DicomImage, sop_instance_uid=instance_uid)
    if not img.file_path:
        raise Http404("DICOM file not found")
    try:
        fh = img.file_path.open("rb")
    except Exception:
        raise Http404("DICOM file not found")
    resp = FileResponse(fh, content_type="application/dicom")
    resp["Content-Disposition"] = f'attachment; filename="{os.path.basename(img.file_path.name)}"'
    resp["Cache-Control"] = "private, max-age=0, no-store"
    return resp


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_cpp_dicom_info(request, instance_uid: str):
    if not _cpp_compat_enabled():
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    img = get_object_or_404(DicomImage, sop_instance_uid=instance_uid)
    if not img.file_path:
        return Response({"error": "DICOM file not found"}, status=status.HTTP_404_NOT_FOUND)
    try:
        with img.file_path.open("rb") as f:
            ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
        info = {
            "patient_name": str(getattr(ds, "PatientName", "")),
            "patient_id": str(getattr(ds, "PatientID", "")),
            "patient_birth_date": str(getattr(ds, "PatientBirthDate", "")),
            "patient_sex": str(getattr(ds, "PatientSex", "")),
            "study_date": str(getattr(ds, "StudyDate", "")),
            "study_time": str(getattr(ds, "StudyTime", "")),
            "study_description": str(getattr(ds, "StudyDescription", "")),
            "series_description": str(getattr(ds, "SeriesDescription", "")),
            "modality": str(getattr(ds, "Modality", "")),
            "institution_name": str(getattr(ds, "InstitutionName", "")),
            "rows": getattr(ds, "Rows", None),
            "columns": getattr(ds, "Columns", None),
            "pixel_spacing": safe_dicom_str(getattr(ds, "PixelSpacing", "")),
            "slice_thickness": safe_dicom_str(getattr(ds, "SliceThickness", "")),
            "window_center": safe_dicom_str(getattr(ds, "WindowCenter", "")),
            "window_width": safe_dicom_str(getattr(ds, "WindowWidth", "")),
        }
        return Response({"instance_uid": instance_uid, "dicom_info": info}, status=status.HTTP_200_OK)
    except Exception:
        return Response({"error": "Cannot read DICOM metadata"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_cpp_viewer_sessions(request):
    if not _cpp_compat_enabled():
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
    # Minimal stub for compatibility with C++ app
    return Response({"active_sessions": []}, status=status.HTTP_200_OK)
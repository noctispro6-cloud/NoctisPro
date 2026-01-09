from django.http import JsonResponse, HttpResponse, Http404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from django.conf import settings
from worklist.models import Study, Series, DicomImage
from .dicom_utils import safe_dicom_str
import os
import json
import pydicom

@require_http_methods(["GET"])
@login_required
def api_cpp_worklist(request):
    # Return a simple array of worklist-like items expected by the C++ app
    items = []
    studies = Study.objects.select_related("patient", "modality", "facility").order_by("-study_date")
    if hasattr(request.user, "is_facility_user") and request.user.is_facility_user() and getattr(request.user, "facility", None):
        studies = studies.filter(facility=request.user.facility)
    studies = studies[:50]
    for study in studies:
        series = study.series_set.first()
        dicom_path = None
        if series:
            first_img = series.images.first()
            if first_img and first_img.file_path:
                try:
                    dicom_path = os.path.dirname(first_img.file_path.path)
                except Exception:
                    dicom_path = None
        items.append({
            "patient_name": getattr(study.patient, "full_name", str(study.patient)),
            "study_description": study.study_description,
            "dicom_path": dicom_path or "",
        })
    return JsonResponse(items, safe=False)

@require_http_methods(["POST"])
@login_required
def api_cpp_study_status(request):
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    study_uid = data.get("study_id")
    status_value = data.get("status")
    if not study_uid or not status_value:
        return JsonResponse({"error": "Missing required fields"}, status=400)

    study = Study.objects.filter(study_instance_uid=study_uid).first()
    if not study:
        return JsonResponse({"error": "Study not found"}, status=404)
    if hasattr(request.user, "is_facility_user") and request.user.is_facility_user() and getattr(request.user, "facility", None):
        if getattr(study, "facility", None) != request.user.facility:
            return JsonResponse({"error": "Permission denied"}, status=403)

    # Map incoming statuses to our Study.status choices
    mapped = {
        "viewing": "in_progress",
        "completed": "completed",
    }.get(status_value)
    if mapped:
        study.status = mapped
        study.save(update_fields=["status"])

    return JsonResponse({"success": True, "message": f"Study status set to {study.status}"})

@require_http_methods(["GET"])
@login_required
def api_cpp_series(request, study_id:str):
    study = get_object_or_404(Study, study_instance_uid=study_id)
    if hasattr(request.user, "is_facility_user") and request.user.is_facility_user() and getattr(request.user, "facility", None):
        if getattr(study, "facility", None) != request.user.facility:
            raise Http404()
    series_list = study.series_set.order_by("series_number")
    payload = {"study_id": study_id, "series": []}
    for s in series_list:
        images = s.images.order_by("instance_number")
        files = []
        for img in images:
            try:
                file_path = img.file_path.path if img.file_path else ""
                file_size = os.path.getsize(file_path) if file_path and os.path.exists(file_path) else 0
            except Exception:
                file_path = ""
                file_size = 0
            files.append({
                "instance_uid": img.sop_instance_uid,
                "instance_number": img.instance_number,
                "file_path": file_path,
                "file_size": file_size,
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
    return JsonResponse(payload)

@require_http_methods(["GET"])
@login_required
def api_cpp_dicom_file(request, instance_uid:str):
    img = get_object_or_404(DicomImage, sop_instance_uid=instance_uid)
    try:
        if hasattr(request.user, "is_facility_user") and request.user.is_facility_user() and getattr(request.user, "facility", None):
            if img.series.study.facility != request.user.facility:
                raise Http404()
    except Exception:
        raise Http404()
    if not img.file_path or not os.path.exists(img.file_path.path):
        raise Http404("DICOM file not found")
    with open(img.file_path.path, "rb") as f:
        resp = HttpResponse(f.read(), content_type="application/dicom")
        resp["Content-Disposition"] = f'attachment; filename="{os.path.basename(img.file_path.name)}"'
        return resp

@require_http_methods(["GET"])
@login_required
def api_cpp_dicom_info(request, instance_uid:str):
    img = get_object_or_404(DicomImage, sop_instance_uid=instance_uid)
    try:
        if hasattr(request.user, "is_facility_user") and request.user.is_facility_user() and getattr(request.user, "facility", None):
            if img.series.study.facility != request.user.facility:
                return JsonResponse({"error": "Permission denied"}, status=403)
    except Exception:
        return JsonResponse({"error": "Permission denied"}, status=403)
    if not img.file_path or not os.path.exists(img.file_path.path):
        return JsonResponse({"error": "DICOM file not found"}, status=404)
    try:
        ds = pydicom.dcmread(img.file_path.path, stop_before_pixels=True)
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
        return JsonResponse({"instance_uid": instance_uid, "dicom_info": info})
    except Exception:
        return JsonResponse({"error": "Cannot read DICOM metadata"}, status=500)

@require_http_methods(["GET"]) 
@login_required
def api_cpp_viewer_sessions(request):
    # Minimal stub for compatibility with C++ app
    return JsonResponse({"active_sessions": []})
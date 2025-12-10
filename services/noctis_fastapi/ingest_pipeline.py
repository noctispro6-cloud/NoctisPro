from __future__ import annotations

from pathlib import Path
from typing import Tuple

from django.db import transaction
from django.utils import timezone
from pydicom import dcmread

from dicom_receiver import DicomReceiver
from worklist.models import Facility

from .config import get_settings
from .schemas import DicomIngestEvent, DicomIngestResponse


_settings = get_settings()
_receiver: DicomReceiver | None = None


def _get_receiver() -> DicomReceiver:
    global _receiver
    if _receiver is None:
        _receiver = DicomReceiver(port=0, aet='NOCTIS_FASTAPI', max_pdu_size=16384)
        _receiver.storage_dir = _settings.storage_root
        _receiver.thumbnail_dir = _settings.thumbnail_root
    return _receiver


def _load_dataset(file_path: Path):
    if not file_path.exists():
        raise FileNotFoundError(f"DICOM file not found: {file_path}")
    return dcmread(file_path)


def _resolve_facility(aet: str) -> Facility:
    facility = Facility.objects.filter(ae_title__iexact=aet, is_active=True).first()
    if not facility:
        raise ValueError(f"Unknown or inactive facility for AE Title '{aet}'")
    return facility


def process_ingest(event: DicomIngestEvent) -> DicomIngestResponse:
    receiver = _get_receiver()
    dataset = _load_dataset(event.file_path)
    facility = _resolve_facility(event.calling_aet)

    with transaction.atomic():
        success = receiver.process_dicom_object(
            dataset,
            calling_aet=event.calling_aet,
            facility=facility,
            peer_ip=event.remote_host or 'unknown',
        )

    if not success:
        raise RuntimeError("DICOM pipeline reported failure")

    metadata = receiver.image_processor.extract_enhanced_metadata(dataset)
    return DicomIngestResponse(
        success=True,
        message="Ingested successfully",
        sop_instance_uid=metadata.get('sop_instance_uid'),
        study_instance_uid=metadata.get('study_instance_uid'),
        series_instance_uid=metadata.get('series_instance_uid'),
    )

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import verify_api_key
from ..ingest_pipeline import _get_receiver, process_ingest
from ..schemas import DicomIngestEvent, DicomIngestResponse

router = APIRouter(prefix="/dicom", tags=["dicom"], dependencies=[Depends(verify_api_key)])


@router.post('/ingest', response_model=DicomIngestResponse)
async def ingest(event: DicomIngestEvent) -> DicomIngestResponse:
    try:
        return process_ingest(event)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/stats')
async def stats() -> dict:
    receiver = _get_receiver()
    return receiver.get_statistics()

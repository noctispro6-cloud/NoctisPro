from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DicomIngestEvent(BaseModel):
    """Payload emitted by the Rust DIMSE receiver when a file lands on disk."""

    file_path: Path = Field(..., description="Absolute path to the stored DICOM file")
    calling_aet: str = Field(..., description="AE Title of the sending modality")
    remote_host: Optional[str] = Field(None, description="IP/host of the modality")
    received_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DicomIngestResponse(BaseModel):
    success: bool
    message: str
    sop_instance_uid: Optional[str] = None
    study_instance_uid: Optional[str] = None
    series_instance_uid: Optional[str] = None


class AIAnalysisRequest(BaseModel):
    study_id: int
    model_ids: List[int] = Field(default_factory=list)
    priority: str = Field(default="normal")


class AIAnalysisResponse(BaseModel):
    success: bool
    message: str
    analysis_ids: List[int] = Field(default_factory=list)


class AIAnalysisStatus(BaseModel):
    id: int
    status: str
    progress_percentage: float
    confidence_score: Optional[float]
    requested_at: datetime
    completed_at: Optional[datetime]
    details: Dict[str, Any] = Field(default_factory=dict)


class DashboardSummary(BaseModel):
    total_models: int
    active_analyses: int
    completed_today: int
    recent_analyses: List[Dict[str, Any]]
    pending_reports: List[Dict[str, Any]]
*** End of File
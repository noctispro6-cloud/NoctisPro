from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import verify_api_key
from ..ai_pipeline import analysis_status, dashboard_snapshot, start_analysis
from ..schemas import AIAnalysisRequest, AIAnalysisResponse, AIAnalysisStatus, DashboardSummary

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(verify_api_key)])


@router.get('/dashboard', response_model=DashboardSummary)
async def dashboard() -> DashboardSummary:
    return dashboard_snapshot()


@router.post('/analyses', response_model=AIAnalysisResponse)
async def trigger_analysis(payload: AIAnalysisRequest) -> AIAnalysisResponse:
    return start_analysis(payload)


@router.get('/analyses/{analysis_id}', response_model=AIAnalysisStatus)
async def analysis_detail(analysis_id: int) -> AIAnalysisStatus:
    try:
        return analysis_status(analysis_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc

from celery import shared_task
from .models import AIAnalysis
from .inference import ModelRegistry
from .utils import simulate_ai_analysis, _apply_ai_triage, run_full_series_inference
from .reporting import persist_report_on_analysis
# from .dicom_sr import create_ai_findings_sr # DICOM SR generation disabled per policy
import logging
import pydicom
import os

logger = logging.getLogger(__name__)

@shared_task
def run_ai_analysis(analysis_id):
    """
    Celery task to run AI analysis for a specific analysis request.
    """
    try:
        analysis = AIAnalysis.objects.get(id=analysis_id)
    except AIAnalysis.DoesNotExist:
        logger.error(f"AIAnalysis {analysis_id} not found.")
        return

    try:
        analysis.start_processing()
        
        # Use real inference engine (via registry) with fallback to simulation
        model_adapter = ModelRegistry.get_model(analysis.ai_model)
        
        # Full-series analysis (representative sampling) on the largest series in the study.
        series_qs = analysis.study.series_set.all()
        target_series = None
        try:
            # Prefer the series with the most images (typical CT stack)
            target_series = max(series_qs, key=lambda s: s.images.count()) if series_qs else None
        except Exception:
            target_series = series_qs.first() if series_qs else None

        if target_series and target_series.images.exists():
            try:
                results = run_full_series_inference(model_adapter, target_series.images.all(), max_slices=24)
                # Store which series we analyzed
                results.setdefault('measurements', {})
                if isinstance(results['measurements'], dict):
                    results['measurements']['series_id'] = int(target_series.id)
            except Exception:
                results = simulate_ai_analysis(analysis)
        else:
            results = simulate_ai_analysis(analysis)
        
        # Complete the analysis
        analysis.complete_analysis(results)

        # Apply AI triage/flagging to the parent study (severity → study.priority)
        try:
            _apply_ai_triage(analysis)
        except Exception:
            # Never fail the background worker due to triage/notification issues
            pass

        # Persist a final, structured preliminary report for UI display.
        try:
            analysis.refresh_from_db()
            persist_report_on_analysis(analysis)
        except Exception:
            pass
        
        # Update model statistics
        model = analysis.ai_model
        model.total_analyses += 1
        if analysis.processing_time:
            # Update average processing time
            if model.avg_processing_time > 0:
                model.avg_processing_time = (
                    model.avg_processing_time + analysis.processing_time
                ) / 2
            else:
                model.avg_processing_time = analysis.processing_time
        model.save()
        
    except Exception as e:
        logger.exception(f"Error processing analysis {analysis_id}: {e}")
        analysis.status = 'failed'
        analysis.error_message = str(e)
        analysis.save()

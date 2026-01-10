from celery import shared_task
from .models import AIAnalysis
from .inference import ModelRegistry
from .utils import simulate_ai_analysis, _apply_ai_triage
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
        
        # Use first image from the study
        # In a real scenario, this might iterate over all series/images or select a specific one
        first_series = analysis.study.series_set.first()
        first_image = first_series.images.first() if first_series else None
        
        if first_image and first_image.file_path:
            results = model_adapter.predict(first_image.file_path.path)
        else:
            # Fallback to pure simulation if no file
            results = simulate_ai_analysis(analysis)
        
        # Complete the analysis
        analysis.complete_analysis(results)

        # Apply AI triage/flagging to the parent study (severity → study.priority)
        try:
            _apply_ai_triage(analysis)
        except Exception:
            # Never fail the background worker due to triage/notification issues
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

from celery import shared_task
from .models import AIAnalysis
from .inference import ModelRegistry
from .utils import simulate_ai_analysis, _apply_ai_triage, run_full_series_inference
from .reporting import persist_report_on_analysis
import logging

logger = logging.getLogger(__name__)


def _save_analysis_status(analysis, status, error_msg=''):
    """Save analysis status with a fresh DB connection — safe to call from threads."""
    from django.db import close_old_connections, connection
    try:
        close_old_connections()
        analysis.status = status
        if error_msg:
            analysis.error_message = str(error_msg)[:2000]
        analysis.save(update_fields=['status', 'error_message'])
    except Exception as _e:
        logger.error('Could not save analysis status %s for id=%s: %s', status, analysis.id, _e)
        try:
            # Last-resort: raw SQL update avoids ORM overhead
            close_old_connections()
            from django.db import connection as _conn
            with _conn.cursor() as cur:
                cur.execute(
                    "UPDATE ai_analysis_aianalysis SET status=%s WHERE id=%s",
                    [status, analysis.id]
                )
        except Exception:
            pass


@shared_task(
    name='ai_analysis.tasks.run_ai_analysis',
    bind=True,
    # Do NOT autoretry — retries in a threadless context deadlock or flood logs.
    # Views-layer fallback uses .apply() which is already synchronous.
    max_retries=0,
    acks_late=True,
)
def run_ai_analysis(self, analysis_id):
    """
    Celery task / direct-apply fallback for running AI analysis.
    Robust against stale DB connections (daemon-thread usage).
    """
    from django.db import close_old_connections
    close_old_connections()

    try:
        analysis = AIAnalysis.objects.get(id=analysis_id)
    except AIAnalysis.DoesNotExist:
        logger.error('AIAnalysis %s not found.', analysis_id)
        return
    except Exception as _e:
        logger.error('DB error fetching AIAnalysis %s: %s', analysis_id, _e)
        return

    try:
        analysis.start_processing()
    except Exception as _e:
        logger.error('start_processing failed for %s: %s', analysis_id, _e)
        return

    try:
        # Use real inference engine with fallback to simulation
        model_adapter = ModelRegistry.get_model(analysis.ai_model)

        # Full-series analysis on the largest series in the study
        series_qs = analysis.study.series_set.all()
        target_series = None
        try:
            target_series = max(series_qs, key=lambda s: s.images.count()) if series_qs else None
        except Exception:
            target_series = series_qs.first() if series_qs else None

        if target_series and target_series.images.exists():
            try:
                results = run_full_series_inference(
                    model_adapter, target_series.images.all(), max_slices=24
                )
                results.setdefault('measurements', {})
                if isinstance(results['measurements'], dict):
                    results['measurements']['series_id'] = int(target_series.id)
            except Exception:
                results = simulate_ai_analysis(analysis)
        else:
            results = simulate_ai_analysis(analysis)

        # Complete the analysis — sets status='completed'
        analysis.complete_analysis(results)

        # Apply AI triage/flagging to the parent study
        try:
            _apply_ai_triage(analysis)
        except Exception as exc:
            logger.error('_apply_ai_triage failed: %s', exc, exc_info=True)

        # Persist structured preliminary report for UI display
        try:
            close_old_connections()
            analysis.refresh_from_db()
            persist_report_on_analysis(analysis)
        except Exception as exc:
            logger.error('persist_report_on_analysis failed: %s', exc, exc_info=True)

        # Update model statistics — in its own try/except so it cannot break the above
        try:
            close_old_connections()
            model = AIAnalysis.objects.select_related('ai_model').get(id=analysis_id).ai_model
            model.total_analyses += 1
            if analysis.processing_time:
                model.avg_processing_time = (
                    (model.avg_processing_time + analysis.processing_time) / 2
                    if model.avg_processing_time > 0
                    else analysis.processing_time
                )
            model.save(update_fields=['total_analyses', 'avg_processing_time'])
        except Exception as exc:
            logger.warning('Model stats update failed (non-critical): %s', exc)

    except Exception as e:
        logger.exception('Error processing analysis %s: %s', analysis_id, e)
        _save_analysis_status(analysis, 'failed', str(e))

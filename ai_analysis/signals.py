from django.db.models.signals import post_save
from django.dispatch import receiver
from notifications.models import Notification
from worklist.models import Study
from .models import AIModel, AIAnalysis
from .views import process_ai_analyses
import threading
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Notification)
def trigger_ai_analysis_on_upload(sender, instance, created, **kwargs):
    """
    Trigger AI analysis when a 'new_study' notification is created or updated.
    This effectively acts as a 'study uploaded' hook.
    """
    try:
        # Check if it's a new study notification
        if not instance.notification_type or instance.notification_type.code != 'new_study':
            return

        study = instance.study
        if not study:
            return

        # Find active AI models for this modality
        modality_code = getattr(study.modality, 'code', None)
        if not modality_code:
            return
            
        # Select all active models for the modality
        ai_models = AIModel.objects.filter(
            is_active=True, 
            modality__in=[modality_code, 'ALL']
        )
        
        if not ai_models.exists():
            return

        analyses_to_run = []
        for ai_model in ai_models:
            # Check if analysis already exists/running to avoid duplicates
            existing = AIAnalysis.objects.filter(
                study=study,
                ai_model=ai_model,
                status__in=['pending', 'processing', 'completed']
            ).exists()
            
            if existing:
                continue
                
            # Create new analysis
            # We use 'normal' priority for auto-analysis, but if it flags as urgent, 
            # the _apply_ai_triage will handle the escalation.
            analysis = AIAnalysis.objects.create(
                study=study,
                ai_model=ai_model,
                priority='normal',
                status='pending'
            )
            analyses_to_run.append(analysis)
        
        if analyses_to_run:
            logger.info(f"Triggering auto-analysis for Study {study.accession_number} with {len(analyses_to_run)} models.")
            # Run in background
            threading.Thread(
                target=process_ai_analyses,
                args=(analyses_to_run,),
                daemon=True
            ).start()
            
    except Exception as e:
        logger.error(f"Error triggering AI analysis for notification {instance.id}: {e}")

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from notifications.models import Notification
from worklist.models import Study
from .models import AIModel, AIAnalysis, AIFeedback, AITrainingData
from .tasks import run_ai_analysis
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=AIFeedback)
def handle_ai_feedback(sender, instance, created, **kwargs):
    """
    Process AI feedback for active learning loop.
    If feedback indicates an error (False Positive/Negative), 
    automatically flag the study/data for retraining.
    """
    if not created:
        return

    try:
        # Check if feedback indicates model failure
        if instance.feedback_type in ['false_positive', 'false_negative'] or instance.rating <= 2:
            logger.info(f"Negative feedback received for Analysis {instance.ai_analysis.id}. Flagging for retraining.")
            
            # Create Training Data entry
            # In a real system, we might copy the specific image or mask here
            # For now, we link the study/image from the analysis
            
            analysis = instance.ai_analysis
            # Attempt to find the image used (currently we just grab the first image of the study as per inference logic)
            image = analysis.study.series_set.first().images.first() if analysis.study.series_set.exists() else None
            
            if image:
                AITrainingData.objects.create(
                    ai_model=analysis.ai_model,
                    study=analysis.study,
                    image=image,
                    data_type='image',
                    ground_truth_labels={
                        'feedback_type': instance.feedback_type,
                        'user_correction': instance.comments,
                        'incorrect_findings': instance.incorrect_findings,
                        'missed_findings': instance.missed_findings
                    },
                    validation_notes=f"Auto-flagged from feedback #{instance.id} by {instance.user.username}",
                    is_validated=False, # Needs data scientist review
                    used_in_training=False
                )
    except Exception as e:
        logger.error(f"Error handling feedback signal: {e}")

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
            # Subscription check for auto-analysis
            if ai_model.requires_subscription:
                if not study.facility or not study.facility.has_ai_subscription:
                    continue
                if study.facility.subscription_expires_at and study.facility.subscription_expires_at < timezone.now():
                    continue

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
            # Run in background via Celery
            for analysis in analyses_to_run:
                run_ai_analysis.delay(analysis.id)
            
    except Exception as e:
        logger.error(f"Error triggering AI analysis for notification {instance.id}: {e}")

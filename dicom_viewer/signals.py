"""
Signals for the DICOM viewer app.

Auto-triggers ML bone reconstruction when a new CT study notification arrives,
provided the series has enough slices for a clinically useful 3D model.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

_CT_MODALITIES = {'CT', 'CTA', 'CBCT'}
_MIN_SLICES = 16   # minimum axial slices for meaningful reconstruction


@receiver(post_save, sender='notifications.Notification')
def _auto_bone_on_new_study(sender, instance, created, **kwargs):
    """Queue ML bone reconstruction when a new CT study arrives."""
    if not created:
        return

    try:
        ntype = getattr(instance, 'notification_type', None)
        if not ntype or getattr(ntype, 'code', None) != 'new_study':
            return

        study = getattr(instance, 'study', None)
        if not study:
            return

        modality_code = getattr(study.modality, 'code', '').upper().strip()
        if modality_code not in _CT_MODALITIES:
            return

        # Pick the series with the most images (most clinically complete)
        best = None
        best_count = 0
        for series in study.series_set.all():
            cnt = series.images.count()
            if cnt >= _MIN_SLICES and cnt > best_count:
                best = series
                best_count = cnt

        if best is None:
            logger.debug(
                'auto_bone signal: study %s has no CT series with >= %d slices',
                study.accession_number, _MIN_SLICES,
            )
            return

        from dicom_viewer.tasks import auto_bone_reconstruction
        # Try Celery first; fall back to a background thread when Redis/broker is unavailable.
        try:
            auto_bone_reconstruction.delay(best.id)
            logger.info(
                'auto_bone signal: queued (Celery) series %d (study %s, %d slices)',
                best.id, study.accession_number, best_count,
            )
        except Exception:
            import threading
            def _run():
                try:
                    auto_bone_reconstruction(best.id)
                except Exception as _e:
                    logger.error('auto_bone background thread failed: %s', _e)
            threading.Thread(target=_run, daemon=True).start()
            logger.info(
                'auto_bone signal: started background thread series %d (study %s, %d slices)',
                best.id, study.accession_number, best_count,
            )

    except Exception as exc:
        logger.error('auto_bone signal error: %s', exc, exc_info=True)

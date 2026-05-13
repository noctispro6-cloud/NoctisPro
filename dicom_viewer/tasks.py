"""
Background Celery tasks for DICOM viewer — 3D bone reconstruction.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name='dicom_viewer.tasks.auto_bone_reconstruction',
    bind=True,
    max_retries=1,
    acks_late=True,
)
def auto_bone_reconstruction(self, series_id: int):
    """
    Auto-run ML bone segmentation + marching-cubes mesh on a CT series.

    The ML engine isolates bone voxels; it never modifies the DICOM pixel data.
    Fractures appear as discontinuities (gaps) in the mesh — this is correct
    clinical behaviour and must not be smoothed away.
    """
    from django.db import close_old_connections
    close_old_connections()

    try:
        from worklist.models import Series
        from dicom_viewer.models import ReconstructionJob
        from django.contrib.auth import get_user_model

        series = Series.objects.select_related('study').get(id=series_id)
        User = get_user_model()

        system_user = (
            User.objects.filter(is_superuser=True).first()
            or User.objects.first()
        )
        if system_user is None:
            logger.error('auto_bone_reconstruction: no users in DB, aborting')
            return

        # Idempotency guard
        if ReconstructionJob.objects.filter(
            series=series,
            job_type='bone_3d',
            status__in=['pending', 'processing', 'completed'],
        ).exists():
            logger.info(
                'auto_bone_reconstruction: job already exists for series %d, skipping',
                series_id,
            )
            return

        job = ReconstructionJob(user=system_user, series=series, job_type='bone_3d')
        job.set_parameters({
            'threshold': 300,
            'smoothing': True,
            'decimation': 0.7,
            'use_ml': True,
            'auto_triggered': True,
        })
        job.save()

        job.status = 'processing'
        job.save(update_fields=['status'])

        from dicom_viewer.reconstruction import Bone3DProcessor
        result_path = Bone3DProcessor().process_series(series, job.get_parameters())

        from django.utils import timezone
        job.status = 'completed'
        job.result_path = result_path or ''
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'result_path', 'completed_at'])
        logger.info('auto_bone_reconstruction: done series=%d path=%s', series_id, result_path)

    except Exception as exc:
        logger.exception('auto_bone_reconstruction failed for series %d', series_id)
        try:
            from dicom_viewer.models import ReconstructionJob
            ReconstructionJob.objects.filter(
                series_id=series_id,
                status='processing',
                job_type='bone_3d',
            ).update(status='failed', error_message=str(exc)[:2000])
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30)

"""Celery tasks for the noctis_pro core app."""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='noctis_pro.tasks.run_backup', bind=True, max_retries=2)
def run_backup(self, db_only=False, media_only=False):
    """Run the backup_system management command as a Celery task."""
    try:
        from django.core.management import call_command
        call_command('backup_system', db_only=db_only, media_only=media_only)
        logger.info(
            'Backup completed successfully (db_only=%s, media_only=%s)',
            db_only, media_only,
        )
    except Exception as exc:
        logger.error('Backup failed: %s', exc)
        raise self.retry(exc=exc, countdown=300)  # retry after 5 minutes

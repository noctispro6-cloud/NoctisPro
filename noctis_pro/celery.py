import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'noctis_pro.settings')

app = Celery('noctis_pro')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')


from celery.schedules import crontab  # noqa: E402
app.conf.beat_schedule = {
    'daily-database-backup': {
        'task': 'noctis_pro.tasks.run_backup',
        'schedule': crontab(hour=2, minute=0),  # 2 AM daily
        'kwargs': {'db_only': True},
    },
    'weekly-full-backup': {
        'task': 'noctis_pro.tasks.run_backup',
        'schedule': crontab(hour=3, minute=0, day_of_week='sunday'),  # 3 AM Sunday
        'kwargs': {},
    },
}

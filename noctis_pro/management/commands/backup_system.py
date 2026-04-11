"""
Management command: backup_system
Creates a compressed backup of the database and media files.
Usage:
  python manage.py backup_system
  python manage.py backup_system --db-only
  python manage.py backup_system --media-only
"""
import os
import tarfile
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Create a backup of the database and/or media files'

    def add_arguments(self, parser):
        parser.add_argument('--db-only', action='store_true', help='Back up database only')
        parser.add_argument('--media-only', action='store_true', help='Back up media only')
        parser.add_argument('--output', help='Output directory (default: BACKUP_ROOT setting)')

    def handle(self, *args, **options):
        backup_root = options.get('output') or getattr(settings, 'BACKUP_ROOT', None)
        if not backup_root:
            backup_root = os.path.join(settings.BASE_DIR, 'backups')

        os.makedirs(backup_root, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        db_only = options['db_only']
        media_only = options['media_only']

        errors = []
        created_files = []

        if not media_only:
            db_file = self._backup_database(backup_root, timestamp, errors)
            if db_file:
                created_files.append(db_file)

        if not db_only:
            media_file = self._backup_media(backup_root, timestamp, errors)
            if media_file:
                created_files.append(media_file)

        self._apply_retention(backup_root)

        if errors:
            for e in errors:
                self.stderr.write(self.style.ERROR(e))
        if created_files:
            for f in created_files:
                self.stdout.write(self.style.SUCCESS(f'Backup created: {f}'))

        return 0 if not errors else 1

    def _backup_database(self, backup_root, timestamp, errors):
        db_settings = settings.DATABASES.get('default', {})
        engine = db_settings.get('ENGINE', '')
        fname = os.path.join(backup_root, f'db_{timestamp}.sql.gz')

        try:
            if 'postgresql' in engine or 'postgis' in engine:
                env = os.environ.copy()
                if db_settings.get('PASSWORD'):
                    env['PGPASSWORD'] = db_settings['PASSWORD']
                cmd = [
                    'pg_dump',
                    '-h', db_settings.get('HOST', 'localhost'),
                    '-p', str(db_settings.get('PORT', 5432)),
                    '-U', db_settings.get('USER', 'postgres'),
                    db_settings.get('NAME', 'postgres'),
                ]
                import gzip
                proc = subprocess.run(cmd, capture_output=True, env=env)
                if proc.returncode != 0:
                    errors.append(f'pg_dump failed: {proc.stderr.decode()}')
                    return None
                with gzip.open(fname, 'wb') as gf:
                    gf.write(proc.stdout)
            else:
                # SQLite
                db_path = str(db_settings.get('NAME', settings.BASE_DIR / 'db.sqlite3'))
                import gzip
                with open(db_path, 'rb') as f_in:
                    with gzip.open(fname, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
        except Exception as e:
            errors.append(f'Database backup error: {e}')
            return None
        return fname

    def _backup_media(self, backup_root, timestamp, errors):
        media_root = str(settings.MEDIA_ROOT)
        if not os.path.exists(media_root):
            return None
        fname = os.path.join(backup_root, f'media_{timestamp}.tar.gz')
        try:
            with tarfile.open(fname, 'w:gz') as tar:
                tar.add(media_root, arcname='media')
        except Exception as e:
            errors.append(f'Media backup error: {e}')
            return None
        return fname

    def _apply_retention(self, backup_root):
        retention_days = getattr(settings, 'BACKUP_RETENTION_DAYS', 30)
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=retention_days)
        for fname in os.listdir(backup_root):
            fpath = os.path.join(backup_root, fname)
            if os.path.isfile(fpath):
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    os.remove(fpath)
                    self.stdout.write(f'Removed old backup: {fname}')

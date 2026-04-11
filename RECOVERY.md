# Noctis Pro PACS — Recovery Procedures

## Database Recovery

### From SQL dump (PostgreSQL)
```bash
gunzip -c /path/to/backups/db_YYYYMMDD_HHMMSS.sql.gz | psql -h HOST -U USER -d DB_NAME
```

### From SQLite backup
```bash
gunzip -c /path/to/backups/db_YYYYMMDD_HHMMSS.sql.gz > db.sqlite3
```

## Media Files Recovery
```bash
tar -xzf /path/to/backups/media_YYYYMMDD_HHMMSS.tar.gz -C /opt/noctispro/
```

## Full System Recovery Steps
1. Stop the running application
2. Restore the database (see above)
3. Restore media files (see above)
4. Run migrations: `python manage.py migrate`
5. Collect static files: `python manage.py collectstatic --noinput`
6. Restart the application

## Running a Manual Backup
```bash
python manage.py backup_system           # full backup
python manage.py backup_system --db-only # database only
python manage.py backup_system --media-only # media only
```

## Automated Backups
Backups run automatically via Celery Beat:
- Daily at 2 AM: database-only backup
- Sunday at 3 AM: full backup (database + media)

See `BACKUP_ROOT` and `BACKUP_RETENTION_DAYS` in settings or `.env.example`.

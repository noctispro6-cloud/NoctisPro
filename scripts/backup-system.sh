#!/bin/bash

# NOCTIS Pro - System Backup Script
# Creates comprehensive backups of the NOCTIS Pro system

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NOCTIS_DIR="/opt/noctis"
BACKUP_DIR="$NOCTIS_DIR/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="noctis_backup_$DATE"
RETENTION_DAYS=30
COMPOSE_FILE="$NOCTIS_DIR/docker-compose.production.yml"

# Logging functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$BACKUP_DIR/backup.log"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}" | tee -a "$BACKUP_DIR/backup.log"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" | tee -a "$BACKUP_DIR/backup.log"
}

# Check prerequisites
check_prerequisites() {
    log "Checking backup prerequisites..."
    
    # Check if NOCTIS directory exists
    if [ ! -d "$NOCTIS_DIR" ]; then
        error "NOCTIS directory not found: $NOCTIS_DIR"
        exit 1
    fi
    
    # Check if compose file exists
    if [ ! -f "$COMPOSE_FILE" ]; then
        error "Docker compose file not found: $COMPOSE_FILE"
        exit 1
    fi
    
    # Create backup directory if it doesn't exist
    mkdir -p "$BACKUP_DIR"
    
    # Check available disk space
    available_space=$(df "$BACKUP_DIR" | awk 'NR==2 {print $4}')
    required_space=1048576  # 1GB in KB
    
    if [ "$available_space" -lt "$required_space" ]; then
        warn "Low disk space. Available: $(($available_space/1024))MB, Recommended: 1GB+"
    fi
    
    log "Prerequisites check completed"
}

# Create backup directory structure
create_backup_structure() {
    log "Creating backup structure..."
    
    mkdir -p "$BACKUP_DIR/$BACKUP_NAME"/{database,media,dicom_storage,config,logs,system}
    
    log "Backup structure created: $BACKUP_DIR/$BACKUP_NAME"
}

# Backup database
backup_database() {
    log "Backing up PostgreSQL database..."
    
    cd "$NOCTIS_DIR"
    
    # Check if database service is running
    if ! docker compose -f docker-compose.production.yml ps db | grep -q "Up"; then
        warn "Database service is not running. Starting it..."
        docker compose -f docker-compose.production.yml up -d db
        sleep 10
    fi
    
    # Create database dump
    docker compose -f docker-compose.production.yml exec -T db pg_dump -U noctis_user noctis_pro > "$BACKUP_DIR/$BACKUP_NAME/database/database.sql"
    
    # Create compressed version
    gzip -c "$BACKUP_DIR/$BACKUP_NAME/database/database.sql" > "$BACKUP_DIR/$BACKUP_NAME/database/database.sql.gz"
    
    # Create schema-only dump
    docker compose -f docker-compose.production.yml exec -T db pg_dump -U noctis_user noctis_pro --schema-only > "$BACKUP_DIR/$BACKUP_NAME/database/schema.sql"
    
    # Get database statistics
    docker compose -f docker-compose.production.yml exec -T db psql -U noctis_user noctis_pro -c "SELECT schemaname,tablename,n_tup_ins,n_tup_upd,n_tup_del FROM pg_stat_user_tables;" > "$BACKUP_DIR/$BACKUP_NAME/database/stats.txt"
    
    db_size=$(du -sh "$BACKUP_DIR/$BACKUP_NAME/database" | cut -f1)
    log "Database backup completed: $db_size"
}

# Backup Redis data
backup_redis() {
    log "Backing up Redis data..."
    
    cd "$NOCTIS_DIR"
    
    # Check if Redis service is running
    if docker compose -f docker-compose.production.yml ps redis | grep -q "Up"; then
        # Force Redis to save current state
        docker compose -f docker-compose.production.yml exec redis redis-cli BGSAVE
        sleep 5
        
        # Copy Redis dump file
        docker cp $(docker compose -f docker-compose.production.yml ps -q redis):/data/dump.rdb "$BACKUP_DIR/$BACKUP_NAME/database/redis_dump.rdb" 2>/dev/null || warn "Redis dump file not found"
        
        # Get Redis info
        docker compose -f docker-compose.production.yml exec redis redis-cli INFO > "$BACKUP_DIR/$BACKUP_NAME/database/redis_info.txt"
    else
        warn "Redis service is not running. Skipping Redis backup."
    fi
    
    log "Redis backup completed"
}

# Backup media files
backup_media() {
    log "Backing up media files..."
    
    if [ -d "$NOCTIS_DIR/data/media" ] && [ "$(ls -A $NOCTIS_DIR/data/media)" ]; then
        cp -r "$NOCTIS_DIR/data/media"/* "$BACKUP_DIR/$BACKUP_NAME/media/"
        media_size=$(du -sh "$BACKUP_DIR/$BACKUP_NAME/media" | cut -f1)
        log "Media files backup completed: $media_size"
    else
        log "No media files to backup"
        touch "$BACKUP_DIR/$BACKUP_NAME/media/.gitkeep"
    fi
}

# Backup DICOM storage
backup_dicom() {
    log "Backing up DICOM storage..."
    
    if [ -d "$NOCTIS_DIR/data/dicom_storage" ] && [ "$(ls -A $NOCTIS_DIR/data/dicom_storage)" ]; then
        cp -r "$NOCTIS_DIR/data/dicom_storage"/* "$BACKUP_DIR/$BACKUP_NAME/dicom_storage/"
        dicom_size=$(du -sh "$BACKUP_DIR/$BACKUP_NAME/dicom_storage" | cut -f1)
        log "DICOM storage backup completed: $dicom_size"
    else
        log "No DICOM files to backup"
        touch "$BACKUP_DIR/$BACKUP_NAME/dicom_storage/.gitkeep"
    fi
}

# Backup configuration files
backup_config() {
    log "Backing up configuration files..."
    
    # Copy Docker compose files
    [ -f "$NOCTIS_DIR/docker-compose.production.yml" ] && cp "$NOCTIS_DIR/docker-compose.production.yml" "$BACKUP_DIR/$BACKUP_NAME/config/"
    [ -f "$NOCTIS_DIR/docker-compose.yml" ] && cp "$NOCTIS_DIR/docker-compose.yml" "$BACKUP_DIR/$BACKUP_NAME/config/"
    
    # Copy environment files (without sensitive data)
    if [ -f "$NOCTIS_DIR/.env" ]; then
        # Create sanitized version without passwords
        grep -v "PASSWORD\|SECRET\|KEY" "$NOCTIS_DIR/.env" > "$BACKUP_DIR/$BACKUP_NAME/config/env_template.txt" || true
    fi
    
    # Copy scripts
    if [ -d "$NOCTIS_DIR/scripts" ]; then
        cp -r "$NOCTIS_DIR/scripts" "$BACKUP_DIR/$BACKUP_NAME/config/"
    fi
    
    # Copy deployment configurations
    if [ -d "$NOCTIS_DIR/deployment" ]; then
        cp -r "$NOCTIS_DIR/deployment" "$BACKUP_DIR/$BACKUP_NAME/config/"
    fi
    
    # Copy SSL certificates (if any)
    if [ -d "$NOCTIS_DIR/ssl" ]; then
        cp -r "$NOCTIS_DIR/ssl" "$BACKUP_DIR/$BACKUP_NAME/config/"
    fi
    
    log "Configuration backup completed"
}

# Backup logs
backup_logs() {
    log "Backing up application logs..."
    
    # Copy application logs
    if [ -d "$NOCTIS_DIR/logs" ]; then
        find "$NOCTIS_DIR/logs" -name "*.log" -mtime -7 -exec cp {} "$BACKUP_DIR/$BACKUP_NAME/logs/" \; 2>/dev/null || true
    fi
    
    # Export Docker container logs
    cd "$NOCTIS_DIR"
    docker compose -f docker-compose.production.yml logs --since 7d web > "$BACKUP_DIR/$BACKUP_NAME/logs/web.log" 2>/dev/null || true
    docker compose -f docker-compose.production.yml logs --since 7d celery > "$BACKUP_DIR/$BACKUP_NAME/logs/celery.log" 2>/dev/null || true
    docker compose -f docker-compose.production.yml logs --since 7d dicom_receiver > "$BACKUP_DIR/$BACKUP_NAME/logs/dicom_receiver.log" 2>/dev/null || true
    docker compose -f docker-compose.production.yml logs --since 7d db > "$BACKUP_DIR/$BACKUP_NAME/logs/database.log" 2>/dev/null || true
    docker compose -f docker-compose.production.yml logs --since 7d redis > "$BACKUP_DIR/$BACKUP_NAME/logs/redis.log" 2>/dev/null || true
    
    log "Logs backup completed"
}

# Backup system information
backup_system_info() {
    log "Collecting system information..."
    
    # System information
    cat > "$BACKUP_DIR/$BACKUP_NAME/system/system_info.txt" <<EOF
NOCTIS Pro System Backup Information
===================================

Backup Date: $(date)
Backup Name: $BACKUP_NAME
System: $(uname -a)
Docker Version: $(docker --version)
Docker Compose Version: $(docker compose version)
Disk Usage: $(df -h)

Services Status:
$(cd "$NOCTIS_DIR" && docker compose -f docker-compose.production.yml ps)

Container Information:
$(docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}")

Network Information:
$(docker network ls)

Volume Information:
$(docker volume ls)

Memory Usage:
$(free -h)

CPU Information:
$(lscpu | head -10)
EOF

    # Docker system information
    docker system df > "$BACKUP_DIR/$BACKUP_NAME/system/docker_system.txt"
    docker images > "$BACKUP_DIR/$BACKUP_NAME/system/docker_images.txt"
    
    # Network configuration
    ip addr show > "$BACKUP_DIR/$BACKUP_NAME/system/network.txt"
    
    log "System information collected"
}

# Create backup manifest
create_manifest() {
    log "Creating backup manifest..."
    
    cat > "$BACKUP_DIR/$BACKUP_NAME/MANIFEST.txt" <<EOF
NOCTIS Pro Backup Manifest
=========================

Backup Information:
- Name: $BACKUP_NAME
- Date: $(date)
- Type: Full System Backup
- Retention: $RETENTION_DAYS days

Components Included:
- Database: PostgreSQL dump (SQL and compressed)
- Redis: Data dump and configuration
- Media Files: User uploaded content
- DICOM Storage: Medical imaging files
- Configuration: Docker compose files and scripts
- Logs: Application and system logs (last 7 days)
- System Info: Server and container status

File Structure:
├── database/
│   ├── database.sql          # Full database dump
│   ├── database.sql.gz       # Compressed database dump
│   ├── schema.sql           # Database schema only
│   ├── stats.txt            # Database statistics
│   └── redis_dump.rdb       # Redis data dump
├── media/                   # User uploaded files
├── dicom_storage/          # DICOM medical images
├── config/                 # Configuration files
│   ├── docker-compose.production.yml
│   ├── scripts/
│   └── deployment/
├── logs/                   # Application logs
├── system/                 # System information
└── MANIFEST.txt           # This file

Backup Statistics:
- Database Size: $(du -sh "$BACKUP_DIR/$BACKUP_NAME/database" 2>/dev/null | cut -f1 || echo 'Unknown')
- Media Size: $(du -sh "$BACKUP_DIR/$BACKUP_NAME/media" 2>/dev/null | cut -f1 || echo 'Unknown')
- DICOM Size: $(du -sh "$BACKUP_DIR/$BACKUP_NAME/dicom_storage" 2>/dev/null | cut -f1 || echo 'Unknown')
- Config Size: $(du -sh "$BACKUP_DIR/$BACKUP_NAME/config" 2>/dev/null | cut -f1 || echo 'Unknown')
- Logs Size: $(du -sh "$BACKUP_DIR/$BACKUP_NAME/logs" 2>/dev/null | cut -f1 || echo 'Unknown')
- System Size: $(du -sh "$BACKUP_DIR/$BACKUP_NAME/system" 2>/dev/null | cut -f1 || echo 'Unknown')
- Total Size: $(du -sh "$BACKUP_DIR/$BACKUP_NAME" 2>/dev/null | cut -f1 || echo 'Unknown')

Restore Instructions:
1. Extract backup to temporary location
2. Run: ./scripts/restore-system.sh $BACKUP_NAME.tar.gz
3. Follow the restore script instructions

Notes:
- This backup can be used for disaster recovery
- Sensitive data (passwords, keys) are not included in config backup
- For full restoration, ensure target system has same or compatible setup
EOF

    log "Backup manifest created"
}

# Create compressed archive
create_archive() {
    log "Creating compressed archive..."
    
    cd "$BACKUP_DIR"
    tar -czf "$BACKUP_NAME.tar.gz" "$BACKUP_NAME"
    
    # Calculate checksums
    sha256sum "$BACKUP_NAME.tar.gz" > "$BACKUP_NAME.tar.gz.sha256"
    md5sum "$BACKUP_NAME.tar.gz" > "$BACKUP_NAME.tar.gz.md5"
    
    # Remove uncompressed directory
    rm -rf "$BACKUP_NAME"
    
    archive_size=$(du -sh "$BACKUP_NAME.tar.gz" | cut -f1)
    log "Archive created: $BACKUP_NAME.tar.gz ($archive_size)"
}

# Clean old backups
cleanup_old_backups() {
    log "Cleaning up old backups (older than $RETENTION_DAYS days)..."
    
    deleted_count=0
    while IFS= read -r -d '' backup_file; do
        rm -f "$backup_file" "$backup_file.sha256" "$backup_file.md5"
        deleted_count=$((deleted_count + 1))
        log "Deleted old backup: $(basename "$backup_file")"
    done < <(find "$BACKUP_DIR" -name "noctis_backup_*.tar.gz" -mtime +$RETENTION_DAYS -print0)
    
    if [ $deleted_count -eq 0 ]; then
        log "No old backups to clean up"
    else
        log "Cleaned up $deleted_count old backup(s)"
    fi
}

# Send notification (if configured)
send_notification() {
    if [ -n "$BACKUP_NOTIFICATION_EMAIL" ]; then
        archive_size=$(du -sh "$BACKUP_DIR/$BACKUP_NAME.tar.gz" | cut -f1)
        
        # Simple email notification (requires mail command)
        if command -v mail &> /dev/null; then
            echo "NOCTIS Pro backup completed successfully.
            
Backup: $BACKUP_NAME.tar.gz
Size: $archive_size
Date: $(date)
Location: $BACKUP_DIR

This is an automated notification." | mail -s "NOCTIS Pro Backup Completed" "$BACKUP_NOTIFICATION_EMAIL"
            
            log "Notification sent to $BACKUP_NOTIFICATION_EMAIL"
        fi
    fi
}

# Main backup function
main() {
    log "Starting NOCTIS Pro system backup..."
    
    check_prerequisites
    create_backup_structure
    backup_database
    backup_redis
    backup_media
    backup_dicom
    backup_config
    backup_logs
    backup_system_info
    create_manifest
    create_archive
    cleanup_old_backups
    send_notification
    
    log ""
    log "Backup completed successfully!"
    log ""
    log "Backup Details:"
    log "- Archive: $BACKUP_DIR/$BACKUP_NAME.tar.gz"
    log "- Size: $(du -sh $BACKUP_DIR/$BACKUP_NAME.tar.gz | cut -f1)"
    log "- SHA256: $(cat $BACKUP_DIR/$BACKUP_NAME.tar.gz.sha256 | cut -d' ' -f1)"
    log ""
    log "Available Backups:"
    ls -lah "$BACKUP_DIR"/noctis_backup_*.tar.gz 2>/dev/null | tail -5 || log "No previous backups found"
    log ""
    log "To restore this backup:"
    log "./scripts/restore-system.sh $BACKUP_DIR/$BACKUP_NAME.tar.gz"
}

# Handle script interruption
trap 'error "Backup interrupted"; exit 1' INT TERM

# Run main function
main "$@"
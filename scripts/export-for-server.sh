#!/bin/bash

# NOCTIS Pro - Export Data for Server Transfer
# This script exports all data from desktop development environment for server deployment

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
EXPORT_DIR="./noctis-export-$(date +%Y%m%d_%H%M%S)"
COMPOSE_FILE="docker-compose.desktop.yml"

# Logging functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

# Check if docker-compose file exists
check_prerequisites() {
    log "Checking prerequisites..."
    
    if [ ! -f "$COMPOSE_FILE" ]; then
        error "Docker compose file not found: $COMPOSE_FILE"
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed or not in PATH"
        exit 1
    fi
    
    # Check if containers are running
    if ! docker compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
        warn "Containers don't appear to be running. Starting them..."
        docker compose -f "$COMPOSE_FILE" up -d
        sleep 10
    fi
}

# Create export directory
create_export_directory() {
    log "Creating export directory: $EXPORT_DIR"
    mkdir -p "$EXPORT_DIR"/{database,media,dicom_storage,config,logs}
}

# Export database
export_database() {
    log "Exporting PostgreSQL database..."
    
    # Get database connection info
    DB_NAME=$(docker compose -f "$COMPOSE_FILE" exec -T db printenv POSTGRES_DB 2>/dev/null || echo "noctis_pro")
    DB_USER=$(docker compose -f "$COMPOSE_FILE" exec -T db printenv POSTGRES_USER 2>/dev/null || echo "noctis_user")
    
    # Create database dump
    docker compose -f "$COMPOSE_FILE" exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$EXPORT_DIR/database/database.sql"
    
    # Also create a compressed version
    gzip -c "$EXPORT_DIR/database/database.sql" > "$EXPORT_DIR/database/database.sql.gz"
    
    # Export database schema only (for reference)
    docker compose -f "$COMPOSE_FILE" exec -T db pg_dump -U "$DB_USER" "$DB_NAME" --schema-only > "$EXPORT_DIR/database/schema.sql"
    
    log "Database exported successfully"
}

# Export media files
export_media_files() {
    log "Exporting media files..."
    
    if [ -d "./data/media" ]; then
        cp -r ./data/media/* "$EXPORT_DIR/media/" 2>/dev/null || true
        log "Media files exported: $(du -sh $EXPORT_DIR/media 2>/dev/null | cut -f1 || echo '0B')"
    else
        warn "No media directory found"
        touch "$EXPORT_DIR/media/.gitkeep"
    fi
}

# Export DICOM storage
export_dicom_storage() {
    log "Exporting DICOM storage..."
    
    if [ -d "./data/dicom_storage" ]; then
        cp -r ./data/dicom_storage/* "$EXPORT_DIR/dicom_storage/" 2>/dev/null || true
        log "DICOM storage exported: $(du -sh $EXPORT_DIR/dicom_storage 2>/dev/null | cut -f1 || echo '0B')"
    else
        warn "No DICOM storage directory found"
        touch "$EXPORT_DIR/dicom_storage/.gitkeep"
    fi
}

# Export configuration files
export_configuration() {
    log "Exporting configuration files..."
    
    # Copy environment files
    [ -f ".env" ] && cp .env "$EXPORT_DIR/config/desktop.env"
    [ -f ".env.desktop.example" ] && cp .env.desktop.example "$EXPORT_DIR/config/"
    [ -f ".env.server.example" ] && cp .env.server.example "$EXPORT_DIR/config/"
    
    # Copy Docker compose files
    [ -f "docker-compose.desktop.yml" ] && cp docker-compose.desktop.yml "$EXPORT_DIR/config/"
    [ -f "docker-compose.production.yml" ] && cp docker-compose.production.yml "$EXPORT_DIR/config/"
    [ -f "docker-compose.yml" ] && cp docker-compose.yml "$EXPORT_DIR/config/"
    
    # Copy important application files
    [ -f "requirements.txt" ] && cp requirements.txt "$EXPORT_DIR/config/"
    [ -f "manage.py" ] && cp manage.py "$EXPORT_DIR/config/"
    
    # Copy deployment scripts
    if [ -d "scripts" ]; then
        cp -r scripts "$EXPORT_DIR/config/"
    fi
    
    # Copy deployment directory
    if [ -d "deployment" ]; then
        cp -r deployment "$EXPORT_DIR/config/"
    fi
    
    log "Configuration files exported"
}

# Export logs (last 7 days)
export_logs() {
    log "Exporting recent logs..."
    
    # Export Docker container logs
    docker compose -f "$COMPOSE_FILE" logs --since 7d web > "$EXPORT_DIR/logs/web.log" 2>/dev/null || true
    docker compose -f "$COMPOSE_FILE" logs --since 7d celery > "$EXPORT_DIR/logs/celery.log" 2>/dev/null || true
    docker compose -f "$COMPOSE_FILE" logs --since 7d dicom_receiver > "$EXPORT_DIR/logs/dicom_receiver.log" 2>/dev/null || true
    docker compose -f "$COMPOSE_FILE" logs --since 7d db > "$EXPORT_DIR/logs/database.log" 2>/dev/null || true
    docker compose -f "$COMPOSE_FILE" logs --since 7d redis > "$EXPORT_DIR/logs/redis.log" 2>/dev/null || true
    
    # Export system logs if available
    if [ -d "./logs" ]; then
        find ./logs -name "*.log" -mtime -7 -exec cp {} "$EXPORT_DIR/logs/" \; 2>/dev/null || true
    fi
    
    log "Logs exported"
}

# Create system information file
create_system_info() {
    log "Creating system information file..."
    
    cat > "$EXPORT_DIR/system_info.txt" <<EOF
NOCTIS Pro Export Information
============================

Export Date: $(date)
Export Directory: $EXPORT_DIR
Source System: $(uname -a)
Docker Version: $(docker --version)
Docker Compose Version: $(docker compose version)

Database Information:
- Database Name: $(docker compose -f "$COMPOSE_FILE" exec -T db printenv POSTGRES_DB 2>/dev/null || echo "Unknown")
- Database User: $(docker compose -f "$COMPOSE_FILE" exec -T db printenv POSTGRES_USER 2>/dev/null || echo "Unknown")

File Sizes:
- Database: $(du -sh $EXPORT_DIR/database 2>/dev/null | cut -f1 || echo 'Unknown')
- Media Files: $(du -sh $EXPORT_DIR/media 2>/dev/null | cut -f1 || echo 'Unknown')
- DICOM Storage: $(du -sh $EXPORT_DIR/dicom_storage 2>/dev/null | cut -f1 || echo 'Unknown')
- Configuration: $(du -sh $EXPORT_DIR/config 2>/dev/null | cut -f1 || echo 'Unknown')
- Logs: $(du -sh $EXPORT_DIR/logs 2>/dev/null | cut -f1 || echo 'Unknown')

Total Export Size: $(du -sh $EXPORT_DIR 2>/dev/null | cut -f1 || echo 'Unknown')

Container Status at Export:
$(docker compose -f "$COMPOSE_FILE" ps)

Notes:
- This export contains all data needed to migrate to a production server
- Import using the import-from-desktop.sh script on the target server
- Make sure to configure .env file for production before importing
- Database dump is in both SQL and compressed formats
EOF

    log "System information file created"
}

# Create import instructions
create_import_instructions() {
    log "Creating import instructions..."
    
    cat > "$EXPORT_DIR/IMPORT_INSTRUCTIONS.md" <<EOF
# NOCTIS Pro Server Import Instructions

This export was created on: $(date)

## Prerequisites on Target Server

1. Ubuntu Server 18.04+ with Docker installed
2. Run the server setup script: \`./scripts/setup-ubuntu-server.sh\`
3. Ensure the server has sufficient disk space for the data

## Import Process

1. **Transfer this export directory to your server:**
   \`\`\`bash
   scp -r $EXPORT_DIR user@your-server:/tmp/
   \`\`\`

2. **On the server, run the import script:**
   \`\`\`bash
   cd /opt/noctis
   sudo /tmp/$EXPORT_DIR/config/scripts/import-from-desktop.sh /tmp/$EXPORT_DIR
   \`\`\`

3. **Configure environment for production:**
   \`\`\`bash
   cp .env.server.example .env
   nano .env  # Edit with your production settings
   \`\`\`

4. **Start the production services:**
   \`\`\`bash
   docker compose -f docker-compose.production.yml up -d
   \`\`\`

5. **Configure SSL certificates:**
   \`\`\`bash
   sudo certbot --nginx
   \`\`\`

## Verification

- Check that all services are running: \`docker compose ps\`
- Access the web interface: \`https://noctis-pro\`
- Check logs: \`docker compose logs -f\`
- Test DICOM receiver on port 11112

## Data Included

- **Database**: Complete PostgreSQL dump with all data
- **Media Files**: User uploaded files and generated content
- **DICOM Storage**: Medical imaging files
- **Configuration**: Docker compose files and scripts
- **Logs**: Recent application logs for debugging

## Security Notes

- Change all default passwords in .env file
- Configure firewall rules
- Set up SSL certificates
- Configure backup automation
- Review and update security settings

## Support

If you encounter issues during import:
1. Check the import logs in /opt/noctis/logs/
2. Verify Docker containers are healthy
3. Check database connection and data integrity
4. Ensure all required ports are open
5. Review the system_info.txt file for export details
EOF

    log "Import instructions created"
}

# Create compressed archive
create_archive() {
    log "Creating compressed archive..."
    
    ARCHIVE_NAME="${EXPORT_DIR}.tar.gz"
    tar -czf "$ARCHIVE_NAME" "$EXPORT_DIR"
    
    # Calculate checksums
    sha256sum "$ARCHIVE_NAME" > "$ARCHIVE_NAME.sha256"
    md5sum "$ARCHIVE_NAME" > "$ARCHIVE_NAME.md5"
    
    log "Archive created: $ARCHIVE_NAME"
    log "Archive size: $(du -sh $ARCHIVE_NAME | cut -f1)"
    log "SHA256: $(cat $ARCHIVE_NAME.sha256 | cut -d' ' -f1)"
    log "MD5: $(cat $ARCHIVE_NAME.md5 | cut -d' ' -f1)"
}

# Cleanup
cleanup() {
    log "Cleaning up temporary files..."
    rm -rf "$EXPORT_DIR"
    log "Temporary export directory removed"
}

# Main export function
main() {
    log "Starting NOCTIS Pro data export for server transfer..."
    
    check_prerequisites
    create_export_directory
    export_database
    export_media_files
    export_dicom_storage
    export_configuration
    export_logs
    create_system_info
    create_import_instructions
    create_archive
    cleanup
    
    log ""
    log "Export completed successfully!"
    log ""
    log "Files created:"
    log "- Archive: ${EXPORT_DIR}.tar.gz"
    log "- SHA256 checksum: ${EXPORT_DIR}.tar.gz.sha256"
    log "- MD5 checksum: ${EXPORT_DIR}.tar.gz.md5"
    log ""
    log "Next steps:"
    log "1. Transfer the archive to your Ubuntu server"
    log "2. Run the server setup script if not already done"
    log "3. Use the import script to restore data on the server"
    log "4. Configure production environment variables"
    log "5. Start production services"
    log ""
    log "Transfer command example:"
    log "scp ${EXPORT_DIR}.tar.gz* user@your-server:/tmp/"
}

# Handle script interruption
trap 'error "Export interrupted"; exit 1' INT TERM

# Run main function
main "$@"
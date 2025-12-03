#!/bin/bash

# NOCTIS Pro - Quick Start for Ubuntu Desktop
# One-command setup for development environment

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.desktop.yml"
ENV_FILE=".env"

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

# Install Docker if not present
install_docker() {
    log "Checking Docker installation..."
    
    # Check if Docker is already installed and working
    if command -v docker &> /dev/null && docker compose version &> /dev/null && groups | grep -q docker; then
        log "Docker installation verified"
        return 0
    fi
    
    # Install Docker if not present
    if ! command -v docker &> /dev/null; then
        log "Docker not found. Installing Docker..."
        
        # Download and install Docker
        log "Downloading Docker installation script..."
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        
        log "Installing Docker (this may take a few minutes)..."
        sudo sh /tmp/get-docker.sh
        
        # Clean up
        rm -f /tmp/get-docker.sh
        
        log "Docker installation completed"
    fi
    
    # Install Docker Compose plugin if not present
    if ! docker compose version &> /dev/null; then
        log "Installing Docker Compose plugin..."
        sudo apt update
        sudo apt install -y docker-compose-plugin
    fi
    
    # Add user to docker group if not already
    if ! groups | grep -q docker; then
        log "Adding user to docker group..."
        sudo usermod -aG docker $USER
        
        warn "User added to docker group. You need to log out and back in for changes to take effect."
        warn "Alternatively, you can run: newgrp docker"
        
        # Try to use newgrp to activate docker group for current session
        log "Attempting to activate docker group for current session..."
        if command -v newgrp &> /dev/null; then
            warn "If you see a permission error below, please log out and back in, then run this script again."
        fi
    fi
    
    # Final verification
    log "Verifying Docker installation..."
    if command -v docker &> /dev/null; then
        log "Docker installation verified successfully"
        docker --version
        docker compose version 2>/dev/null || warn "Docker Compose plugin may need session restart"
    else
        error "Docker installation failed. Please install Docker manually and run this script again."
        exit 1
    fi
}

# Check if compose file exists
check_compose_file() {
    log "Checking Docker Compose configuration..."
    
    if [ ! -f "$COMPOSE_FILE" ]; then
        error "Docker Compose file not found: $COMPOSE_FILE"
        error "Please ensure you're in the NOCTIS Pro project directory"
        exit 1
    fi
    
    log "Docker Compose configuration found"
}

# Setup environment file
setup_environment() {
    log "Setting up environment configuration..."
    
    if [ ! -f "$ENV_FILE" ]; then
        if [ -f ".env.desktop.example" ]; then
            log "Creating .env file from template..."
            cp .env.desktop.example "$ENV_FILE"
            
            # Generate a random secret key
            SECRET_KEY=$(openssl rand -base64 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || echo "dev-secret-key-$(date +%s)")
            
            # Replace the default secret key
            if command -v sed &> /dev/null; then
                sed -i "s#dev-secret-key-change-before-production-use#$SECRET_KEY#" "$ENV_FILE"
                log "Generated random secret key"
            fi
            
            log "Environment file created: $ENV_FILE"
        else
            error "Environment template not found: .env.desktop.example"
            exit 1
        fi
    else
        log "Environment file already exists: $ENV_FILE"
    fi
}

# Create data directories
create_directories() {
    log "Creating data directories..."
    
    mkdir -p data/{postgres,redis,media,static,dicom_storage}
    mkdir -p logs
    mkdir -p backups
    
    log "Data directories created"
}

# Pull Docker images
pull_images() {
    log "Pulling Docker images..."
    
    docker compose -f "$COMPOSE_FILE" pull
    
    log "Docker images pulled"
}

# Build application image
build_image() {
    log "Building application image..."
    
    docker compose -f "$COMPOSE_FILE" build
    
    log "Application image built"
}

# Start services
start_services() {
    log "Starting NOCTIS Pro services..."
    
    docker compose -f "$COMPOSE_FILE" up -d
    
    log "Services started"
}

# Wait for services to be ready
wait_for_services() {
    log "Waiting for services to be ready..."
    
    # Wait for database
    log "Waiting for database..."
    for i in {1..30}; do
        if docker compose -f "$COMPOSE_FILE" exec db pg_isready -U noctis_user -d noctis_pro >/dev/null 2>&1; then
            log "Database is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            error "Database failed to start within 5 minutes"
            exit 1
        fi
        sleep 10
    done
    
    # Wait for Redis
    log "Waiting for Redis..."
    for i in {1..10}; do
        if docker compose -f "$COMPOSE_FILE" exec redis redis-cli ping >/dev/null 2>&1; then
            log "Redis is ready"
            break
        fi
        if [ $i -eq 10 ]; then
            error "Redis failed to start within 100 seconds"
            exit 1
        fi
        sleep 10
    done
    
    # Wait for web application
    log "Waiting for web application..."
    for i in {1..20}; do
        if curl -f http://localhost:8000/health/ >/dev/null 2>&1; then
            log "Web application is ready"
            break
        fi
        if [ $i -eq 20 ]; then
            warn "Web application health check failed, but continuing..."
            break
        fi
        sleep 15
    done
}

# Run initial setup
run_initial_setup() {
    log "Running initial Django setup..."
    
    # Run migrations
    docker compose -f "$COMPOSE_FILE" exec web python manage.py migrate --noinput
    
    # Collect static files
    docker compose -f "$COMPOSE_FILE" exec web python manage.py collectstatic --noinput
    
    # Create superuser (if not exists)
    docker compose -f "$COMPOSE_FILE" exec web python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('Superuser created: admin / admin123')
else:
    print('Superuser already exists')
" 2>/dev/null || warn "Could not create superuser automatically"
    
    log "Initial setup completed"
}

# Display status and information
show_status() {
    log "Checking service status..."
    
    echo ""
    echo "==================================="
    echo "NOCTIS Pro Development Environment"
    echo "==================================="
    echo ""
    
    # Show container status
    docker compose -f "$COMPOSE_FILE" ps
    
    echo ""
    echo "Access Information:"
    echo "==================="
    echo "🌐 Web Application:    http://localhost:8000"
    echo "🔧 Admin Panel:        http://localhost:8000/admin"
    echo "📊 Database (Adminer): http://localhost:8080 (if tools profile enabled)"
    echo "📈 Redis Commander:    http://localhost:8081 (if tools profile enabled)"
    echo "🏥 DICOM Receiver:     Port 11112"
    echo ""
    echo "Database Connection:"
    echo "==================="
    echo "Host:     localhost"
    echo "Port:     5432"
    echo "Database: noctis_pro"
    echo "Username: noctis_user"
    echo "Password: (check .env file)"
    echo ""
    echo "Default Login:"
    echo "=============="
    echo "Username: admin"
    echo "Password: admin123"
    echo ""
    echo "Useful Commands:"
    echo "================"
    echo "View logs:           docker compose -f $COMPOSE_FILE logs -f"
    echo "Stop services:       docker compose -f $COMPOSE_FILE down"
    echo "Restart services:    docker compose -f $COMPOSE_FILE restart"
    echo "Shell access:        docker compose -f $COMPOSE_FILE exec web bash"
    echo "Database shell:      docker compose -f $COMPOSE_FILE exec db psql -U noctis_user -d noctis_pro"
    echo "Enable dev tools:    ENABLE_DEV_TOOLS=true docker compose -f $COMPOSE_FILE --profile tools up -d"
    echo ""
    echo "Export for server:   ./scripts/export-for-server.sh"
    echo ""
}

# Enable development tools (optional)
enable_dev_tools() {
    read -p "Enable development tools (Adminer, Redis Commander)? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log "Enabling development tools..."
        ENABLE_DEV_TOOLS=true docker compose -f "$COMPOSE_FILE" --profile tools up -d
        log "Development tools enabled"
        echo "📊 Adminer (DB):      http://localhost:8080"
        echo "📈 Redis Commander:   http://localhost:8081"
    fi
}

# Main function
main() {
    echo ""
    echo "🚀 NOCTIS Pro Quick Start for Ubuntu Desktop"
    echo "=============================================="
    echo ""
    
    install_docker
    check_compose_file
    setup_environment
    create_directories
    pull_images
    build_image
    start_services
    wait_for_services
    run_initial_setup
    show_status
    enable_dev_tools
    
    log ""
    log "🎉 NOCTIS Pro development environment is ready!"
    log ""
    log "Next steps:"
    log "1. Open http://localhost:8000 in your browser"
    log "2. Login with admin/admin123"
    log "3. Start developing!"
    log ""
    log "When ready to deploy to server:"
    log "./scripts/export-for-server.sh"
}

# Handle script interruption
trap 'error "Setup interrupted"; exit 1' INT TERM

# Run main function
main "$@"
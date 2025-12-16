#!/bin/bash

# NOCTIS Pro - Complete Desktop Setup Script
# This script installs Docker and sets up NoctisPro in one command
# Perfect for Ubuntu Desktop users

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] INFO: $1${NC}"
}

# Print banner
print_banner() {
    echo ""
    echo "🏥 NOCTIS Pro - Complete Desktop Setup"
    echo "======================================"
    echo ""
    echo "This script will:"
    echo "  ✅ Install Docker and Docker Compose"
    echo "  ✅ Set up NoctisPro medical imaging platform"
    echo "  ✅ Create all necessary configurations"
    echo "  ✅ Start all services"
    echo ""
    echo "Requirements:"
    echo "  - Ubuntu 18.04+ Desktop"
    echo "  - Internet connection"
    echo "  - At least 4GB RAM and 20GB free space"
    echo "  - sudo/admin privileges"
    echo ""
    read -p "Press Enter to continue or Ctrl+C to cancel..."
    echo ""
}

# Check system requirements
check_requirements() {
    log "Checking system requirements..."
    
    # Check Ubuntu version
    if ! grep -q "Ubuntu" /etc/os-release; then
        warn "This script is designed for Ubuntu. It may work on other Debian-based systems."
    fi
    
    # Check available space
    AVAILABLE_SPACE=$(df / | awk 'NR==2 {print $4}')
    REQUIRED_SPACE=20971520  # 20GB in KB
    
    if [ "$AVAILABLE_SPACE" -lt "$REQUIRED_SPACE" ]; then
        error "Insufficient disk space. Required: 20GB, Available: $(( AVAILABLE_SPACE / 1024 / 1024 ))GB"
        exit 1
    fi
    
    # Check if running as root
    if [[ $EUID -eq 0 ]]; then
        error "Please run this script as a regular user (not root/sudo)"
        error "The script will ask for sudo password when needed"
        exit 1
    fi
    
    log "System requirements check passed"
}

# Install Docker
install_docker() {
    log "Installing Docker..."
    
    # Check if Docker is already installed and working
    if command -v docker &> /dev/null && docker compose version &> /dev/null 2>&1; then
        if groups | grep -q docker || docker ps &> /dev/null; then
            log "Docker is already installed and working"
            return 0
        fi
    fi
    
    # Update system
    log "Updating system packages..."
    sudo apt update
    
    # Install prerequisites
    log "Installing prerequisites..."
    sudo apt install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        apt-transport-https \
        software-properties-common
    
    # Remove old Docker versions
    log "Removing old Docker versions..."
    sudo apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true
    
    # Method 1: Try official Docker script (faster)
    log "Installing Docker using official script..."
    if curl -fsSL https://get.docker.com -o /tmp/get-docker.sh && sudo sh /tmp/get-docker.sh; then
        log "Docker installed successfully using official script"
    else
        # Method 2: Manual installation (more reliable)
        log "Official script failed, trying manual installation..."
        
        # Add Docker's official GPG key
        sudo mkdir -p /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
        
        # Add Docker repository
        echo \
            "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
            $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        
        # Install Docker
        sudo apt update
        sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
    
    # Clean up
    rm -f /tmp/get-docker.sh
    
    # Start Docker service
    sudo systemctl start docker
    sudo systemctl enable docker
    
    # Add user to docker group
    log "Adding user to docker group..."
    sudo usermod -aG docker $USER
    
    # Test Docker installation
    log "Testing Docker installation..."
    if sudo docker --version && sudo docker compose version; then
        log "Docker installed successfully!"
        sudo docker --version
        sudo docker compose version
    else
        error "Docker installation failed"
        exit 1
    fi
    
    warn "Docker installed! You may need to log out and back in for full functionality."
    warn "For now, we'll use sudo for Docker commands."
}

# Setup NoctisPro
setup_noctis() {
    log "Setting up NoctisPro..."
    
    # Check if we're in the right directory
    if [ ! -f "docker-compose.desktop.yml" ]; then
        error "docker-compose.desktop.yml not found. Please run this script from the NoctisPro directory"
        exit 1
    fi
    
    # Create environment file
    log "Creating environment configuration..."
    if [ ! -f ".env" ]; then
        if [ -f ".env.desktop.example" ]; then
            cp .env.desktop.example .env
            
            # Generate a random secret key
            SECRET_KEY=$(openssl rand -base64 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || echo "dev-secret-key-$(date +%s)")
            
            # Replace the default secret key
            sed -i "s#dev-secret-key-change-before-production-use#$SECRET_KEY#" .env
            log "Environment file created with random secret key"
        else
            error "Environment template not found: .env.desktop.example"
            exit 1
        fi
    else
        log "Environment file already exists"
    fi
    
    # Create data directories
    log "Creating data directories..."
    mkdir -p data/postgres data/redis media/uploads logs backups
    
    # Pull and start services
    log "Starting NoctisPro services..."
    
    # Use sudo for Docker commands if user not in docker group yet
    if groups | grep -q docker && docker ps &> /dev/null 2>&1; then
        DOCKER_CMD="docker"
        COMPOSE_CMD="docker compose"
    else
        DOCKER_CMD="sudo docker"
        COMPOSE_CMD="sudo docker compose"
    fi
    
    # Pull images
    log "Pulling Docker images (this may take several minutes)..."
    $COMPOSE_CMD -f docker-compose.desktop.yml pull
    
    # Build custom images
    log "Building NoctisPro application..."
    $COMPOSE_CMD -f docker-compose.desktop.yml build
    
    # Start services
    log "Starting all services..."
    $COMPOSE_CMD -f docker-compose.desktop.yml up -d
    
    # Wait for services to start
    log "Waiting for services to start..."
    sleep 10
    
    # Run migrations
    log "Running database migrations..."
    $COMPOSE_CMD -f docker-compose.desktop.yml exec -T web python manage.py migrate
    
    # Create superuser (non-interactive)
    log "Creating admin user..."
    $COMPOSE_CMD -f docker-compose.desktop.yml exec -T web python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@noctis-pro.com', 'admin123')
    print('Superuser created: admin / admin123')
else:
    print('Superuser already exists')
"
    
    # Collect static files
    log "Collecting static files..."
    $COMPOSE_CMD -f docker-compose.desktop.yml exec -T web python manage.py collectstatic --noinput
    
    log "NoctisPro setup completed!"
}

# Print success message
print_success() {
    echo ""
    echo "🎉 SUCCESS! NoctisPro is now running!"
    echo "=================================="
    echo ""
    echo "🌐 Access your installation:"
    echo "   Web Interface: http://localhost:8000"
    echo "   Admin Panel:   http://localhost:8000/admin/"
    echo ""
    echo "🔐 Default admin credentials:"
    echo "   Username: admin"
    echo "   Password: admin123"
    echo ""
    echo "📚 Important notes:"
    echo "   - Change the admin password after first login"
    echo "   - The system is now running in development mode"
    echo "   - Data is stored in the 'data/' directory"
    echo "   - Logs are available in the 'logs/' directory"
    echo ""
    echo "🔧 Management commands:"
    echo "   Stop services:  docker compose -f docker-compose.desktop.yml down"
    echo "   Start services: docker compose -f docker-compose.desktop.yml up -d"
    echo "   View logs:      docker compose -f docker-compose.desktop.yml logs -f"
    echo ""
    echo "For production deployment, see: deploy_noctis_production.sh"
    echo ""
}

# Main execution
main() {
    print_banner
    check_requirements
    install_docker
    setup_noctis
    print_success
}

# Run main function
main "$@"
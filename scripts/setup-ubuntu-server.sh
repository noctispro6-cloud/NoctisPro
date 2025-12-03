#!/bin/bash

# NOCTIS Pro - Ubuntu Server Setup Script
# This script sets up a fresh Ubuntu server for NOCTIS Pro deployment

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

# Check if running as root
check_root() {
    if [[ $EUID -eq 0 ]]; then
        error "This script should not be run as root. Please run as a regular user with sudo privileges."
        exit 1
    fi
}

# Check Ubuntu version
check_ubuntu_version() {
    log "Checking Ubuntu version..."
    
    if ! grep -q "Ubuntu" /etc/os-release; then
        error "This script is designed for Ubuntu. Detected: $(lsb_release -d | cut -f2)"
        exit 1
    fi
    
    VERSION=$(lsb_release -rs)
    log "Detected Ubuntu $VERSION"
    
    # Check if version is supported (18.04+)
    if dpkg --compare-versions "$VERSION" "lt" "18.04"; then
        error "Ubuntu 18.04 or later is required. Current version: $VERSION"
        exit 1
    fi
}

# Update system
update_system() {
    log "Updating system packages..."
    sudo apt update
    sudo apt upgrade -y
    sudo apt autoremove -y
}

# Install essential packages
install_essentials() {
    log "Installing essential packages..."
    sudo apt install -y \
        curl \
        wget \
        git \
        unzip \
        software-properties-common \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        ufw \
        fail2ban \
        htop \
        nano \
        vim \
        tree \
        jq \
        certbot \
        python3-certbot-nginx
}

# Install Docker
install_docker() {
    log "Installing Docker..."
    
    # Remove old versions
    sudo apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true
    
    # Add Docker's official GPG key
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    
    # Add Docker repository
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Install Docker
    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    # Add user to docker group
    sudo usermod -aG docker $USER
    
    # Enable and start Docker
    sudo systemctl enable docker
    sudo systemctl start docker
    
    log "Docker installed successfully"
}

# Configure firewall
configure_firewall() {
    log "Configuring UFW firewall..."
    
    # Reset UFW to defaults
    sudo ufw --force reset
    
    # Set default policies
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    
    # Allow SSH (current connection)
    sudo ufw allow ssh
    
    # Allow HTTP and HTTPS
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp
    
    # Allow DICOM port
    sudo ufw allow 11112/tcp
    
    # Enable UFW
    sudo ufw --force enable
    
    log "Firewall configured successfully"
}

# Configure Fail2Ban
configure_fail2ban() {
    log "Configuring Fail2Ban..."
    
    # Create custom jail configuration
    sudo tee /etc/fail2ban/jail.local > /dev/null <<EOF
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
backend = systemd

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
port = http,https
logpath = /var/log/nginx/error.log

[nginx-noscript]
enabled = true
port = http,https
filter = nginx-noscript
logpath = /var/log/nginx/access.log
maxretry = 6

[nginx-badbots]
enabled = true
port = http,https
filter = nginx-badbots
logpath = /var/log/nginx/access.log
maxretry = 2

[nginx-noproxy]
enabled = true
port = http,https
filter = nginx-noproxy
logpath = /var/log/nginx/access.log
maxretry = 2
EOF

    # Restart Fail2Ban
    sudo systemctl restart fail2ban
    sudo systemctl enable fail2ban
    
    log "Fail2Ban configured successfully"
}

# Create application directories
create_directories() {
    log "Creating application directories..."
    
    sudo mkdir -p /opt/noctis/{data,logs,backups,ssl}
    sudo mkdir -p /opt/noctis/data/{postgres,redis,media,staticfiles,dicom_storage}
    
    # Set ownership to current user
    sudo chown -R $USER:$USER /opt/noctis
    
    log "Application directories created"
}

# Setup log rotation
setup_log_rotation() {
    log "Setting up log rotation..."
    
    sudo tee /etc/logrotate.d/noctis > /dev/null <<EOF
/opt/noctis/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0644 $USER $USER
    postrotate
        docker compose -f /opt/noctis/docker-compose.production.yml restart web celery dicom_receiver 2>/dev/null || true
    endscript
}
EOF

    log "Log rotation configured"
}

# Install monitoring tools (optional)
install_monitoring() {
    log "Installing monitoring tools..."
    
    # Install netdata for system monitoring
    bash <(curl -Ss https://my-netdata.io/kickstart.sh) --dont-wait --disable-telemetry
    
    log "Monitoring tools installed"
}

# Setup SSH security
setup_ssh_security() {
    log "Configuring SSH security..."
    
    # Backup original config
    sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup
    
    # Configure SSH
    sudo sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
    sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
    sudo sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config
    sudo sed -i 's/#MaxAuthTries 6/MaxAuthTries 3/' /etc/ssh/sshd_config
    
    # Restart SSH
    sudo systemctl restart ssh
    
    log "SSH security configured"
}

# Setup automatic security updates
setup_auto_updates() {
    log "Setting up automatic security updates..."
    
    sudo apt install -y unattended-upgrades
    
    sudo tee /etc/apt/apt.conf.d/50unattended-upgrades > /dev/null <<EOF
Unattended-Upgrade::Allowed-Origins {
    "\${distro_id}:\${distro_codename}-security";
    "\${distro_id}ESM:\${distro_codename}";
};
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF

    sudo systemctl enable unattended-upgrades
    
    log "Automatic security updates configured"
}

# Setup backup directory with proper permissions
setup_backup_system() {
    log "Setting up backup system..."
    
    # Create backup script
    tee /opt/noctis/backup.sh > /dev/null <<'EOF'
#!/bin/bash
# NOCTIS Pro Backup Script

BACKUP_DIR="/opt/noctis/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="noctis_backup_$DATE"

echo "Starting backup: $BACKUP_NAME"

# Create backup directory
mkdir -p "$BACKUP_DIR/$BACKUP_NAME"

# Backup database
docker compose -f /opt/noctis/docker-compose.production.yml exec -T db pg_dump -U noctis_user noctis_pro > "$BACKUP_DIR/$BACKUP_NAME/database.sql"

# Backup media files
cp -r /opt/noctis/data/media "$BACKUP_DIR/$BACKUP_NAME/"

# Backup DICOM storage
cp -r /opt/noctis/data/dicom_storage "$BACKUP_DIR/$BACKUP_NAME/"

# Create archive
cd "$BACKUP_DIR"
tar -czf "$BACKUP_NAME.tar.gz" "$BACKUP_NAME"
rm -rf "$BACKUP_NAME"

echo "Backup completed: $BACKUP_NAME.tar.gz"

# Clean old backups (keep 30 days)
find "$BACKUP_DIR" -name "noctis_backup_*.tar.gz" -mtime +30 -delete
EOF

    chmod +x /opt/noctis/backup.sh
    
    # Setup cron job for daily backups
    (crontab -l 2>/dev/null; echo "0 2 * * * /opt/noctis/backup.sh >> /opt/noctis/logs/backup.log 2>&1") | crontab -
    
    log "Backup system configured"
}

# Main setup function
main() {
    log "Starting NOCTIS Pro Ubuntu Server Setup..."
    
    check_root
    check_ubuntu_version
    update_system
    install_essentials
    install_docker
    configure_firewall
    configure_fail2ban
    create_directories
    setup_log_rotation
    setup_ssh_security
    setup_auto_updates
    setup_backup_system
    
    # Optional monitoring
    read -p "Install monitoring tools (netdata)? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        install_monitoring
    fi
    
    log "Server setup completed successfully!"
    log ""
    log "Next steps:"
    log "1. Log out and back in to apply Docker group membership"
    log "2. Copy your NOCTIS Pro application to /opt/noctis/"
    log "3. Configure your .env file based on .env.server.example"
    log "4. Run: docker compose -f docker-compose.production.yml up -d"
    log "5. Configure SSL certificates with: sudo certbot --nginx"
    log ""
    log "Important security notes:"
    log "- SSH root login is disabled"
    log "- Password authentication is disabled (SSH keys only)"
    log "- Firewall is configured to allow only necessary ports"
    log "- Fail2Ban is configured to prevent brute force attacks"
    log "- Automatic security updates are enabled"
    log ""
    warn "Please reboot the server to ensure all changes take effect:"
    warn "sudo reboot"
}

# Run main function
main "$@"
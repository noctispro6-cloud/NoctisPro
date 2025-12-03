#!/bin/bash

# NOCTIS Pro - Internet Access Deployment Script
# Configures the system for internet accessibility with DICOM machines

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NOCTIS_DIR="/opt/noctis"
COMPOSE_FILE="$NOCTIS_DIR/docker-compose.internet.yml"
ENV_FILE="$NOCTIS_DIR/.env"

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

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites for internet deployment..."
    
    # Check if running on Ubuntu server
    if ! grep -q "Ubuntu" /etc/os-release; then
        error "This script requires Ubuntu Server"
        exit 1
    fi
    
    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed. Run setup-ubuntu-server.sh first"
        exit 1
    fi
    
    # Check if NOCTIS directory exists
    if [ ! -d "$NOCTIS_DIR" ]; then
        error "NOCTIS directory not found. Import your application first"
        exit 1
    fi
    
    # Check if compose file exists
    if [ ! -f "$COMPOSE_FILE" ]; then
        error "Internet compose file not found: $COMPOSE_FILE"
        exit 1
    fi
    
    # Check if environment file exists
    if [ ! -f "$ENV_FILE" ]; then
        error "Environment file not found. Create .env from .env.internet.example"
        exit 1
    fi
    
    log "Prerequisites check passed"
}

# Validate environment configuration
validate_environment() {
    log "Validating environment configuration..."
    
    source "$ENV_FILE"
    
    # Check critical settings
    if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "CHANGE-THIS-TO-A-STRONG-SECRET-KEY-FOR-PRODUCTION" ]; then
        error "SECRET_KEY must be configured in .env file"
        exit 1
    fi
    
    if [ -z "$DOMAIN_NAME" ] || [ "$DOMAIN_NAME" = "your-domain.com" ]; then
        error "DOMAIN_NAME must be configured in .env file"
        exit 1
    fi
    
    if [ -z "$POSTGRES_PASSWORD" ] || [ "$POSTGRES_PASSWORD" = "CHANGE-THIS-TO-A-STRONG-DATABASE-PASSWORD" ]; then
        error "POSTGRES_PASSWORD must be configured in .env file"
        exit 1
    fi
    
    if [ "$DEBUG" != "False" ]; then
        warn "DEBUG should be False for internet deployment"
    fi
    
    if [ "$DICOM_EXTERNAL_ACCESS" != "True" ]; then
        warn "DICOM_EXTERNAL_ACCESS should be True for internet access"
    fi
    
    log "Environment validation passed"
}

# Configure firewall for internet access
configure_internet_firewall() {
    log "Configuring firewall for internet access..."
    
    # Check if UFW is available
    if ! command -v ufw &> /dev/null; then
        error "UFW firewall not found. Install with: sudo apt install ufw"
        exit 1
    fi
    
    # Configure UFW for internet access
    sudo ufw --force reset
    
    # Default policies
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    
    # Allow SSH (be careful not to lock yourself out)
    sudo ufw allow ssh
    
    # Allow HTTP and HTTPS
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp
    
    # Allow DICOM port for internet access
    sudo ufw allow 11112/tcp
    
    # Optional: Limit SSH to specific IPs (uncomment and modify)
    # sudo ufw delete allow ssh
    # sudo ufw allow from YOUR_ADMIN_IP to any port 22
    
    # Enable firewall
    sudo ufw --force enable
    
    # Show status
    sudo ufw status verbose
    
    log "Firewall configured for internet access"
    warn "DICOM port 11112 is now accessible from the internet"
    warn "Ensure your DICOM machines are properly configured with facility AE titles"
}

# Setup enhanced fail2ban for DICOM security
setup_dicom_fail2ban() {
    log "Setting up enhanced fail2ban for DICOM security..."
    
    # Install fail2ban if not present
    if ! command -v fail2ban-client &> /dev/null; then
        sudo apt update
        sudo apt install -y fail2ban
    fi
    
    # Create DICOM-specific fail2ban configuration
    sudo tee /etc/fail2ban/filter.d/dicom-security.conf > /dev/null <<'EOF'
# Fail2Ban filter for DICOM security events
[Definition]
failregex = ^.*BLOCKED IP <HOST>:.*$
            ^.*RATE LIMITED connection from <HOST>.*$
            ^.*Unknown Calling AET.*from <HOST>.*$
            ^.*Failed to store DICOM.*from <HOST>.*$

ignoreregex =
EOF

    # Create DICOM jail configuration
    sudo tee /etc/fail2ban/jail.d/dicom.conf > /dev/null <<EOF
[dicom-security]
enabled = true
port = 11112
filter = dicom-security
logpath = /opt/noctis/logs/dicom_security.log
maxretry = 3
findtime = 600
bantime = 3600
action = iptables-multiport[name=dicom, port="11112", protocol=tcp]
EOF

    # Restart fail2ban
    sudo systemctl restart fail2ban
    sudo systemctl enable fail2ban
    
    log "Enhanced fail2ban configured for DICOM security"
}

# Setup SSL certificates for internet access
setup_ssl_certificates() {
    log "Setting up SSL certificates for internet access..."
    
    source "$ENV_FILE"
    
    # Check if certbot is installed
    if ! command -v certbot &> /dev/null; then
        sudo apt update
        sudo apt install -y certbot python3-certbot-nginx
    fi
    
    # Stop nginx temporarily for certificate generation
    docker compose -f "$COMPOSE_FILE" stop nginx 2>/dev/null || true
    
    # Generate certificates for all domains
    if [ -n "$LETSENCRYPT_EMAIL" ] && [ "$LETSENCRYPT_EMAIL" != "your-email@example.com" ]; then
        log "Generating SSL certificates..."
        
        # Main domain
        sudo certbot certonly --standalone --non-interactive --agree-tos \
            --email "$LETSENCRYPT_EMAIL" \
            -d "$DOMAIN_NAME" \
            -d "www.$DOMAIN_NAME" \
            -d "dicom.$DOMAIN_NAME"
        
        # Setup auto-renewal
        if ! sudo crontab -l 2>/dev/null | grep -q certbot; then
            (sudo crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet --deploy-hook 'docker compose -f $COMPOSE_FILE restart nginx'") | sudo crontab -
            log "SSL auto-renewal configured"
        fi
        
        log "SSL certificates configured successfully"
    else
        warn "LETSENCRYPT_EMAIL not configured. SSL setup skipped."
        warn "Configure SSL manually after deployment"
    fi
}

# Deploy internet-accessible services
deploy_internet_services() {
    log "Deploying internet-accessible services..."
    
    cd "$NOCTIS_DIR"
    
    # Pull latest images
    docker compose -f docker-compose.internet.yml pull
    
    # Build application images
    docker compose -f docker-compose.internet.yml build
    
    # Start core services first
    docker compose -f docker-compose.internet.yml up -d db redis
    
    # Wait for database
    log "Waiting for database..."
    for i in {1..30}; do
        if docker compose -f docker-compose.internet.yml exec -T db pg_isready -U noctis_user -d noctis_pro >/dev/null 2>&1; then
            break
        fi
        if [ $i -eq 30 ]; then
            error "Database failed to start"
            exit 1
        fi
        sleep 10
    done
    
    # Start application services
    docker compose -f docker-compose.internet.yml up -d web celery celery-beat
    
    # Wait for web application
    log "Waiting for web application..."
    for i in {1..20}; do
        if docker compose -f docker-compose.internet.yml exec -T web python manage.py check >/dev/null 2>&1; then
            break
        fi
        if [ $i -eq 20 ]; then
            warn "Web application startup timeout"
        fi
        sleep 15
    done
    
    # Start DICOM receiver with internet access
    docker compose -f docker-compose.internet.yml up -d dicom_receiver
    
    # Start nginx
    docker compose -f docker-compose.internet.yml up -d nginx
    
    log "Internet-accessible services deployed"
}

# Test DICOM connectivity
test_dicom_connectivity() {
    log "Testing DICOM connectivity..."
    
    cd "$NOCTIS_DIR"
    source "$ENV_FILE"
    
    # Test internal connectivity
    if docker compose -f docker-compose.internet.yml exec -T dicom_receiver python -c "
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('localhost', 11112))
sock.close()
print('DICOM port accessible internally' if result == 0 else 'DICOM port not accessible internally')
exit(result)
" >/dev/null 2>&1; then
        log "✅ DICOM port accessible internally"
    else
        error "❌ DICOM port not accessible internally"
    fi
    
    # Test external connectivity (if possible)
    if command -v telnet &> /dev/null; then
        if timeout 5 telnet "$DOMAIN_NAME" 11112 >/dev/null 2>&1; then
            log "✅ DICOM port accessible externally"
        else
            warn "⚠️  DICOM port may not be accessible externally (check firewall/DNS)"
        fi
    fi
    
    log "DICOM connectivity test completed"
}

# Create facility setup guide
create_facility_guide() {
    log "Creating facility setup guide..."
    
    source "$ENV_FILE"
    
    cat > "$NOCTIS_DIR/FACILITY_SETUP_GUIDE.md" <<EOF
# NOCTIS Pro - Facility and DICOM Machine Setup Guide

## Overview

Your NOCTIS Pro system is now accessible from the internet for DICOM machines. Each facility gets a unique AE Title that must be configured on their DICOM machines.

## Server Information

- **Domain**: $DOMAIN_NAME
- **DICOM Port**: 11112
- **Called AE Title**: NOCTIS_SCP
- **Web Interface**: https://$DOMAIN_NAME
- **Admin Panel**: https://$DOMAIN_NAME/admin/

## For System Administrators

### 1. Create a New Facility

1. Access admin panel: https://$DOMAIN_NAME/admin/
2. Navigate to "Facility Management"
3. Click "Add Facility"
4. Fill in facility details:
   - Facility Name (e.g., "City Hospital")
   - Address, Phone, Email
   - License Number
   - AE Title (auto-generated from name if left blank)
5. Optionally create a facility user account
6. Save the facility

### 2. Note the AE Title

After creating the facility, note the generated AE Title (e.g., "CITY_HOSPITAL"). This will be used to configure the DICOM machine.

## For DICOM Machine Operators

### 1. Configure Your DICOM Machine

Configure your DICOM machine with these settings:

- **Called AE Title**: NOCTIS_SCP
- **Calling AE Title**: [Your facility's AE Title from admin panel]
- **Hostname**: $DOMAIN_NAME
- **Port**: 11112
- **Protocol**: DICOM TCP/IP
- **Timeout**: 30 seconds

### 2. Test the Connection

1. **Test connectivity**: Send a C-ECHO (ping) to verify connection
2. **Send test image**: Send a test DICOM image
3. **Verify reception**: Check the web interface for the received image

### 3. Verify Image Routing

1. Login to the web interface: https://$DOMAIN_NAME
2. Navigate to your facility's worklist
3. Verify that images appear under your facility
4. Check that patient data is correctly parsed

## Example Configurations

### Example 1: City Hospital
- **Facility Name**: "City Hospital"
- **Generated AE Title**: "CITY_HOSPITAL"
- **DICOM Config**:
  - Called AE: NOCTIS_SCP
  - Calling AE: CITY_HOSPITAL
  - Host: $DOMAIN_NAME
  - Port: 11112

### Example 2: Regional Medical Center  
- **Facility Name**: "Regional Medical Center"
- **Generated AE Title**: "REGIONAL_MED"
- **DICOM Config**:
  - Called AE: NOCTIS_SCP
  - Calling AE: REGIONAL_MED
  - Host: $DOMAIN_NAME
  - Port: 11112

## Security Features

### Automatic Security
- **AE Title Validation**: Only registered facilities can send images
- **Rate Limiting**: Prevents connection flooding
- **IP Blocking**: Automatic blocking of suspicious IPs
- **Fail2Ban Integration**: Advanced intrusion prevention
- **SSL/TLS**: All web traffic encrypted

### Monitoring
- **Connection Logs**: All DICOM connections logged
- **Security Alerts**: Notifications for security events
- **Facility Attribution**: All images tracked by facility
- **Audit Trail**: Complete activity logging

## Troubleshooting

### Connection Issues

1. **Cannot connect to DICOM port**:
   - Check firewall: \`sudo ufw status\`
   - Verify service: \`docker compose ps\`
   - Test port: \`telnet $DOMAIN_NAME 11112\`

2. **Unknown AE Title error**:
   - Verify facility is created and active
   - Check AE title spelling (case-insensitive)
   - Review DICOM machine configuration

3. **Images not appearing**:
   - Check DICOM logs: \`docker compose logs dicom_receiver\`
   - Verify facility association
   - Check user permissions

### Security Issues

1. **IP blocked**:
   - Check security logs: \`/opt/noctis/logs/dicom_security.log\`
   - Review fail2ban status: \`sudo fail2ban-client status\`
   - Unblock if legitimate: \`sudo fail2ban-client set dicom-security unbanip IP_ADDRESS\`

2. **Rate limited**:
   - Reduce connection frequency
   - Check for multiple simultaneous connections
   - Review rate limiting settings

## Support Commands

\`\`\`bash
# View DICOM logs
docker compose -f docker-compose.internet.yml logs -f dicom_receiver

# Check security logs
tail -f /opt/noctis/logs/dicom_security.log

# Test DICOM connectivity
telnet $DOMAIN_NAME 11112

# Check firewall status
sudo ufw status verbose

# View fail2ban status
sudo fail2ban-client status dicom-security

# Check SSL certificates
sudo certbot certificates

# Monitor system resources
docker stats
\`\`\`

## Contact Information

For technical support:
- Check logs first using the commands above
- Review this guide for common solutions
- Contact your system administrator

---

**Important**: Keep this guide accessible to facility staff who will be configuring DICOM machines.
EOF

    log "Facility setup guide created: $NOCTIS_DIR/FACILITY_SETUP_GUIDE.md"
}

# Verify facility and user management functionality
verify_facility_management() {
    log "Verifying facility and user management functionality..."
    
    cd "$NOCTIS_DIR"
    
    # Check Django system
    if docker compose -f docker-compose.internet.yml exec -T web python manage.py check >/dev/null 2>&1; then
        log "✅ Django system check passed"
    else
        error "❌ Django system check failed"
        return 1
    fi
    
    # Check actual facility and user data
    facility_check=$(docker compose -f docker-compose.internet.yml exec -T web python manage.py shell -c "
from accounts.models import Facility, User
from admin_panel.views import _standardize_aetitle

# Get actual counts
facility_count = Facility.objects.count()
active_facilities = Facility.objects.filter(is_active=True).count()
user_count = User.objects.count()
admin_count = User.objects.filter(role='admin', is_active=True).count()

print(f'FACILITIES:{facility_count}')
print(f'ACTIVE_FACILITIES:{active_facilities}')
print(f'USERS:{user_count}')
print(f'ADMINS:{admin_count}')

# Test AE title function
ae_test = _standardize_aetitle('Regional Medical Center')
print(f'AE_FUNCTION:WORKING:{ae_test}')
" 2>/dev/null)

    if [ $? -eq 0 ]; then
        facility_count=$(echo "$facility_check" | grep "FACILITIES:" | cut -d: -f2)
        active_facilities=$(echo "$facility_check" | grep "ACTIVE_FACILITIES:" | cut -d: -f2)
        user_count=$(echo "$facility_check" | grep "USERS:" | cut -d: -f2)
        admin_count=$(echo "$facility_check" | grep "ADMINS:" | cut -d: -f2)
        
        log "✅ Facility and user management verified"
        log "   Total facilities: $facility_count"
        log "   Active facilities: $active_facilities"
        log "   Total users: $user_count"
        log "   Admin users: $admin_count"
        
        if [ "$admin_count" -eq 0 ]; then
            warn "No admin users found. Create one with:"
            warn "docker compose -f docker-compose.internet.yml exec web python manage.py createsuperuser"
        fi
    else
        error "❌ Facility and user management verification failed"
        return 1
    fi
}

# Display deployment status
show_deployment_status() {
    log "Checking internet deployment status..."
    
    cd "$NOCTIS_DIR"
    source "$ENV_FILE"
    
    echo ""
    echo "================================================="
    echo "NOCTIS Pro - Internet-Accessible Deployment"
    echo "================================================="
    echo ""
    
    # Show container status
    docker compose -f docker-compose.internet.yml ps
    
    echo ""
    echo "🌐 Internet Access Information:"
    echo "==============================="
    echo "Web Interface:     https://$DOMAIN_NAME"
    echo "Admin Panel:       https://$DOMAIN_NAME/admin/"
    echo "DICOM Receiver:    $DOMAIN_NAME:11112"
    echo "DICOM Status:      https://dicom.$DOMAIN_NAME"
    echo ""
    echo "🏥 DICOM Configuration for Facilities:"
    echo "======================================"
    echo "Called AE Title:   NOCTIS_SCP"
    echo "Calling AE Title:  [Facility's AE Title from admin panel]"
    echo "Hostname:          $DOMAIN_NAME"
    echo "Port:              11112"
    echo "Protocol:          DICOM TCP/IP"
    echo ""
    echo "🔒 Security Status:"
    echo "=================="
    echo "Firewall:          $(sudo ufw status | head -1)"
    echo "SSL Status:        $([ -d "/etc/letsencrypt/live/$DOMAIN_NAME" ] && echo "✅ Configured" || echo "❌ Not configured")"
    echo "Fail2Ban:          $(sudo systemctl is-active fail2ban)"
    echo "DICOM Security:    Enhanced logging and rate limiting enabled"
    echo ""
    echo "📊 System Resources:"
    echo "==================="
    echo "Disk Usage:        $(df -h /opt/noctis | tail -1 | awk '{print $3 "/" $2 " (" $5 ")"}')"
    echo "Memory Usage:      $(free -h | grep Mem | awk '{print $3 "/" $2}')"
    echo ""
    echo "📁 Important Files:"
    echo "=================="
    echo "Environment:       $ENV_FILE"
    echo "Compose File:      $COMPOSE_FILE"
    echo "Facility Guide:    $NOCTIS_DIR/FACILITY_SETUP_GUIDE.md"
    echo "DICOM Logs:        /opt/noctis/logs/dicom_receiver.log"
    echo "Security Logs:     /opt/noctis/logs/dicom_security.log"
    echo ""
}

# Perform comprehensive health checks
run_health_checks() {
    log "Performing comprehensive health checks..."
    
    cd "$NOCTIS_DIR"
    source "$ENV_FILE"
    
    # Database health
    if docker compose -f docker-compose.internet.yml exec -T db pg_isready -U noctis_user -d noctis_pro >/dev/null 2>&1; then
        log "✅ Database: Healthy"
    else
        error "❌ Database: Unhealthy"
    fi
    
    # Redis health
    if docker compose -f docker-compose.internet.yml exec -T redis redis-cli ping >/dev/null 2>&1; then
        log "✅ Redis: Healthy"
    else
        error "❌ Redis: Unhealthy"
    fi
    
    # Web application health
    if curl -f "http://localhost:8000/health/" >/dev/null 2>&1; then
        log "✅ Web Application: Healthy"
    else
        warn "⚠️  Web Application: Health check failed"
    fi
    
    # HTTPS health (if SSL configured)
    if [ -d "/etc/letsencrypt/live/$DOMAIN_NAME" ]; then
        if curl -f "https://$DOMAIN_NAME/health/" >/dev/null 2>&1; then
            log "✅ HTTPS: Healthy"
        else
            warn "⚠️  HTTPS: Not accessible"
        fi
    fi
    
    # DICOM port accessibility
    if timeout 5 bash -c "</dev/tcp/localhost/11112" >/dev/null 2>&1; then
        log "✅ DICOM Port: Accessible"
    else
        error "❌ DICOM Port: Not accessible"
    fi
    
    # Facility management test
    facility_count=$(docker compose -f docker-compose.internet.yml exec -T web python manage.py shell -c "
from accounts.models import Facility
print(Facility.objects.count())
" 2>/dev/null | tail -1)
    
    if [ "$facility_count" -ge 0 ] 2>/dev/null; then
        log "✅ Facility Management: Working ($facility_count facilities)"
    else
        error "❌ Facility Management: Not working"
    fi
    
    log "Health checks completed"
}

# Main deployment function
main() {
    echo ""
    echo "🌍 NOCTIS Pro - Internet Access Deployment"
    echo "=========================================="
    echo ""
    
    check_prerequisites
    validate_environment
    configure_internet_firewall
    setup_dicom_fail2ban
    setup_ssl_certificates
    deploy_internet_services
    verify_facility_management
    test_dicom_connectivity
    create_facility_guide
    show_deployment_status
    run_health_checks
    
    echo ""
    log "🎉 Internet-accessible deployment completed successfully!"
    echo ""
    log "Next steps:"
    log "1. Create facilities in admin panel: https://$DOMAIN_NAME/admin/"
    log "2. Configure DICOM machines with facility AE titles"
    log "3. Test DICOM connectivity from your machines"
    log "4. Monitor security logs for any issues"
    log "5. Set up monitoring and alerting"
    echo ""
    log "Important security reminders:"
    warn "- DICOM port 11112 is now accessible from the internet"
    warn "- Only facilities with registered AE titles can send images"
    warn "- Monitor security logs regularly: /opt/noctis/logs/dicom_security.log"
    warn "- Review fail2ban logs: sudo fail2ban-client status dicom-security"
    echo ""
    log "Facility setup guide: $NOCTIS_DIR/FACILITY_SETUP_GUIDE.md"
    log "Share this guide with facilities configuring DICOM machines"
}

# Handle script interruption
trap 'error "Internet deployment interrupted"; exit 1' INT TERM

# Run main function
main "$@"
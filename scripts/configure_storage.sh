#!/bin/bash

# NoctisPro Storage Configuration Script
# Automatically configures SSD + HDD storage layout for optimal performance
# SSD: OS, Docker containers, application runtime
# HDD: DICOM images, media files, backups, long-term storage

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root (sudo)"
   exit 1
fi

log_info "Starting NoctisPro Storage Configuration..."

# Function to detect storage devices
detect_storage() {
    log_info "Detecting storage devices..."
    
    # List all block devices
    lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE
    echo ""
    
    # Detect SSD (typically NVMe or smaller SSD)
    SSD_DEVICE=""
    HDD_DEVICE=""
    
    # Look for NVMe devices (most likely SSD)
    if ls /dev/nvme* 2>/dev/null; then
        SSD_DEVICE=$(ls /dev/nvme*n1 2>/dev/null | head -1)
        log_info "Detected NVMe SSD: $SSD_DEVICE"
    fi
    
    # Look for SATA devices
    SATA_DEVICES=$(ls /dev/sd* 2>/dev/null | grep -E '/dev/sd[a-z]$' || true)
    
    if [[ -n "$SATA_DEVICES" ]]; then
        for device in $SATA_DEVICES; do
            # Get device size in GB
            size_bytes=$(blockdev --getsize64 $device 2>/dev/null || echo 0)
            size_gb=$((size_bytes / 1024 / 1024 / 1024))
            
            log_info "Found SATA device: $device (${size_gb}GB)"
            
            # If no SSD detected yet and device is small (likely SSD)
            if [[ -z "$SSD_DEVICE" && $size_gb -lt 1000 ]]; then
                SSD_DEVICE="$device"
                log_info "Assuming $device is SSD based on size (${size_gb}GB)"
            elif [[ $size_gb -gt 1000 ]]; then
                HDD_DEVICE="$device"
                log_info "Assuming $device is HDD based on size (${size_gb}GB)"
            fi
        done
    fi
    
    # If still no SSD detected, use first available device
    if [[ -z "$SSD_DEVICE" ]]; then
        SSD_DEVICE=$(ls /dev/sd* 2>/dev/null | head -1 || echo "")
        log_warning "No clear SSD detected, using $SSD_DEVICE as primary storage"
    fi
    
    log_info "Storage configuration:"
    log_info "  SSD Device: $SSD_DEVICE (for OS, Docker, application)"
    log_info "  HDD Device: $HDD_DEVICE (for data storage)"
}

# Function to configure HDD for data storage
configure_hdd_storage() {
    if [[ -z "$HDD_DEVICE" ]]; then
        log_warning "No HDD detected - using SSD for all storage"
        return 0
    fi
    
    log_info "Configuring HDD for data storage..."
    
    # Check if HDD already has partitions
    if [[ -b "${HDD_DEVICE}1" ]]; then
        log_info "HDD partition ${HDD_DEVICE}1 already exists"
        HDD_PARTITION="${HDD_DEVICE}1"
    else
        log_info "Creating partition on HDD: $HDD_DEVICE"
        
        # Create single partition using entire disk
        parted -s $HDD_DEVICE mklabel gpt
        parted -s $HDD_DEVICE mkpart primary ext4 0% 100%
        
        HDD_PARTITION="${HDD_DEVICE}1"
        
        # Wait for partition to be recognized
        sleep 2
        partprobe $HDD_DEVICE
        sleep 2
    fi
    
    # Check if partition has filesystem
    if ! blkid $HDD_PARTITION &>/dev/null; then
        log_info "Formatting HDD partition with ext4..."
        mkfs.ext4 -F $HDD_PARTITION
        log_success "HDD partition formatted"
    else
        log_info "HDD partition already formatted"
    fi
    
    # Create mount point
    mkdir -p /data
    
    # Get UUID of HDD partition
    HDD_UUID=$(blkid -s UUID -o value $HDD_PARTITION)
    log_info "HDD UUID: $HDD_UUID"
    
    # Check if already in fstab
    if ! grep -q "$HDD_UUID" /etc/fstab; then
        log_info "Adding HDD to fstab..."
        echo "# NoctisPro data storage (HDD)" >> /etc/fstab
        echo "UUID=$HDD_UUID /data ext4 defaults,noatime,data=writeback 0 2" >> /etc/fstab
        log_success "HDD added to fstab"
    else
        log_info "HDD already configured in fstab"
    fi
    
    # Mount the HDD
    if ! mountpoint -q /data; then
        log_info "Mounting HDD data partition..."
        mount /data
        log_success "HDD mounted at /data"
    else
        log_info "HDD already mounted at /data"
    fi
    
    # Set permissions
    chmod 755 /data
    log_success "HDD storage configured successfully"
}

# Function to configure Docker on SSD
configure_docker_ssd() {
    log_info "Configuring Docker for SSD optimization..."
    
    # Create Docker configuration directory
    mkdir -p /etc/docker
    
    # Create optimized Docker daemon configuration
    cat > /etc/docker/daemon.json << 'EOF'
{
  "data-root": "/var/lib/docker",
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=true"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "live-restore": true,
  "userland-proxy": false,
  "experimental": false,
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 64000,
      "Soft": 64000
    }
  }
}
EOF
    
    log_success "Docker configuration created for SSD optimization"
}

# Function to create directory structure
create_directory_structure() {
    log_info "Creating optimized directory structure..."
    
    # Create SSD directories (fast access)
    mkdir -p /opt/noctis_pro_fast/{cache,sessions,temp_processing,logs}
    mkdir -p /var/lib/docker
    
    # Create HDD directories (large storage)
    if [[ -d "/data" ]]; then
        mkdir -p /data/noctis_pro/{media,dicom_images,backups,logs,exports,temp}
        mkdir -p /data/noctis_pro/media/{studies,uploads,processed}
        mkdir -p /data/noctis_pro/backups/{database,media,system}
        
        # Set proper ownership for data directories
        chown -R 1000:1000 /data/noctis_pro/
        chmod -R 755 /data/noctis_pro/
        
        log_success "HDD directory structure created"
    else
        log_warning "No HDD mounted - creating all directories on SSD"
        mkdir -p /opt/noctis_pro/{media,dicom_images,backups,logs,exports,temp}
    fi
    
    # Set proper ownership for SSD directories
    chown -R 1000:1000 /opt/noctis_pro_fast/
    chmod -R 755 /opt/noctis_pro_fast/
    
    log_success "Directory structure created successfully"
}

# Function to optimize file systems
optimize_filesystems() {
    log_info "Applying filesystem optimizations..."
    
    # Create temporary fstab backup
    cp /etc/fstab /etc/fstab.backup.$(date +%Y%m%d_%H%M%S)
    
    # SSD optimizations (if not already present)
    if ! grep -q "# SSD optimizations" /etc/fstab; then
        echo "" >> /etc/fstab
        echo "# SSD optimizations for NoctisPro" >> /etc/fstab
        
        # Add SSD optimization for root filesystem if it's SSD
        if [[ -n "$SSD_DEVICE" ]]; then
            # Check if root is on SSD
            ROOT_DEVICE=$(df / | tail -1 | awk '{print $1}' | sed 's/[0-9]*$//')
            if [[ "$ROOT_DEVICE" == "$SSD_DEVICE" ]]; then
                log_info "Root filesystem is on SSD - applying optimizations"
                # Note: We don't modify root mount options as it could cause boot issues
                # Instead, we'll optimize specific directories
            fi
        fi
    fi
    
    # Apply mount optimizations
    if mountpoint -q /data; then
        log_info "Remounting /data with optimizations..."
        mount -o remount,noatime,data=writeback /data || true
    fi
    
    log_success "Filesystem optimizations applied"
}

# Function to create storage monitoring script
create_monitoring_script() {
    log_info "Creating storage monitoring script..."
    
    cat > /usr/local/bin/noctis-storage-monitor.sh << 'EOF'
#!/bin/bash

# NoctisPro Storage Monitoring Script

echo "=== NoctisPro Storage Status ==="
echo "Date: $(date)"
echo ""

echo "=== Disk Usage ==="
df -h | grep -E "(Filesystem|nvme|sda|data)"
echo ""

echo "=== Docker Storage ==="
if command -v docker &> /dev/null; then
    docker system df 2>/dev/null || echo "Docker not running"
else
    echo "Docker not installed"
fi
echo ""

echo "=== DICOM Storage ==="
if [[ -d "/data/noctis_pro/media" ]]; then
    echo "DICOM Images: $(du -sh /data/noctis_pro/media 2>/dev/null | cut -f1)"
    echo "Total Studies: $(find /data/noctis_pro/media -name "*.dcm" 2>/dev/null | wc -l)"
elif [[ -d "/opt/noctis_pro/media" ]]; then
    echo "DICOM Images: $(du -sh /opt/noctis_pro/media 2>/dev/null | cut -f1)"
    echo "Total Studies: $(find /opt/noctis_pro/media -name "*.dcm" 2>/dev/null | wc -l)"
else
    echo "DICOM storage not found"
fi
echo ""

echo "=== Backup Storage ==="
if [[ -d "/data/noctis_pro/backups" ]]; then
    echo "Backup Size: $(du -sh /data/noctis_pro/backups 2>/dev/null | cut -f1)"
    echo "Recent Backups: $(ls -1 /data/noctis_pro/backups/database/ 2>/dev/null | tail -5)"
elif [[ -d "/opt/backups" ]]; then
    echo "Backup Size: $(du -sh /opt/backups 2>/dev/null | cut -f1)"
else
    echo "Backup storage not found"
fi
echo ""

echo "=== Storage Health ==="
# Check SSD health if available
if [[ -b "/dev/nvme0n1" ]]; then
    smartctl -H /dev/nvme0n1 2>/dev/null | grep -E "(SMART|overall)" || echo "SMART data not available for SSD"
fi

# Check HDD health if available
if [[ -b "/dev/sda" ]]; then
    smartctl -H /dev/sda 2>/dev/null | grep -E "(SMART|overall)" || echo "SMART data not available for HDD"
fi

echo ""
echo "=== Storage Recommendations ==="
# Check if SSD usage is high
SSD_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [[ $SSD_USAGE -gt 80 ]]; then
    echo "⚠️  WARNING: SSD usage is ${SSD_USAGE}% - consider cleaning Docker images"
    echo "   Run: sudo docker system prune -a"
fi

# Check if HDD usage is high
if mountpoint -q /data; then
    HDD_USAGE=$(df /data | tail -1 | awk '{print $5}' | sed 's/%//')
    if [[ $HDD_USAGE -gt 90 ]]; then
        echo "⚠️  WARNING: HDD usage is ${HDD_USAGE}% - consider archiving old DICOM studies"
    fi
fi

echo "✅ Storage monitoring complete"
EOF

    chmod +x /usr/local/bin/noctis-storage-monitor.sh
    log_success "Storage monitoring script created"
}

# Function to create storage verification script
create_verification_script() {
    log_info "Creating storage verification script..."
    
    cat > /usr/local/bin/verify_storage.sh << 'EOF'
#!/bin/bash

# NoctisPro Storage Verification Script

echo "=== Storage Verification ==="

# Check if Docker directory is on SSD
DOCKER_MOUNT=$(df /var/lib/docker | tail -1 | awk '{print $1}')
echo "Docker storage: $DOCKER_MOUNT"

# Check if data directory exists and is properly mounted
if mountpoint -q /data; then
    DATA_MOUNT=$(df /data | tail -1 | awk '{print $1}')
    echo "Data storage: $DATA_MOUNT"
    echo "✅ HDD data storage properly mounted"
else
    echo "⚠️  No separate data storage - using SSD for all data"
fi

# Check directory structure
echo ""
echo "=== Directory Structure ==="
if [[ -d "/data/noctis_pro" ]]; then
    echo "✅ HDD data directories:"
    ls -la /data/noctis_pro/
else
    echo "⚠️  Using SSD for data storage"
fi

echo ""
echo "✅ SSD fast directories:"
ls -la /opt/noctis_pro_fast/ 2>/dev/null || echo "Fast directories not yet created"

echo ""
echo "=== Storage Performance Test ==="
echo "Testing write performance..."

# Test SSD write speed
echo "SSD write test..."
dd if=/dev/zero of=/tmp/ssd_test bs=1M count=100 2>&1 | grep -E "(copied|MB/s)" || echo "SSD test completed"
rm -f /tmp/ssd_test

# Test HDD write speed if available
if mountpoint -q /data; then
    echo "HDD write test..."
    dd if=/dev/zero of=/data/hdd_test bs=1M count=100 2>&1 | grep -E "(copied|MB/s)" || echo "HDD test completed"
    rm -f /data/hdd_test
fi

echo ""
echo "✅ Storage verification complete"
EOF

    chmod +x /usr/local/bin/verify_storage.sh
    log_success "Storage verification script created"
}

# Function to configure swap if needed
configure_swap() {
    log_info "Checking swap configuration..."
    
    # Check current swap
    CURRENT_SWAP=$(free -h | grep Swap | awk '{print $2}')
    
    if [[ "$CURRENT_SWAP" == "0B" ]]; then
        log_info "No swap detected - creating swap file..."
        
        # Create 4GB swap file
        fallocate -l 4G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile
        
        # Add to fstab
        if ! grep -q "/swapfile" /etc/fstab; then
            echo "/swapfile none swap sw 0 0" >> /etc/fstab
        fi
        
        log_success "4GB swap file created"
    else
        log_info "Swap already configured: $CURRENT_SWAP"
    fi
}

# Main execution
main() {
    log_info "=== NoctisPro Storage Configuration ==="
    
    # Detect storage devices
    detect_storage
    
    # Configure HDD for data storage
    configure_hdd_storage
    
    # Configure Docker for SSD
    configure_docker_ssd
    
    # Create directory structure
    create_directory_structure
    
    # Optimize filesystems
    optimize_filesystems
    
    # Configure swap
    configure_swap
    
    # Create monitoring and verification scripts
    create_monitoring_script
    create_verification_script
    
    echo ""
    log_success "=== Storage Configuration Complete ==="
    echo ""
    
    # Display final configuration
    log_info "Final Storage Layout:"
    echo ""
    df -h | grep -E "(Filesystem|nvme|sda|data)" || df -h
    echo ""
    
    log_info "Storage Directories Created:"
    if [[ -d "/data/noctis_pro" ]]; then
        echo "📁 HDD Storage (Large files):"
        echo "   /data/noctis_pro/media/ - DICOM images and studies"
        echo "   /data/noctis_pro/backups/ - System backups"
        echo "   /data/noctis_pro/logs/ - Long-term logs"
        echo "   /data/noctis_pro/exports/ - Report exports"
    fi
    
    echo "📁 SSD Storage (Fast access):"
    echo "   /var/lib/docker/ - Docker containers and images"
    echo "   /opt/noctis_pro_fast/ - Cache and temporary processing"
    echo "   / - Operating system and applications"
    
    echo ""
    log_info "Monitoring Commands:"
    echo "   sudo /usr/local/bin/noctis-storage-monitor.sh - Check storage status"
    echo "   sudo /usr/local/bin/verify_storage.sh - Verify configuration"
    echo "   df -h - Quick disk usage check"
    
    echo ""
    log_success "✅ Storage configuration completed successfully!"
    log_info "You can now proceed with the main deployment: sudo ./deploy_noctis_production.sh"
}

# Run main function
main "$@"
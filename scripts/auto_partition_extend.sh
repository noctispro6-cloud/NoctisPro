#!/bin/bash

# Ubuntu Server Automatic Partition Extension Script
# This script monitors disk usage and automatically extends partitions when free space is available

set -euo pipefail

# Configuration
SCRIPT_NAME="auto_partition_extend"
LOG_FILE="/var/log/${SCRIPT_NAME}.log"
CONFIG_FILE="/etc/${SCRIPT_NAME}.conf"
THRESHOLD_PERCENT=85
MIN_FREE_SPACE_GB=10

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "ERROR: $1"
    exit 1
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error_exit "This script must be run as root"
    fi
}

# Load configuration
load_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        source "$CONFIG_FILE"
        log "Configuration loaded from $CONFIG_FILE"
    else
        log "No configuration file found, using defaults"
    fi
}

# Get partition information
get_partition_info() {
    df -h | grep -E '^/dev/' | while read filesystem size used avail use_percent mount; do
        # Remove % from use_percent
        use_num=$(echo "$use_percent" | sed 's/%//')
        
        echo "$filesystem $size $used $avail $use_num $mount"
    done
}

# Get available space on other partitions
get_available_space() {
    local target_partition="$1"
    
    # Get list of all block devices
    lsblk -rno NAME,SIZE,MOUNTPOINT,FSTYPE | while read name size mount fstype; do
        # Skip if it's the target partition or already mounted
        if [[ "$name" == "${target_partition##*/}" ]] || [[ -n "$mount" ]]; then
            continue
        fi
        
        # Check if it's a valid partition
        if [[ -b "/dev/$name" ]] && [[ "$fstype" != "swap" ]]; then
            # Convert size to GB
            size_gb=$(echo "$size" | numfmt --from=iec --to-unit=1000000000)
            if (( $(echo "$size_gb >= $MIN_FREE_SPACE_GB" | bc -l) )); then
                echo "/dev/$name $size_gb"
            fi
        fi
    done
}

# Extend logical volume if using LVM
extend_lvm_partition() {
    local target_partition="$1"
    local source_device="$2"
    local size_gb="$3"
    
    log "Attempting to extend LVM partition $target_partition using $source_device"
    
    # Get volume group name
    local vg_name=$(lvdisplay "$target_partition" | grep "VG Name" | awk '{print $3}')
    
    if [[ -z "$vg_name" ]]; then
        log "ERROR: Could not determine volume group for $target_partition"
        return 1
    fi
    
    # Create physical volume on source device
    pvcreate "$source_device" || {
        log "ERROR: Failed to create physical volume on $source_device"
        return 1
    }
    
    # Extend volume group
    vgextend "$vg_name" "$source_device" || {
        log "ERROR: Failed to extend volume group $vg_name"
        return 1
    }
    
    # Extend logical volume
    lvextend -l +100%FREE "$target_partition" || {
        log "ERROR: Failed to extend logical volume $target_partition"
        return 1
    }
    
    # Resize filesystem
    resize_filesystem "$target_partition"
    
    log "Successfully extended LVM partition $target_partition"
    return 0
}

# Resize filesystem after partition extension
resize_filesystem() {
    local partition="$1"
    
    # Determine filesystem type
    local fstype=$(blkid -o value -s TYPE "$partition")
    
    case "$fstype" in
        ext2|ext3|ext4)
            resize2fs "$partition" || {
                log "ERROR: Failed to resize ext filesystem on $partition"
                return 1
            }
            ;;
        xfs)
            xfs_growfs "$partition" || {
                log "ERROR: Failed to resize XFS filesystem on $partition"
                return 1
            }
            ;;
        btrfs)
            btrfs filesystem resize max "$partition" || {
                log "ERROR: Failed to resize Btrfs filesystem on $partition"
                return 1
            }
            ;;
        *)
            log "WARNING: Unsupported filesystem type $fstype for $partition"
            return 1
            ;;
    esac
    
    log "Successfully resized $fstype filesystem on $partition"
    return 0
}

# Main partition extension logic
extend_partition() {
    local target_partition="$1"
    local mount_point="$2"
    local usage_percent="$3"
    
    log "Checking for available space to extend $target_partition (${usage_percent}% full)"
    
    # Get available unallocated space
    local available_space
    available_space=$(get_available_space "$target_partition")
    
    if [[ -z "$available_space" ]]; then
        log "No available unallocated space found for extending $target_partition"
        return 1
    fi
    
    # Process available space
    echo "$available_space" | while read device size_gb; do
        log "Found available space: $device with ${size_gb}GB"
        
        # Check if target partition uses LVM
        if lvdisplay "$target_partition" &>/dev/null; then
            extend_lvm_partition "$target_partition" "$device" "$size_gb"
            return $?
        else
            log "Non-LVM partition extension not implemented yet for $target_partition"
            return 1
        fi
    done
}

# Monitor disk usage and trigger extension if needed
monitor_and_extend() {
    log "Starting disk usage monitoring"
    
    get_partition_info | while read filesystem size used avail use_percent mount; do
        if (( use_percent >= THRESHOLD_PERCENT )); then
            log "Partition $filesystem at $mount is ${use_percent}% full (threshold: ${THRESHOLD_PERCENT}%)"
            
            # Attempt to extend the partition
            if extend_partition "$filesystem" "$mount" "$use_percent"; then
                log "Successfully extended $filesystem"
                
                # Send notification
                if command -v notify-send &> /dev/null; then
                    notify-send "Disk Extension" "Successfully extended $filesystem at $mount"
                fi
            else
                log "Failed to extend $filesystem"
                
                # Send warning notification
                if command -v notify-send &> /dev/null; then
                    notify-send "Disk Warning" "Could not extend $filesystem at $mount (${use_percent}% full)"
                fi
            fi
        else
            log "Partition $filesystem at $mount is ${use_percent}% full (OK)"
        fi
    done
}

# Install required packages
install_dependencies() {
    log "Installing required packages"
    
    apt-get update
    apt-get install -y lvm2 bc parted gdisk util-linux
    
    log "Dependencies installed successfully"
}

# Create systemd service for continuous monitoring
create_service() {
    local service_file="/etc/systemd/system/${SCRIPT_NAME}.service"
    local timer_file="/etc/systemd/system/${SCRIPT_NAME}.timer"
    
    # Resolve script path dynamically
    local script_path
    script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

    # Create service file
    cat > "$service_file" << EOF
[Unit]
Description=Automatic Partition Extension Service
After=multi-user.target

[Service]
Type=oneshot
ExecStart=${script_path} --monitor
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # Create timer file for periodic execution
    cat > "$timer_file" << EOF
[Unit]
Description=Run Automatic Partition Extension every 30 minutes
Requires=${SCRIPT_NAME}.service

[Timer]
OnCalendar=*:0/30
Persistent=true

[Install]
WantedBy=timers.target
EOF

    # Enable and start the service
    systemctl daemon-reload
    systemctl enable "${SCRIPT_NAME}.timer"
    systemctl start "${SCRIPT_NAME}.timer"
    
    log "Systemd service and timer created and started"
}

# Main function
main() {
    case "${1:-}" in
        --install)
            check_root
            install_dependencies
            create_service
            log "Auto partition extension system installed successfully"
            ;;
        --monitor)
            check_root
            load_config
            monitor_and_extend
            ;;
        --status)
            systemctl status "${SCRIPT_NAME}.timer" || true
            systemctl status "${SCRIPT_NAME}.service" || true
            ;;
        --help|*)
            echo "Usage: $0 [--install|--monitor|--status|--help]"
            echo "  --install  Install the service and dependencies"
            echo "  --monitor  Run disk monitoring (used by systemd service)"
            echo "  --status   Show service status"
            echo "  --help     Show this help message"
            ;;
    esac
}

# Run main function with all arguments
main "$@"
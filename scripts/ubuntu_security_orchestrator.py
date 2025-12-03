#!/usr/bin/env python3

"""
Ubuntu Server Security and Storage Orchestrator
Main orchestration script that coordinates:
1. Automatic partition extension
2. Log filtering and exploit detection
3. DICOM traffic sanitization
4. Reports and chat content sanitization

This script provides a unified interface and monitoring for all security components.
"""

import os
import sys
import json
import logging
import asyncio
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import sqlite3
import psutil
import shutil
from concurrent.futures import ThreadPoolExecutor
import signal
import configparser

# Add scripts directory to path for imports
sys.path.insert(0, '/workspace/scripts')

try:
    from log_filter_system import LogFilterSystem
    from dicom_traffic_sanitizer import DicomTrafficSanitizationSystem
    from reports_chat_sanitizer import ContentSanitizationSystem
except ImportError as e:
    logging.warning(f"Could not import some modules: {e}")

@dataclass
class SystemStatus:
    timestamp: datetime
    partition_extension: Dict[str, Any]
    log_filtering: Dict[str, Any]
    dicom_sanitization: Dict[str, Any]
    content_sanitization: Dict[str, Any]
    system_resources: Dict[str, Any]
    overall_health: str

@dataclass
class ComponentHealth:
    name: str
    status: str  # 'healthy', 'warning', 'error', 'stopped'
    last_check: datetime
    details: Dict[str, Any]
    metrics: Dict[str, float]

class SystemMonitor:
    """Monitor system resources and component health"""
    
    def __init__(self):
        self.monitoring = False
        self.health_checks = {}
        self.alert_thresholds = {
            'cpu_percent': 80.0,
            'memory_percent': 85.0,
            'disk_percent': 90.0,
            'load_average': 4.0
        }
    
    def get_system_resources(self) -> Dict[str, Any]:
        """Get current system resource usage"""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            load_avg = os.getloadavg()
            
            # Memory usage
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Disk usage
            disk_usage = {}
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disk_usage[partition.mountpoint] = {
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': round((usage.used / usage.total) * 100, 2)
                    }
                except PermissionError:
                    continue
            
            # Network stats
            network = psutil.net_io_counters()
            
            # Process count
            process_count = len(psutil.pids())
            
            return {
                'cpu': {
                    'percent': cpu_percent,
                    'count': cpu_count,
                    'load_average': load_avg
                },
                'memory': {
                    'total': memory.total,
                    'used': memory.used,
                    'free': memory.free,
                    'percent': memory.percent,
                    'swap_percent': swap.percent
                },
                'disk': disk_usage,
                'network': {
                    'bytes_sent': network.bytes_sent,
                    'bytes_recv': network.bytes_recv,
                    'packets_sent': network.packets_sent,
                    'packets_recv': network.packets_recv
                },
                'processes': process_count,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logging.error(f"Error getting system resources: {e}")
            return {'error': str(e)}
    
    def check_disk_space_alerts(self) -> List[Dict[str, Any]]:
        """Check for disk space alerts"""
        alerts = []
        
        try:
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    percent_used = (usage.used / usage.total) * 100
                    
                    if percent_used > self.alert_thresholds['disk_percent']:
                        alerts.append({
                            'type': 'disk_space',
                            'severity': 'critical' if percent_used > 95 else 'warning',
                            'partition': partition.mountpoint,
                            'percent_used': round(percent_used, 2),
                            'free_space_gb': round(usage.free / (1024**3), 2),
                            'message': f"Disk space critical on {partition.mountpoint}: {percent_used:.1f}% used"
                        })
                except PermissionError:
                    continue
                    
        except Exception as e:
            logging.error(f"Error checking disk space: {e}")
        
        return alerts

class PartitionManager:
    """Manage automatic partition extension"""
    
    def __init__(self, script_path: str = "/workspace/scripts/auto_partition_extend.sh"):
        self.script_path = script_path
        self.last_check = None
        self.extension_history = []
    
    def check_and_extend_partitions(self) -> Dict[str, Any]:
        """Check partitions and extend if needed"""
        try:
            # Run the partition extension script in monitor mode
            result = subprocess.run(
                [self.script_path, '--monitor'],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            self.last_check = datetime.now()
            
            if result.returncode == 0:
                return {
                    'status': 'success',
                    'last_check': self.last_check.isoformat(),
                    'output': result.stdout,
                    'extensions_performed': self._count_extensions_in_output(result.stdout)
                }
            else:
                return {
                    'status': 'error',
                    'last_check': self.last_check.isoformat(),
                    'error': result.stderr,
                    'return_code': result.returncode
                }
                
        except subprocess.TimeoutExpired:
            return {
                'status': 'timeout',
                'last_check': datetime.now().isoformat(),
                'error': 'Partition check timed out'
            }
        except Exception as e:
            return {
                'status': 'error',
                'last_check': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def _count_extensions_in_output(self, output: str) -> int:
        """Count the number of partition extensions performed"""
        extension_indicators = [
            'Successfully extended',
            'Extension completed',
            'Partition extended'
        ]
        
        count = 0
        for line in output.split('\n'):
            for indicator in extension_indicators:
                if indicator.lower() in line.lower():
                    count += 1
                    break
        
        return count
    
    def get_partition_status(self) -> Dict[str, Any]:
        """Get current partition status"""
        try:
            # Get disk usage information
            partitions = []
            
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    partitions.append({
                        'device': partition.device,
                        'mountpoint': partition.mountpoint,
                        'fstype': partition.fstype,
                        'total_gb': round(usage.total / (1024**3), 2),
                        'used_gb': round(usage.used / (1024**3), 2),
                        'free_gb': round(usage.free / (1024**3), 2),
                        'percent_used': round((usage.used / usage.total) * 100, 2)
                    })
                except PermissionError:
                    continue
            
            return {
                'partitions': partitions,
                'last_check': self.last_check.isoformat() if self.last_check else None,
                'total_extensions': len(self.extension_history)
            }
            
        except Exception as e:
            logging.error(f"Error getting partition status: {e}")
            return {'error': str(e)}

class ServiceManager:
    """Manage system services and components"""
    
    def __init__(self):
        self.services = {
            'log_filter': {
                'script': '/workspace/scripts/log_filter_system.py',
                'process': None,
                'enabled': True
            },
            'dicom_sanitizer': {
                'script': '/workspace/scripts/dicom_traffic_sanitizer.py',
                'process': None,
                'enabled': True
            },
            'content_sanitizer': {
                'script': '/workspace/scripts/reports_chat_sanitizer.py',
                'process': None,
                'enabled': True
            }
        }
        self.executor = ThreadPoolExecutor(max_workers=4)
    
    async def start_service(self, service_name: str) -> bool:
        """Start a specific service"""
        if service_name not in self.services:
            return False
        
        service = self.services[service_name]
        if service['process'] and service['process'].poll() is None:
            logging.info(f"Service {service_name} is already running")
            return True
        
        try:
            if service_name == 'log_filter':
                service['process'] = subprocess.Popen([
                    sys.executable, service['script'], '--realtime'
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            elif service_name == 'dicom_sanitizer':
                service['process'] = subprocess.Popen([
                    sys.executable, service['script'], '--start-proxy'
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            elif service_name == 'content_sanitizer':
                # Content sanitizer runs on-demand, so we just mark it as ready
                service['process'] = True
            
            logging.info(f"Started service: {service_name}")
            return True
            
        except Exception as e:
            logging.error(f"Error starting service {service_name}: {e}")
            return False
    
    async def stop_service(self, service_name: str) -> bool:
        """Stop a specific service"""
        if service_name not in self.services:
            return False
        
        service = self.services[service_name]
        
        try:
            if hasattr(service['process'], 'terminate'):
                service['process'].terminate()
                service['process'].wait(timeout=10)
            
            service['process'] = None
            logging.info(f"Stopped service: {service_name}")
            return True
            
        except Exception as e:
            logging.error(f"Error stopping service {service_name}: {e}")
            return False
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get status of all services"""
        status = {}
        
        for service_name, service in self.services.items():
            if service['process'] is None:
                status[service_name] = 'stopped'
            elif service['process'] is True:  # Content sanitizer
                status[service_name] = 'ready'
            elif hasattr(service['process'], 'poll'):
                if service['process'].poll() is None:
                    status[service_name] = 'running'
                else:
                    status[service_name] = 'stopped'
                    service['process'] = None
            else:
                status[service_name] = 'unknown'
        
        return status

class SecurityOrchestrator:
    """Main orchestrator for all security components"""
    
    def __init__(self, config_path: str = "/etc/security_orchestrator.conf"):
        self.config = self._load_config(config_path)
        self.monitor = SystemMonitor()
        self.partition_manager = PartitionManager()
        self.service_manager = ServiceManager()
        self.db_path = self.config.get('database_path', '/var/log/security_orchestrator.db')
        
        # Component instances
        self.log_filter = None
        self.dicom_sanitizer = None
        self.content_sanitizer = None
        
        self.running = False
        self.monitoring_task = None
        
        self._init_database()
        self._setup_logging()
        
        # Initialize components
        self._init_components()
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from file"""
        default_config = {
            'monitoring_interval': 300,  # 5 minutes
            'partition_check_interval': 1800,  # 30 minutes
            'log_retention_days': 30,
            'enable_auto_partition_extension': True,
            'enable_log_filtering': True,
            'enable_dicom_sanitization': True,
            'enable_content_sanitization': True,
            'database_path': '/var/log/security_orchestrator.db',
            'alert_email': None,
            'webhook_url': None
        }
        
        if Path(config_path).exists():
            try:
                config = configparser.ConfigParser()
                config.read(config_path)
                
                # Convert to dict
                loaded_config = {}
                for section in config.sections():
                    for key, value in config[section].items():
                        # Convert string values to appropriate types
                        if value.lower() in ['true', 'false']:
                            loaded_config[key] = value.lower() == 'true'
                        elif value.isdigit():
                            loaded_config[key] = int(value)
                        else:
                            loaded_config[key] = value
                
                default_config.update(loaded_config)
                
            except Exception as e:
                logging.error(f"Error loading config: {e}")
        
        return default_config
    
    def _setup_logging(self):
        """Setup logging configuration"""
        log_level = logging.INFO
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        
        logging.basicConfig(
            level=log_level,
            format=log_format,
            handlers=[
                logging.FileHandler('/var/log/security_orchestrator.log'),
                logging.StreamHandler()
            ]
        )
        
        # Reduce noise from some modules
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)
    
    def _init_database(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                component TEXT NOT NULL,
                status TEXT NOT NULL,
                metrics TEXT,
                alerts TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                source TEXT,
                description TEXT,
                details TEXT,
                resolved BOOLEAN DEFAULT FALSE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _init_components(self):
        """Initialize security components"""
        try:
            if self.config.get('enable_log_filtering', True):
                self.log_filter = LogFilterSystem()
                logging.info("Log filtering system initialized")
            
            if self.config.get('enable_dicom_sanitization', True):
                self.dicom_sanitizer = DicomTrafficSanitizationSystem()
                logging.info("DICOM sanitization system initialized")
            
            if self.config.get('enable_content_sanitization', True):
                self.content_sanitizer = ContentSanitizationSystem()
                logging.info("Content sanitization system initialized")
                
        except Exception as e:
            logging.error(f"Error initializing components: {e}")
    
    async def start_orchestrator(self):
        """Start the security orchestrator"""
        logging.info("Starting Ubuntu Security Orchestrator")
        self.running = True
        
        # Start services
        if self.config.get('enable_log_filtering', True):
            await self.service_manager.start_service('log_filter')
        
        if self.config.get('enable_dicom_sanitization', True):
            await self.service_manager.start_service('dicom_sanitizer')
        
        if self.config.get('enable_content_sanitization', True):
            await self.service_manager.start_service('content_sanitizer')
        
        # Start monitoring loop
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        try:
            await self.monitoring_task
        except asyncio.CancelledError:
            logging.info("Monitoring task cancelled")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logging.info(f"Received signal {signum}, shutting down...")
        self.running = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        last_partition_check = datetime.min
        
        while self.running:
            try:
                current_time = datetime.now()
                
                # System resource monitoring
                resources = self.monitor.get_system_resources()
                disk_alerts = self.monitor.check_disk_space_alerts()
                
                # Log disk alerts
                for alert in disk_alerts:
                    await self._log_security_event(
                        'disk_space_alert',
                        alert['severity'],
                        'system_monitor',
                        alert['message'],
                        alert
                    )
                
                # Partition extension check
                partition_status = {}
                if (self.config.get('enable_auto_partition_extension', True) and 
                    (current_time - last_partition_check).seconds > self.config.get('partition_check_interval', 1800)):
                    
                    partition_status = self.partition_manager.check_and_extend_partitions()
                    last_partition_check = current_time
                    
                    if partition_status.get('extensions_performed', 0) > 0:
                        await self._log_security_event(
                            'partition_extension',
                            'info',
                            'partition_manager',
                            f"Extended {partition_status['extensions_performed']} partitions",
                            partition_status
                        )
                
                # Service status check
                service_status = self.service_manager.get_service_status()
                
                # Component health checks
                component_health = await self._check_component_health()
                
                # Store system status
                await self._store_system_status(resources, partition_status, service_status, component_health)
                
                # Sleep until next check
                await asyncio.sleep(self.config.get('monitoring_interval', 300))
                
            except Exception as e:
                logging.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Short sleep on error
    
    async def _check_component_health(self) -> Dict[str, ComponentHealth]:
        """Check health of all components"""
        health = {}
        
        try:
            # Check log filter system
            if self.log_filter:
                try:
                    # Get recent exploit summary
                    exploit_summary = self.log_filter.database.get_exploit_summary(1)
                    health['log_filter'] = ComponentHealth(
                        name='log_filter',
                        status='healthy',
                        last_check=datetime.now(),
                        details={'exploit_summary': exploit_summary},
                        metrics={'total_exploits': exploit_summary.get('total_exploits', 0)}
                    )
                except Exception as e:
                    health['log_filter'] = ComponentHealth(
                        name='log_filter',
                        status='error',
                        last_check=datetime.now(),
                        details={'error': str(e)},
                        metrics={}
                    )
            
            # Check DICOM sanitizer
            if self.dicom_sanitizer:
                try:
                    status = self.dicom_sanitizer.get_system_status()
                    health['dicom_sanitizer'] = ComponentHealth(
                        name='dicom_sanitizer',
                        status='healthy',
                        last_check=datetime.now(),
                        details=status,
                        metrics={
                            'total_connections': status.get('traffic_summary', {}).get('total_connections', 0),
                            'blocked_connections': status.get('traffic_summary', {}).get('blocked_connections', 0)
                        }
                    )
                except Exception as e:
                    health['dicom_sanitizer'] = ComponentHealth(
                        name='dicom_sanitizer',
                        status='error',
                        last_check=datetime.now(),
                        details={'error': str(e)},
                        metrics={}
                    )
            
            # Check content sanitizer
            if self.content_sanitizer:
                try:
                    stats = self.content_sanitizer.get_system_stats(1)
                    health['content_sanitizer'] = ComponentHealth(
                        name='content_sanitizer',
                        status='healthy',
                        last_check=datetime.now(),
                        details=stats,
                        metrics={
                            'total_processed': sum(s.get('total_processed', 0) for s in stats.get('sanitization_stats', [])),
                            'unsafe_count': sum(s.get('unsafe_count', 0) for s in stats.get('sanitization_stats', []))
                        }
                    )
                except Exception as e:
                    health['content_sanitizer'] = ComponentHealth(
                        name='content_sanitizer',
                        status='error',
                        last_check=datetime.now(),
                        details={'error': str(e)},
                        metrics={}
                    )
            
        except Exception as e:
            logging.error(f"Error checking component health: {e}")
        
        return health
    
    async def _store_system_status(self, resources: Dict, partition_status: Dict, 
                                  service_status: Dict, component_health: Dict):
        """Store system status in database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            timestamp = datetime.now().isoformat()
            
            # Store overall system status
            cursor.execute("""
                INSERT INTO system_status (timestamp, component, status, metrics, alerts)
                VALUES (?, ?, ?, ?, ?)
            """, (
                timestamp,
                'system_resources',
                'healthy' if not resources.get('error') else 'error',
                json.dumps(resources),
                json.dumps([])  # No alerts for now
            ))
            
            # Store component statuses
            for component_name, health in component_health.items():
                cursor.execute("""
                    INSERT INTO system_status (timestamp, component, status, metrics, alerts)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    timestamp,
                    component_name,
                    health.status,
                    json.dumps(health.metrics),
                    json.dumps([])  # Health details stored separately
                ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logging.error(f"Error storing system status: {e}")
    
    async def _log_security_event(self, event_type: str, severity: str, source: str, 
                                 description: str, details: Dict):
        """Log a security event"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO security_events 
                (timestamp, event_type, severity, source, description, details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                event_type,
                severity,
                source,
                description,
                json.dumps(details)
            ))
            
            conn.commit()
            conn.close()
            
            logging.info(f"Security event logged: {event_type} - {description}")
            
        except Exception as e:
            logging.error(f"Error logging security event: {e}")
    
    def get_system_overview(self) -> SystemStatus:
        """Get complete system overview"""
        try:
            # Get current system resources
            resources = self.monitor.get_system_resources()
            
            # Get partition status
            partition_status = self.partition_manager.get_partition_status()
            
            # Get service status
            service_status = self.service_manager.get_service_status()
            
            # Get component health
            component_health = {}
            if self.log_filter:
                try:
                    exploit_summary = self.log_filter.database.get_exploit_summary(24)
                    component_health['log_filtering'] = {
                        'status': 'healthy',
                        'metrics': exploit_summary
                    }
                except:
                    component_health['log_filtering'] = {'status': 'error'}
            
            if self.dicom_sanitizer:
                try:
                    dicom_status = self.dicom_sanitizer.get_system_status()
                    component_health['dicom_sanitization'] = {
                        'status': 'healthy',
                        'metrics': dicom_status
                    }
                except:
                    component_health['dicom_sanitization'] = {'status': 'error'}
            
            if self.content_sanitizer:
                try:
                    content_stats = self.content_sanitizer.get_system_stats(24)
                    component_health['content_sanitization'] = {
                        'status': 'healthy',
                        'metrics': content_stats
                    }
                except:
                    component_health['content_sanitization'] = {'status': 'error'}
            
            # Determine overall health
            overall_health = 'healthy'
            if any(status == 'error' for status in service_status.values()):
                overall_health = 'degraded'
            if resources.get('error'):
                overall_health = 'error'
            
            return SystemStatus(
                timestamp=datetime.now(),
                partition_extension=partition_status,
                log_filtering=component_health.get('log_filtering', {}),
                dicom_sanitization=component_health.get('dicom_sanitization', {}),
                content_sanitization=component_health.get('content_sanitization', {}),
                system_resources=resources,
                overall_health=overall_health
            )
            
        except Exception as e:
            logging.error(f"Error getting system overview: {e}")
            return SystemStatus(
                timestamp=datetime.now(),
                partition_extension={'error': str(e)},
                log_filtering={'error': str(e)},
                dicom_sanitization={'error': str(e)},
                content_sanitization={'error': str(e)},
                system_resources={'error': str(e)},
                overall_health='error'
            )
    
    async def stop_orchestrator(self):
        """Stop the orchestrator and all services"""
        logging.info("Stopping Ubuntu Security Orchestrator")
        self.running = False
        
        # Stop all services
        for service_name in self.service_manager.services.keys():
            await self.service_manager.stop_service(service_name)
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logging.info("Ubuntu Security Orchestrator stopped")

async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Ubuntu Security Orchestrator')
    parser.add_argument('--config', default='/etc/security_orchestrator.conf', help='Configuration file')
    parser.add_argument('--start', action='store_true', help='Start the orchestrator')
    parser.add_argument('--status', action='store_true', help='Show system status')
    parser.add_argument('--install', action='store_true', help='Install system services')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon')
    
    args = parser.parse_args()
    
    orchestrator = SecurityOrchestrator(args.config)
    
    try:
        if args.install:
            await install_system_services(orchestrator)
        
        elif args.status:
            status = orchestrator.get_system_overview()
            print(json.dumps(asdict(status), indent=2, default=str))
        
        elif args.start or args.daemon:
            await orchestrator.start_orchestrator()
        
        else:
            print("No action specified. Use --help for usage information.")
            print("Available actions: --start, --status, --install, --daemon")
    
    except KeyboardInterrupt:
        logging.info("Received interrupt, shutting down...")
        await orchestrator.stop_orchestrator()
    except Exception as e:
        logging.error(f"Error in main: {e}")
        raise

async def install_system_services(orchestrator: SecurityOrchestrator):
    """Install systemd services for the orchestrator"""
    logging.info("Installing system services...")
    
    # Create systemd service file
    service_content = f"""[Unit]
Description=Ubuntu Security Orchestrator
After=multi-user.target network.target
Wants=network.target

[Service]
Type=simple
ExecStart={sys.executable} /workspace/scripts/ubuntu_security_orchestrator.py --daemon
Restart=always
RestartSec=10
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    
    service_path = "/etc/systemd/system/ubuntu-security-orchestrator.service"
    
    try:
        with open(service_path, 'w') as f:
            f.write(service_content)
        
        # Reload systemd and enable service
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'ubuntu-security-orchestrator'], check=True)
        
        # Install partition extension service
        subprocess.run(['/workspace/scripts/auto_partition_extend.sh', '--install'], check=True)
        
        logging.info("System services installed successfully")
        logging.info("Start with: systemctl start ubuntu-security-orchestrator")
        
    except Exception as e:
        logging.error(f"Error installing services: {e}")
        raise

if __name__ == "__main__":
    # Ensure we're running as root for system operations
    if os.geteuid() != 0 and '--status' not in sys.argv:
        print("This script requires root privileges for system operations.")
        print("Run with sudo for full functionality, or use --status for read-only operations.")
        if '--status' not in sys.argv:
            sys.exit(1)
    
    asyncio.run(main())
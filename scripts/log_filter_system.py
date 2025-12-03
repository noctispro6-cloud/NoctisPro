#!/usr/bin/env python3

"""
Advanced Log Filtering System for Ubuntu Server
Filters logs to save only valid information and block exploit attempts
"""

import re
import json
import logging
import hashlib
import asyncio
import aiofiles
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import geoip2.database
import ipaddress
import sqlite3
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    source: str
    message: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_path: Optional[str] = None
    status_code: Optional[int] = None
    is_exploit: bool = False
    exploit_type: Optional[str] = None
    risk_score: int = 0

class ExploitDetector:
    """Advanced exploit detection using pattern matching and behavioral analysis"""
    
    def __init__(self):
        self.sql_injection_patterns = [
            r"(?i)(union\s+select|select\s+.*\s+from|insert\s+into|delete\s+from|drop\s+table)",
            r"(?i)(\'\s*(or|and)\s*\'\s*=\s*\'|\'\s*(or|and)\s*1\s*=\s*1)",
            r"(?i)(exec\s*\(|execute\s*\(|sp_executesql)",
            r"(?i)(xp_cmdshell|sp_configure|openrowset|opendatasource)"
        ]
        
        self.xss_patterns = [
            r"(?i)<script[^>]*>.*?</script>",
            r"(?i)javascript\s*:",
            r"(?i)on(load|error|click|mouseover)\s*=",
            r"(?i)(alert\s*\(|confirm\s*\(|prompt\s*\()",
            r"(?i)(document\.cookie|document\.write|eval\s*\()"
        ]
        
        self.path_traversal_patterns = [
            r"\.\.[\\/]",
            r"[\\/]\.\.[\\/]",
            r"(etc[\\/]passwd|windows[\\/]system32)",
            r"(?i)(boot\.ini|win\.ini|autoexec\.bat)"
        ]
        
        self.command_injection_patterns = [
            r"(?i)(\|\s*nc\s+|\|\s*netcat\s+|\|\s*wget\s+|\|\s*curl\s+)",
            r"(?i)(\$\(.*\)|\`.*\`|;\s*(cat|ls|pwd|whoami|id))",
            r"(?i)(&&\s*|;\s*)(rm\s+-rf|chmod\s+777|chown\s+)"
        ]
        
        self.rfi_lfi_patterns = [
            r"(?i)(http://|https://|ftp://|file://)",
            r"(?i)(php://input|php://filter|data://|expect://)",
            r"(?i)(include\s*\(|require\s*\(|include_once\s*\()"
        ]
        
        self.brute_force_indicators = [
            r"(?i)(failed\s+login|authentication\s+failed|invalid\s+password)",
            r"(?i)(too\s+many\s+requests|rate\s+limit|blocked)",
            r"(?i)(403\s+forbidden|401\s+unauthorized|429\s+too\s+many)"
        ]
        
        # Compile patterns for better performance
        self.compiled_patterns = {
            'sql_injection': [re.compile(p) for p in self.sql_injection_patterns],
            'xss': [re.compile(p) for p in self.xss_patterns],
            'path_traversal': [re.compile(p) for p in self.path_traversal_patterns],
            'command_injection': [re.compile(p) for p in self.command_injection_patterns],
            'rfi_lfi': [re.compile(p) for p in self.rfi_lfi_patterns],
            'brute_force': [re.compile(p) for p in self.brute_force_indicators]
        }
        
        # Known malicious user agents
        self.malicious_user_agents = [
            r"(?i)(nikto|sqlmap|nmap|masscan|zap|burp|acunetix)",
            r"(?i)(havij|pangolin|sqlninja|bsqlbf)",
            r"(?i)(python-requests|curl|wget).*bot",
            r"(?i)(scanner|crawler|spider)(?!.*google|.*bing)"
        ]
        
        self.compiled_ua_patterns = [re.compile(p) for p in self.malicious_user_agents]

    def detect_exploit(self, log_entry: LogEntry) -> Tuple[bool, Optional[str], int]:
        """
        Detect if a log entry contains exploit attempts
        Returns: (is_exploit, exploit_type, risk_score)
        """
        message = log_entry.message.lower()
        user_agent = (log_entry.user_agent or "").lower()
        request_path = (log_entry.request_path or "").lower()
        
        exploit_types = []
        risk_score = 0
        
        # Check all pattern categories
        for category, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(message) or pattern.search(request_path):
                    exploit_types.append(category)
                    risk_score += self._get_risk_score(category)
                    break
        
        # Check user agent
        for pattern in self.compiled_ua_patterns:
            if pattern.search(user_agent):
                exploit_types.append('malicious_ua')
                risk_score += 30
                break
        
        # Additional behavioral checks
        if log_entry.ip_address:
            risk_score += self._check_ip_reputation(log_entry.ip_address)
        
        is_exploit = len(exploit_types) > 0 or risk_score > 50
        exploit_type = ','.join(exploit_types) if exploit_types else None
        
        return is_exploit, exploit_type, min(risk_score, 100)
    
    def _get_risk_score(self, category: str) -> int:
        """Get risk score for exploit category"""
        scores = {
            'sql_injection': 80,
            'xss': 60,
            'path_traversal': 70,
            'command_injection': 90,
            'rfi_lfi': 75,
            'brute_force': 40
        }
        return scores.get(category, 30)
    
    def _check_ip_reputation(self, ip_address: str) -> int:
        """Check IP reputation (simplified implementation)"""
        try:
            ip = ipaddress.ip_address(ip_address)
            
            # Check if IP is in private ranges (lower risk)
            if ip.is_private:
                return 0
            
            # Check for known malicious ranges (simplified)
            # In production, integrate with threat intelligence feeds
            if ip_address.startswith(('1.1.1.', '8.8.8.')):  # Example safe IPs
                return 0
            
            # Default risk for unknown public IPs
            return 10
            
        except ValueError:
            return 20  # Invalid IP format

class LogDatabase:
    """SQLite database for storing filtered logs"""
    
    def __init__(self, db_path: str = "/var/log/filtered_logs.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS filtered_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT,
                source TEXT,
                message TEXT,
                ip_address TEXT,
                user_agent TEXT,
                request_path TEXT,
                status_code INTEGER,
                is_exploit BOOLEAN,
                exploit_type TEXT,
                risk_score INTEGER,
                hash TEXT UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON filtered_logs(timestamp);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_is_exploit ON filtered_logs(is_exploit);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_score ON filtered_logs(risk_score);
        """)
        
        conn.commit()
        conn.close()
    
    def store_log_entry(self, log_entry: LogEntry) -> bool:
        """Store log entry in database, avoiding duplicates"""
        try:
            # Create hash for deduplication
            entry_hash = hashlib.md5(
                f"{log_entry.timestamp}{log_entry.message}".encode()
            ).hexdigest()
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR IGNORE INTO filtered_logs 
                (timestamp, level, source, message, ip_address, user_agent, 
                 request_path, status_code, is_exploit, exploit_type, risk_score, hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_entry.timestamp.isoformat(),
                log_entry.level,
                log_entry.source,
                log_entry.message,
                log_entry.ip_address,
                log_entry.user_agent,
                log_entry.request_path,
                log_entry.status_code,
                log_entry.is_exploit,
                log_entry.exploit_type,
                log_entry.risk_score,
                entry_hash
            ))
            
            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            
            return success
            
        except Exception as e:
            logging.error(f"Error storing log entry: {e}")
            return False
    
    def get_exploit_summary(self, hours: int = 24) -> Dict:
        """Get summary of exploits in the last N hours"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        cursor.execute("""
            SELECT exploit_type, COUNT(*), AVG(risk_score), MAX(risk_score)
            FROM filtered_logs 
            WHERE is_exploit = 1 AND timestamp > ?
            GROUP BY exploit_type
        """, (since,))
        
        results = cursor.fetchall()
        conn.close()
        
        return {
            'period_hours': hours,
            'exploits': [
                {
                    'type': row[0],
                    'count': row[1],
                    'avg_risk': round(row[2], 2),
                    'max_risk': row[3]
                }
                for row in results
            ],
            'total_exploits': sum(row[1] for row in results)
        }

class LogParser:
    """Parse different log formats"""
    
    def __init__(self):
        # Common log patterns
        self.apache_pattern = re.compile(
            r'(?P<ip>\S+) \S+ \S+ \[(?P<timestamp>[^\]]+)\] '
            r'"(?P<method>\S+) (?P<path>\S+) (?P<protocol>\S+)" '
            r'(?P<status>\d+) (?P<size>\S+) "(?P<referer>[^"]*)" "(?P<user_agent>[^"]*)"'
        )
        
        self.nginx_pattern = re.compile(
            r'(?P<ip>\S+) - \S+ \[(?P<timestamp>[^\]]+)\] '
            r'"(?P<method>\S+) (?P<path>\S+) (?P<protocol>\S+)" '
            r'(?P<status>\d+) (?P<size>\S+) "(?P<referer>[^"]*)" "(?P<user_agent>[^"]*)"'
        )
        
        self.syslog_pattern = re.compile(
            r'(?P<timestamp>\w+\s+\d+\s+\d+:\d+:\d+) (?P<hostname>\S+) '
            r'(?P<process>\S+): (?P<message>.*)'
        )
    
    def parse_log_line(self, line: str, source: str) -> Optional[LogEntry]:
        """Parse a log line based on source format"""
        try:
            if 'apache' in source.lower() or 'access' in source.lower():
                return self._parse_apache_log(line, source)
            elif 'nginx' in source.lower():
                return self._parse_nginx_log(line, source)
            elif 'syslog' in source.lower() or 'messages' in source.lower():
                return self._parse_syslog(line, source)
            else:
                return self._parse_generic_log(line, source)
        except Exception as e:
            logging.warning(f"Error parsing log line from {source}: {e}")
            return None
    
    def _parse_apache_log(self, line: str, source: str) -> Optional[LogEntry]:
        """Parse Apache access log format"""
        match = self.apache_pattern.match(line)
        if not match:
            return None
        
        groups = match.groupdict()
        
        return LogEntry(
            timestamp=self._parse_timestamp(groups['timestamp']),
            level='INFO',
            source=source,
            message=line,
            ip_address=groups['ip'],
            user_agent=groups['user_agent'],
            request_path=groups['path'],
            status_code=int(groups['status'])
        )
    
    def _parse_nginx_log(self, line: str, source: str) -> Optional[LogEntry]:
        """Parse Nginx access log format"""
        match = self.nginx_pattern.match(line)
        if not match:
            return None
        
        groups = match.groupdict()
        
        return LogEntry(
            timestamp=self._parse_timestamp(groups['timestamp']),
            level='INFO',
            source=source,
            message=line,
            ip_address=groups['ip'],
            user_agent=groups['user_agent'],
            request_path=groups['path'],
            status_code=int(groups['status'])
        )
    
    def _parse_syslog(self, line: str, source: str) -> Optional[LogEntry]:
        """Parse syslog format"""
        match = self.syslog_pattern.match(line)
        if not match:
            return self._parse_generic_log(line, source)
        
        groups = match.groupdict()
        
        return LogEntry(
            timestamp=self._parse_syslog_timestamp(groups['timestamp']),
            level=self._extract_log_level(groups['message']),
            source=source,
            message=groups['message']
        )
    
    def _parse_generic_log(self, line: str, source: str) -> LogEntry:
        """Parse generic log format"""
        return LogEntry(
            timestamp=datetime.now(),
            level=self._extract_log_level(line),
            source=source,
            message=line.strip()
        )
    
    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp from log"""
        try:
            # Apache/Nginx format: 10/Oct/2023:13:55:36 +0000
            return datetime.strptime(timestamp_str.split()[0], '%d/%b/%Y:%H:%M:%S')
        except:
            return datetime.now()
    
    def _parse_syslog_timestamp(self, timestamp_str: str) -> datetime:
        """Parse syslog timestamp"""
        try:
            # Syslog format: Oct 10 13:55:36
            current_year = datetime.now().year
            return datetime.strptime(f"{current_year} {timestamp_str}", '%Y %b %d %H:%M:%S')
        except:
            return datetime.now()
    
    def _extract_log_level(self, message: str) -> str:
        """Extract log level from message"""
        message_lower = message.lower()
        if 'error' in message_lower or 'err' in message_lower:
            return 'ERROR'
        elif 'warn' in message_lower:
            return 'WARNING'
        elif 'debug' in message_lower:
            return 'DEBUG'
        else:
            return 'INFO'

class LogFileWatcher(FileSystemEventHandler):
    """Watch log files for changes and process new entries"""
    
    def __init__(self, log_filter: 'LogFilterSystem'):
        self.log_filter = log_filter
        self.file_positions = {}
    
    def on_modified(self, event):
        """Handle file modification events"""
        if not event.is_directory and event.src_path in self.log_filter.watched_files:
            asyncio.create_task(self._process_new_lines(event.src_path))
    
    async def _process_new_lines(self, file_path: str):
        """Process new lines added to log file"""
        try:
            current_pos = self.file_positions.get(file_path, 0)
            
            async with aiofiles.open(file_path, 'r') as f:
                await f.seek(current_pos)
                new_lines = await f.readlines()
                self.file_positions[file_path] = await f.tell()
            
            for line in new_lines:
                if line.strip():
                    await self.log_filter.process_log_line(line.strip(), file_path)
                    
        except Exception as e:
            logging.error(f"Error processing new lines from {file_path}: {e}")

class LogFilterSystem:
    """Main log filtering system"""
    
    def __init__(self, config_path: str = "/etc/log_filter_config.json"):
        self.config = self._load_config(config_path)
        self.exploit_detector = ExploitDetector()
        self.log_parser = LogParser()
        self.database = LogDatabase(self.config.get('database_path', '/var/log/filtered_logs.db'))
        self.watched_files = set()
        self.observer = None
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/var/log/log_filter_system.log'),
                logging.StreamHandler()
            ]
        )
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from JSON file"""
        default_config = {
            "watched_directories": ["/var/log"],
            "watched_files": [
                "/var/log/apache2/access.log",
                "/var/log/nginx/access.log",
                "/var/log/syslog",
                "/var/log/auth.log"
            ],
            "database_path": "/var/log/filtered_logs.db",
            "max_log_age_days": 30,
            "risk_threshold": 50,
            "enable_realtime": True
        }
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                # Merge with defaults
                default_config.update(config)
                return default_config
        except FileNotFoundError:
            logging.info(f"Config file {config_path} not found, using defaults")
            return default_config
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing config file: {e}")
            return default_config
    
    async def process_log_line(self, line: str, source: str):
        """Process a single log line"""
        log_entry = self.log_parser.parse_log_line(line, source)
        if not log_entry:
            return
        
        # Detect exploits
        is_exploit, exploit_type, risk_score = self.exploit_detector.detect_exploit(log_entry)
        
        log_entry.is_exploit = is_exploit
        log_entry.exploit_type = exploit_type
        log_entry.risk_score = risk_score
        
        # Only store if it's valid info or an exploit
        if self._should_store_log(log_entry):
            success = self.database.store_log_entry(log_entry)
            if success and is_exploit:
                logging.warning(f"Exploit detected: {exploit_type} (Risk: {risk_score}) from {log_entry.ip_address}")
    
    def _should_store_log(self, log_entry: LogEntry) -> bool:
        """Determine if log entry should be stored"""
        # Always store exploits
        if log_entry.is_exploit:
            return True
        
        # Store high-risk entries
        if log_entry.risk_score >= self.config.get('risk_threshold', 50):
            return True
        
        # Store error logs
        if log_entry.level in ['ERROR', 'CRITICAL']:
            return True
        
        # Store successful authentications
        if 'login' in log_entry.message.lower() and 'success' in log_entry.message.lower():
            return True
        
        # Filter out noise (common valid requests)
        noise_patterns = [
            r'GET.*\.(css|js|png|jpg|ico|woff)',
            r'200.*favicon',
            r'OPTIONS.*',
        ]
        
        for pattern in noise_patterns:
            if re.search(pattern, log_entry.message, re.IGNORECASE):
                return False
        
        return True
    
    def start_realtime_monitoring(self):
        """Start real-time log file monitoring"""
        if not self.config.get('enable_realtime', True):
            return
        
        self.observer = Observer()
        file_watcher = LogFileWatcher(self)
        
        # Watch configured directories
        for directory in self.config.get('watched_directories', []):
            if Path(directory).exists():
                self.observer.schedule(file_watcher, directory, recursive=True)
                logging.info(f"Watching directory: {directory}")
        
        # Add specific files to watched set
        for file_path in self.config.get('watched_files', []):
            if Path(file_path).exists():
                self.watched_files.add(file_path)
                logging.info(f"Watching file: {file_path}")
        
        self.observer.start()
        logging.info("Real-time log monitoring started")
    
    def stop_realtime_monitoring(self):
        """Stop real-time log file monitoring"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            logging.info("Real-time log monitoring stopped")
    
    async def process_existing_logs(self):
        """Process existing log files"""
        for file_path in self.config.get('watched_files', []):
            if Path(file_path).exists():
                await self._process_log_file(file_path)
    
    async def _process_log_file(self, file_path: str):
        """Process an entire log file"""
        logging.info(f"Processing log file: {file_path}")
        
        try:
            async with aiofiles.open(file_path, 'r') as f:
                async for line in f:
                    if line.strip():
                        await self.process_log_line(line.strip(), file_path)
        except Exception as e:
            logging.error(f"Error processing log file {file_path}: {e}")
    
    def cleanup_old_logs(self):
        """Clean up old log entries from database"""
        max_age = self.config.get('max_log_age_days', 30)
        cutoff_date = (datetime.now() - timedelta(days=max_age)).isoformat()
        
        conn = sqlite3.connect(self.database.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM filtered_logs WHERE timestamp < ?", (cutoff_date,))
        deleted_count = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        logging.info(f"Cleaned up {deleted_count} old log entries")
    
    def get_security_report(self) -> Dict:
        """Generate security report"""
        return {
            'timestamp': datetime.now().isoformat(),
            'exploit_summary_24h': self.database.get_exploit_summary(24),
            'exploit_summary_7d': self.database.get_exploit_summary(168),
            'config': self.config
        }

async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Advanced Log Filtering System')
    parser.add_argument('--config', default='/etc/log_filter_config.json', help='Configuration file path')
    parser.add_argument('--process-existing', action='store_true', help='Process existing log files')
    parser.add_argument('--realtime', action='store_true', help='Enable real-time monitoring')
    parser.add_argument('--report', action='store_true', help='Generate security report')
    parser.add_argument('--cleanup', action='store_true', help='Clean up old logs')
    
    args = parser.parse_args()
    
    log_filter = LogFilterSystem(args.config)
    
    try:
        if args.process_existing:
            await log_filter.process_existing_logs()
        
        if args.cleanup:
            log_filter.cleanup_old_logs()
        
        if args.report:
            report = log_filter.get_security_report()
            print(json.dumps(report, indent=2))
        
        if args.realtime:
            log_filter.start_realtime_monitoring()
            try:
                while True:
                    await asyncio.sleep(60)  # Keep running
            except KeyboardInterrupt:
                log_filter.stop_realtime_monitoring()
    
    except Exception as e:
        logging.error(f"Error in main: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
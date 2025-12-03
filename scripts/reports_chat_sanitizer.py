#!/usr/bin/env python3

"""
Reports and Chat Sanitization System
Advanced sanitization for reports, chat messages, and user-generated content
before reaching the server infrastructure
"""

import re
import json
import logging
import hashlib
import asyncio
import aiofiles
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from dataclasses import dataclass, asdict
import sqlite3
import threading
from collections import defaultdict
import html
import bleach
from urllib.parse import urlparse, parse_qs
import base64
import mimetypes
from cryptography.fernet import Fernet
import textstat
import langdetect
from profanity_check import predict as is_profanity
import spacy
from transformers import pipeline

@dataclass
class SanitizationResult:
    original_content: str
    sanitized_content: str
    content_type: str
    risk_score: int
    is_safe: bool
    removed_elements: List[Dict[str, str]]
    warnings: List[str]
    metadata: Dict[str, Any]
    processing_time: float

@dataclass
class ContentAnalysis:
    language: str
    readability_score: float
    sentiment_score: float
    toxicity_score: float
    contains_pii: bool
    contains_profanity: bool
    word_count: int
    character_count: int

class AdvancedContentAnalyzer:
    """Advanced content analysis using NLP models"""
    
    def __init__(self):
        try:
            # Load spaCy model for NER
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            logging.warning("spaCy model not found. Install with: python -m spacy download en_core_web_sm")
            self.nlp = None
        
        try:
            # Load toxicity detection model
            self.toxicity_classifier = pipeline(
                "text-classification", 
                model="unitary/toxic-bert",
                device=-1  # Use CPU
            )
        except Exception as e:
            logging.warning(f"Could not load toxicity model: {e}")
            self.toxicity_classifier = None
        
        # PII patterns
        self.pii_patterns = {
            'ssn': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
            'credit_card': re.compile(r'\b(?:\d{4}[\s-]?){3}\d{4}\b'),
            'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'phone': re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
            'ip_address': re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
            'mac_address': re.compile(r'\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b'),
            'passport': re.compile(r'\b[A-Z]{2}\d{7}\b'),
            'license_plate': re.compile(r'\b[A-Z]{2,3}[-\s]?\d{2,4}[-\s]?[A-Z]{1,3}\b'),
        }
    
    def analyze_content(self, content: str) -> ContentAnalysis:
        """Perform comprehensive content analysis"""
        start_time = datetime.now()
        
        # Basic metrics
        word_count = len(content.split())
        character_count = len(content)
        
        # Language detection
        try:
            language = langdetect.detect(content) if content.strip() else 'unknown'
        except:
            language = 'unknown'
        
        # Readability
        readability_score = textstat.flesch_reading_ease(content) if content.strip() else 0
        
        # PII detection
        contains_pii = any(pattern.search(content) for pattern in self.pii_patterns.values())
        
        # Profanity detection
        contains_profanity = is_profanity(content) if content.strip() else False
        
        # Sentiment and toxicity
        sentiment_score = 0.0
        toxicity_score = 0.0
        
        if self.toxicity_classifier and content.strip():
            try:
                # Limit content length for model
                content_sample = content[:512]  
                toxicity_result = self.toxicity_classifier(content_sample)
                if isinstance(toxicity_result, list) and len(toxicity_result) > 0:
                    # Assuming binary classification with toxic/non-toxic
                    toxicity_score = toxicity_result[0].get('score', 0.0)
                    if toxicity_result[0].get('label') == 'NON_TOXIC':
                        toxicity_score = 1.0 - toxicity_score
            except Exception as e:
                logging.warning(f"Toxicity analysis failed: {e}")
        
        return ContentAnalysis(
            language=language,
            readability_score=readability_score,
            sentiment_score=sentiment_score,
            toxicity_score=toxicity_score,
            contains_pii=contains_pii,
            contains_profanity=contains_profanity,
            word_count=word_count,
            character_count=character_count
        )
    
    def extract_entities(self, content: str) -> List[Dict[str, str]]:
        """Extract named entities from content"""
        entities = []
        
        if self.nlp and content.strip():
            try:
                doc = self.nlp(content[:1000])  # Limit for performance
                for ent in doc.ents:
                    entities.append({
                        'text': ent.text,
                        'label': ent.label_,
                        'description': spacy.explain(ent.label_) or ent.label_
                    })
            except Exception as e:
                logging.warning(f"Entity extraction failed: {e}")
        
        return entities

class ReportSanitizer:
    """Specialized sanitizer for medical/technical reports"""
    
    def __init__(self):
        self.content_analyzer = AdvancedContentAnalyzer()
        
        # Medical report specific patterns
        self.medical_pii_patterns = {
            'mrn': re.compile(r'\bMRN\s*:?\s*\d{6,10}\b', re.IGNORECASE),
            'patient_id': re.compile(r'\bpatient\s*(?:id|number)\s*:?\s*\d+\b', re.IGNORECASE),
            'dob': re.compile(r'\b(?:dob|date\s*of\s*birth)\s*:?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', re.IGNORECASE),
            'provider_npi': re.compile(r'\bNPI\s*:?\s*\d{10}\b', re.IGNORECASE),
            'insurance_id': re.compile(r'\b(?:insurance|policy)\s*(?:id|number)\s*:?\s*[A-Z0-9]{6,20}\b', re.IGNORECASE),
        }
        
        # Sensitive medical information patterns
        self.sensitive_medical_patterns = {
            'diagnosis_codes': re.compile(r'\b[A-Z]\d{2}(?:\.\d{1,2})?\b'),  # ICD-10 codes
            'procedure_codes': re.compile(r'\b\d{5}(?:-\d{2})?\b'),  # CPT codes
            'drug_names': re.compile(r'\b(?:mg|mcg|ml|units?)\s+(?:of\s+)?[A-Za-z]{3,}\b', re.IGNORECASE),
        }
        
        # Allowed HTML tags for rich text reports
        self.allowed_tags = [
            'p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li', 'table', 'tr', 'td', 'th', 'thead', 'tbody',
            'div', 'span', 'blockquote', 'pre', 'code'
        ]
        
        self.allowed_attributes = {
            '*': ['class', 'id'],
            'table': ['border', 'cellpadding', 'cellspacing'],
            'td': ['colspan', 'rowspan'],
            'th': ['colspan', 'rowspan'],
        }
    
    def sanitize_report(self, content: str, content_type: str = 'text') -> SanitizationResult:
        """Sanitize medical/technical report content"""
        start_time = datetime.now()
        original_content = content
        sanitized_content = content
        removed_elements = []
        warnings = []
        risk_score = 0
        
        # Content analysis
        analysis = self.content_analyzer.analyze_content(content)
        
        # HTML sanitization for rich text reports
        if content_type.lower() in ['html', 'rich_text']:
            sanitized_content = bleach.clean(
                sanitized_content,
                tags=self.allowed_tags,
                attributes=self.allowed_attributes,
                strip=True
            )
            # Check for removed HTML
            if len(sanitized_content) < len(content) * 0.9:
                warnings.append("Significant HTML content removed")
                risk_score += 20
        
        # Remove medical PII
        for pii_type, pattern in self.medical_pii_patterns.items():
            matches = pattern.findall(sanitized_content)
            if matches:
                sanitized_content = pattern.sub(f'[{pii_type.upper()}_REDACTED]', sanitized_content)
                removed_elements.extend([{
                    'type': 'medical_pii',
                    'subtype': pii_type,
                    'content': match,
                    'reason': 'Privacy protection'
                } for match in matches])
                risk_score += len(matches) * 15
        
        # Handle sensitive medical information with care
        for info_type, pattern in self.sensitive_medical_patterns.items():
            matches = pattern.findall(sanitized_content)
            if matches:
                # For medical codes, we might want to keep them but flag them
                if info_type in ['diagnosis_codes', 'procedure_codes']:
                    # Keep codes but add warning
                    warnings.append(f"Contains {info_type}: review for appropriateness")
                    risk_score += len(matches) * 5
                else:
                    # Redact other sensitive info
                    sanitized_content = pattern.sub(f'[{info_type.upper()}_REDACTED]', sanitized_content)
                    removed_elements.extend([{
                        'type': 'sensitive_medical',
                        'subtype': info_type,
                        'content': match,
                        'reason': 'Sensitive medical information'
                    } for match in matches])
                    risk_score += len(matches) * 10
        
        # Remove general PII
        for pii_type, pattern in self.content_analyzer.pii_patterns.items():
            matches = pattern.findall(sanitized_content)
            if matches:
                sanitized_content = pattern.sub(f'[{pii_type.upper()}_REDACTED]', sanitized_content)
                removed_elements.extend([{
                    'type': 'pii',
                    'subtype': pii_type,
                    'content': match,
                    'reason': 'Personal information protection'
                } for match in matches])
                risk_score += len(matches) * 20
        
        # Check for profanity and inappropriate content
        if analysis.contains_profanity:
            warnings.append("Contains inappropriate language")
            risk_score += 30
        
        # Check toxicity score
        if analysis.toxicity_score > 0.7:
            warnings.append(f"High toxicity score: {analysis.toxicity_score:.2f}")
            risk_score += int(analysis.toxicity_score * 40)
        
        # Additional report-specific sanitization
        sanitized_content = self._sanitize_report_specific(sanitized_content, warnings, removed_elements)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return SanitizationResult(
            original_content=original_content,
            sanitized_content=sanitized_content,
            content_type=content_type,
            risk_score=min(risk_score, 100),
            is_safe=risk_score < 50,
            removed_elements=removed_elements,
            warnings=warnings,
            metadata={
                'analysis': asdict(analysis),
                'original_length': len(original_content),
                'sanitized_length': len(sanitized_content),
                'reduction_ratio': 1 - (len(sanitized_content) / len(original_content)) if original_content else 0
            },
            processing_time=processing_time
        )
    
    def _sanitize_report_specific(self, content: str, warnings: List[str], removed_elements: List[Dict]) -> str:
        """Report-specific sanitization rules"""
        
        # Remove excessive whitespace and normalize formatting
        content = re.sub(r'\s+', ' ', content)
        content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)
        
        # Remove potential code injection in report templates
        code_patterns = [
            r'<%.*?%>',  # Template code
            r'\{\{.*?\}\}',  # Template variables
            r'\$\{.*?\}',  # Variable substitution
            r'<\?.*?\?>',  # PHP code
        ]
        
        for pattern in code_patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            if matches:
                content = re.sub(pattern, '[TEMPLATE_CODE_REMOVED]', content, flags=re.DOTALL)
                removed_elements.extend([{
                    'type': 'code_injection',
                    'subtype': 'template_code',
                    'content': match,
                    'reason': 'Potential code injection'
                } for match in matches])
                warnings.append("Template code removed for security")
        
        # Remove SQL-like patterns
        sql_patterns = [
            r'(?i)\b(select|insert|update|delete|drop|create|alter)\s+.*?\b(from|into|table|database)\b',
            r'(?i)\bunion\s+select\b',
            r'(?i)\bor\s+1\s*=\s*1\b',
        ]
        
        for pattern in sql_patterns:
            if re.search(pattern, content):
                content = re.sub(pattern, '[SQL_PATTERN_REMOVED]', content, flags=re.IGNORECASE)
                warnings.append("SQL-like patterns removed")
        
        return content.strip()

class ChatSanitizer:
    """Specialized sanitizer for chat messages and conversations"""
    
    def __init__(self):
        self.content_analyzer = AdvancedContentAnalyzer()
        
        # Chat-specific patterns
        self.spam_patterns = [
            r'(?i)\b(click\s+here|visit\s+now|act\s+fast|limited\s+time)\b',
            r'(?i)\b(free\s+money|easy\s+cash|work\s+from\s+home)\b',
            r'(?i)\b(viagra|cialis|pharmacy|pills)\b',
            r'(?i)\b(casino|poker|gambling|lottery)\b',
        ]
        
        self.malicious_link_patterns = [
            r'(?i)\b(bit\.ly|tinyurl|t\.co|goo\.gl|ow\.ly)/[a-zA-Z0-9]+',
            r'(?i)\bhttps?://[a-zA-Z0-9.-]+\.(?:tk|ml|ga|cf|xyz|click|download)\b',
            r'(?i)\bhttps?://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b',
        ]
        
        # Emoji and special character handling
        self.excessive_emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]{5,}')
        self.excessive_caps_pattern = re.compile(r'\b[A-Z]{4,}\b')
        
        self.compiled_spam = [re.compile(pattern) for pattern in self.spam_patterns]
        self.compiled_malicious_links = [re.compile(pattern) for pattern in self.malicious_link_patterns]
    
    def sanitize_chat_message(self, message: str, user_id: Optional[str] = None, 
                             conversation_context: Optional[List[str]] = None) -> SanitizationResult:
        """Sanitize individual chat message"""
        start_time = datetime.now()
        original_content = message
        sanitized_content = message
        removed_elements = []
        warnings = []
        risk_score = 0
        
        # Content analysis
        analysis = self.content_analyzer.analyze_content(message)
        
        # Remove PII from chat
        for pii_type, pattern in self.content_analyzer.pii_patterns.items():
            matches = pattern.findall(sanitized_content)
            if matches:
                sanitized_content = pattern.sub(f'[{pii_type.upper()}_REMOVED]', sanitized_content)
                removed_elements.extend([{
                    'type': 'pii',
                    'subtype': pii_type,
                    'content': match,
                    'reason': 'Privacy protection in chat'
                } for match in matches])
                risk_score += len(matches) * 25
        
        # Check for spam patterns
        for pattern in self.compiled_spam:
            if pattern.search(sanitized_content):
                warnings.append("Potential spam content detected")
                risk_score += 40
        
        # Check for malicious links
        for pattern in self.compiled_malicious_links:
            matches = pattern.findall(sanitized_content)
            if matches:
                sanitized_content = pattern.sub('[SUSPICIOUS_LINK_REMOVED]', sanitized_content)
                removed_elements.extend([{
                    'type': 'malicious_link',
                    'subtype': 'suspicious_url',
                    'content': match,
                    'reason': 'Potentially malicious URL'
                } for match in matches])
                warnings.append("Suspicious links removed")
                risk_score += len(matches) * 50
        
        # Handle excessive formatting
        if self.excessive_emoji_pattern.search(sanitized_content):
            sanitized_content = self.excessive_emoji_pattern.sub('[EXCESSIVE_EMOJIS_REMOVED]', sanitized_content)
            warnings.append("Excessive emoji usage reduced")
            risk_score += 10
        
        if len(self.excessive_caps_pattern.findall(sanitized_content)) > 3:
            sanitized_content = self.excessive_caps_pattern.sub(lambda m: m.group().lower(), sanitized_content)
            warnings.append("Excessive caps converted to lowercase")
            risk_score += 5
        
        # Check profanity
        if analysis.contains_profanity:
            warnings.append("Inappropriate language detected")
            risk_score += 20
        
        # Check toxicity
        if analysis.toxicity_score > 0.6:
            warnings.append(f"High toxicity score: {analysis.toxicity_score:.2f}")
            risk_score += int(analysis.toxicity_score * 30)
        
        # Context-based analysis
        if conversation_context:
            context_risk = self._analyze_conversation_context(sanitized_content, conversation_context)
            risk_score += context_risk
            if context_risk > 20:
                warnings.append("Message flagged based on conversation context")
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return SanitizationResult(
            original_content=original_content,
            sanitized_content=sanitized_content,
            content_type='chat_message',
            risk_score=min(risk_score, 100),
            is_safe=risk_score < 40,  # Stricter threshold for chat
            removed_elements=removed_elements,
            warnings=warnings,
            metadata={
                'analysis': asdict(analysis),
                'user_id_hash': hashlib.md5(user_id.encode()).hexdigest()[:8] if user_id else None,
                'message_length': len(original_content),
                'has_context': bool(conversation_context)
            },
            processing_time=processing_time
        )
    
    def _analyze_conversation_context(self, message: str, context: List[str]) -> int:
        """Analyze message in conversation context"""
        risk_score = 0
        
        # Check for repetitive messages (spam indicator)
        similar_messages = sum(1 for ctx_msg in context if self._similarity_score(message, ctx_msg) > 0.8)
        if similar_messages > 2:
            risk_score += 20
        
        # Check for escalating toxicity
        if len(context) >= 3:
            recent_context = context[-3:]
            toxicity_trend = []
            
            for ctx_msg in recent_context:
                ctx_analysis = self.content_analyzer.analyze_content(ctx_msg)
                toxicity_trend.append(ctx_analysis.toxicity_score)
            
            # If toxicity is increasing
            if len(toxicity_trend) >= 2 and toxicity_trend[-1] > toxicity_trend[-2]:
                risk_score += 15
        
        return risk_score
    
    def _similarity_score(self, msg1: str, msg2: str) -> float:
        """Calculate similarity between two messages"""
        if not msg1 or not msg2:
            return 0.0
        
        # Simple Jaccard similarity on words
        words1 = set(msg1.lower().split())
        words2 = set(msg2.lower().split())
        
        if not words1 and not words2:
            return 1.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0

class ContentSanitizationSystem:
    """Main system for sanitizing reports and chat content"""
    
    def __init__(self, config_path: str = "/etc/content_sanitizer_config.json"):
        self.config = self._load_config(config_path)
        self.report_sanitizer = ReportSanitizer()
        self.chat_sanitizer = ChatSanitizer()
        self.db_path = self.config.get('database_path', '/var/log/content_sanitizer.db')
        self._init_database()
        
        # Rate limiting for chat messages
        self.user_message_counts = defaultdict(list)
        self.rate_limit_window = timedelta(minutes=5)
        self.max_messages_per_window = 20
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/var/log/content_sanitization.log'),
                logging.StreamHandler()
            ]
        )
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration"""
        default_config = {
            "database_path": "/var/log/content_sanitizer.db",
            "log_retention_days": 30,
            "enable_ml_analysis": True,
            "strict_mode": False,
            "quarantine_high_risk": True,
            "notification_webhook": None
        }
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                default_config.update(config)
                return default_config
        except FileNotFoundError:
            logging.info(f"Config file {config_path} not found, using defaults")
            return default_config
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing config file: {e}")
            return default_config
    
    def _init_database(self):
        """Initialize database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sanitization_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                content_type TEXT NOT NULL,
                user_id_hash TEXT,
                original_length INTEGER,
                sanitized_length INTEGER,
                risk_score INTEGER,
                is_safe BOOLEAN,
                removed_elements_count INTEGER,
                warnings_count INTEGER,
                processing_time REAL,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quarantined_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                content_type TEXT NOT NULL,
                user_id_hash TEXT,
                content_hash TEXT UNIQUE,
                risk_score INTEGER,
                reason TEXT,
                content_preview TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def sanitize_report(self, content: str, content_type: str = 'text', 
                       metadata: Optional[Dict] = None) -> SanitizationResult:
        """Sanitize report content"""
        result = self.report_sanitizer.sanitize_report(content, content_type)
        
        # Log to database
        self._log_sanitization_result(result, 'report', metadata)
        
        # Quarantine if high risk
        if not result.is_safe and self.config.get('quarantine_high_risk', True):
            self._quarantine_content(result, 'report')
        
        return result
    
    def sanitize_chat_message(self, message: str, user_id: str, 
                             conversation_context: Optional[List[str]] = None) -> SanitizationResult:
        """Sanitize chat message"""
        # Check rate limiting
        if not self._check_rate_limit(user_id):
            # Return a blocked result
            return SanitizationResult(
                original_content=message,
                sanitized_content="[MESSAGE_RATE_LIMITED]",
                content_type='chat_message',
                risk_score=100,
                is_safe=False,
                removed_elements=[],
                warnings=["Rate limit exceeded"],
                metadata={'rate_limited': True, 'user_id_hash': hashlib.md5(user_id.encode()).hexdigest()[:8]},
                processing_time=0.0
            )
        
        result = self.chat_sanitizer.sanitize_chat_message(message, user_id, conversation_context)
        
        # Log to database
        self._log_sanitization_result(result, 'chat', {'user_id': user_id})
        
        # Quarantine if high risk
        if not result.is_safe and self.config.get('quarantine_high_risk', True):
            self._quarantine_content(result, 'chat', user_id)
        
        return result
    
    def _check_rate_limit(self, user_id: str) -> bool:
        """Check if user is within rate limits"""
        now = datetime.now()
        user_messages = self.user_message_counts[user_id]
        
        # Remove old messages outside the window
        cutoff_time = now - self.rate_limit_window
        user_messages[:] = [msg_time for msg_time in user_messages if msg_time > cutoff_time]
        
        # Check if under limit
        if len(user_messages) >= self.max_messages_per_window:
            return False
        
        # Add current message
        user_messages.append(now)
        return True
    
    def _log_sanitization_result(self, result: SanitizationResult, content_type: str, 
                                metadata: Optional[Dict] = None):
        """Log sanitization result to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            user_id_hash = None
            if metadata and 'user_id' in metadata:
                user_id_hash = hashlib.md5(metadata['user_id'].encode()).hexdigest()[:8]
            elif 'user_id_hash' in result.metadata:
                user_id_hash = result.metadata['user_id_hash']
            
            cursor.execute("""
                INSERT INTO sanitization_results 
                (timestamp, content_type, user_id_hash, original_length, sanitized_length,
                 risk_score, is_safe, removed_elements_count, warnings_count, 
                 processing_time, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                content_type,
                user_id_hash,
                len(result.original_content),
                len(result.sanitized_content),
                result.risk_score,
                result.is_safe,
                len(result.removed_elements),
                len(result.warnings),
                result.processing_time,
                json.dumps(result.metadata)
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logging.error(f"Error logging sanitization result: {e}")
    
    def _quarantine_content(self, result: SanitizationResult, content_type: str, 
                           user_id: Optional[str] = None):
        """Quarantine high-risk content"""
        try:
            content_hash = hashlib.sha256(result.original_content.encode()).hexdigest()
            user_id_hash = hashlib.md5(user_id.encode()).hexdigest()[:8] if user_id else None
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR IGNORE INTO quarantined_content 
                (timestamp, content_type, user_id_hash, content_hash, risk_score, 
                 reason, content_preview)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                content_type,
                user_id_hash,
                content_hash,
                result.risk_score,
                '; '.join(result.warnings),
                result.original_content[:200] + '...' if len(result.original_content) > 200 else result.original_content
            ))
            
            conn.commit()
            conn.close()
            
            logging.warning(f"Quarantined {content_type} content (risk: {result.risk_score})")
            
        except Exception as e:
            logging.error(f"Error quarantining content: {e}")
    
    def get_system_stats(self, hours: int = 24) -> Dict:
        """Get system statistics"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get sanitization stats
        cursor.execute("""
            SELECT content_type, COUNT(*), AVG(risk_score), 
                   SUM(CASE WHEN is_safe = 0 THEN 1 ELSE 0 END),
                   AVG(processing_time), SUM(removed_elements_count)
            FROM sanitization_results 
            WHERE timestamp > ?
            GROUP BY content_type
        """, (since,))
        
        sanitization_stats = cursor.fetchall()
        
        # Get quarantine stats
        cursor.execute("""
            SELECT content_type, COUNT(*), AVG(risk_score)
            FROM quarantined_content 
            WHERE timestamp > ?
            GROUP BY content_type
        """, (since,))
        
        quarantine_stats = cursor.fetchall()
        
        conn.close()
        
        return {
            'period_hours': hours,
            'sanitization_stats': [
                {
                    'content_type': row[0],
                    'total_processed': row[1],
                    'avg_risk_score': round(row[2] or 0, 2),
                    'unsafe_count': row[3],
                    'avg_processing_time': round(row[4] or 0, 4),
                    'total_elements_removed': row[5] or 0
                }
                for row in sanitization_stats
            ],
            'quarantine_stats': [
                {
                    'content_type': row[0],
                    'quarantined_count': row[1],
                    'avg_risk_score': round(row[2] or 0, 2)
                }
                for row in quarantine_stats
            ],
            'system_config': self.config
        }
    
    def cleanup_old_data(self):
        """Clean up old data based on retention policy"""
        retention_days = self.config.get('log_retention_days', 30)
        cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM sanitization_results WHERE timestamp < ?", (cutoff_date,))
        results_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM quarantined_content WHERE timestamp < ?", (cutoff_date,))
        quarantine_deleted = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        logging.info(f"Cleaned up {results_deleted} old sanitization results and {quarantine_deleted} quarantined items")

async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Content Sanitization System')
    parser.add_argument('--config', default='/etc/content_sanitizer_config.json', help='Configuration file')
    parser.add_argument('--sanitize-report', help='Sanitize a report file')
    parser.add_argument('--sanitize-text', help='Sanitize text content')
    parser.add_argument('--content-type', default='text', help='Content type (text, html, rich_text)')
    parser.add_argument('--user-id', help='User ID for chat messages')
    parser.add_argument('--stats', action='store_true', help='Show system statistics')
    parser.add_argument('--cleanup', action='store_true', help='Clean up old data')
    
    args = parser.parse_args()
    
    system = ContentSanitizationSystem(args.config)
    
    try:
        if args.sanitize_report:
            with open(args.sanitize_report, 'r', encoding='utf-8') as f:
                content = f.read()
            result = system.sanitize_report(content, args.content_type)
            print(json.dumps(asdict(result), indent=2, default=str))
        
        elif args.sanitize_text:
            if args.user_id:
                result = system.sanitize_chat_message(args.sanitize_text, args.user_id)
            else:
                result = system.sanitize_report(args.sanitize_text, args.content_type)
            print(json.dumps(asdict(result), indent=2, default=str))
        
        elif args.stats:
            stats = system.get_system_stats()
            print(json.dumps(stats, indent=2))
        
        elif args.cleanup:
            system.cleanup_old_data()
        
        else:
            print("No action specified. Use --help for usage information.")
    
    except Exception as e:
        logging.error(f"Error in main: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
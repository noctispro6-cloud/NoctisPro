# NoctisPro Universal Settings for Windows Server Deployment
# Professional grade configuration for worldwide access

import os
from pathlib import Path
from .settings import *

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: Don't run with debug turned on in production!
DEBUG = False

# Hosts/domain names that are valid for this site
ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '*.trycloudflare.com',  # Cloudflare tunnel domains
    '*.ngrok.io',           # Ngrok tunnel domains
    '*.loca.lt',            # LocalTunnel domains
    '*',                    # Allow all for universal access
]

# Generate secure secret key
SECRET_KEY = 'django-insecure-universal-deployment-change-in-production-2024-noctispro-professional-grade-security-key'

# Database configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 30,
            'check_same_thread': False,
        }
    }
}

# Cache configuration
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'noctis-universal-cache',
        'OPTIONS': {
            'MAX_ENTRIES': 1000,
            'CULL_FREQUENCY': 3,
        }
    }
}

# Security middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Security headers for internet exposure
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'SAMEORIGIN'  # Allow embedding for DICOM viewer

# Session security
SESSION_COOKIE_AGE = 43200  # 12 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = False  # Set to True when using HTTPS in production
SESSION_SAVE_EVERY_REQUEST = True

# CSRF protection
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = False  # Set to True when using HTTPS in production
CSRF_TRUSTED_ORIGINS = [
    'https://*.trycloudflare.com',
    'https://*.ngrok.io',
    'https://*.loca.lt',
    'http://localhost:8000',
    'http://127.0.0.1:8000'
]

# CORS settings for API access
CORS_ALLOW_ALL_ORIGINS = True  # For universal access via tunnels
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# File upload settings
# - Allow up to 5GB total upload payloads
# - Keep per-file in-memory buffering modest so large files stream to disk
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024 * 1024  # 5GB
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_BYTES
DATA_UPLOAD_MAX_NUMBER_FILES = 5000  # Support large DICOM batches
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
FILE_UPLOAD_PERMISSIONS = 0o644

# Media files configuration
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Static files configuration
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# Login/logout URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/worklist/'
LOGOUT_REDIRECT_URL = '/login/'

# Email configuration (for notifications)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'noctis@yourdomain.com'

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'noctis_pro.log',
            'maxBytes': 1024*1024*10,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False,
        },
        'noctis_pro': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# DICOM configuration
DICOM_SCP_PORT = 11112
DICOM_AE_TITLE = 'NOCTISPRO'
DICOM_BIND_ADDRESS = '0.0.0.0'  # Listen on all interfaces for internet access
DICOM_MAX_ASSOCIATIONS = 10      # Limit concurrent connections
DICOM_TIMEOUT = 30               # Connection timeout in seconds

# Application-specific settings
NOCTIS_VERSION = '1.0.0'
NOCTIS_DEPLOYMENT_TYPE = 'universal'
NOCTIS_PLATFORM = 'windows_server'

print("🔧 NoctisPro Universal settings loaded successfully")
print(f"   Debug: {DEBUG}")
print(f"   Platform: {NOCTIS_PLATFORM}")
print(f"   Deployment: {NOCTIS_DEPLOYMENT_TYPE}")
print(f"   DICOM Port: {DICOM_SCP_PORT}")
print(f"   AE Title: {DICOM_AE_TITLE}")
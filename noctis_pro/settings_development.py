# IMPORTANT: settings_development.py disables HTTPS enforcement.
# Never use this settings module in production.
# For production, use settings.py and set:
#   SSL_ENABLED=True
#   SECURE_SSL_REDIRECT=True
#   SESSION_COOKIE_SECURE=True
#   CSRF_COOKIE_SECURE=True

# Development settings for NoctisPro
# This file provides SQLite fallback for development when PostgreSQL is not available

import os
from .settings import *

# Override database settings for development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Development-specific settings
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

# Use dummy cache for development
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

# Use database sessions instead of Redis
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Disable some production security features for development
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

print("🔧 Using development settings with SQLite database")

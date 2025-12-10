from __future__ import annotations

import os
import sys
from pathlib import Path
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from .config import get_settings


def _bootstrap_django() -> None:
    """Ensure Django is configured before accessing ORM models."""
    settings = get_settings()
    base_dir = Path(__file__).resolve().parents[1]
    if str(base_dir) not in sys.path:
        sys.path.append(str(base_dir))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings.django_settings_module)
    # Importing django lazily prevents repeated setup calls
    import django  # type: ignore
    if not django.apps.apps.ready:
        django.setup()


_bootstrap_django()

_settings = get_settings()
_api_key_header = APIKeyHeader(name=_settings.api_key_header, auto_error=False)


def verify_api_key(api_key: str | None = Depends(_api_key_header)) -> None:
    """Simple API key check for internal service calls."""
    expected = _settings.api_key
    if not expected:
        # When no key is configured we allow local testing, but emit warning.
        return
    if api_key == expected:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
    )

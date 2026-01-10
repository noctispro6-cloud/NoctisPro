"""
Project package initializer.

Celery is optional in some deployment modes (e.g. minimal docker builds),
so importing it must not prevent Django from starting.
"""

try:
    from .celery import app as celery_app  # type: ignore
except Exception:  # pragma: no cover
    celery_app = None  # type: ignore

__all__ = ("celery_app",)

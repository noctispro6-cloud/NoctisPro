from __future__ import annotations

from typing import Any, Optional

from django.http import HttpRequest

from .models import AuditLog, Facility, User


def get_client_ip(request: HttpRequest) -> str:
    """
    Best-effort IP extraction.
    If you're behind a proxy, ensure you set Django/Nginx forwarding correctly.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def log_audit(
    *,
    request: HttpRequest,
    action: str,
    user: Optional[User] = None,
    facility: Optional[Facility] = None,
    study_instance_uid: str = "",
    series_instance_uid: str = "",
    sop_instance_uid: str = "",
    image_id: Optional[int] = None,
    series_id: Optional[int] = None,
    study_id: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    try:
        u = user or getattr(request, "user", None)
        f = facility or getattr(u, "facility", None)
        AuditLog.objects.create(
            user=u if getattr(u, "is_authenticated", False) else None,
            facility=f,
            action=action,
            study_instance_uid=study_instance_uid or "",
            series_instance_uid=series_instance_uid or "",
            sop_instance_uid=sop_instance_uid or "",
            image_id=image_id,
            series_id=series_id,
            study_id=study_id,
            ip_address=get_client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:2048],
            extra=extra or {},
        )
    except Exception:
        # Audit logging must never break clinical workflows.
        return


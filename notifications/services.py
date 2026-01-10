from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from django.db import transaction
from django.utils import timezone

from accounts.models import User, Facility
from worklist.models import Study
from .models import Notification, NotificationType


@dataclass(frozen=True)
class StudyUploadNotificationPayload:
    """
    Standard payload for a "study uploaded" notification.

    We intentionally dedupe by StudyInstanceUID (and recipient) so multi-series
    uploads don't spam users with one notification per series.
    """

    title: str
    message: str
    priority: str = "normal"
    series_count: Optional[int] = None
    images_count: Optional[int] = None


def _get_or_create_type(code: str = "new_study") -> NotificationType:
    notif_type, _ = NotificationType.objects.get_or_create(
        code=code,
        defaults={
            "name": "New Study Uploaded",
            "description": "A new study has been uploaded",
            "is_system": True,
        },
    )
    return notif_type


def _dedupe_key(study: Study) -> str:
    uid = (getattr(study, "study_instance_uid", None) or "").strip()
    return f"study_upload:{uid or study.id}"


def _push_realtime(recipient_id: int, message: str) -> None:
    """
    Best-effort websocket push. Safe to call from sync code.
    """
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if not layer:
            return
        async_to_sync(layer.group_send)(
            f"notifications_{recipient_id}",
            {
                "type": "send_notification",
                "notification_type": "notification",
                "message": message,
            },
        )
    except Exception:
        # Never break uploads because realtime isn't configured.
        return


@transaction.atomic
def upsert_study_upload_notification(
    *,
    study: Study,
    facility: Optional[Facility],
    recipients: Iterable[User],
    sender: Optional[User] = None,
    payload: StudyUploadNotificationPayload,
    notification_code: str = "new_study",
) -> int:
    """
    Create (or update) a single notification per (recipient, study).

    Returns the number of recipients notified (created or updated).
    """
    notif_type = _get_or_create_type(notification_code)
    key = _dedupe_key(study)
    now = timezone.now().isoformat()

    notified = 0
    for recipient in recipients:
        # Dedupe by recipient + study (and also embed key into JSON for safety).
        existing = (
            Notification.objects.filter(
                notification_type=notif_type,
                recipient=recipient,
                study=study,
            )
            .order_by("-created_at")
            .first()
        )

        data = {
            "dedupe_key": key,
            "study_id": study.id,
            "study_instance_uid": getattr(study, "study_instance_uid", None),
            "accession_number": getattr(study, "accession_number", None),
            "series_count": payload.series_count,
            "images_count": payload.images_count,
            "updated_at": now,
        }

        if existing:
            # Update in place rather than creating a new row.
            # Keep read/dismiss state intact; just refresh the content.
            existing.title = payload.title
            existing.message = payload.message
            existing.priority = payload.priority or existing.priority
            existing.sender = sender
            existing.facility = facility
            existing.data = {**(existing.data or {}), **{k: v for k, v in data.items() if v is not None}}
            existing.save(update_fields=["title", "message", "priority", "sender", "facility", "data"])
            _push_realtime(recipient.id, payload.message)
            notified += 1
            continue

        Notification.objects.create(
            notification_type=notif_type,
            recipient=recipient,
            sender=sender,
            title=payload.title,
            message=payload.message,
            priority=payload.priority or "normal",
            study=study,
            facility=facility,
            data={k: v for k, v in data.items() if v is not None},
        )
        _push_realtime(recipient.id, payload.message)
        notified += 1

    return notified

"""
Out-of-band notification delivery (SMS / Phone Call).

This is intentionally optional: if provider credentials are not configured,
delivery will be skipped and the in-app web notification remains available.

Currently supported provider: Twilio via REST API (no extra dependency).
Env vars:
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_FROM_NUMBER  (E.164, used for SMS and Calls)
"""

import os
from typing import Optional

import requests


def _get_system_config(key: str) -> Optional[str]:
    """
    Best-effort read of admin_panel.SystemConfiguration without hard dependency.
    Returns None if DB/model isn't available yet.
    """
    try:
        from admin_panel.models import SystemConfiguration
        row = SystemConfiguration.objects.filter(key=key).first()
        if not row:
            return None
        val = (row.value or "").strip()
        return val or None
    except Exception:
        return None


def _twilio_config() -> tuple[Optional[str], Optional[str], Optional[str]]:
    # Environment variables override DB configuration.
    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip() or _get_system_config("twilio_account_sid")
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip() or _get_system_config("twilio_auth_token")
    from_number = (os.environ.get("TWILIO_FROM_NUMBER") or "").strip() or _get_system_config("twilio_from_number")
    return sid or None, token or None, from_number or None


def can_deliver_out_of_band() -> bool:
    sid, token, from_number = _twilio_config()
    return bool(sid and token and from_number)


def send_sms(to_number: str, body: str) -> bool:
    """Send an SMS via Twilio. Returns True if request accepted."""
    sid, token, from_number = _twilio_config()
    if not (sid and token and from_number and to_number):
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    resp = requests.post(
        url,
        data={"From": from_number, "To": to_number, "Body": body[:1600]},
        auth=(sid, token),
        timeout=10,
    )
    return bool(resp.ok)


def place_call(to_number: str, say_text: str) -> bool:
    """Place a phone call via Twilio with simple TwiML. Returns True if accepted."""
    sid, token, from_number = _twilio_config()
    if not (sid and token and from_number and to_number):
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
    # Twilio accepts TwiML in the "Twiml" parameter.
    twiml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<Response>"
        "<Say voice='alice'>"
        f"{say_text[:800]}"
        "</Say>"
        "</Response>"
    )
    resp = requests.post(
        url,
        data={"From": from_number, "To": to_number, "Twiml": twiml},
        auth=(sid, token),
        timeout=10,
    )
    return bool(resp.ok)


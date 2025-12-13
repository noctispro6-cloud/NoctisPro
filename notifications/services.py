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

from __future__ import annotations

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


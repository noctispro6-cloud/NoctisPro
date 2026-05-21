import json
from django.conf import settings


DEFAULT_CAPS = {
    'manage_users': False,
    'manage_facilities': False,
    'view_logs': False,
    'manage_settings': False,
    'run_backup': True,
    'manage_permissions': False,
    'ai_visible': True,
    'manage_ai': False,
    'can_amend_reports': True,
    'can_delete_studies': False,
}

_DEFAULT_ROLE_TOGGLES = {
    'admin':       {'ai_visible': True},
    'radiologist': {'ai_visible': True},
    'facility':    {'ai_visible': False},
}

_USER_CAPS_KEY_PREFIX = 'user_caps:'
_ROLE_TOGGLES_KEY = 'role_toggles'


def _get_config(key: str, default):
    """Read a json-typed SystemConfiguration row, returning default on any error."""
    try:
        from .models import SystemConfiguration
        obj = SystemConfiguration.objects.filter(key=key).first()
        if obj is None:
            return default
        return json.loads(obj.value)
    except Exception:
        return default


def _set_config(key: str, value) -> None:
    """Upsert a json-typed SystemConfiguration row. Raises on failure."""
    from .models import SystemConfiguration
    serialized = json.dumps(value)
    obj, _ = SystemConfiguration.objects.get_or_create(
        key=key,
        defaults={
            'value': serialized,
            'data_type': 'json',
            'category': 'permissions',
        },
    )
    if obj.value != serialized or obj.data_type != 'json':
        obj.value = serialized
        obj.data_type = 'json'
        obj.category = 'permissions'
        obj.save(update_fields=['value', 'data_type', 'category'])


def get_user_caps(username: str) -> dict:
    raw = _get_config(_USER_CAPS_KEY_PREFIX + username, None)
    if not isinstance(raw, dict):
        raw = {}
    return {**DEFAULT_CAPS, **raw}


def set_user_caps(username: str, caps_update: dict) -> None:
    cleaned = {k: bool(caps_update.get(k, DEFAULT_CAPS.get(k))) for k in DEFAULT_CAPS}
    _set_config(_USER_CAPS_KEY_PREFIX + username, cleaned)


def get_role_toggles() -> dict:
    raw = _get_config(_ROLE_TOGGLES_KEY, None)
    if not isinstance(raw, dict):
        raw = {}
    merged = {r: dict(v) for r, v in _DEFAULT_ROLE_TOGGLES.items()}
    for role, conf in raw.items():
        if role in merged and isinstance(conf, dict):
            merged[role].update(conf)
    return merged


def set_role_toggles(updates: dict) -> None:
    current = get_role_toggles()
    for role, conf in updates.items():
        if role in current:
            current[role]['ai_visible'] = bool(conf.get('ai_visible', current[role].get('ai_visible')))
    _set_config(_ROLE_TOGGLES_KEY, current)


def load_capabilities() -> dict:
    """Legacy shim — no longer used for storage but kept for call-site compatibility."""
    return {}


def is_ai_visible(user) -> bool:
    try:
        if not user or not user.is_authenticated:
            return False
        # User-level cap can explicitly disable AI for an individual
        caps = get_user_caps(user.username)
        if caps.get('ai_visible', True) is False:
            return False
        # Role-level toggle (set in permissions dashboard)
        roles = get_role_toggles()
        role_key = 'admin' if user.is_admin() else 'radiologist' if user.is_radiologist() else 'facility'
        if not roles.get(role_key, {}).get('ai_visible', role_key != 'facility'):
            return False
        # Facility-level subscription gate (non-admins only)
        if not getattr(user, 'is_admin', lambda: False)():
            facility = getattr(user, 'facility', None)
            if facility is not None and not getattr(facility, 'has_ai_subscription', True):
                return False
        return True
    except Exception:
        return False

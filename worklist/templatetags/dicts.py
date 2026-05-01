from django import template
from admin_panel.utils import get_user_caps, is_ai_visible

register = template.Library()

@register.filter(name='get_item')
def get_item(d, key):
	try:
		return d.get(key, []) if isinstance(d, dict) else []
	except Exception:
		return []

@register.simple_tag(takes_context=True)
def user_caps(context):
    try:
        user = context.get('user')
        if not user or not getattr(user, 'username', None):
            return {}
        caps = dict(get_user_caps(user.username))
        # Combine user-level cap with role-level toggle so both controls take effect
        caps['ai_visible'] = is_ai_visible(user)
        return caps
    except Exception:
        return {}
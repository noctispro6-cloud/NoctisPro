from django import template
from admin_panel.utils import get_user_caps

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
        return get_user_caps(user.username)
    except Exception:
        return {}
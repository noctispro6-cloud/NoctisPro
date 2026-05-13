from .models import SystemConfiguration


def theme(request):
    """Inject accent_color into every template context."""
    try:
        cfg = SystemConfiguration.objects.filter(key="accent_color").values_list("value", flat=True).first()
        color = (cfg or "").strip()
    except Exception:
        color = ""
    return {"accent_color_override": color}

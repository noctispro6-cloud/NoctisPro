from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User


@receiver(post_save, sender=User)
def ensure_notification_preferences(sender, instance: User, created: bool, **kwargs):
    """
    Ensure every user has a NotificationPreference row so urgent alerts can be routed
    via web/SMS/call based on preference.
    """
    try:
        from notifications.models import NotificationPreference
        NotificationPreference.objects.get_or_create(user=instance)
    except Exception:
        # Best-effort only; the profile page will also create the row.
        pass


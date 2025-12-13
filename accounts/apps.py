from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Register signals (best-effort).
        try:
            from . import signals  # noqa: F401
        except Exception:
            pass

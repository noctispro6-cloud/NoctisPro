from django.apps import AppConfig


class AiAnalysisConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_analysis'

    def ready(self):
        import ai_analysis.signals

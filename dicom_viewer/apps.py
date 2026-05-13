from django.apps import AppConfig


class DicomViewerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dicom_viewer'

    def ready(self):
        import dicom_viewer.signals  # noqa: F401 — registers signal handlers

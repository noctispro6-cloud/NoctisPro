from django.urls import path

from . import dicomweb_views

app_name = "dicomweb"


urlpatterns = [
    # Minimal DICOMweb STOW-RS endpoint
    # Standard-ish: POST /dicomweb/studies/
    path("studies/", dicomweb_views.DicomWebStowView.as_view(), name="stow_rs"),
]


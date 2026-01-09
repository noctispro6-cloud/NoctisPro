from django.urls import path

from . import dicomweb_views

app_name = "dicomweb"


urlpatterns = [
    # DICOMweb (minimal):
    # - STOW-RS: POST /dicomweb/studies/
    # - QIDO-RS: GET  /dicomweb/studies/
    path("studies/", dicomweb_views.DicomWebStowView.as_view(), name="studies"),

    # QIDO-RS: Series / Instances
    path("studies/<str:study_uid>/series/", dicomweb_views.DicomWebSeriesView.as_view(), name="qido_series"),
    path(
        "studies/<str:study_uid>/series/<str:series_uid>/instances/",
        dicomweb_views.DicomWebInstancesView.as_view(),
        name="qido_instances",
    ),

    # WADO-RS: Retrieve instance / metadata
    path(
        "studies/<str:study_uid>/series/<str:series_uid>/instances/<str:instance_uid>",
        dicomweb_views.DicomWebWadoInstanceView.as_view(),
        name="wado_instance",
    ),
    path(
        "studies/<str:study_uid>/series/<str:series_uid>/instances/<str:instance_uid>/metadata",
        dicomweb_views.DicomWebWadoInstanceView.as_view(),
        name="wado_instance_metadata",
    ),
]


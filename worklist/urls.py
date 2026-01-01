from django.urls import path
from . import views
# from attachment_viewer import api_view_attachment, attachment_viewer_page, api_attachment_search

app_name = 'worklist'

urlpatterns = [
    # Main worklist interfaces
    path('', views.dashboard, name='dashboard'),
    path('ui/', views.modern_worklist, name='modern_worklist'),
    path('modern/', views.modern_dashboard, name='modern_dashboard'),
    path('upload/', views.upload_study, name='upload_study'),
    # Service Worker for background uploads (must be under /worklist/ for scope)
    path('sw-dicom-upload.js', views.sw_dicom_upload, name='sw_dicom_upload'),
    path('studies/', views.study_list, name='study_list'),
    path('study/<int:study_id>/', views.study_detail, name='study_detail'),
    
    # Study attachments
    path('study/<int:study_id>/upload/', views.upload_attachment, name='upload_attachment'),
    path('attachment/<int:attachment_id>/view/', views.view_attachment, name='view_attachment'),
    path('attachment/<int:attachment_id>/comments/', views.attachment_comments, name='attachment_comments'),
    path('attachment/<int:attachment_id>/delete/', views.delete_attachment, name='delete_attachment'),
    
    # Attachment viewer - COMMENTED OUT until functions are implemented
    # path('attachment/<int:attachment_id>/viewer/', attachment_viewer_page, name='attachment_viewer'),
    # path('api/attachment/<int:attachment_id>/view/', api_view_attachment, name='api_view_attachment'),
    # path('api/attachment/<int:attachment_id>/search/', api_attachment_search, name='api_attachment_search'),
    
    # API endpoints
    path('api/studies/', views.api_studies, name='api_studies'),
    path('api/search-studies/', views.api_search_studies, name='api_search_studies'),
    path('api/study/<int:study_id>/', views.api_study_detail, name='api_study_detail'),
    path('api/study/<int:study_id>/update-status/', views.api_update_study_status, name='api_update_study_status'),
    path('api/study/<int:study_id>/update-clinical-info/', views.api_update_clinical_info, name='api_update_clinical_info'),
    path('api/study/<int:study_id>/delete/', views.api_delete_study, name='api_delete_study'),
    path('api/refresh-worklist/', views.api_refresh_worklist, name='api_refresh_worklist'),
    path('api/upload-stats/', views.api_get_upload_stats, name='api_get_upload_stats'),
    path('api/study/<int:study_id>/reassign-facility/', views.api_reassign_study_facility, name='api_reassign_study_facility'),
]
from django.urls import path
from . import views

app_name = 'ai_analysis'

urlpatterns = [
    # Main interfaces
    path('', views.ai_dashboard, name='ai_dashboard'),
    path('studies/', views.study_picker, name='study_picker'),
    path('study/<int:study_id>/analyze/', views.analyze_study, name='analyze_study'),
    path('models/', views.model_management, name='model_management'),
    
    # AI Analysis API endpoints
    path('api/series/<int:series_id>/analyze/', views.api_analyze_series, name='api_analyze_series'),
    path('api/analysis/<int:analysis_id>/status/', views.api_analysis_status, name='api_analysis_status'),
    path('api/analysis/<int:analysis_id>/feedback/', views.api_ai_feedback, name='api_ai_feedback'),
    path('api/realtime/analyses/', views.api_realtime_analyses, name='api_realtime_analyses'),
    path('api/models/', views.api_list_models, name='api_list_models'),
    
    # Auto-report generation
    path('api/study/<int:study_id>/generate-report/', views.generate_auto_report, name='generate_auto_report'),
    path('report/<int:report_id>/review/', views.review_auto_report, name='review_auto_report'),

    # Evidence and references
    path('api/references/', views.api_medical_references, name='api_medical_references'),
]
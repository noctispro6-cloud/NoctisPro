from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.report_list, name='report_list'),
    path('write/<int:study_id>/', views.write_report, name='write_report'),
    path('print/<int:study_id>/', views.print_report_stub, name='print_report'),
    path('export/pdf/<int:study_id>/', views.export_report_pdf, name='export_report_pdf'),
    path('export/docx/<int:study_id>/', views.export_report_docx, name='export_report_docx'),
]
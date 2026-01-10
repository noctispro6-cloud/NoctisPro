from django.urls import path
from . import views
from . import views_permissions

app_name = 'admin_panel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    
    # User management
    path('users/', views.user_management, name='user_management'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/edit/<int:user_id>/', views.user_edit, name='user_edit'),
    path('users/delete/<int:user_id>/', views.user_delete, name='user_delete'),
    path('users/bulk-action/', views.bulk_user_action, name='bulk_user_action'),
    
    # Facility management
    path('facilities/', views.facility_management, name='facility_management'),
    path('facilities/create/', views.facility_create, name='facility_create'),
    path('facilities/edit/<int:facility_id>/', views.facility_edit, name='facility_edit'),
    path('facilities/delete/<int:facility_id>/', views.facility_delete, name='facility_delete'),
    path('facilities/bulk-action/', views.bulk_facility_action, name='bulk_facility_action'),

    # Placeholder routes referenced by templates
    path('logs/', views.system_logs, name='system_logs'),
    path('settings/', views.settings_view, name='settings'),
    path('upload-facilities/', views.upload_facilities, name='upload_facilities'),

    # Permissions and capabilities management
    path('permissions/', views_permissions.permissions_dashboard, name='permissions_dashboard'),
    path('permissions/user/<str:username>/', views_permissions.edit_user_permissions, name='edit_user_permissions'),

    # QA / diagnostics
    path('qa/responsive/', views.responsive_qa, name='responsive_qa'),
]
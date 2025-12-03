from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.notification_list, name='notification_list'),
    path('api/notifications/', views.api_notifications, name='api_notifications'),
    path('api/unread-count/', views.api_unread_count, name='api_unread_count'),
    path('mark-read/<int:notification_id>/', views.mark_read, name='mark_read'),
]
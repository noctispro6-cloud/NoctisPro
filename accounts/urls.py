from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('portal/login/', views.portal_login, name='portal_login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('change-password/', views.change_password, name='change_password'),
    path('api/check-session/', views.check_session, name='check_session'),
    path('api/user-info/', views.user_api_info, name='user_api_info'),
    path('session-extend/', views.session_extend, name='session_extend'),
    path('session-keep-alive/', views.session_keep_alive, name='session_keep_alive'),
]
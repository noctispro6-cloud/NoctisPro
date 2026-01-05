from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.chat_rooms, name='chat_rooms'),
    path('room/<uuid:room_id>/', views.chat_room, name='chat_room'),
    path('room/<uuid:room_id>/settings/', views.update_room_settings, name='update_room_settings'),
    path('room/<uuid:room_id>/invite/', views.invite_user, name='invite_user'),
    path('room/<uuid:room_id>/search-users/', views.api_search_users, name='api_search_users'),
    path('room/<uuid:room_id>/participants/<int:user_id>/remove/', views.remove_participant, name='remove_participant'),
    path('room/<uuid:room_id>/participants/<int:user_id>/role/', views.update_participant_role, name='update_participant_role'),
    path('create/', views.create_room, name='create_room'),
    path('join/<uuid:room_id>/', views.join_room, name='join_room'),
    path('leave/<uuid:room_id>/', views.leave_room, name='leave_room'),
    path('invitation/<int:invitation_id>/accept/', views.accept_invitation, name='accept_invitation'),
    path('invitation/<int:invitation_id>/decline/', views.decline_invitation, name='decline_invitation'),
]
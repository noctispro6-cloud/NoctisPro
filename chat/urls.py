from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.chat_rooms, name='chat_rooms'),
    path('room/<uuid:room_id>/', views.chat_room, name='chat_room'),
    path('create/', views.create_room, name='create_room'),
    path('join/<uuid:room_id>/', views.join_room, name='join_room'),
    path('leave/<uuid:room_id>/', views.leave_room, name='leave_room'),
]
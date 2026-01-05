import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            await self.close()
            return

        try:
            self.user_id = int(self.scope["url_route"]["kwargs"]["user_id"])
        except Exception:
            await self.close()
            return

        # Prevent users from subscribing to other users' streams.
        if int(getattr(user, "id", -1)) != self.user_id:
            await self.close()
            return

        self.notification_group_name = f"notifications_{self.user_id}"

        # Join notification group
        await self.channel_layer.group_add(
            self.notification_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave notification group
        await self.channel_layer.group_discard(
            self.notification_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        notification_type = text_data_json.get('type', 'info')
        message = text_data_json['message']

        # Send notification to user group
        await self.channel_layer.group_send(
            self.notification_group_name,
            {
                'type': 'send_notification',
                'notification_type': notification_type,
                'message': message,
            }
        )

    # Send notification to WebSocket
    async def send_notification(self, event):
        notification_type = event['notification_type']
        message = event['message']

        # Send notification to WebSocket
        await self.send(text_data=json.dumps({
            'type': notification_type,
            'message': message,
        }))


class SystemStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.system_group_name = 'system_status'

        # Join system status group
        await self.channel_layer.group_add(
            self.system_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave system status group
        await self.channel_layer.group_discard(
            self.system_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        status_type = text_data_json.get('type', 'info')
        message = text_data_json['message']

        # Send status update to system group
        await self.channel_layer.group_send(
            self.system_group_name,
            {
                'type': 'system_status_update',
                'status_type': status_type,
                'message': message,
            }
        )

    # Send system status update to WebSocket
    async def system_status_update(self, event):
        status_type = event['status_type']
        message = event['message']

        # Send status update to WebSocket
        await self.send(text_data=json.dumps({
            'type': status_type,
            'message': message,
        }))
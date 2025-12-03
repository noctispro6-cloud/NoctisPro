import json
import logging
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from django.utils import timezone
from .models import ChatRoom, ChatParticipant, ChatMessage, ChatMessageReaction

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return
            
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'

        # Check if user has permission to join this room
        has_permission = await self.check_room_permission()
        if not has_permission:
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Update user online status
        await self.update_online_status(True)

        await self.accept()

        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_status',
            'status': 'connected',
            'room_id': self.room_id,
            'user_id': self.user.id,
            'username': self.user.username,
            'timestamp': timezone.now().isoformat()
        }))

    async def disconnect(self, close_code):
        # Update user online status
        await self.update_online_status(False)
        
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type', 'message')
            
            if message_type == 'message':
                await self.handle_chat_message(text_data_json)
            elif message_type == 'typing':
                await self.handle_typing_indicator(text_data_json)
            elif message_type == 'reaction':
                await self.handle_message_reaction(text_data_json)
            elif message_type == 'edit_message':
                await self.handle_edit_message(text_data_json)
            elif message_type == 'delete_message':
                await self.handle_delete_message(text_data_json)
            elif message_type == 'mark_read':
                await self.handle_mark_read(text_data_json)
            else:
                logger.warning(f"Unknown message type: {message_type}")
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")

    async def handle_chat_message(self, data):
        message_content = data.get('message', '').strip()
        reply_to_id = data.get('reply_to')
        
        if not message_content:
            return
            
        # Save message to database
        message = await self.save_message(
            content=message_content,
            reply_to_id=reply_to_id
        )
        
        if message:
            # Send message to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message_id': str(message.id),
                    'message': message_content,
                    'user_id': self.user.id,
                    'username': self.user.username,
                    'user_avatar': getattr(self.user, 'avatar', ''),
                    'timestamp': message.created_at.isoformat(),
                    'reply_to': reply_to_id,
                    'is_edited': False
                }
            )

    async def handle_typing_indicator(self, data):
        is_typing = data.get('is_typing', False)
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user_id': self.user.id,
                'username': self.user.username,
                'is_typing': is_typing
            }
        )

    async def handle_message_reaction(self, data):
        message_id = data.get('message_id')
        emoji = data.get('emoji')
        action = data.get('action', 'add')  # add or remove
        
        if not message_id or not emoji:
            return
            
        reaction = await self.toggle_reaction(message_id, emoji, action)
        if reaction is not None:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_reaction',
                    'message_id': message_id,
                    'emoji': emoji,
                    'user_id': self.user.id,
                    'username': self.user.username,
                    'action': action
                }
            )

    async def handle_edit_message(self, data):
        message_id = data.get('message_id')
        new_content = data.get('content', '').strip()
        
        if not message_id or not new_content:
            return
            
        success = await self.edit_message(message_id, new_content)
        if success:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_edited',
                    'message_id': message_id,
                    'new_content': new_content,
                    'user_id': self.user.id,
                    'edited_at': timezone.now().isoformat()
                }
            )

    async def handle_delete_message(self, data):
        message_id = data.get('message_id')
        
        if not message_id:
            return
            
        success = await self.delete_message(message_id)
        if success:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'message_deleted',
                    'message_id': message_id,
                    'user_id': self.user.id,
                    'deleted_at': timezone.now().isoformat()
                }
            )

    async def handle_mark_read(self, data):
        await self.mark_messages_as_read()

    # Event handlers for group messages
    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    async def typing_indicator(self, event):
        # Don't send typing indicator back to the sender
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps(event))

    async def message_reaction(self, event):
        await self.send(text_data=json.dumps(event))

    async def message_edited(self, event):
        await self.send(text_data=json.dumps(event))

    async def message_deleted(self, event):
        await self.send(text_data=json.dumps(event))

    async def user_joined(self, event):
        await self.send(text_data=json.dumps(event))

    async def user_left(self, event):
        await self.send(text_data=json.dumps(event))

    # Database operations
    @database_sync_to_async
    def check_room_permission(self):
        try:
            room = ChatRoom.objects.get(id=self.room_id, is_active=True)
            participant = ChatParticipant.objects.get(
                room=room, 
                user=self.user, 
                is_active=True
            )
            return True
        except (ChatRoom.DoesNotExist, ChatParticipant.DoesNotExist):
            return False

    @database_sync_to_async
    def update_online_status(self, is_online):
        try:
            participant = ChatParticipant.objects.get(
                room_id=self.room_id, 
                user=self.user, 
                is_active=True
            )
            participant.is_online = is_online
            participant.last_seen = timezone.now()
            participant.save()
        except ChatParticipant.DoesNotExist:
            pass

    @database_sync_to_async
    def save_message(self, content, reply_to_id=None):
        try:
            room = ChatRoom.objects.get(id=self.room_id, is_active=True)
            
            reply_to = None
            if reply_to_id:
                try:
                    reply_to = ChatMessage.objects.get(id=reply_to_id, room=room)
                except ChatMessage.DoesNotExist:
                    pass
            
            message = ChatMessage.objects.create(
                room=room,
                sender=self.user,
                content=content,
                reply_to=reply_to,
                message_type='text'
            )
            
            # Update room's last activity
            room.last_activity = timezone.now()
            room.save()
            
            return message
        except Exception as e:
            logger.error(f"Error saving message: {str(e)}")
            return None

    @database_sync_to_async
    def toggle_reaction(self, message_id, emoji, action):
        try:
            message = ChatMessage.objects.get(id=message_id, room_id=self.room_id)
            
            if action == 'add':
                reaction, created = ChatMessageReaction.objects.get_or_create(
                    message=message,
                    user=self.user,
                    emoji=emoji
                )
                return reaction
            elif action == 'remove':
                try:
                    reaction = ChatMessageReaction.objects.get(
                        message=message,
                        user=self.user,
                        emoji=emoji
                    )
                    reaction.delete()
                    return True
                except ChatMessageReaction.DoesNotExist:
                    return False
        except Exception as e:
            logger.error(f"Error toggling reaction: {str(e)}")
            return None

    @database_sync_to_async
    def edit_message(self, message_id, new_content):
        try:
            message = ChatMessage.objects.get(
                id=message_id, 
                room_id=self.room_id, 
                sender=self.user,
                is_deleted=False
            )
            message.edit_message(new_content)
            return True
        except ChatMessage.DoesNotExist:
            return False
        except Exception as e:
            logger.error(f"Error editing message: {str(e)}")
            return False

    @database_sync_to_async
    def delete_message(self, message_id):
        try:
            message = ChatMessage.objects.get(
                id=message_id, 
                room_id=self.room_id, 
                sender=self.user,
                is_deleted=False
            )
            message.delete_message()
            return True
        except ChatMessage.DoesNotExist:
            return False
        except Exception as e:
            logger.error(f"Error deleting message: {str(e)}")
            return False

    @database_sync_to_async
    def mark_messages_as_read(self):
        try:
            participant = ChatParticipant.objects.get(
                room_id=self.room_id, 
                user=self.user, 
                is_active=True
            )
            participant.mark_as_read()
        except ChatParticipant.DoesNotExist:
            pass


class UserChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user_id = self.scope['url_route']['kwargs']['user_id']
        self.user_group_name = f'user_{self.user_id}'

        # Join user group
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave user group
        await self.channel_layer.group_discard(
            self.user_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']
        target_user_id = text_data_json.get('target_user_id')

        if target_user_id:
            # Send message to target user
            await self.channel_layer.group_send(
                f'user_{target_user_id}',
                {
                    'type': 'user_message',
                    'message': message,
                    'from_user_id': self.user_id,
                }
            )

    # Receive message from user group
    async def user_message(self, event):
        message = event['message']
        from_user_id = event['from_user_id']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'message': message,
            'from_user_id': from_user_id,
        }))
from django.db import models
from django.utils import timezone
from accounts.models import User, Facility
from worklist.models import Study
import uuid

class ChatRoom(models.Model):
    """Chat room for communication between users"""
    ROOM_TYPES = [
        ('direct', 'Direct Message'),
        ('facility', 'Facility Discussion'),
        ('study', 'Study Discussion'),
        ('general', 'General Discussion'),
        ('support', 'Technical Support'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES, default='general')
    description = models.TextField(blank=True)
    
    # Related objects
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, null=True, blank=True)
    
    # Room settings
    is_active = models.BooleanField(default=True)
    is_private = models.BooleanField(default=False)
    max_participants = models.IntegerField(default=50)
    
    # Timestamps
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_rooms')
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_activity']

    def __str__(self):
        return f"{self.name} ({self.get_room_type_display()})"

    def get_participants_count(self):
        return self.participants.filter(is_active=True).count()

    def get_unread_count(self, user):
        """Get unread message count for a specific user"""
        try:
            participant = self.participants.get(user=user)
            return self.messages.filter(
                created_at__gt=participant.last_read_at or timezone.now()
            ).exclude(sender=user).count()
        except ChatParticipant.DoesNotExist:
            return 0

class ChatParticipant(models.Model):
    """Participants in chat rooms"""
    PARTICIPANT_ROLES = [
        ('member', 'Member'),
        ('moderator', 'Moderator'),
        ('admin', 'Admin'),
    ]

    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=PARTICIPANT_ROLES, default='member')
    
    # Status
    is_active = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(auto_now=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    
    # Notifications
    muted = models.BooleanField(default=False)
    notification_settings = models.JSONField(default=dict, blank=True)
    
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['room', 'user']

    def __str__(self):
        return f"{self.user.username} in {self.room.name}"

    def mark_as_read(self):
        """Mark all messages as read for this participant"""
        self.last_read_at = timezone.now()
        self.save()

class ChatMessage(models.Model):
    """Individual chat messages"""
    MESSAGE_TYPES = [
        ('text', 'Text'),
        ('image', 'Image'),
        ('file', 'File'),
        ('system', 'System Message'),
        ('study_link', 'Study Link'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default='text')
    content = models.TextField()
    
    # File attachments
    attachment = models.FileField(upload_to='chat_attachments/', null=True, blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    
    # Message references
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    study_reference = models.ForeignKey(Study, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Status
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    # Additional data
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message from {self.sender.username} in {self.room.name}"

    def edit_message(self, new_content):
        """Edit message content"""
        self.content = new_content
        self.is_edited = True
        self.edited_at = timezone.now()
        self.save()

    def delete_message(self):
        """Soft delete message"""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.content = "[Message deleted]"
        self.save()

class ChatMessageReaction(models.Model):
    """Reactions to chat messages (emoji reactions)"""
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=10)  # Unicode emoji
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['message', 'user', 'emoji']

    def __str__(self):
        return f"{self.emoji} by {self.user.username}"

class ChatModerationLog(models.Model):
    """Log of moderation actions in chat rooms"""
    MODERATION_ACTIONS = [
        ('warn', 'Warning'),
        ('mute', 'Mute User'),
        ('unmute', 'Unmute User'),
        ('kick', 'Kick from Room'),
        ('ban', 'Ban from Room'),
        ('unban', 'Unban from Room'),
        ('delete_message', 'Delete Message'),
        ('edit_message', 'Edit Message'),
    ]

    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='moderation_logs')
    moderator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='moderation_actions')
    target_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='moderation_received')
    action = models.CharField(max_length=20, choices=MODERATION_ACTIONS)
    reason = models.TextField()
    message = models.ForeignKey(ChatMessage, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Duration for temporary actions
    duration = models.DurationField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} by {self.moderator.username} on {self.target_user.username}"

class ChatInvitation(models.Model):
    """Invitations to join chat rooms"""
    INVITATION_STATUS = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]

    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='invitations')
    invited_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_invitations')
    invited_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_invitations')
    
    status = models.CharField(max_length=20, choices=INVITATION_STATUS, default='pending')
    message = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        unique_together = ['room', 'invited_user']

    def __str__(self):
        return f"Invitation to {self.room.name} for {self.invited_user.username}"

    def accept(self):
        """Accept the invitation"""
        if self.status == 'pending' and timezone.now() < self.expires_at:
            self.status = 'accepted'
            self.responded_at = timezone.now()
            self.save()
            
            # Add user to room as participant
            ChatParticipant.objects.get_or_create(
                room=self.room,
                user=self.invited_user,
                defaults={'role': 'member'}
            )
            return True
        return False

    def decline(self):
        """Decline the invitation"""
        if self.status == 'pending':
            self.status = 'declined'
            self.responded_at = timezone.now()
            self.save()
            return True
        return False

class ChatSettings(models.Model):
    """Global chat system settings"""
    max_message_length = models.IntegerField(default=2000)
    max_file_size = models.BigIntegerField(default=10485760)  # 10MB
    allowed_file_types = models.JSONField(default=list)
    message_retention_days = models.IntegerField(default=365)
    enable_file_sharing = models.BooleanField(default=True)
    enable_emoji_reactions = models.BooleanField(default=True)
    enable_message_editing = models.BooleanField(default=True)
    profanity_filter_enabled = models.BooleanField(default=True)
    
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Chat Settings"

    def __str__(self):
        return "Chat System Settings"

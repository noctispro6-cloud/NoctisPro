from django.db import models
from django.utils import timezone
from accounts.models import User, Facility
from worklist.models import Study
import json

class NotificationType(models.Model):
    """Types of notifications in the system"""
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)  # System-generated vs user-generated
    default_priority = models.CharField(max_length=20, choices=[
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ], default='normal')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

class Notification(models.Model):
    """System notifications model"""
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    notification_type = models.ForeignKey(NotificationType, on_delete=models.CASCADE)
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                              related_name='sent_notifications')
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    
    # Related objects
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, null=True, blank=True)
    
    # Status tracking
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_dismissed = models.BooleanField(default=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    
    # Additional data
    data = models.JSONField(default=dict, blank=True)  # Additional context data
    action_url = models.URLField(blank=True)  # URL to take action
    
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.recipient.username}"

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()

    def dismiss(self):
        """Dismiss notification"""
        if not self.is_dismissed:
            self.is_dismissed = True
            self.dismissed_at = timezone.now()
            self.save()

class SystemError(models.Model):
    """System error tracking for admin notifications"""
    ERROR_LEVELS = [
        ('debug', 'Debug'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    level = models.CharField(max_length=20, choices=ERROR_LEVELS)
    module = models.CharField(max_length=100)  # Which part of system
    error_code = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Context information
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    study = models.ForeignKey(Study, on_delete=models.SET_NULL, null=True, blank=True)
    facility = models.ForeignKey(Facility, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Technical details
    stack_trace = models.TextField(blank=True)
    request_data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Status
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='resolved_errors')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.level.upper()}] {self.title}"

    def resolve(self, user, notes=''):
        """Mark error as resolved"""
        self.is_resolved = True
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.resolution_notes = notes
        self.save()

class UploadStatus(models.Model):
    """Track file upload status for notifications"""
    UPLOAD_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE)
    study = models.ForeignKey(Study, on_delete=models.SET_NULL, null=True, blank=True)
    
    file_name = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    file_type = models.CharField(max_length=50)
    
    status = models.CharField(max_length=20, choices=UPLOAD_STATUS_CHOICES, default='pending')
    progress = models.IntegerField(default=0)  # 0-100
    
    # Error handling
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.file_name} - {self.status}"

class NotificationPreference(models.Model):
    """User notification preferences"""
    DELIVERY_METHODS = [
        ('web', 'Web Notification'),
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('call', 'Phone Call'),
        ('push', 'Push Notification'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preferences')
    
    # Notification types preferences
    new_study_notifications = models.BooleanField(default=True)
    report_ready_notifications = models.BooleanField(default=True)
    system_error_notifications = models.BooleanField(default=True)
    chat_notifications = models.BooleanField(default=True)
    upload_notifications = models.BooleanField(default=True)
    
    # Delivery preferences
    preferred_method = models.CharField(max_length=20, choices=DELIVERY_METHODS, default='web')
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    
    # Email settings
    email_digest = models.BooleanField(default=False)
    digest_frequency = models.CharField(max_length=20, choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ], default='daily')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences for {self.user.username}"

class NotificationQueue(models.Model):
    """Queue for processing notifications"""
    notification = models.OneToOneField(Notification, on_delete=models.CASCADE)
    delivery_method = models.CharField(max_length=20)
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    next_attempt = models.DateTimeField(default=timezone.now)
    is_processed = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Queue for {self.notification.title}"

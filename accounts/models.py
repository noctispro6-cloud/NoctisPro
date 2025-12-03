from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

class Facility(models.Model):
    """Model for healthcare facilities"""
    name = models.CharField(max_length=200)
    address = models.TextField()
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    license_number = models.CharField(max_length=100, unique=True)
    letterhead = models.ImageField(upload_to='letterheads/', null=True, blank=True)
    # DICOM networking identifier so studies can be attributed to facilities
    ae_title = models.CharField(max_length=32, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Facilities"

    def __str__(self):
        return self.name

class User(AbstractUser):
    """Custom User model with role-based access"""
    USER_ROLES = (
        ('admin', 'Administrator'),
        ('radiologist', 'Radiologist'),
        ('facility', 'Facility User'),
    )
    
    role = models.CharField(max_length=20, choices=USER_ROLES, default='facility')
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    license_number = models.CharField(max_length=100, blank=True)
    specialization = models.CharField(max_length=100, blank=True)
    is_verified = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def is_admin(self):
        # Treat Django superusers and staff as admins for access control
        if getattr(self, 'is_superuser', False) or getattr(self, 'is_staff', False):
            return True
        return self.role == 'admin'

    def is_radiologist(self):
        return self.role == 'radiologist'

    def is_facility_user(self):
        return self.role == 'facility'

    def can_edit_reports(self):
        return self.role in ['admin', 'radiologist']

    def can_manage_users(self):
        # Allow superusers/staff to manage users, in addition to role-based admin
        if getattr(self, 'is_superuser', False) or getattr(self, 'is_staff', False):
            return True
        return self.role == 'admin'

class UserSession(models.Model):
    """Track user sessions for security"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} - {self.login_time}"

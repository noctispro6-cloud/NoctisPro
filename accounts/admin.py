from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AuditLog, Facility, User, UserSession


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ("name", "license_number", "ae_title", "is_active", "created_at")
    search_fields = ("name", "license_number", "ae_title")
    list_filter = ("is_active",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Noctis Pro", {"fields": ("role", "facility", "phone", "license_number", "specialization", "is_verified", "last_login_ip")}),
    )
    list_display = ("username", "email", "role", "facility", "is_staff", "is_superuser", "is_active", "last_login")
    list_filter = ("role", "facility", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "ip_address", "login_time", "logout_time", "is_active")
    list_filter = ("is_active",)
    search_fields = ("user__username", "ip_address")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "user", "facility", "study_instance_uid", "series_instance_uid", "sop_instance_uid", "ip_address")
    list_filter = ("action", "facility")
    search_fields = ("user__username", "study_instance_uid", "series_instance_uid", "sop_instance_uid", "ip_address")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

# Register your models here.
